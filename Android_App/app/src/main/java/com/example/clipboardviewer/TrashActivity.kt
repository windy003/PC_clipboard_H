package com.example.clipboardviewer

import android.Manifest
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.os.Environment
import android.provider.Settings
import android.view.View
import android.widget.Toast
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AlertDialog
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.ContextCompat
import androidx.recyclerview.widget.LinearLayoutManager
import com.example.clipboardviewer.databinding.ActivityTrashBinding

/**
 * 垃圾箱界面：显示 trash.txt 中的条目。
 *
 * 交互与主界面一致的左右滑动：
 *  - 左滑「彻底删除」：从 trash.txt 永久删除该行；
 *  - 右滑「延后3天」：从 trash.txt 删除该行，写回 local_3_days_later.txt（重新等 3 天）。
 *
 * 主界面左滑「删除」的条目会进入这里（见 MainActivity.moveToTrash）。
 */
class TrashActivity : AppCompatActivity() {

    private lateinit var binding: ActivityTrashBinding
    private val adapter = FavAdapter { item -> confirmPurge(item) }

    private val requestWritePermission =
        registerForActivityResult(ActivityResultContracts.RequestPermission()) { granted ->
            if (granted) toast("已授予存储权限，请重新操作") else toast("未授予存储权限，无法写入")
        }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        binding = ActivityTrashBinding.inflate(layoutInflater)
        setContentView(binding.root)

        binding.recyclerView.layoutManager = LinearLayoutManager(this)
        binding.recyclerView.adapter = adapter
        attachSwipe()

        binding.backButton.setOnClickListener { finish() }

        loadTrash()
    }

    // ---------- 滑动手势：左滑彻底删除 / 右滑延后3天放回队列 ----------
    private fun attachSwipe() {
        SwipeUi.attach(
            recyclerView = binding.recyclerView,
            adapter = adapter,
            leftLabel = "彻底删除",   // 左滑：永久删除
            rightLabel = "延后3天",   // 右滑：放回 3 天后队列
            onLeft = { item -> purgeAt(item.id) },
            onRight = { item -> restore(item.id, item.text) },
        )
    }

    // ---------- 读取垃圾箱清单 ----------
    private fun loadTrash() {
        showError(null)
        val entries = try {
            TrashStore.readEntries()
        } catch (e: Exception) {
            showError("读取垃圾箱失败：${e.message}")
            emptyList()
        }

        val rows = mutableListOf<Row>()
        rows.add(Row.Header("垃圾箱  (${entries.size})"))
        for (e in entries) {
            rows.add(Row.Item(e.index, e.text, ""))   // id = trash.txt 的行索引
        }
        adapter.submit(rows)

        binding.statusText.text = "垃圾箱  (${entries.size})"
        showError(if (entries.isEmpty()) "垃圾箱是空的" else null)
    }

    /** 彻底删除 trash.txt 第 index 行。 */
    private fun purgeAt(index: Int) {
        if (!ensureStoragePermission()) return
        try {
            TrashStore.deleteAt(index)
            toast("已彻底删除")
            loadTrash()
        } catch (e: Exception) {
            showError("删除失败：${e.message}")
        }
    }

    /** 从垃圾箱恢复：删掉 trash.txt 该行，写回「3天后」清单（重新等 3 天）。 */
    private fun restore(index: Int, text: String) {
        if (!ensureStoragePermission()) return
        try {
            LocalStore.append(text)
            TrashStore.deleteAt(index)
            toast("已延后到 3 天后")
            loadTrash()
        } catch (e: Exception) {
            showError("操作失败：${e.message}")
        }
    }

    /** 长按条目：确认后彻底删除。 */
    private fun confirmPurge(item: Row.Item) {
        val preview = if (item.text.length > 100) item.text.substring(0, 100) + "…" else item.text
        AlertDialog.Builder(this)
            .setTitle("彻底删除")
            .setMessage(preview)
            .setPositiveButton("彻底删除") { _, _ -> purgeAt(item.id) }
            .setNegativeButton("取消", null)
            .show()
    }

    // ---------- 外部存储写权限 ----------
    private fun hasStoragePermission(): Boolean =
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
            Environment.isExternalStorageManager()
        } else {
            ContextCompat.checkSelfPermission(
                this, Manifest.permission.WRITE_EXTERNAL_STORAGE
            ) == PackageManager.PERMISSION_GRANTED
        }

    /** 确保有写外部存储权限；没有则发起申请并返回 false。 */
    private fun ensureStoragePermission(): Boolean {
        if (hasStoragePermission()) return true
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
            toast("需要「所有文件访问」权限才能写入外部存储，请在设置中开启后重试")
            try {
                startActivity(
                    Intent(
                        Settings.ACTION_MANAGE_APP_ALL_FILES_ACCESS_PERMISSION,
                        Uri.parse("package:$packageName")
                    )
                )
            } catch (e: Exception) {
                startActivity(Intent(Settings.ACTION_MANAGE_ALL_FILES_ACCESS_PERMISSION))
            }
        } else {
            requestWritePermission.launch(Manifest.permission.WRITE_EXTERNAL_STORAGE)
        }
        return false
    }

    private fun showError(msg: String?) {
        if (msg.isNullOrEmpty()) {
            binding.errorText.visibility = View.GONE
        } else {
            binding.errorText.visibility = View.VISIBLE
            binding.errorText.text = msg
        }
    }

    private fun toast(msg: String) = Toast.makeText(this, msg, Toast.LENGTH_SHORT).show()
}
