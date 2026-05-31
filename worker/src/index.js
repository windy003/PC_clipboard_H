/**
 * 剪贴板收藏夹同步 Worker（账号 + 密码登录版）。
 *
 * 客户端（PC / 安卓）不存任何密钥：用户输入账号密码换取有时效的 JWT，
 * 之后用 JWT 访问数据接口。Cloudflare 的真实访问权限只在本 Worker 的 D1 绑定中。
 *
 * 接口：
 *   POST /register  需 header X-Register-Secret: <REGISTER_SECRET>
 *                   body { username, password } -> 创建账号
 *   POST /login     body { username, password } -> { ok, token, expires_at }
 *   POST /load      需 Authorization: Bearer <JWT> -> { ok, favorites }
 *   POST /save      需 Authorization: Bearer <JWT>，body { favorites } -> { ok }
 *
 * 数据按 user_id 隔离，每个账号各自独立的收藏夹。
 *
 * 密码：PBKDF2-SHA256 + 随机盐，只存哈希，绝不存明文。
 * token：HMAC-SHA256 签名的 JWT，用 secret JWT_SECRET 签发与校验。
 *
 * 需要的 Worker secret（用 `wrangler secret put` 设置）：
 *   JWT_SECRET       —— 给 JWT 签名用的随机长字符串
 *   REGISTER_SECRET  —— 开账号时要带的管理密钥，防止陌生人乱注册
 */

const JSON_HEADERS = { "Content-Type": "application/json; charset=utf-8" };
const PBKDF2_ITERATIONS = 100000;
const TOKEN_TTL_SECONDS = 60 * 60 * 24 * 30; // token 有效期 30 天

function json(body, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: JSON_HEADERS });
}

/** 常量时间字符串比较，避免时序侧信道。 */
function safeEqual(a, b) {
  if (typeof a !== "string" || typeof b !== "string" || a.length !== b.length) {
    return false;
  }
  let diff = 0;
  for (let i = 0; i < a.length; i++) {
    diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
  }
  return diff === 0;
}

// ---------- base64 / base64url 编解码 ----------
function bytesToBase64(bytes) {
  let bin = "";
  for (let i = 0; i < bytes.length; i++) bin += String.fromCharCode(bytes[i]);
  return btoa(bin);
}
function base64ToBytes(b64) {
  const bin = atob(b64);
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return out;
}
function base64urlFromBytes(bytes) {
  return bytesToBase64(bytes).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}
function base64urlFromString(str) {
  return base64urlFromBytes(new TextEncoder().encode(str));
}
function base64urlToBytes(b64url) {
  let b64 = b64url.replace(/-/g, "+").replace(/_/g, "/");
  while (b64.length % 4) b64 += "=";
  return base64ToBytes(b64);
}

// ---------- 密码哈希（PBKDF2-SHA256）----------
async function hashPassword(password, saltBytes) {
  const salt = saltBytes || crypto.getRandomValues(new Uint8Array(16));
  const keyMaterial = await crypto.subtle.importKey(
    "raw",
    new TextEncoder().encode(password),
    "PBKDF2",
    false,
    ["deriveBits"]
  );
  const bits = await crypto.subtle.deriveBits(
    { name: "PBKDF2", salt, iterations: PBKDF2_ITERATIONS, hash: "SHA-256" },
    keyMaterial,
    256
  );
  return {
    saltB64: bytesToBase64(salt),
    hashB64: bytesToBase64(new Uint8Array(bits)),
  };
}

async function verifyPassword(password, saltB64, expectedHashB64) {
  const { hashB64 } = await hashPassword(password, base64ToBytes(saltB64));
  return safeEqual(hashB64, expectedHashB64);
}

// ---------- JWT（HMAC-SHA256）----------
async function importHmacKey(secret) {
  return crypto.subtle.importKey(
    "raw",
    new TextEncoder().encode(secret),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign", "verify"]
  );
}

async function signJwt(payload, secret) {
  const header = { alg: "HS256", typ: "JWT" };
  const headerB64 = base64urlFromString(JSON.stringify(header));
  const payloadB64 = base64urlFromString(JSON.stringify(payload));
  const signingInput = `${headerB64}.${payloadB64}`;
  const key = await importHmacKey(secret);
  const sig = await crypto.subtle.sign("HMAC", key, new TextEncoder().encode(signingInput));
  return `${signingInput}.${base64urlFromBytes(new Uint8Array(sig))}`;
}

async function verifyJwt(token, secret) {
  if (typeof token !== "string") return null;
  const parts = token.split(".");
  if (parts.length !== 3) return null;
  const [headerB64, payloadB64, sigB64] = parts;
  const key = await importHmacKey(secret);
  const valid = await crypto.subtle.verify(
    "HMAC",
    key,
    base64urlToBytes(sigB64),
    new TextEncoder().encode(`${headerB64}.${payloadB64}`)
  );
  if (!valid) return null;
  let payload;
  try {
    payload = JSON.parse(new TextDecoder().decode(base64urlToBytes(payloadB64)));
  } catch {
    return null;
  }
  if (typeof payload.exp === "number" && Date.now() / 1000 > payload.exp) {
    return null; // 已过期
  }
  return payload;
}

// ---------- 数据库 schema ----------
async function ensureSchema(db) {
  await db.batch([
    db.prepare(
      "CREATE TABLE IF NOT EXISTS users (" +
        "id INTEGER PRIMARY KEY AUTOINCREMENT, " +
        "username TEXT UNIQUE NOT NULL, " +
        "salt TEXT NOT NULL, " +
        "password_hash TEXT NOT NULL, " +
        "created_at INTEGER NOT NULL)"
    ),
    db.prepare(
      "CREATE TABLE IF NOT EXISTS folders (" +
        "user_id INTEGER NOT NULL, " +
        "name TEXT NOT NULL, " +
        "position INTEGER NOT NULL, " +
        "PRIMARY KEY (user_id, name))"
    ),
    db.prepare(
      "CREATE TABLE IF NOT EXISTS favorites (" +
        "id INTEGER PRIMARY KEY AUTOINCREMENT, " +
        "user_id INTEGER NOT NULL, " +
        "folder TEXT NOT NULL, " +
        "text TEXT NOT NULL, " +
        "description TEXT DEFAULT '', " +
        "position INTEGER NOT NULL)"
    ),
  ]);
}

// ---------- 业务：账号 ----------
async function registerUser(db, username, password) {
  await ensureSchema(db);
  const existing = await db
    .prepare("SELECT id FROM users WHERE username = ?")
    .bind(username)
    .first();
  if (existing) {
    return { error: "用户名已存在", status: 409 };
  }
  const { saltB64, hashB64 } = await hashPassword(password);
  await db
    .prepare(
      "INSERT INTO users (username, salt, password_hash, created_at) VALUES (?, ?, ?, ?)"
    )
    .bind(username, saltB64, hashB64, Math.floor(Date.now() / 1000))
    .run();
  return { ok: true };
}

async function authenticate(db, username, password) {
  await ensureSchema(db);
  const row = await db
    .prepare("SELECT id, salt, password_hash FROM users WHERE username = ?")
    .bind(username)
    .first();
  if (!row) return null;
  const ok = await verifyPassword(password, row.salt, row.password_hash);
  if (!ok) return null;
  return { id: row.id, username };
}

// ---------- 业务：收藏夹（按 user_id 隔离）----------
async function loadFavorites(db, userId, folderName = null) {
  await ensureSchema(db);
  const favorites = {};

  // 只查指定收藏夹
  if (folderName) {
    const exists = await db
      .prepare("SELECT name FROM folders WHERE user_id = ? AND name = ?")
      .bind(userId, folderName)
      .first();
    if (!exists) return {};
    favorites[folderName] = [];
    const itemRes = await db
      .prepare(
        "SELECT id, text, description FROM favorites WHERE user_id = ? AND folder = ? " +
          "ORDER BY position ASC"
      )
      .bind(userId, folderName)
      .all();
    for (const row of itemRes.results || []) {
      favorites[folderName].push({
        id: row.id,
        text: row.text || "",
        description: row.description || "",
      });
    }
    return favorites;
  }

  // 查全部收藏夹
  const folderRes = await db
    .prepare("SELECT name FROM folders WHERE user_id = ? ORDER BY position ASC")
    .bind(userId)
    .all();
  for (const row of folderRes.results || []) {
    favorites[row.name] = [];
  }

  const itemRes = await db
    .prepare(
      "SELECT id, folder, text, description FROM favorites WHERE user_id = ? " +
        "ORDER BY folder ASC, position ASC"
    )
    .bind(userId)
    .all();
  for (const row of itemRes.results || []) {
    if (!favorites[row.folder]) favorites[row.folder] = [];
    favorites[row.folder].push({
      id: row.id,
      text: row.text || "",
      description: row.description || "",
    });
  }
  return favorites;
}

/** 删除当前账号的一条收藏（按条目 id）。 */
async function deleteItem(db, userId, id) {
  await ensureSchema(db);
  await db
    .prepare("DELETE FROM favorites WHERE user_id = ? AND id = ?")
    .bind(userId, id)
    .run();
}

/** 列出所有收藏夹名及各自的条目数（轻量，用于客户端做切换）。 */
async function listFolders(db, userId) {
  await ensureSchema(db);
  const res = await db
    .prepare(
      "SELECT f.name AS name, COUNT(v.id) AS count " +
        "FROM folders f " +
        "LEFT JOIN favorites v ON v.user_id = f.user_id AND v.folder = f.name " +
        "WHERE f.user_id = ? " +
        "GROUP BY f.name ORDER BY f.position ASC"
    )
    .bind(userId)
    .all();
  return (res.results || []).map((r) => ({ name: r.name, count: r.count || 0 }));
}

async function saveFavorites(db, userId, favorites) {
  await ensureSchema(db);

  const stmts = [
    db.prepare("DELETE FROM favorites WHERE user_id = ?").bind(userId),
    db.prepare("DELETE FROM folders WHERE user_id = ?").bind(userId),
  ];

  const folderNames = Object.keys(favorites);
  folderNames.forEach((name, pos) => {
    stmts.push(
      db
        .prepare("INSERT INTO folders (user_id, name, position) VALUES (?, ?, ?)")
        .bind(userId, name, pos)
    );
  });

  for (const folder of folderNames) {
    const entries = favorites[folder] || [];
    entries.forEach((entry, pos) => {
      let text = "";
      let desc = "";
      if (entry && typeof entry === "object") {
        text = entry.text != null ? String(entry.text) : "";
        desc = entry.description != null ? String(entry.description) : "";
      } else {
        text = String(entry);
      }
      stmts.push(
        db
          .prepare(
            "INSERT INTO favorites (user_id, folder, text, description, position) " +
              "VALUES (?, ?, ?, ?, ?)"
          )
          .bind(userId, folder, text, desc, pos)
      );
    });
  }

  await db.batch(stmts);
}

// ---------- 请求处理 ----------
async function readJsonBody(request) {
  try {
    return await request.json();
  } catch {
    return null;
  }
}

async function requireUser(request, env) {
  if (!env.JWT_SECRET) return null;
  const header = request.headers.get("Authorization") || "";
  const prefix = "Bearer ";
  if (!header.startsWith(prefix)) return null;
  return verifyJwt(header.slice(prefix.length), env.JWT_SECRET);
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    if (request.method !== "POST") {
      return json({ ok: false, error: "Method Not Allowed" }, 405);
    }

    try {
      // ---- 开账号 ----
      if (url.pathname === "/register") {
        if (!env.REGISTER_SECRET) {
          return json({ ok: false, error: "服务端未配置 REGISTER_SECRET" }, 500);
        }
        const provided = request.headers.get("X-Register-Secret") || "";
        if (!safeEqual(provided, env.REGISTER_SECRET)) {
          return json({ ok: false, error: "注册密钥错误" }, 403);
        }
        const body = await readJsonBody(request);
        const username = body && typeof body.username === "string" ? body.username.trim() : "";
        const password = body && typeof body.password === "string" ? body.password : "";
        if (!username || !password) {
          return json({ ok: false, error: "username 和 password 不能为空" }, 400);
        }
        const res = await registerUser(env.DB, username, password);
        if (res.error) return json({ ok: false, error: res.error }, res.status || 400);
        return json({ ok: true });
      }

      // ---- 登录 ----
      if (url.pathname === "/login") {
        if (!env.JWT_SECRET) {
          return json({ ok: false, error: "服务端未配置 JWT_SECRET" }, 500);
        }
        const body = await readJsonBody(request);
        const username = body && typeof body.username === "string" ? body.username.trim() : "";
        const password = body && typeof body.password === "string" ? body.password : "";
        if (!username || !password) {
          return json({ ok: false, error: "username 和 password 不能为空" }, 400);
        }
        const user = await authenticate(env.DB, username, password);
        if (!user) {
          return json({ ok: false, error: "账号或密码错误" }, 401);
        }
        const now = Math.floor(Date.now() / 1000);
        const exp = now + TOKEN_TTL_SECONDS;
        const token = await signJwt(
          { sub: user.id, username: user.username, iat: now, exp },
          env.JWT_SECRET
        );
        return json({ ok: true, token, expires_at: exp });
      }

      // ---- 以下接口需要有效 JWT ----
      const payload = await requireUser(request, env);
      if (!payload) {
        return json({ ok: false, error: "未登录或 token 无效/已过期" }, 401);
      }
      const userId = payload.sub;

      if (url.pathname === "/folders") {
        const folders = await listFolders(env.DB, userId);
        return json({ ok: true, folders });
      }

      if (url.pathname === "/load") {
        // body 可带 { folder: "名称" } 只查该收藏夹；不带则返回全部（兼容 PC 端）
        const body = await readJsonBody(request);
        const folder =
          body && typeof body.folder === "string" && body.folder ? body.folder : null;
        const favorites = await loadFavorites(env.DB, userId, folder);
        return json({ ok: true, favorites });
      }

      if (url.pathname === "/save") {
        const body = await readJsonBody(request);
        const favorites = body && body.favorites;
        if (!favorites || typeof favorites !== "object" || Array.isArray(favorites)) {
          return json({ ok: false, error: "Missing 'favorites' object" }, 400);
        }
        await saveFavorites(env.DB, userId, favorites);
        return json({ ok: true });
      }

      if (url.pathname === "/delete") {
        const body = await readJsonBody(request);
        const id = body && Number.isInteger(body.id) ? body.id : null;
        if (id == null) {
          return json({ ok: false, error: "缺少条目 id" }, 400);
        }
        await deleteItem(env.DB, userId, id);
        return json({ ok: true });
      }

      return json({ ok: false, error: "Not Found" }, 404);
    } catch (err) {
      return json(
        { ok: false, error: String(err && err.message ? err.message : err) },
        500
      );
    }
  },
};
