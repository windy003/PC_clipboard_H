# -*- coding: utf-8 -*-
"""收藏夹云端存储模块（账号 + 密码登录版，经由 Cloudflare Worker）。

桌面端不存任何固定密钥：用户输入账号密码，向 Worker 的 /login 换取一个有
时效的 JWT，之后用这个 token 访问 /load、/save。token 缓存在本地文件，过期
或失效后需要重新登录。Cloudflare 的真实访问权限只在 Worker 端。

仅使用标准库 urllib，无需额外依赖，便于 PyInstaller 打包。

收藏数据结构（与主程序 self.favorites 一致）：
    { 收藏夹名: [ {"text": ..., "description": ...}, ... ], ... }

注：类名仍为 D1Storage，数据接口（enabled / load / save / save_async）保持不变，
以便主程序的收藏夹读写逻辑无需改动；新增 login / token 管理（账号注册改由命令行调用 Worker /register）。
"""

import json
import os
import time
import threading
import urllib.request
import urllib.error


class AuthError(Exception):
    """未登录或 token 无效/已过期（HTTP 401）。"""
    pass


def load_env_file(path):
    """读取 .env 文件并写入 os.environ（不覆盖已存在的同名环境变量）。

    支持 KEY=VALUE 形式，忽略空行与 # 注释，自动去除值两侧的引号。
    """
    if not path or not os.path.exists(path):
        return
    try:
        with open(path, 'r', encoding='utf-8') as f:
            for raw in f:
                line = raw.strip()
                if not line or line.startswith('#') or '=' not in line:
                    continue
                key, _, value = line.partition('=')
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                if key and key not in os.environ:
                    os.environ[key] = value
    except Exception as e:
        print(f"读取 .env 文件出错: {e}")


class D1Storage:
    """封装对收藏夹云端数据的读写（账号密码登录 + JWT，经由 Worker）。"""

    def __init__(self, worker_url, token_file=None, timeout=15):
        # 去掉末尾斜杠，便于后续拼接 /login、/load、/save
        self.worker_url = (worker_url or "").strip().rstrip("/")
        self.timeout = timeout
        self.token_file = token_file or os.path.join(
            os.path.dirname(os.path.abspath(__file__)), '.clipboard_token.json')

        self.token = ""
        self.expires_at = 0      # JWT 过期的 unix 时间戳
        self.username = ""

        # 后台异步保存所需：锁 + 待保存快照 + 工作线程
        self._lock = threading.Lock()
        self._pending = None
        self._worker = None

        self._load_token()

    @property
    def enabled(self):
        """配置了 Worker 地址即视为启用云同步（是否登录是另一回事）。"""
        return bool(self.worker_url)

    @classmethod
    def from_env(cls):
        """从环境变量创建实例。"""
        return cls(worker_url=os.environ.get("CLIPBOARD_WORKER_URL", ""))

    # ---------- token 本地缓存 ----------
    def _load_token(self):
        """从本地文件读取上次登录的 token（仅当 Worker 地址匹配且未过期才采用）。"""
        try:
            if not os.path.exists(self.token_file):
                return
            with open(self.token_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            if data.get("worker_url") != self.worker_url:
                return
            self.token = data.get("token", "")
            self.expires_at = data.get("expires_at", 0) or 0
            self.username = data.get("username", "")
        except Exception as e:
            print(f"读取本地 token 出错: {e}")

    def _save_token(self):
        try:
            with open(self.token_file, 'w', encoding='utf-8') as f:
                json.dump({
                    "worker_url": self.worker_url,
                    "username": self.username,
                    "token": self.token,
                    "expires_at": self.expires_at,
                }, f, ensure_ascii=False)
        except Exception as e:
            print(f"保存本地 token 出错: {e}")

    def has_valid_token(self):
        """本地是否持有未过期的 token（留 60 秒余量）。"""
        return bool(self.token) and time.time() < (self.expires_at - 60)

    def logout(self):
        """清除本地登录状态。"""
        self.token = ""
        self.expires_at = 0
        self.username = ""
        try:
            if os.path.exists(self.token_file):
                os.remove(self.token_file)
        except Exception:
            pass

    # ---------- 底层 HTTP ----------
    def _post(self, path, payload=None, extra_headers=None, with_token=False):
        """向 Worker 发送一次 POST，返回解析后的 JSON。

        with_token=True 时附带 Authorization: Bearer。HTTP 401 抛 AuthError，
        其它失败抛 RuntimeError。
        """
        url = f"{self.worker_url}{path}"
        body = json.dumps(payload or {}).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            # 带浏览器风格 UA：Cloudflare 边缘会拦截 Python-urllib 默认 UA（错误码 1010）
            "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                           "AppleWebKit/537.36 (KHTML, like Gecko) "
                           "Chrome/120.0.0.0 Safari/537.36"),
        }
        if with_token:
            headers["Authorization"] = f"Bearer {self.token}"
        if extra_headers:
            headers.update(extra_headers)

        req = urllib.request.Request(url, data=body, method="POST", headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            detail = ""
            try:
                detail = e.read().decode("utf-8")
            except Exception:
                pass
            if e.code == 401:
                raise AuthError(detail or "未登录或 token 已过期") from e
            raise RuntimeError(f"Worker 请求失败 HTTP {e.code}: {detail}") from e

    # ---------- 账号 ----------
    def login(self, username, password):
        """登录换取 token。成功返回 True 并缓存 token，失败抛异常。"""
        data = self._post("/login", {"username": username, "password": password})
        if not data.get("ok"):
            raise RuntimeError(data.get("error") or "登录失败")
        self.token = data.get("token", "")
        self.expires_at = data.get("expires_at", 0) or 0
        self.username = username
        self._save_token()
        return True

    # ---------- 读取 ----------
    def load(self):
        """从 Worker 读取当前账号的全部收藏夹数据，返回有序字典。"""
        data = self._post("/load", with_token=True)
        if not data.get("ok"):
            raise RuntimeError(data.get("error") or "读取失败")
        favorites = data.get("favorites") or {}
        if not isinstance(favorites, dict):
            return {}
        result = {}
        for folder, entries in favorites.items():
            items = []
            for entry in entries or []:
                if isinstance(entry, dict):
                    items.append({
                        "text": entry.get("text") or "",
                        "description": entry.get("description") or "",
                    })
                else:
                    items.append({"text": str(entry), "description": ""})
            result[folder] = items
        return result

    # ---------- 保存（全量覆盖）----------
    def save(self, favorites):
        """用传入的数据全量替换当前账号的云端收藏夹。"""
        data = self._post("/save", {"favorites": favorites}, with_token=True)
        if not data.get("ok"):
            raise RuntimeError(data.get("error") or "保存失败")

    # ---------- 只追加（出箱模式）----------
    def append(self, folder, entries):
        """把若干条目「只追加」到云端指定收藏夹，不影响其它数据。

        用于「记忆」出箱：PC 推送成功后本地删除该条，云端只增不减，交给安卓 app
        处理。entries 形如 [{"text": ..., "description": ...}, ...]。返回实际写入条数。
        """
        data = self._post("/append", {"folder": folder, "entries": entries}, with_token=True)
        if not data.get("ok"):
            raise RuntimeError(data.get("error") or "追加失败")
        return data.get("count", 0)

    # ---------- 异步保存 ----------
    def save_async(self, favorites):
        """在后台线程保存，避免阻塞 UI；总是推送最新快照。"""
        snapshot = {
            folder: [dict(e) if isinstance(e, dict) else {"text": str(e), "description": ""}
                     for e in entries]
            for folder, entries in favorites.items()
        }
        with self._lock:
            self._pending = snapshot
            if self._worker is None or not self._worker.is_alive():
                self._worker = threading.Thread(target=self._drain, daemon=True)
                self._worker.start()

    def _drain(self):
        """工作线程：不断取出最新快照保存，直到没有待保存数据。"""
        while True:
            with self._lock:
                snapshot = self._pending
                self._pending = None
                if snapshot is None:
                    return
            try:
                self.save(snapshot)
                print("收藏夹已同步到云端 Worker")
            except AuthError:
                # token 失效：丢弃本次快照，标记需要重新登录（主线程下次会处理）
                print("登录已过期，收藏夹未能同步，请重新登录")
                self.token = ""
            except Exception as e:
                print(f"同步到 Worker 失败: {e}")
