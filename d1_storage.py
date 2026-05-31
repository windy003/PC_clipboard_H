# -*- coding: utf-8 -*-
"""Cloudflare D1 数据库存储模块。

通过 Cloudflare D1 的 REST API 读写收藏夹数据（内容 text 与描述 description）。
仅使用标准库 urllib，无需额外依赖，便于 PyInstaller 打包。

收藏数据结构（与主程序 self.favorites 一致）：
    { 收藏夹名: [ {"text": ..., "description": ...}, ... ], ... }

使用两张表保存：
    folders   —— 保存收藏夹名称及其顺序（同时保留空收藏夹）
    favorites —— 保存每条收藏的内容、描述，以及在所属收藏夹内的顺序
"""

import json
import os
import threading
import urllib.request
import urllib.error


# Cloudflare D1 单条查询最多绑定 100 个参数，这里按列数换算每批最大行数
_MAX_BOUND_PARAMS = 100


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
    """封装对 Cloudflare D1 收藏夹数据的读写。"""

    _API_TEMPLATE = ("https://api.cloudflare.com/client/v4/accounts/"
                     "{account_id}/d1/database/{database_id}/query")

    def __init__(self, account_id, database_id, api_token, timeout=15):
        self.account_id = (account_id or "").strip()
        self.database_id = (database_id or "").strip()
        self.api_token = (api_token or "").strip()
        self.timeout = timeout
        self._schema_ready = False

        # 后台异步保存所需：锁 + 待保存快照 + 工作线程
        self._lock = threading.Lock()
        self._pending = None
        self._worker = None

    @property
    def enabled(self):
        """三项凭据齐全时才启用 D1。"""
        return bool(self.account_id and self.database_id and self.api_token)

    @classmethod
    def from_env(cls):
        """从环境变量创建实例。"""
        return cls(
            account_id=os.environ.get("CLOUDFLARE_ACCOUNT_ID", ""),
            database_id=os.environ.get("CLOUDFLARE_D1_DATABASE_ID", ""),
            api_token=os.environ.get("CLOUDFLARE_API_TOKEN", ""),
        )

    # ---------- 底层 HTTP ----------
    def _query(self, sql, params=None):
        """向 D1 发送一条 SQL，返回 result 数组。失败抛出异常。"""
        url = self._API_TEMPLATE.format(
            account_id=self.account_id, database_id=self.database_id)
        body = json.dumps({"sql": sql, "params": params or []}).encode("utf-8")
        req = urllib.request.Request(
            url, data=body, method="POST",
            headers={
                "Authorization": f"Bearer {self.api_token}",
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            detail = ""
            try:
                detail = e.read().decode("utf-8")
            except Exception:
                pass
            raise RuntimeError(f"D1 请求失败 HTTP {e.code}: {detail}") from e

        if not data.get("success"):
            raise RuntimeError(f"D1 返回错误: {data.get('errors')}")
        return data.get("result", [])

    def ensure_schema(self):
        """确保两张表存在（只需执行一次）。"""
        if self._schema_ready:
            return
        self._query(
            "CREATE TABLE IF NOT EXISTS folders ("
            "name TEXT PRIMARY KEY, position INTEGER NOT NULL)")
        self._query(
            "CREATE TABLE IF NOT EXISTS favorites ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "folder TEXT NOT NULL, "
            "text TEXT NOT NULL, "
            "description TEXT DEFAULT '', "
            "position INTEGER NOT NULL)")
        self._schema_ready = True

    # ---------- 读取 ----------
    def load(self):
        """从 D1 读取全部收藏夹数据，返回有序字典。"""
        self.ensure_schema()

        favorites = {}
        # 1) 按顺序读取收藏夹（保留空收藏夹）
        folder_res = self._query("SELECT name FROM folders ORDER BY position ASC")
        for row in self._rows(folder_res):
            favorites[row["name"]] = []

        # 2) 读取条目，按所属收藏夹内顺序填充
        item_res = self._query(
            "SELECT folder, text, description FROM favorites "
            "ORDER BY folder ASC, position ASC")
        for row in self._rows(item_res):
            folder = row["folder"]
            favorites.setdefault(folder, []).append({
                "text": row.get("text") or "",
                "description": row.get("description") or "",
            })
        return favorites

    @staticmethod
    def _rows(result):
        """从 D1 result 数组中取出第一条语句的 results 行。"""
        if result and isinstance(result, list):
            return result[0].get("results", []) or []
        return []

    # ---------- 保存（全量覆盖）----------
    def save(self, favorites):
        """用传入的数据全量替换 D1 中的收藏夹内容。"""
        self.ensure_schema()

        # 清空旧数据
        self._query("DELETE FROM favorites")
        self._query("DELETE FROM folders")

        # 写入收藏夹顺序
        folders = list(favorites.keys())
        if folders:
            self._bulk_insert(
                "INSERT INTO folders (name, position) VALUES ",
                "(?,?)",
                [(name, pos) for pos, name in enumerate(folders)],
            )

        # 写入每条收藏
        items = []
        for folder, entries in favorites.items():
            for pos, entry in enumerate(entries):
                if isinstance(entry, dict):
                    text = entry.get("text", "")
                    desc = entry.get("description", "") or ""
                else:
                    text, desc = str(entry), ""
                items.append((folder, text, desc, pos))
        if items:
            self._bulk_insert(
                "INSERT INTO favorites (folder, text, description, position) VALUES ",
                "(?,?,?,?)",
                items,
            )

    def _bulk_insert(self, prefix, row_placeholder, rows):
        """多行批量插入，自动按参数上限分批。

        prefix: INSERT ... VALUES 前缀
        row_placeholder: 单行占位符，例如 "(?,?,?,?)"
        rows: 元组列表，每个元组对应一行的参数
        """
        cols = row_placeholder.count("?")
        chunk_size = max(1, _MAX_BOUND_PARAMS // cols)
        for i in range(0, len(rows), chunk_size):
            chunk = rows[i:i + chunk_size]
            placeholders = ",".join([row_placeholder] * len(chunk))
            params = []
            for row in chunk:
                params.extend(row)
            self._query(prefix + placeholders, params)

    # ---------- 异步保存 ----------
    def save_async(self, favorites):
        """在后台线程保存，避免阻塞 UI；总是推送最新快照。"""
        # 深拷贝一份快照，避免后续 UI 改动影响保存内容
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
                print("收藏夹已同步到 Cloudflare D1")
            except Exception as e:
                print(f"同步到 D1 失败: {e}")
