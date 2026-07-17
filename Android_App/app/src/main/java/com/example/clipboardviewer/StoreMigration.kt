package com.example.clipboardviewer

import android.os.Build
import android.os.Environment
import java.io.File

/**
 * 一次性数据迁移：把旧位置的本地清单搬到新目录。
 *
 * 旧位置：外部存储根目录 / 1 / *.txt
 * 新位置：外部存储根目录 / 1 / clipboard_to_remember / *.txt
 *
 * 设计要点：
 *  - 不用「已迁移」标记位，靠「旧文件是否还在」判断——搬完即删旧文件，
 *    下次启动 src 不存在自动跳过，天然幂等、可自愈。
 *  - Android 11+ 无「所有文件访问」权限时读不到根目录，直接返回，
 *    等授权后下次启动再补搬（不会被标记卡死）。
 *  - 搬运优先 renameTo（同盘瞬移），失败退回复制+删除。
 *  - 目标已存在时不覆盖，改为「旧内容在前 + 新内容在后」合并，保持条目生成顺序。
 *
 * trash.txt 为新功能、旧位置不存在，无需迁移。
 */
object StoreMigration {
    private const val OLD_DIR = "1"
    private const val NEW_DIR = "1/clipboard_to_remember"
    private val FILES = listOf("local_3_days_later.txt", "ready_to_release.txt")

    /** App 启动时调用（幂等）。搬运出错时静默忽略，下次启动再试。 */
    fun migrateIfNeeded() {
        // 无权限则读不到根目录，先返回，等授权后下次补搬
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R &&
            !Environment.isExternalStorageManager()
        ) return

        val root = Environment.getExternalStorageDirectory()
        val oldDir = File(root, OLD_DIR)
        val newDir = File(root, NEW_DIR)
        if (!newDir.exists()) newDir.mkdirs()

        for (name in FILES) {
            val src = File(oldDir, name)
            if (!src.exists()) continue
            val dst = File(newDir, name)
            try {
                if (!dst.exists()) {
                    // 目标不存在：优先瞬移，失败退回复制+删除
                    if (!src.renameTo(dst)) {
                        dst.writeText(src.readText(Charsets.UTF_8), Charsets.UTF_8)
                        src.delete()
                    }
                } else {
                    // 目标已存在：合并（旧在前、新在后），再删旧文件
                    val merged = src.readText(Charsets.UTF_8) + dst.readText(Charsets.UTF_8)
                    dst.writeText(merged, Charsets.UTF_8)
                    src.delete()
                }
            } catch (e: Exception) {
                // 单个文件失败不影响其它文件；下次启动会再试
            }
        }
    }
}
