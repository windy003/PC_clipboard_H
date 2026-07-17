package com.example.clipboardviewer

import android.os.Environment
import java.io.File
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

/**
 * 垃圾箱 trash.txt 的读写。
 *
 * 文件位置：外部存储根目录 / 1 / clipboard_to_remember / trash.txt
 * （即 /storage/emulated/0/1/clipboard_to_remember/trash.txt）
 *
 * 主界面左滑「删除」时，条目会从 ready_to_release.txt 移入本文件（附上移入垃圾箱的
 * 时间戳，格式与 local_3_days_later.txt 一致：`内容  2026/6/4  05:41`）。
 *
 * 垃圾箱界面：
 *  - 左滑「彻底删除」：从本文件永久删除该行；
 *  - 右滑「延后3天」：从本文件删除该行，并写回 local_3_days_later.txt（重新等 3 天）。
 *
 * 内容中的换行会被替换为空格，保证一条记录占一行，便于按行读取/删除。
 * 时间戳解析复用 LocalStore.stripTimestamp。
 */
object TrashStore {
    private const val DIR = "1/clipboard_to_remember"
    private const val FILE = "trash.txt"

    // 写入用：与 LocalStore 一致，日期不补零、时间补零。
    private val WRITE_FMT = SimpleDateFormat("yyyy/M/d  HH:mm", Locale.getDefault())

    /** 垃圾箱里的一条记录。index 为文件行号（用于删除/恢复）。 */
    data class TrashEntry(val index: Int, val text: String)

    /** 返回目标文件（必要时递归创建 `1/clipboard_to_remember` 目录）。 */
    fun file(): File {
        val dir = File(Environment.getExternalStorageDirectory(), DIR)
        if (!dir.exists()) dir.mkdirs()
        return File(dir, FILE)
    }

    /** 追加一条记录到垃圾箱，自动附上当前移入时间戳。 */
    fun append(text: String) {
        val oneLine = text.replace("\r", " ").replace("\n", " ").trim()
        val line = "$oneLine  ${WRITE_FMT.format(Date())}"
        file().appendText(line + "\n", Charsets.UTF_8)
    }

    /** 读取所有非空原始行。 */
    fun readLines(): List<String> {
        val f = file()
        if (!f.exists()) return emptyList()
        return f.readLines(Charsets.UTF_8).filter { it.isNotBlank() }
    }

    /** 解析所有记录（去掉行尾时间戳，只保留内容）。index 与 readLines 顺序一致。 */
    fun readEntries(): List<TrashEntry> =
        readLines().mapIndexed { idx, line ->
            TrashEntry(idx, LocalStore.stripTimestamp(line))
        }

    /** 彻底删除第 index 行（基于 readLines/readEntries 的索引）。 */
    fun deleteAt(index: Int) {
        val lines = readLines().toMutableList()
        if (index in lines.indices) {
            lines.removeAt(index)
            val content = if (lines.isEmpty()) "" else lines.joinToString("\n") + "\n"
            file().writeText(content, Charsets.UTF_8)
        }
    }
}
