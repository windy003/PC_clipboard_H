package com.example.clipboardviewer

import android.content.Context
import android.os.Build
import android.os.Environment
import java.io.File
import java.text.SimpleDateFormat
import java.util.Calendar
import java.util.Date
import java.util.Locale

/**
 * 「待发布」清单 ready_to_release.txt 的读写与每日发布排程。
 *
 * 文件位置：外部存储根目录 / 1 / clipboard_to_remember / ready_to_release.txt
 * （即 /storage/emulated/0/1/clipboard_to_remember/ready_to_release.txt）
 *
 * 流程：
 *  1. 每天 8:00 做一次检查（runDailyCheck，幂等；错过 8:00 时下次调用自动补跑）：
 *     把 local_3_days_later.txt 中已满 3 天的条目移入本文件（保留原加入时间戳，
 *     顺序即条目生成顺序）。
 *  2. 移入后统计本文件条目数 N，把 8:00-16:00 这 8 小时均分：
 *     间隔 = 8小时 / N，第 i 条（0 起）的发布时间 = 8:00 + i*间隔，
 *     写到该行行尾（"  =>2026/6/10 09:36"）。
 *  3. App 本地界面只显示「发布时间已到」的条目；未到时间的隐藏。
 *
 * 每天 8:00 都会对文件中剩余的全部条目重新排程（前一天发布了但未处理的条目，
 * 第二天会按新的间隔重新错峰显示）。
 *
 * 行格式：`内容  2026/6/4  05:41  =>2026/6/10 09:36`
 *  - 第一个时间戳是原始加入时间（从 local_3_days_later.txt 带过来）；
 *  - "=>" 后是当天排程的发布时间；尚未排程的行没有该标记，下次 8:00 检查时补上。
 */
object ReleaseStore {
    private const val DIR = "1/clipboard_to_remember"
    private const val FILE = "ready_to_release.txt"

    private const val RELEASE_HOUR = 8                       // 每天 8:00 检查并排程
    private const val WINDOW_MS = 8L * 60 * 60 * 1000        // 8:00-16:00 共 8 小时发布窗口

    private const val PREFS = "clipboard_viewer"
    private const val KEY_LAST_SCHEDULE_DAY = "release_last_schedule_day"

    // 行尾的发布时间标记，例如 "  =>2026/6/10 09:36"
    private val RELEASE_REGEX = Regex("""\s*=>\s*\d{4}/\d{1,2}/\d{1,2}\s+\d{1,2}:\d{2}\s*$""")
    private val WRITE_FMT = SimpleDateFormat("yyyy/M/d HH:mm", Locale.getDefault())
    private val PARSE_FMT = SimpleDateFormat("yyyy/M/d H:mm", Locale.getDefault())
    private val DAY_FMT = SimpleDateFormat("yyyyMMdd", Locale.US)

    /** 一条待发布记录。index 为文件行号（用于删除）；releaseAt 为发布时间，未排程时为 Long.MAX_VALUE。 */
    data class ReleaseEntry(val index: Int, val text: String, val releaseAt: Long)

    /** 返回目标文件（必要时递归创建 `1/clipboard_to_remember` 目录）。 */
    fun file(): File {
        val dir = File(Environment.getExternalStorageDirectory(), DIR)
        if (!dir.exists()) dir.mkdirs()
        return File(dir, FILE)
    }

    /** 读取所有非空原始行。 */
    fun readLines(): List<String> {
        val f = file()
        if (!f.exists()) return emptyList()
        return f.readLines(Charsets.UTF_8).filter { it.isNotBlank() }
    }

    /** 解析所有记录（含未到发布时间的）。index 与 readLines 的顺序一致。 */
    fun readEntries(): List<ReleaseEntry> =
        readLines().mapIndexed { idx, line ->
            val releaseAt = parseReleaseAt(line)
            val text = LocalStore.stripTimestamp(stripReleaseMark(line))
            ReleaseEntry(idx, text, releaseAt)
        }

    /** 只返回「发布时间已到」的记录——即本地列表应显示的内容。 */
    fun releasedEntries(): List<ReleaseEntry> {
        val now = System.currentTimeMillis()
        return readEntries().filter { now >= it.releaseAt }
    }

    /** 删除第 index 行（基于 readLines/readEntries 的索引）。 */
    fun deleteAt(index: Int) {
        val lines = readLines().toMutableList()
        if (index in lines.indices) {
            lines.removeAt(index)
            val content = if (lines.isEmpty()) "" else lines.joinToString("\n") + "\n"
            file().writeText(content, Charsets.UTF_8)
        }
    }

    /**
     * 每日 8:00 检查（幂等，可随时调用）：
     *  - 8:00 之前调用：什么都不做；
     *  - 当天已做过：直接返回；
     *  - 否则：把满 3 天的条目从 local_3_days_later.txt 移入本文件，
     *    再按条目数把 8:00-16:00 均分，给每行写上发布时间。
     *
     * 错过 8:00（比如中午才打开 App）也按当天 8:00 为基准补排，
     * 发布时间已过的条目会立即全部显示出来。
     */
    @Synchronized
    fun runDailyCheck(context: Context) {
        // 没有「所有文件访问」权限时读不到文件，先返回，等授权后再补跑
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R &&
            !Environment.isExternalStorageManager()
        ) return

        val now = System.currentTimeMillis()
        val today8 = Calendar.getInstance().apply {
            set(Calendar.HOUR_OF_DAY, RELEASE_HOUR)
            set(Calendar.MINUTE, 0)
            set(Calendar.SECOND, 0)
            set(Calendar.MILLISECOND, 0)
        }.timeInMillis
        if (now < today8) return

        val dayKey = DAY_FMT.format(Date(today8))
        val prefs = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
        if (prefs.getString(KEY_LAST_SCHEDULE_DAY, "") == dayKey) return

        // 1) 把已满 3 天的条目从本地清单移过来（保留原始时间戳，顺序=生成顺序）
        val promoted = LocalStore.takeDueLines()

        // 2) 对文件中全部条目重新排程：间隔 = 8 小时 / 条目数
        val all = (readLines().map { stripReleaseMark(it) } + promoted.map { it.trim() })
            .filter { it.isNotBlank() }
        if (all.isNotEmpty()) {
            val interval = WINDOW_MS / all.size
            val content = all.mapIndexed { i, line ->
                "$line  =>${WRITE_FMT.format(Date(today8 + i * interval))}"
            }.joinToString("\n") + "\n"
            file().writeText(content, Charsets.UTF_8)
        }

        prefs.edit().putString(KEY_LAST_SCHEDULE_DAY, dayKey).apply()
    }

    /** 去掉一行末尾的发布时间标记。 */
    fun stripReleaseMark(line: String): String = line.replace(RELEASE_REGEX, "").trimEnd()

    /** 解析行尾发布时间为毫秒；未排程（无标记/解析失败）返回 Long.MAX_VALUE（隐藏）。 */
    private fun parseReleaseAt(line: String): Long {
        val m = RELEASE_REGEX.find(line) ?: return Long.MAX_VALUE
        val ts = m.value.trim().removePrefix("=>").trim().replace(Regex("""\s+"""), " ")
        return try {
            PARSE_FMT.parse(ts)?.time ?: Long.MAX_VALUE
        } catch (e: Exception) {
            Long.MAX_VALUE
        }
    }
}
