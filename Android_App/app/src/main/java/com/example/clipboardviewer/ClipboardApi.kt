package com.example.clipboardviewer

import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL

/** 一条收藏。 */
data class FavItem(val text: String, val description: String)

/** 一个收藏夹及其条目。 */
data class Folder(val name: String, val items: List<FavItem>)

/** 收藏夹概要：名称 + 条目数（用于切换列表）。 */
data class FolderInfo(val name: String, val count: Int)

/** Worker 返回的业务错误（带 HTTP 状态码，401 表示未登录/过期）。 */
class ApiException(message: String, val code: Int = 0) : Exception(message)

/**
 * 访问 Cloudflare Worker 的最小客户端：登录换 token、查询收藏夹列表、拉取收藏夹内容。
 * 只用 JDK 自带的 HttpURLConnection + org.json，无第三方网络依赖。
 *
 * 这些方法会阻塞网络，请在后台线程（Dispatchers.IO）调用。
 */
object ClipboardApi {
    // 带浏览器 UA：Cloudflare 边缘会拦截脚本默认 UA（错误码 1010）。
    private const val UA =
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 " +
            "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

    /** 去掉末尾斜杠，便于拼接路径。 */
    fun normalizeUrl(url: String): String = url.trim().trimEnd('/')

    private fun post(urlStr: String, body: String, token: String?): JSONObject {
        val conn = (URL(urlStr).openConnection() as HttpURLConnection).apply {
            requestMethod = "POST"
            connectTimeout = 15000
            readTimeout = 15000
            doOutput = true
            setRequestProperty("Content-Type", "application/json")
            setRequestProperty("User-Agent", UA)
            if (token != null) setRequestProperty("Authorization", "Bearer $token")
        }
        try {
            conn.outputStream.use { it.write(body.toByteArray(Charsets.UTF_8)) }
            val code = conn.responseCode
            val stream = if (code in 200..299) conn.inputStream else conn.errorStream
            val text = stream?.bufferedReader(Charsets.UTF_8)?.use { it.readText() } ?: ""
            val json = if (text.trimStart().startsWith("{")) JSONObject(text) else JSONObject()
            if (code !in 200..299) {
                throw ApiException(json.optString("error", "HTTP $code"), code)
            }
            return json
        } finally {
            conn.disconnect()
        }
    }

    /** 登录，返回 (token, 过期时间秒)。失败抛 ApiException。 */
    fun login(workerUrl: String, username: String, password: String): Pair<String, Long> {
        val body = JSONObject().put("username", username).put("password", password).toString()
        val json = post("${normalizeUrl(workerUrl)}/login", body, null)
        if (!json.optBoolean("ok")) throw ApiException(json.optString("error", "登录失败"))
        return json.getString("token") to json.optLong("expires_at", 0L)
    }

    /** 查询所有收藏夹名及条目数。失败抛 ApiException。 */
    fun listFolders(workerUrl: String, token: String): List<FolderInfo> {
        val json = post("${normalizeUrl(workerUrl)}/folders", "{}", token)
        if (!json.optBoolean("ok")) throw ApiException(json.optString("error", "获取收藏夹失败"))
        val arr = json.optJSONArray("folders") ?: return emptyList()
        val list = mutableListOf<FolderInfo>()
        for (i in 0 until arr.length()) {
            val o = arr.optJSONObject(i) ?: continue
            list.add(FolderInfo(o.optString("name", ""), o.optInt("count", 0)))
        }
        return list
    }

    /**
     * 拉取收藏夹内容。folder 为 null 时返回全部收藏夹，否则只返回该收藏夹。
     * 失败抛 ApiException（401 表示需重新登录）。
     */
    fun load(workerUrl: String, token: String, folder: String? = null): List<Folder> {
        val body = if (folder.isNullOrEmpty()) "{}" else JSONObject().put("folder", folder).toString()
        val json = post("${normalizeUrl(workerUrl)}/load", body, token)
        if (!json.optBoolean("ok")) throw ApiException(json.optString("error", "读取失败"))
        val favs = json.optJSONObject("favorites") ?: JSONObject()
        val folders = mutableListOf<Folder>()
        for (name in favs.keys()) {
            val arr = favs.optJSONArray(name) ?: continue
            val items = mutableListOf<FavItem>()
            for (i in 0 until arr.length()) {
                val o = arr.optJSONObject(i) ?: continue
                items.add(FavItem(o.optString("text", ""), o.optString("description", "")))
            }
            folders.add(Folder(name, items))
        }
        return folders
    }
}
