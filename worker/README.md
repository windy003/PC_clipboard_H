# clipboard-fav-worker

剪贴板收藏夹同步的 Cloudflare Worker，**账号 + 密码登录**版。

客户端（PC / 安卓）**不存任何密钥**：用户输入账号密码，向 `/login` 换取一个
有时效的 JWT，之后用这个 token 访问数据接口。Cloudflare 的真实访问权限只存在
于本 Worker 的 D1 绑定中。数据按账号隔离，每个账号各自独立的收藏夹。

## 接口

| 路径        | 鉴权                              | 请求体                  | 响应                                  |
| ----------- | --------------------------------- | ----------------------- | ------------------------------------- |
| `/register` | header `X-Register-Secret`        | `{ username, password }`| `{ ok: true }`                        |
| `/login`    | 无                                | `{ username, password }`| `{ ok, token, expires_at }`           |
| `/load`     | `Authorization: Bearer <token>`   | 无                      | `{ ok, favorites }`                   |
| `/save`     | `Authorization: Bearer <token>`   | `{ favorites }`         | `{ ok: true }`                        |

方法均为 `POST`。`favorites` 结构：
`{ 收藏夹名: [ { "text": "...", "description": "..." }, … ], … }`

- 密码：服务端用 PBKDF2-SHA256 + 随机盐做哈希，**只存哈希，不存明文**。
- token：HMAC-SHA256 签名的 JWT，默认有效期 30 天。

## 两个 secret

| secret            | 作用                                          |
| ----------------- | --------------------------------------------- |
| `JWT_SECRET`      | 给登录 token 签名，必须设置                    |
| `REGISTER_SECRET` | 开账号时请求头要带的管理密钥，防止陌生人注册   |

## 首次部署

前置：已安装 Node + `wrangler`，且 `wrangler login`（或配好有 Workers + D1 权限的凭据）。

1. **填配置**：编辑 `wrangler.toml`，把 `account_id`、`database_id`、`database_name`
   填成你自己的（`wrangler d1 list` 可查库信息）。

2. **迁移旧表（重要）**：如果这个 D1 库之前跑过老版本（没有账号体系的 `folders`/
   `favorites`），新结构加了 `user_id` 列、`CREATE TABLE IF NOT EXISTS` 不会改旧表，
   所以要先删掉旧表（你的数据在桌面端本地 `.clipboard_favorites.json` 里还在，登录后
   会自动重新上传）：
   ```
   wrangler d1 execute <database_name> --remote --command "DROP TABLE IF EXISTS favorites; DROP TABLE IF EXISTS folders;"
   ```
   全新的库可跳过这步。

3. **设置 secret**（各想一段随机长字符串）：
   ```
   wrangler secret put JWT_SECRET
   wrangler secret put REGISTER_SECRET
   ```

4. **部署**：
   ```
   cd worker
   npm install      # 安装 wrangler（若用全局 wrangler 可跳过）
   wrangler deploy
   ```
   成功会输出 Worker 地址，形如
   `https://clipboard-fav-worker.<你的子域>.workers.dev`。

5. **开第一个账号**：用刚设的 `REGISTER_SECRET` 调一次 `/register`：
   ```
   curl -X POST https://你的worker地址/register ^
     -H "X-Register-Secret: 你的REGISTER_SECRET" ^
     -H "Content-Type: application/json" ^
     -d "{\"username\":\"想要的账号\",\"password\":\"想要的密码\"}"
   ```
   （或在桌面端 `.env` 里临时填 `CLIPBOARD_REGISTER_SECRET`，登录框上会出现“注册”按钮。）

6. **配置桌面端**：项目根目录 `.env` 写入：
   ```
   CLIPBOARD_WORKER_URL=https://clipboard-fav-worker.<你的子域>.workers.dev
   ```
   启动桌面端后会弹登录框，输入第 5 步的账号密码即可。

## 本地调试

```
cp .dev.vars.example .dev.vars   # 填入 JWT_SECRET、REGISTER_SECRET
wrangler dev                     # 默认 http://localhost:8787
```
桌面端 `.env` 把 `CLIPBOARD_WORKER_URL` 指向 `http://localhost:8787` 即可联调。
