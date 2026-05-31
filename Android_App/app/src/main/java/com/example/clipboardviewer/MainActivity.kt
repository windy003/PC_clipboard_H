package com.example.clipboardviewer

import android.content.Context
import android.os.Bundle
import android.view.View
import android.widget.AdapterView
import android.widget.ArrayAdapter
import android.widget.Toast
import androidx.appcompat.app.AlertDialog
import androidx.appcompat.app.AppCompatActivity
import androidx.lifecycle.lifecycleScope
import androidx.recyclerview.widget.LinearLayoutManager
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

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        binding = ActivityMainBinding.inflate(layoutInflater)
        setContentView(binding.root)

        binding.recyclerView.layoutManager = LinearLayoutManager(this)
        binding.recyclerView.adapter = adapter

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
        loadFolders()
        loadData()
    }

    /** 拉取收藏夹列表，填充下拉。 */
    private fun loadFolders() {
        val url = prefs.getString(KEY_URL, defaultUrl) ?: defaultUrl
        val token = prefs.getString(KEY_TOKEN, "") ?: ""
        lifecycleScope.launch {
            try {
                val infos = withContext(Dispatchers.IO) { ClipboardApi.listFolders(url, token) }
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
