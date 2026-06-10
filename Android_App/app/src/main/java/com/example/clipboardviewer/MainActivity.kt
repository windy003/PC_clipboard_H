package com.example.clipboardviewer

import android.Manifest
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
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
import androidx.recyclerview.widget.ItemTouchHelper
import androidx.recyclerview.widget.LinearLayoutManager
import androidx.recyclerview.widget.RecyclerView
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

        binding.recyclerView.layoutManager = LinearLayoutManager(this)
        binding.recyclerView.adapter = adapter
        attachSwipe()

        binding.urlInput.setText(prefs.getString(KEY_URL, defaultUrl))
        binding.userInput.setText(prefs.getString(KEY_USER, ""))

        binding.loginButton.setOnClickListener { doLogin() }
        binding.refreshButton.setOnClickListener { refresh() }
        binding.logoutButton.setOnClickListener { logout() }

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

    // ---------- 滑动手势：左滑删除 / 右滑重新延后3天 ----------
    private fun attachSwipe() {
        // 浅色 = 还没滑够，松手不执行；深色 = 已达阈值，松手即执行。
        val redLight = Paint().apply { color = Color.parseColor("#EF9A9A") }    // 删除（未到阈值）
        val redStrong = Paint().apply { color = Color.parseColor("#F44336") }   // 删除（已到阈值）
        val greenLight = Paint().apply { color = Color.parseColor("#A5D6A7") }  // 延后（未到阈值）
        val greenStrong = Paint().apply { color = Color.parseColor("#4CAF50") } // 延后（已到阈值）
        // 滑过条目宽度的该比例即可触发（视觉变色点与触发点一致）。
        val swipeThreshold = 0.4f
        val rightTextPaint = Paint().apply {   // 删除文字（右对齐）
            color = Color.WHITE
            isAntiAlias = true
            textAlign = Paint.Align.RIGHT
            textSize = 44f
        }
        val leftTextPaint = Paint().apply {     // 延后文字（左对齐）
            color = Color.WHITE
            isAntiAlias = true
            textAlign = Paint.Align.LEFT
            textSize = 44f
        }

        val callback = object :
            ItemTouchHelper.SimpleCallback(0, ItemTouchHelper.LEFT or ItemTouchHelper.RIGHT) {
            override fun onMove(
                rv: RecyclerView,
                vh: RecyclerView.ViewHolder,
                target: RecyclerView.ViewHolder
            ): Boolean = false

            // 只允许"条目行"滑动，标题行不可滑
            override fun getSwipeDirs(rv: RecyclerView, vh: RecyclerView.ViewHolder): Int {
                val pos = vh.bindingAdapterPosition
                return if (pos != RecyclerView.NO_POSITION && adapter.itemAt(pos) != null)
                    ItemTouchHelper.LEFT or ItemTouchHelper.RIGHT else 0
            }

            // 触发阈值：与下面变色点保持一致。
            override fun getSwipeThreshold(vh: RecyclerView.ViewHolder): Float = swipeThreshold

            override fun onSwiped(vh: RecyclerView.ViewHolder, direction: Int) {
                val pos = vh.bindingAdapterPosition
                val item = if (pos != RecyclerView.NO_POSITION) adapter.itemAt(pos) else null
                // 先把该行恢复显示（操作完成后会整体刷新列表；失败则保留该行）
                if (pos != RecyclerView.NO_POSITION) adapter.notifyItemChanged(pos)
                if (item == null) return

                if (direction == ItemTouchHelper.RIGHT) {
                    // 右滑：删掉待发布记录，重新写回「3天后」清单（再等 3 天）
                    snoozeLocal(item.id, item.text)
                } else {
                    // 左滑：删除（id 即 ready_to_release.txt 的行索引）
                    deleteLocalAt(item.id)
                }
            }

            override fun onChildDraw(
                c: Canvas,
                rv: RecyclerView,
                vh: RecyclerView.ViewHolder,
                dX: Float,
                dY: Float,
                actionState: Int,
                isCurrentlyActive: Boolean
            ) {
                if (actionState == ItemTouchHelper.ACTION_STATE_SWIPE) {
                    val v = vh.itemView
                    // 是否已滑过触发阈值（达到则用深色，提示松手即执行）
                    val reached = v.width > 0 && Math.abs(dX) >= v.width * swipeThreshold
                    if (dX < 0) {
                        // 左滑：右侧「删除」，未到阈值浅红、到了深红
                        c.drawRect(
                            v.right + dX, v.top.toFloat(), v.right.toFloat(), v.bottom.toFloat(),
                            if (reached) redStrong else redLight
                        )
                        val y = v.top + (v.height + rightTextPaint.textSize) / 2f
                        c.drawText("删除", v.right - 30f, y, rightTextPaint)
                    } else if (dX > 0) {
                        // 右滑：左侧「延后3天」，未到阈值浅绿、到了深绿
                        c.drawRect(
                            v.left.toFloat(), v.top.toFloat(), v.left + dX, v.bottom.toFloat(),
                            if (reached) greenStrong else greenLight
                        )
                        val y = v.top + (v.height + leftTextPaint.textSize) / 2f
                        c.drawText("延后3天", v.left + 30f, y, leftTextPaint)
                    }
                }
                super.onChildDraw(c, rv, vh, dX, dY, actionState, isCurrentlyActive)
            }
        }
        ItemTouchHelper(callback).attachToRecyclerView(binding.recyclerView)
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

    /** 删除待发布清单的第 index 行。 */
    private fun deleteLocalAt(index: Int) {
        if (!ensureStoragePermission()) return
        try {
            ReleaseStore.deleteAt(index)
            toast("已删除")
            loadLocalData()
        } catch (e: Exception) {
            showError("删除失败：${e.message}")
        }
    }

    /** 长按条目：确认后删除。 */
    private fun confirmDelete(item: Row.Item) {
        val preview = if (item.text.length > 100) item.text.substring(0, 100) + "…" else item.text
        AlertDialog.Builder(this)
            .setTitle("删除条目")
            .setMessage(preview)
            .setPositiveButton("删除") { _, _ -> deleteLocalAt(item.id) }
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
