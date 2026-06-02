package com.example.clipboardviewer

import android.app.AlarmManager
import android.app.PendingIntent
import android.appwidget.AppWidgetManager
import android.appwidget.AppWidgetProvider
import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.os.SystemClock
import android.view.View
import android.widget.RemoteViews
import kotlin.concurrent.thread

/**
 * 主屏小部件：每分钟检查一次服务器，显示「记忆」收藏夹的条目数。
 *
 * 三行：
 *  - d1剪贴板（橙色，固定标题）
 *  - N个（红色，条目数）
 *  - X分钟前（绿色，距上次成功检查的时间）
 *
 * 系统小部件自带的 updatePeriodMillis 最短只能 30 分钟，无法满足“每分钟”，
 * 因此用 AlarmManager 每 60 秒发一次广播触发刷新。登录态/Worker 地址复用
 * 主界面写入的同一份 SharedPreferences。
 */
class MemoryWidgetProvider : AppWidgetProvider() {

    override fun onEnabled(context: Context) {
        // 第一个小部件被添加：启动每分钟的定时检查
        scheduleAlarm(context)
        refreshCount(context)
    }

    override fun onDisabled(context: Context) {
        // 最后一个小部件被移除：停止定时检查
        cancelAlarm(context)
    }

    override fun onUpdate(context: Context, mgr: AppWidgetManager, ids: IntArray) {
        // 系统周期更新（兜底，约 30 分钟一次，也用于重启后自愈）：确保闹钟在跑并刷新
        scheduleAlarm(context)
        refreshCount(context)
    }

    override fun onReceive(context: Context, intent: Intent) {
        super.onReceive(context, intent)
        if (intent.action == ACTION_REFRESH) {
            refreshCount(context)
        }
    }

    /** 后台拉取「记忆」条目数，写入缓存后刷新所有小部件实例。 */
    private fun refreshCount(context: Context) {
        val pending = goAsync()
        thread {
            val prefs = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
            try {
                val url = prefs.getString(KEY_URL, "") ?: ""
                val token = prefs.getString(KEY_TOKEN, "") ?: ""
                val exp = prefs.getLong(KEY_EXP, 0L)
                val loggedIn = url.isNotEmpty() && token.isNotEmpty() &&
                    System.currentTimeMillis() / 1000 < exp - 60
                if (loggedIn) {
                    val infos = ClipboardApi.listFolders(url, token)
                    val count = infos.firstOrNull { it.name == MEMORY_FOLDER }?.count ?: 0
                    // 仅在成功时更新条目数与“上次检查时间”
                    prefs.edit()
                        .putInt(KEY_WIDGET_COUNT, count)
                        .putLong(KEY_WIDGET_TIME, System.currentTimeMillis())
                        .apply()
                }
            } catch (e: Exception) {
                // 网络失败/未登录：保留上次缓存，仅刷新“分钟前”显示
            } finally {
                updateAllWidgets(context)
                pending.finish()
            }
        }
    }

    /** 用缓存的数据重绘所有小部件实例。 */
    private fun updateAllWidgets(context: Context) {
        val mgr = AppWidgetManager.getInstance(context)
        val ids = mgr.getAppWidgetIds(ComponentName(context, MemoryWidgetProvider::class.java))
        if (ids.isEmpty()) return

        val prefs = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
        val hasData = prefs.contains(KEY_WIDGET_TIME)
        val count = prefs.getInt(KEY_WIDGET_COUNT, 0)
        val lastTime = prefs.getLong(KEY_WIDGET_TIME, 0L)

        val token = prefs.getString(KEY_TOKEN, "") ?: ""
        val exp = prefs.getLong(KEY_EXP, 0L)
        val loggedIn = token.isNotEmpty() && System.currentTimeMillis() / 1000 < exp - 60

        val countText = if (!loggedIn && !hasData) "未登录" else "${count}个"

        for (id in ids) {
            val views = RemoteViews(context.packageName, R.layout.memory_widget)
            views.setTextViewText(R.id.widget_title, "d1剪贴板")
            views.setTextViewText(R.id.widget_count, countText)

            if (hasData) {
                // 第三行：用 Chronometer 实时跳动显示“距上次检查过了多久”。
                // base 用 elapsedRealtime 基准：把上次检查的墙钟时刻换算成对应的开机计时，
                // 这样桌面会每秒自动 +1；每次成功检查后 lastTime 更新，秒数自动归零重新计。
                val elapsed = System.currentTimeMillis() - lastTime
                val base = SystemClock.elapsedRealtime() - elapsed
                views.setChronometer(R.id.widget_chrono, base, "%s前", true)
                views.setViewVisibility(R.id.widget_chrono, View.VISIBLE)
                views.setViewVisibility(R.id.widget_status, View.GONE)
            } else {
                // 还没有任何数据：停掉计时器，显示占位文字
                views.setChronometer(R.id.widget_chrono, SystemClock.elapsedRealtime(), null, false)
                views.setViewVisibility(R.id.widget_chrono, View.GONE)
                views.setViewVisibility(R.id.widget_status, View.VISIBLE)
                views.setTextViewText(R.id.widget_status, if (loggedIn) "等待检查" else "未登录")
            }

            // 点击整块小部件立即刷新
            views.setOnClickPendingIntent(R.id.widget_root, refreshPendingIntent(context))
            mgr.updateAppWidget(id, views)
        }
    }

    // ---------- 定时器 ----------
    private fun refreshPendingIntent(context: Context): PendingIntent {
        val intent = Intent(context, MemoryWidgetProvider::class.java).apply { action = ACTION_REFRESH }
        val flags = PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        return PendingIntent.getBroadcast(context, 0, intent, flags)
    }

    private fun scheduleAlarm(context: Context) {
        val am = context.getSystemService(Context.ALARM_SERVICE) as AlarmManager
        // 用不精确的可重复闹钟，每 60 秒触发一次（系统可能小幅批处理，足够使用）
        am.setRepeating(
            AlarmManager.ELAPSED_REALTIME_WAKEUP,
            SystemClock.elapsedRealtime() + INTERVAL_MS,
            INTERVAL_MS,
            refreshPendingIntent(context)
        )
    }

    private fun cancelAlarm(context: Context) {
        val am = context.getSystemService(Context.ALARM_SERVICE) as AlarmManager
        am.cancel(refreshPendingIntent(context))
    }

    companion object {
        private const val ACTION_REFRESH = "com.example.clipboardviewer.WIDGET_REFRESH"
        private const val INTERVAL_MS = 60_000L   // 每分钟检查一次

        // 与 MainActivity 共用的登录态
        private const val PREFS = "clipboard_viewer"
        private const val KEY_URL = "worker_url"
        private const val KEY_TOKEN = "token"
        private const val KEY_EXP = "expires_at"
        private const val MEMORY_FOLDER = "记忆"

        // 小部件自身的缓存
        private const val KEY_WIDGET_COUNT = "widget_memory_count"
        private const val KEY_WIDGET_TIME = "widget_memory_time"
    }
}
