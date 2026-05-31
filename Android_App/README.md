# 收藏夹查看器（Android）

查看剪贴板收藏夹的安卓 app：登录云端账号后，从 Cloudflare Worker 拉取你的
收藏夹数据并显示，带一个「刷新」按钮。

## 它是怎么读数据的（重要）

**安卓不会、也无法直接读取 Cloudflare D1 的 `.db` 文件** —— D1 是云端 SQLite，
不对外提供可下载的数据库文件。本 app 和 PC 端一样，通过 Worker 的 HTTP 接口取数：

```
登录(账号+密码) ──POST /login──▶ Worker 返回 JWT token
                                      │
刷新 ──POST /load (带 token)──▶ Worker 校验 token，返回该账号的收藏夹 JSON
```

APK 里**不含任何密钥**，token 是登录后动态获取、存在 app 私有空间
（SharedPreferences）的。

## 功能

- 首次打开：填 Worker 地址（已预填）、账号、密码，点「登录」。
- 登录后：自动拉取并按收藏夹分组显示；token 缓存在本地，下次打开免登录。
- **刷新按钮**：重新拉取最新数据。
- 登出：清除本地 token，回到登录页。

## 如何构建

用 **Android Studio** 打开本目录（`Android_App`）即可：

1. Android Studio → File → Open → 选择 `Android_App` 文件夹。
2. 首次会自动 Gradle Sync、下载依赖（需联网）。
3. 连上手机（开启 USB 调试）或开模拟器，点 ▶ Run。

> 注意：仓库里没有放 Gradle Wrapper 的二进制 `gradle-wrapper.jar`。Android Studio
> 打开时会自动补全；若用命令行构建，先在本目录执行一次 `gradle wrapper`
> （需本机装有 Gradle），之后再用 `./gradlew assembleDebug`。

## 配置

- 默认 Worker 地址写在 `MainActivity.kt` 的 `defaultUrl`，可在登录框里直接改。
- 账号用 PC 端注册过的同一个（数据按账号隔离，登录哪个看哪个的收藏夹）。

## 关于网络

请求已带浏览器 User-Agent，避免被 Cloudflare 边缘以「机器人」拦截（错误码 1010）。
如果你的手机网络访问 `workers.dev` 需要代理/VPN，请确保设备能正常访问该域名。

## 技术栈

Kotlin + 传统 View（XML 布局 + RecyclerView + ViewBinding），网络用 JDK 自带
`HttpURLConnection` + `org.json`，无第三方网络/JSON 依赖。
