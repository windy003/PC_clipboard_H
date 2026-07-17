package com.example.clipboardviewer

import android.Manifest
import android.content.Context
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
import androidx.lifecycle.lifecycleScope
import androidx.recyclerview.widget.LinearLayoutManager
import com.example.clipboardviewer.databinding.ActivityMainBinding
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

/**
 * 主界面：只显示本地「已发布」条目。
 *
 * 数据流（云端界面已取消，云端数据自动落地）：
 *  1. 云端 Worker 有数据时（小部件每分钟检查 / 本页刷新），自动转存到
 *     local_3_days_later.txt 并从云端删除（CloudSync）；
 *  2. 每天 8:00 把满 3 天的条目移入 ready_to_release.txt，并按
 *     「8小时 / 条目数」的间隔在 8:00-16:00 之间排程（ReleaseStore）；
 *  3. 本页只显示发布时间已到的条目。左滑删除，右滑重新延后 3 天。
 *
 * 登录只为给自动同步提供云端 token，登录后界面上没有云端内容。
 */
class MainActivity : AppCompatActivity() {

    private lateinit var binding: ActivityMainBinding
    private val adapter = FavAdapter { item -> confirmDelete(item) }

    private val prefs by lazy { getSharedPreferences(PREFS, Context.MODE_PRIVATE) }

    // 默认填上你的 Worker 地址，按需修改。
    private val defaultUrl = "https://clipboard-fav-worker.mybrowser.workers.dev"

    // Android 10 及以下：运行时申请写外部存储权限
    private val requestWritePermission =
        registerForActivityResult(ActivityResultContracts.RequestPermission()) { granted ->
            if (granted) toast("已授予存储权限，请重新操作") else toast("未授予存储权限，无法写入")
        }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        binding = ActivityMainBinding.inflate(layoutInflater)
        setContentView(binding.root)

        // 一次性把旧位置 /1/*.txt 搬到 /1/clipboard_to_remember/（幂等，无权限时下次补搬）
        try {
            StoreMigration.migrateIfNeeded()
        } catch (e: Exception) {
            // 迁移失败不阻塞启动，下次再试
        }

        binding.recyclerView.layoutManager = LinearLayoutManager(this)
        binding.recyclerView.adapter = adapter
        attachSwipe()

        binding.urlInput.setText(prefs.getString(KEY_URL, defaultUrl))
        binding.userInput.setText(prefs.getString(KEY_USER, ""))

        binding.loginButton.setOnClickListener { doLogin() }
        binding.refreshButton.setOnClickListener { refresh() }
        binding.logoutButton.setOnClickListener { logout() }
        binding.trashButton.setOnClickListener { openTrash() }

        if (hasValidToken()) {
            showContent()
            refresh()
        } else {
            showLogin()
        }
    }

    /** 从小部件再次进入时刷新一遍。 */
    override fun onNewIntent(intent: Intent?) {
        super.onNewIntent(intent)
        if (hasValidToken()) refresh()
    }

    // ---------- 登录态 ----------
    private fun hasValidToken(): Boolean {
        val token = prefs.getString(KEY_TOKEN, "") ?: ""
        val exp = prefs.getLong(KEY_EXP, 0L)
        return token.isNotEmpty() && System.currentTimeMillis() / 1000 < exp - 60
    }

    private fun doLogin() {
        val url = binding.urlInput.text.toString().trim()
        val user = binding.userInput.text.toString().trim()
        val pass = binding.passInput.text.toString()
        if (url.isEmpty() || user.isEmpty() || pass.isEmpty()) {
            toast("请填写地址、账号和密码")
            return
        }
        setLoading(true)
        showError(null)
        lifecycleScope.launch {
            try {
                val (token, exp) = withContext(Dispatchers.IO) {
                    ClipboardApi.login(url, user, pass)
                }
                prefs.edit()
                    .putString(KEY_URL, ClipboardApi.normalizeUrl(url))
                    .putString(KEY_USER, user)
                    .putString(KEY_TOKEN, token)
                    .putLong(KEY_EXP, exp)
                    .apply()
                binding.passInput.setText("")
                showContent()
                refresh()
            } catch (e: Exception) {
                showError("登录失败：${e.message}")
            } finally {
                setLoading(false)
            }
        }
    }

    private fun logout() {
        prefs.edit().remove(KEY_TOKEN).remove(KEY_EXP).apply()
        adapter.submit(emptyList())
        showLogin()
    }

    // ---------- 刷新：云端转存 + 每日检查 + 重新读取本地清单 ----------
    private fun refresh() {
        if (!hasValidToken()) {
            toast("登录已过期，请重新登录")
            logout()
            return
        }
        setLoading(true)
        showError(null)
        lifecycleScope.launch {
            // 1) 云端有数据则转存到本地（网络 IO，放后台线程）
            val moved = withContext(Dispatchers.IO) {
                try {
                    CloudSync.syncOnce(this@MainActivity)
                } catch (e: Exception) {
                    0
                }
            }
            if (moved > 0) toast("已从云端转存 $moved 条到本地")
            // 2) 每日 8:00 检查（幂等）+ 显示本地清单
            setLoading(false)
            loadLocalData()
        }
    }

    // ---------- 滑动手势：左滑移入垃圾箱 / 右滑重新延后3天 ----------
    private fun attachSwipe() {
        SwipeUi.attach(
            recyclerView = binding.recyclerView,
            adapter = adapter,
            leftLabel = "删除",       // 左滑：移入垃圾箱
            rightLabel = "延后3天",   // 右滑：重新等 3 天
            onLeft = { item -> moveToTrash(item.id, item.text) },
            onRight = { item -> snoozeLocal(item.id, item.text) },
        )
    }

    // ---------- 本地清单 ----------
    /**
     * 先跑每日 8:00 检查（幂等：满 3 天的条目移入待发布清单并排程），
     * 再只显示「发布时间已到」的条目。
     */
    private fun loadLocalData() {
        showError(null)
        try {
            ReleaseStore.runDailyCheck(this)
        } catch (e: Exception) {
            // 无权限等：忽略，下面读取时会再报错
        }
        val entries = try {
            ReleaseStore.readEntries()
        } catch (e: Exception) {
            showError("读取本地文件失败：${e.message}")
            emptyList()
        }
        val now = System.currentTimeMillis()
        val released = entries.filter { now >= it.releaseAt }   // 已发布，显示
        val pending = entries.size - released.size               // 已排程未到时间，隐藏
        val waiting3 = try {
            LocalStore.readLines().size                          // 还没满 3 天的条目
        } catch (e: Exception) {
            0
        }

        // 把「已发布」条目数推送到桌面「剪贴板本地」小部件，并让其计时器归零
        LocalWidgetProvider.pushCountFromApp(this, released.size)

        val rows = mutableListOf<Row>()
        rows.add(Row.Header("已发布  (${released.size})"))
        for (e in released) {
            // 界面上只显示内容，不显示时间戳（时间戳仅保留在 txt 文件中）
            rows.add(Row.Item(e.index, e.text, ""))        // id = 文件行索引，用于删除/延后
        }
        adapter.submit(rows)

        val parts = mutableListOf("已发布 ${released.size} 条")
        if (pending > 0) parts.add("$pending 条待发布")
        if (waiting3 > 0) parts.add("$waiting3 条等待满3天")
        binding.statusText.text = parts.joinToString("，")
        showError(if (released.isEmpty()) "暂时没有已发布的条目" else null)
    }

    /** 把已发布条目重新延后 3 天：从待发布清单删掉，再写回「3天后」清单（带当前时间戳）。 */
    private fun snoozeLocal(index: Int, text: String) {
        if (!ensureStoragePermission()) return
        try {
            ReleaseStore.deleteAt(index)
            LocalStore.append(text)
            toast("已延后到 3 天后")
            loadLocalData()
        } catch (e: Exception) {
            showError("操作失败：${e.message}")
        }
    }

    /** 把待发布清单第 index 行移入垃圾箱（从 ready_to_release.txt 删除，写入 trash.txt）。 */
    private fun moveToTrash(index: Int, text: String) {
        if (!ensureStoragePermission()) return
        try {
            TrashStore.append(text)
            ReleaseStore.deleteAt(index)
            toast("已移入垃圾箱")
            loadLocalData()
        } catch (e: Exception) {
            showError("删除失败：${e.message}")
        }
    }

    /** 长按条目：确认后移入垃圾箱。 */
    private fun confirmDelete(item: Row.Item) {
        val preview = if (item.text.length > 100) item.text.substring(0, 100) + "…" else item.text
        AlertDialog.Builder(this)
            .setTitle("移入垃圾箱")
            .setMessage(preview)
            .setPositiveButton("移入垃圾箱") { _, _ -> moveToTrash(item.id, item.text) }
            .setNegativeButton("取消", null)
            .show()
    }

    /** 打开垃圾箱界面。 */
    private fun openTrash() {
        startActivity(Intent(this, TrashActivity::class.java))
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

    /** 确保有写外部存储权限；没有则发起申请并返回 false（用户授权后需重新操作）。 */
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

    // ---------- 界面切换 ----------
    private fun showLogin() {
        binding.loginPanel.visibility = View.VISIBLE
        binding.contentPanel.visibility = View.GONE
        setLoading(false)
    }

    private fun showContent() {
        binding.loginPanel.visibility = View.GONE
        binding.contentPanel.visibility = View.VISIBLE
    }

    private fun setLoading(loading: Boolean) {
        binding.progressBar.visibility = if (loading) View.VISIBLE else View.GONE
        binding.loginButton.isEnabled = !loading
        binding.refreshButton.isEnabled = !loading
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

    companion object {
        private const val PREFS = "clipboard_viewer"
        private const val KEY_URL = "worker_url"
        private const val KEY_USER = "username"
        private const val KEY_TOKEN = "token"
        private const val KEY_EXP = "expires_at"
    }
}
