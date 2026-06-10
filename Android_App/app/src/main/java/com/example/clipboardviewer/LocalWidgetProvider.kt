package com.example.clipboardviewer

import android.app.AlarmManager
import android.app.PendingIntent
import android.appwidget.AppWidgetManager
import android.appwidget.AppWidgetProvider
import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.graphics.Color
import android.os.Build
import android.os.Bundle
import android.os.SystemClock
import android.text.SpannableString
import android.text.Spanned
import android.text.style.ForegroundColorSpan
import android.util.TypedValue
import android.view.View
import android.widget.RemoteViews
import kotlin.concurrent.thread

/**
 * 主屏小部件：每分钟做一次后台检查，显示本地「已发布」的条目数。
 *
 * 每次检查依次完成三件事：
 *  1. CloudSync.syncOnce —— 云端「记忆」夹有数据则转存到 local_3_days_later.txt 并删云端
 *     （仅限「记忆」夹，其它收藏夹是 PC 端的长期数据，不能动）；
 *  2. ReleaseStore.runDailyCheck —— 每天 8:00 把满 3 天的条目移入待发布清单并排程
 *     （幂等，错过 8:00 自动补跑）；
 *  3. 统计 ReleaseStore.releasedEntries() —— 发布时间已到的条目数，显示在小部件上。
 *
 * 三行布局（复用 memory_widget.xml）：
 *  - 剪贴板本地（橙色，固定标题）
 *  - N个（数字红色 + “个”绿色，已发布条目数）
 *  - X分钟前（红色计时器 + 蓝色“前”，距上次检查的时间）
 *
 * 系统小部件自带的 updatePeriodMillis 最短只能 30 分钟，无法满足“每分钟”，
 * 因此用 AlarmManager 每 60 秒触发一次刷新，Chronometer 每秒自动 +1。
 */
class LocalWidgetProvider : AppWidgetProvider() {

    override fun onEnabled(context: Context) {
        // 第一个小部件被添加：立即检查一次（检查完成后会自动排下一次闹钟）
        refreshCount(context)
    }

    override fun onDisabled(context: Context) {
        // 最后一个小部件被移除：停止定时检查
        cancelAlarm(context)
    }

    override fun onUpdate(context: Context, mgr: AppWidgetManager, ids: IntArray) {
        // 系统周期更新（兜底，约 30 分钟一次，也用于重启后自愈）：刷新并重排闹钟链
        refreshCount(context)
    }

    override fun onReceive(context: Context, intent: Intent) {
        super.onReceive(context, intent)
        when (intent.action) {
            ACTION_REFRESH -> refreshCount(context)          // 闹钟/自身触发：后台读取
            ACTION_REDRAW -> updateAllWidgets(context)        // App 已写入数据：只重绘
        }
    }

    override fun onAppWidgetOptionsChanged(
        context: Context,
        mgr: AppWidgetManager,
        id: Int,
        newOptions: Bundle
    ) {
        // 用户调整小部件大小后，按新高度重新计算字号并重绘
        updateAllWidgets(context)
    }

    /** 后台执行：云端转存 → 每日 8:00 检查 → 统计已发布条目数，刷新小部件并排下一次闹钟。 */
    private fun refreshCount(context: Context) {
        val pending = goAsync()
        thread {
            val prefs = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
            try {
                // 1) 云端有数据则自动转存到本地（未登录/无权限/网络失败时内部直接跳过）
                try {
                    CloudSync.syncOnce(context)
                } catch (e: Exception) {
                    // 忽略，下次再试
                }
                // 2) 每日 8:00 检查：满 3 天的条目移入待发布清单并排程（幂等）
                try {
                    ReleaseStore.runDailyCheck(context)
                } catch (e: Exception) {
                    // 忽略，下次再试
                }
                val now = System.currentTimeMillis()
                // 3) 统计「发布时间已到」的条目数
                val count = try {
                    ReleaseStore.releasedEntries().size
                } catch (e: Exception) {
                    // 读取失败（如暂无权限）：沿用上次条目数
                    prefs.getInt(KEY_WIDGET_COUNT, 0)
                }
                // 每次检查都更新条目数与“上次检查时间”（计时器归零）
                prefs.edit()
                    .putInt(KEY_WIDGET_COUNT, count)
                    .putLong(KEY_WIDGET_TIME, now)
                    .apply()
            } finally {
                updateAllWidgets(context)
                scheduleNextAlarm(context)   // 链式排下一次检查
                pending.finish()
            }
        }
    }

    /** 用缓存的数据重绘所有小部件实例。 */
    private fun updateAllWidgets(context: Context) {
        val mgr = AppWidgetManager.getInstance(context)
        val ids = mgr.getAppWidgetIds(ComponentName(context, LocalWidgetProvider::class.java))
        if (ids.isEmpty()) return

        val prefs = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
        val hasData = prefs.contains(KEY_WIDGET_TIME)
        val count = prefs.getInt(KEY_WIDGET_COUNT, 0)
        val lastTime = prefs.getLong(KEY_WIDGET_TIME, 0L)

        val countText = "${count}个"

        for (id in ids) {
            val views = RemoteViews(context.packageName, R.layout.memory_widget)
            views.setTextViewText(R.id.widget_title, WIDGET_TITLE)
            // 第二行：数字红色、“个”绿色
            views.setTextViewText(R.id.widget_count, colorizeCount(countText))

            val thirdText: String
            if (hasData) {
                // 第三行：用 Chronometer 实时跳动显示“距上次检查过了多久”，每秒自动 +1。
                val elapsed = System.currentTimeMillis() - lastTime
                val base = SystemClock.elapsedRealtime() - elapsed
                views.setChronometer(R.id.widget_chrono, base, "%s", true)
                views.setViewVisibility(R.id.widget_chrono_row, View.VISIBLE)
                views.setViewVisibility(R.id.widget_status, View.GONE)
                thirdText = "00:00前"   // 用于按宽度估算字号
            } else {
                // 还没有任何数据：隐藏计时器行，显示占位文字
                views.setChronometer(R.id.widget_chrono, SystemClock.elapsedRealtime(), null, false)
                views.setViewVisibility(R.id.widget_chrono_row, View.GONE)
                views.setViewVisibility(R.id.widget_status, View.VISIBLE)
                views.setTextViewText(R.id.widget_status, "等待检查")
                thirdText = "等待检查"
            }

            // 测量小部件宽高，每行字号取 min(行高, 宽度可容纳)，尽量大且不溢出
            applyRowHeightSizes(views, mgr, id, WIDGET_TITLE, countText, thirdText)

            // 点击整块小部件打开 App 主页
            views.setOnClickPendingIntent(R.id.widget_root, openAppPendingIntent(context))
            mgr.updateAppWidget(id, views)
        }
    }

    /**
     * 测量小部件宽高（dp），分成 3 行。每行字号 = min(行高, 该行文字按宽度能容纳的最大字号)，
     * 既让文字尽量大填满高度，又保证每行文字宽度不超过小部件宽度（不溢出/不截断）。
     */
    private fun applyRowHeightSizes(
        views: RemoteViews,
        mgr: AppWidgetManager,
        id: Int,
        titleText: String,
        countText: String,
        thirdText: String
    ) {
        val opts = mgr.getAppWidgetOptions(id)
        val hMax = opts.getInt(AppWidgetManager.OPTION_APPWIDGET_MAX_HEIGHT, 0)
        val hMin = opts.getInt(AppWidgetManager.OPTION_APPWIDGET_MIN_HEIGHT, 0)
        val heightDp = maxOf(hMax, hMin).let { if (it > 0) it else 110 }
        val wMin = opts.getInt(AppWidgetManager.OPTION_APPWIDGET_MIN_WIDTH, 0)
        val widthDp = (if (wMin > 0) wMin else 60).toFloat() - 4f  // 减去内边距余量

        val rowSize = heightDp / 3f * 0.78f

        fun fitByWidth(text: String): Float {
            var units = 0f
            for (c in text) {
                units += when {
                    c.code >= 0x2E80 -> 1.0f          // 中文/全角
                    c in '0'..'9' -> 0.58f            // 数字
                    c == ':' || c == '.' || c == ' ' -> 0.32f
                    else -> 0.6f                       // 其它半角字符
                }
            }
            if (units < 0.5f) units = 0.5f
            return widthDp / units
        }

        fun sizeFor(text: String) = minOf(rowSize, fitByWidth(text))

        views.setTextViewTextSize(R.id.widget_title, TypedValue.COMPLEX_UNIT_DIP, sizeFor(titleText))
        views.setTextViewTextSize(R.id.widget_count, TypedValue.COMPLEX_UNIT_DIP, sizeFor(countText))
        val thirdSize = sizeFor(thirdText)
        views.setTextViewTextSize(R.id.widget_chrono, TypedValue.COMPLEX_UNIT_DIP, thirdSize)
        views.setTextViewTextSize(R.id.widget_suffix, TypedValue.COMPLEX_UNIT_DIP, thirdSize)
        views.setTextViewTextSize(R.id.widget_status, TypedValue.COMPLEX_UNIT_DIP, thirdSize)
    }

    /** 把 "N个" 着色为：数字红色、“个”绿色。 */
    private fun colorizeCount(text: String): CharSequence {
        val sp = SpannableString(text)
        if (text.endsWith("个") && text.length >= 2) {
            val splitAt = text.length - 1
            sp.setSpan(ForegroundColorSpan(Color.parseColor("#F44336")), 0, splitAt,
                Spanned.SPAN_EXCLUSIVE_EXCLUSIVE)                     // 数字红
            sp.setSpan(ForegroundColorSpan(Color.parseColor("#4CAF50")), splitAt, text.length,
                Spanned.SPAN_EXCLUSIVE_EXCLUSIVE)                     // “个”绿
        } else {
            sp.setSpan(ForegroundColorSpan(Color.parseColor("#F44336")), 0, text.length,
                Spanned.SPAN_EXCLUSIVE_EXCLUSIVE)
        }
        return sp
    }

    /** 点击小部件打开 App 主页（本地清单）。 */
    private fun openAppPendingIntent(context: Context): PendingIntent {
        val intent = Intent(context, MainActivity::class.java).apply {
            flags = Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP or
                Intent.FLAG_ACTIVITY_SINGLE_TOP
        }
        val flags = PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        return PendingIntent.getActivity(context, 1, intent, flags)
    }

    // ---------- 定时器 ----------
    private fun refreshPendingIntent(context: Context): PendingIntent {
        val intent = Intent(context, LocalWidgetProvider::class.java).apply { action = ACTION_REFRESH }
        val flags = PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        return PendingIntent.getBroadcast(context, 1, intent, flags)
    }

    /**
     * 排下一次（60 秒后）的一次性闹钟。每次检查完成后再排下一次。
     * 尽量用“精确 + 允许 Doze”模式；无精确闹钟权限时退回允许 Doze 的非精确闹钟。
     */
    private fun scheduleNextAlarm(context: Context) {
        val am = context.getSystemService(Context.ALARM_SERVICE) as AlarmManager
        val triggerAt = SystemClock.elapsedRealtime() + INTERVAL_MS
        val pi = refreshPendingIntent(context)
        try {
            when {
                Build.VERSION.SDK_INT >= Build.VERSION_CODES.S && !am.canScheduleExactAlarms() ->
                    am.setAndAllowWhileIdle(AlarmManager.ELAPSED_REALTIME_WAKEUP, triggerAt, pi)
                Build.VERSION.SDK_INT >= Build.VERSION_CODES.M ->
                    am.setExactAndAllowWhileIdle(AlarmManager.ELAPSED_REALTIME_WAKEUP, triggerAt, pi)
                else ->
                    am.setExact(AlarmManager.ELAPSED_REALTIME_WAKEUP, triggerAt, pi)
            }
        } catch (e: SecurityException) {
            am.setAndAllowWhileIdle(AlarmManager.ELAPSED_REALTIME_WAKEUP, triggerAt, pi)
        }
    }

    private fun cancelAlarm(context: Context) {
        val am = context.getSystemService(Context.ALARM_SERVICE) as AlarmManager
        am.cancel(refreshPendingIntent(context))
    }

    companion object {
        private const val ACTION_REFRESH = "com.example.clipboardviewer.LOCAL_WIDGET_REFRESH"
        private const val ACTION_REDRAW = "com.example.clipboardviewer.LOCAL_WIDGET_REDRAW"
        private const val INTERVAL_MS = 60_000L   // 每分钟检查一次
        private const val WIDGET_TITLE = "剪贴板本地"   // 第一行标题（本地已发布条目数）

        private const val PREFS = "clipboard_viewer"

        /**
         * 供主界面操作本地清单后调用：写入最新「已发布」条目数与当前时间（计时器归零），
         * 并立即重绘小部件（不再触发后台读取）。
         */
        fun pushCountFromApp(context: Context, dueCount: Int) {
            context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit()
                .putInt(KEY_WIDGET_COUNT, dueCount)
                .putLong(KEY_WIDGET_TIME, System.currentTimeMillis())
                .apply()
            val intent = Intent(context, LocalWidgetProvider::class.java).apply {
                action = ACTION_REDRAW
            }
            context.sendBroadcast(intent)
        }

        // 小部件自身的缓存（与云端组件用不同的键，互不影响）
        private const val KEY_WIDGET_COUNT = "widget_local_count"
        private const val KEY_WIDGET_TIME = "widget_local_time"
    }
}
