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
import android.widget.AdapterView
import android.widget.ArrayAdapter
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

class MainActivity : AppCompatActivity() {

    private lateinit var binding: ActivityMainBinding
    private val adapter = FavAdapter { item -> confirmDelete(item) }

    private val prefs by lazy { getSharedPreferences(PREFS, Context.MODE_PRIVATE) }

    // 默认填上你的 Worker 地址，按需修改。
    private val defaultUrl = "https://clipboard-fav-worker.mybrowser.workers.dev"

    // 下拉每一项对应的收藏夹名；null 表示「全部」。与 spinner 选项一一对应。
    private var folderKeys: List<String?> = listOf(null)
    private var currentFolder: String? = DEFAULT_FOLDER   // 默认打开「记忆」收藏夹
    private var suppressSpinner = false                    // 防止程序性设置 spinner 触发回调

    private var localMode = false                          // false=云条目，true=本地条目
    private var suppressMode = false                       // 防止程序性设置 modeSpinner 触发回调

    // Android 10 及以下：运行时申请写外部存储权限
    private val requestWritePermission =
        registerForActivityResult(ActivityResultContracts.RequestPermission()) { granted ->
            if (granted) toast("已授予存储权限，请重新滑动") else toast("未授予存储权限，无法写入")
        }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        binding = ActivityMainBinding.inflate(layoutInflater)
        setContentView(binding.root)

        binding.recyclerView.layoutManager = LinearLayoutManager(this)
        binding.recyclerView.adapter = adapter
        attachSwipe()

        // 数据源切换下拉：云条目 / 本地条目
        val modeAdapter = ArrayAdapter(
            this,
            android.R.layout.simple_spinner_dropdown_item,
            listOf("云条目", "本地条目")
        )
        suppressMode = true
        binding.modeSpinner.adapter = modeAdapter
        binding.modeSpinner.post { suppressMode = false }
        binding.modeSpinner.onItemSelectedListener = object : AdapterView.OnItemSelectedListener {
            override fun onItemSelected(p: AdapterView<*>?, v: View?, position: Int, id: Long) {
                if (suppressMode) return
                localMode = position == 1
                if (hasValidToken()) refresh()
            }

            override fun onNothingSelected(p: AdapterView<*>?) {}
        }

        binding.urlInput.setText(prefs.getString(KEY_URL, defaultUrl))
        binding.userInput.setText(prefs.getString(KEY_USER, ""))

        binding.loginButton.setOnClickListener { doLogin() }
        binding.refreshButton.setOnClickListener { refresh() }
        binding.logoutButton.setOnClickListener { logout() }

        binding.folderSpinner.onItemSelectedListener = object : AdapterView.OnItemSelectedListener {
            override fun onItemSelected(p: AdapterView<*>?, v: View?, position: Int, id: Long) {
                if (suppressSpinner) return
                currentFolder = folderKeys.getOrNull(position)
                loadData()
            }

            override fun onNothingSelected(p: AdapterView<*>?) {}
        }

        if (hasValidToken()) {
            showContent()
            refresh()
        } else {
            showLogin()
        }
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
                currentFolder = DEFAULT_FOLDER
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
        currentFolder = DEFAULT_FOLDER
        showLogin()
    }

    // ---------- 刷新：重新拉取收藏夹列表 + 当前收藏夹内容 ----------
    private fun refresh() {
        if (!hasValidToken()) {
            toast("登录已过期，请重新登录")
            logout()
            return
        }
        if (localMode) {
            binding.folderSpinner.visibility = View.GONE
            loadLocalData()
        } else {
            binding.folderSpinner.visibility = View.VISIBLE
            loadFolders()
            loadData()
        }
    }

    /** 拉取收藏夹列表，填充下拉。 */
    private fun loadFolders() {
        val url = prefs.getString(KEY_URL, defaultUrl) ?: defaultUrl
        val token = prefs.getString(KEY_TOKEN, "") ?: ""
        lifecycleScope.launch {
            try {
                val infos = withContext(Dispatchers.IO) { ClipboardApi.listFolders(url, token) }

                // 把「记忆」条目数推送到桌面小部件，并让其计时器归零
                val memoryCount = infos.firstOrNull { it.name == DEFAULT_FOLDER }?.count ?: 0
                MemoryWidgetProvider.pushCountFromApp(this@MainActivity, memoryCount)

                val displays = mutableListOf<String>()
                val keys = mutableListOf<String?>()
                var total = 0
                for (f in infos) {
                    displays.add("${f.name} (${f.count})")
                    keys.add(f.name)
                    total += f.count
                }
                displays.add(0, "全部 ($total)")
                keys.add(0, null)
                folderKeys = keys

                // 当前选中的收藏夹若已不存在（比如默认的「记忆」还没建），回到「全部」
                if (currentFolder != null && currentFolder !in keys) currentFolder = null
                val selectIdx = keys.indexOf(currentFolder).let { if (it >= 0) it else 0 }

                val spinnerAdapter = ArrayAdapter(
                    this@MainActivity,
                    android.R.layout.simple_spinner_dropdown_item,
                    displays
                )
                suppressSpinner = true
                binding.folderSpinner.adapter = spinnerAdapter
                binding.folderSpinner.setSelection(selectIdx)
                binding.folderSpinner.post { suppressSpinner = false }
            } catch (e: ApiException) {
                if (e.code == 401) { toast("登录已过期，请重新登录"); logout() }
                else showError("获取收藏夹失败：${e.message}")
            } catch (e: Exception) {
                showError("获取收藏夹失败：${e.message}")
            }
        }
    }

    /** 拉取并显示当前收藏夹（currentFolder=null 时显示全部）。 */
    private fun loadData() {
        if (!hasValidToken()) {
            toast("登录已过期，请重新登录")
            logout()
            return
        }
        val url = prefs.getString(KEY_URL, defaultUrl) ?: defaultUrl
        val token = prefs.getString(KEY_TOKEN, "") ?: ""
        setLoading(true)
        showError(null)
        lifecycleScope.launch {
            try {
                val folders = withContext(Dispatchers.IO) {
                    ClipboardApi.load(url, token, currentFolder)
                }
                adapter.submit(folders.toRows())
                val count = folders.sumOf { it.items.size }
                binding.statusText.text = if (currentFolder == null) {
                    "全部：${folders.size} 个收藏夹，共 $count 条"
                } else {
                    "收藏夹「$currentFolder」：$count 条"
                }
                if (folders.isEmpty()) showError("没有数据") else showError(null)
            } catch (e: ApiException) {
                if (e.code == 401) { toast("登录已过期，请重新登录"); logout() }
                else showError("读取失败：${e.message}")
            } catch (e: Exception) {
                showError("读取失败：${e.message}")
            } finally {
                setLoading(false)
            }
        }
    }

    // ---------- 滑动手势：左滑删除 / 右滑加入本地3天后 ----------
    private fun attachSwipe() {
        // 浅色 = 还没滑够，松手不执行；深色 = 已达阈值，松手即执行。
        val redLight = Paint().apply { color = Color.parseColor("#EF9A9A") }    // 删除（未到阈值）
        val redStrong = Paint().apply { color = Color.parseColor("#F44336") }   // 删除（已到阈值）
        val greenLight = Paint().apply { color = Color.parseColor("#A5D6A7") }  // 加入（未到阈值）
        val greenStrong = Paint().apply { color = Color.parseColor("#4CAF50") } // 加入（已到阈值）
        // 滑过条目宽度的该比例即可触发（视觉变色点与触发点一致）。
        val swipeThreshold = 0.4f
        val rightTextPaint = Paint().apply {   // 删除文字（右对齐）
            color = Color.WHITE
            isAntiAlias = true
            textAlign = Paint.Align.RIGHT
            textSize = 44f
        }
        val leftTextPaint = Paint().apply {     // 加入文字（左对齐）
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
                    // 右滑：加入本地3天后（写入 txt + 当前时间戳，隐藏 3 天后再显示）。
                    if (localMode) {
                        // 本地已到期条目：删掉旧记录，按当前时间重新延后 3 天。
                        snoozeLocal(item.id, item.text)
                    } else {
                        addToLocal(item.text)
                    }
                } else {
                    // 左滑：删除
                    if (localMode) {
                        deleteLocalAt(item.id)   // 本地模式下 id 即文件行索引
                    } else if (item.id > 0) {
                        doDelete(item.id)
                    } else {
                        toast("该条目无法删除")
                    }
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
                        // 右滑：左侧「加入3天后」，未到阈值浅绿、到了深绿
                        c.drawRect(
                            v.left.toFloat(), v.top.toFloat(), v.left + dX, v.bottom.toFloat(),
                            if (reached) greenStrong else greenLight
                        )
                        val y = v.top + (v.height + leftTextPaint.textSize) / 2f
                        c.drawText("加入3天后", v.left + 30f, y, leftTextPaint)
                    }
                }
                super.onChildDraw(c, rv, vh, dX, dY, actionState, isCurrentlyActive)
            }
        }
        ItemTouchHelper(callback).attachToRecyclerView(binding.recyclerView)
    }

    // ---------- 本地「3天后」清单 ----------
    /** 读取本地文件并显示：只显示已满 3 天的条目，未到期的隐藏。 */
    private fun loadLocalData() {
        showError(null)
        val entries = try {
            LocalStore.readEntries()
        } catch (e: Exception) {
            showError("读取本地文件失败：${e.message}")
            emptyList()
        }
        val now = System.currentTimeMillis()
        val due = entries.filter { now >= it.dueAt }       // 已到期，显示
        val waiting = entries.size - due.size              // 未到期，隐藏

        val rows = mutableListOf<Row>()
        rows.add(Row.Header("本地3天后  (${due.size})"))
        for (e in due) {
            // 界面上只显示内容，不显示时间戳（时间戳仅保留在 txt 文件中）
            rows.add(Row.Item(e.index, e.text, ""))        // id = 文件行索引，用于删除/延后
        }
        adapter.submit(rows)
        binding.statusText.text =
            if (waiting > 0) "本地3天后：${due.size} 条已到期，$waiting 条等待中"
            else "本地3天后：${due.size} 条"
        showError(if (due.isEmpty()) "没有已到期的本地条目" else null)
    }

    /** 把一条内容写入本地文件（附时间戳）。 */
    private fun addToLocal(text: String) {
        if (!ensureStoragePermission()) return
        try {
            LocalStore.append(text)
            toast("已加入本地3天后")
            if (localMode) loadLocalData()
        } catch (e: Exception) {
            showError("写入失败：${e.message}")
        }
    }

    /** 本地条目重新延后 3 天：删掉旧行，再以当前时间戳写回（于是又隐藏 3 天）。 */
    private fun snoozeLocal(index: Int, text: String) {
        if (!ensureStoragePermission()) return
        try {
            LocalStore.deleteAt(index)
            LocalStore.append(text)
            toast("已延后到 3 天后")
            loadLocalData()
        } catch (e: Exception) {
            showError("操作失败：${e.message}")
        }
    }

    /** 删除本地文件的第 index 行。 */
    private fun deleteLocalAt(index: Int) {
        if (!ensureStoragePermission()) return
        try {
            LocalStore.deleteAt(index)
            toast("已删除")
            loadLocalData()
        } catch (e: Exception) {
            showError("删除失败：${e.message}")
        }
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

    // ---------- 删除条目 ----------
    private fun confirmDelete(item: Row.Item) {
        if (item.id <= 0) {
            toast("该条目无法删除")
            return
        }
        val preview = if (item.text.length > 100) item.text.substring(0, 100) + "…" else item.text
        AlertDialog.Builder(this)
            .setTitle("删除条目")
            .setMessage(preview)
            .setPositiveButton("删除") { _, _ -> doDelete(item.id) }
            .setNegativeButton("取消", null)
            .show()
    }

    private fun doDelete(id: Int) {
        val url = prefs.getString(KEY_URL, defaultUrl) ?: defaultUrl
        val token = prefs.getString(KEY_TOKEN, "") ?: ""
        setLoading(true)
        lifecycleScope.launch {
            try {
                withContext(Dispatchers.IO) { ClipboardApi.deleteItem(url, token, id) }
            } catch (e: ApiException) {
                setLoading(false)
                if (e.code == 401) { toast("登录已过期，请重新登录"); logout() }
                else showError("删除失败：${e.message}")
                return@launch
            } catch (e: Exception) {
                setLoading(false)
                showError("删除失败：${e.message}")
                return@launch
            }
            toast("已删除")
            // 刷新列表计数与当前内容（loadData 会负责关闭 loading）
            loadFolders()
            loadData()
        }
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
        private const val DEFAULT_FOLDER = "记忆"   // 默认打开的收藏夹
    }
}
