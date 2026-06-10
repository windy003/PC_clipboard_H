package com.example.clipboardviewer

import android.content.Context
import android.os.Build
import android.os.Environment

/**
 * 云端 → 本地 自动同步。
 *
 * 检测到云端（Worker）有条目时，把每条内容追加到本地
 * local_3_days_later.txt（带当前时间戳，进入「3 天后」流程），
 * 写入成功后立即从云端删除该条——相当于云端只是中转，数据最终都落到本地。
 *
 * 触发时机：
 *  - 「剪贴板本地」小部件每分钟的后台检查（LocalWidgetProvider.refreshCount）；
 *  - App 打开/手动刷新（MainActivity.refresh）。
 *
 * 需要登录态（token）与「所有文件访问」权限；缺任一项时本次跳过，下次再试。
 * 逐条处理：先写本地、成功后再删云端，中途失败最多造成个别条目重复，不会丢数据。
 */
object CloudSync {
    private const val PREFS = "clipboard_viewer"
    private const val KEY_URL = "worker_url"
    private const val KEY_TOKEN = "token"
    private const val KEY_EXP = "expires_at"

    /**
     * 同步一次（阻塞网络与文件 IO，请在后台线程调用）。
     * 返回本次成功转存到本地的条目数；未登录/无权限/网络失败等返回 0。
     */
    @Synchronized
    fun syncOnce(context: Context): Int {
        // 没有「所有文件访问」权限时写不了本地文件，跳过
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R &&
            !Environment.isExternalStorageManager()
        ) return 0

        val prefs = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
        val url = prefs.getString(KEY_URL, "") ?: ""
        val token = prefs.getString(KEY_TOKEN, "") ?: ""
        val exp = prefs.getLong(KEY_EXP, 0L)
        val loggedIn = url.isNotEmpty() && token.isNotEmpty() &&
            System.currentTimeMillis() / 1000 < exp - 60
        if (!loggedIn) return 0

        val folders = try {
            ClipboardApi.load(url, token)
        } catch (e: Exception) {
            return 0   // 网络失败：下次闹钟再试
        }

        var moved = 0
        for (folder in folders) {
            for (item in folder.items) {
                if (item.text.isBlank() || item.id <= 0) continue
                try {
                    LocalStore.append(item.text)          // 1) 先落地本地
                    ClipboardApi.deleteItem(url, token, item.id)  // 2) 再删云端
                    moved++
                } catch (e: Exception) {
                    // 本条失败即中止本轮，下次闹钟再试。
                    // （若已写本地但删云端失败，下次会多写一条重复，可在列表中手动删除）
                    return moved
                }
            }
        }
        return moved
    }
}
