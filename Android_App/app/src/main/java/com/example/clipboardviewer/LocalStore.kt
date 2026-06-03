package com.example.clipboardviewer

import android.os.Environment
import java.io.File
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

/**
 * 本地「3天后」清单的读写。
 *
 * 文件位置：外部存储根目录 / 1 / local_3_days_later.txt
 * （即 /storage/emulated/0/1/local_3_days_later.txt）
 *
 * 每行一条记录，格式：`内容  2026/6/4  05:41`
 * 行尾时间戳是「加入时间」。条目在加入后 3 天内对 app 隐藏，
 * 满 3 天才会出现在本地列表中（“3 天后再显示”）。
 * 内容中的换行会被替换为空格，保证一条记录占一行，便于按行读取/删除。
 *
 * 注意：写入外部存储根目录需要「所有文件访问」权限（见 MainActivity 的权限处理）。
 */
object LocalStore {
    private const val DIR = "1"
    private const val FILE = "local_3_days_later.txt"

    private const val THREE_DAYS_MS = 3L * 24 * 60 * 60 * 1000

    // 写入用：日期不补零（2026/6/4），时间补零（05:41），与需求示例一致。
    private val WRITE_FMT = SimpleDateFormat("yyyy/M/d  HH:mm", Locale.getDefault())

    // 解析用：单空格分隔，H/HH 都能解析 "05"。
    private val PARSE_FMT = SimpleDateFormat("yyyy/M/d H:mm", Locale.getDefault())

    // 匹配行尾的时间戳，例如 "  2026/6/4  05:41"。
    private val TS_REGEX = Regex("""\s*\d{4}/\d{1,2}/\d{1,2}\s+\d{1,2}:\d{2}\s*$""")

    /** 一条本地记录。index 为文件中的行号（用于删除）；dueAt 为「应显示时间」= 加入时间 + 3 天。 */
    data class LocalEntry(val index: Int, val text: String, val dueAt: Long)

    /** 返回目标文件（必要时创建 `1` 目录）。 */
    fun file(): File {
        val dir = File(Environment.getExternalStorageDirectory(), DIR)
        if (!dir.exists()) dir.mkdirs()
        return File(dir, FILE)
    }

    /** 追加一条记录，自动附上当前日期时间戳（加入后 3 天内隐藏）。 */
    fun append(text: String) {
        val oneLine = text.replace("\r", " ").replace("\n", " ").trim()
        val line = "$oneLine  ${WRITE_FMT.format(Date())}"
        file().appendText(line + "\n", Charsets.UTF_8)
    }

    /** 读取所有非空行。 */
    fun readLines(): List<String> {
        val f = file()
        if (!f.exists()) return emptyList()
        return f.readLines(Charsets.UTF_8).filter { it.isNotBlank() }
    }

    /** 解析所有记录（含未到期的）。index 与 readLines 的顺序一致。 */
    fun readEntries(): List<LocalEntry> =
        readLines().mapIndexed { idx, line ->
            val added = parseTimestamp(line)
            // 解析不到时间戳的当作「已到期」（立即显示）。
            val dueAt = if (added > 0) added + THREE_DAYS_MS else 0L
            LocalEntry(idx, stripTimestamp(line), dueAt)
        }

    /** 只返回已到期（满 3 天）的记录——即本地列表应显示的内容。 */
    fun dueEntries(): List<LocalEntry> {
        val now = System.currentTimeMillis()
        return readEntries().filter { now >= it.dueAt }
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

    /** 去掉一行末尾的时间戳，得到原始内容。 */
    fun stripTimestamp(line: String): String = line.replace(TS_REGEX, "").trim()

    /** 解析行尾时间戳为毫秒；解析失败返回 0。 */
    private fun parseTimestamp(line: String): Long {
        val m = TS_REGEX.find(line) ?: return 0L
        val normalized = m.value.trim().replace(Regex("""\s+"""), " ")
        return try {
            PARSE_FMT.parse(normalized)?.time ?: 0L
        } catch (e: Exception) {
            0L
        }
    }
}
