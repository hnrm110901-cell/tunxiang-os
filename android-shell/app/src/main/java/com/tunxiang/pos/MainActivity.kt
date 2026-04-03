package com.tunxiang.pos

import android.annotation.SuppressLint
import android.graphics.Bitmap
import android.net.ConnectivityManager
import android.net.NetworkCapabilities
import android.os.Bundle
import android.util.Log
import android.webkit.WebResourceError
import android.webkit.WebResourceRequest
import android.webkit.WebSettings
import android.webkit.WebView
import android.webkit.WebViewClient
import androidx.appcompat.app.AppCompatActivity
import com.tunxiang.pos.bridge.TXBridge

/**
 * MainActivity — 商米 POS 壳层主 Activity
 *
 * 职责：
 * 1. 初始化全屏 WebView（适配商米 T2/V2 触摸屏）
 * 2. 注册 TXBridge 供 React Web App 通过 window.TXBridge.* 调用
 * 3. 联网时加载 Mac mini 本地服务（http://localhost:3000）
 * 4. 离线时从 assets/index.html 加载缓存版本
 *
 * 本类不含业务逻辑，仅做 WebView 壳层配置。
 */
class MainActivity : AppCompatActivity() {

    companion object {
        private const val TAG = "MainActivity"

        // Mac mini 本地 React Web App 地址（Mac mini 作为门店边缘服务器托管前端）
        private const val WEB_APP_URL = "http://localhost:3000"

        // 离线备用：从 assets 加载
        private const val OFFLINE_FALLBACK_URL = "file:///android_asset/index.html"

        // JS Bridge 注册名称（对应 window.TXBridge）
        private const val JS_BRIDGE_NAME = "TXBridge"
    }

    private lateinit var webView: WebView
    private lateinit var txBridge: TXBridge

    @SuppressLint("SetJavaScriptEnabled")
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        // 商米 POS 全屏运行，隐藏 ActionBar
        supportActionBar?.hide()

        webView = WebView(this)
        setContentView(webView)

        txBridge = TXBridge(this)
        setupWebView()
        loadApp()
    }

    /**
     * 配置 WebView：启用 JS、DOM Storage、混合内容、硬件加速。
     * 安全说明：仅在商米局域网内运行，不暴露公网，混合内容仅限 http://localhost。
     */
    @SuppressLint("SetJavaScriptEnabled")
    private fun setupWebView() {
        webView.settings.apply {
            // JavaScript 必须启用（React Web App 依赖）
            javaScriptEnabled = true

            // DOM Storage：React 应用本地状态持久化
            domStorageEnabled = true

            // 允许加载本地 assets 文件（离线回退）
            allowFileAccess = true

            // 缓存策略：优先使用缓存，离线时继续可用
            cacheMode = WebSettings.LOAD_DEFAULT

            // 硬件加速渲染（商米 T2/V2 支持）
            setLayerType(android.view.View.LAYER_TYPE_HARDWARE, null)

            // 允许混合内容（localhost http + assets file://）
            // 安全风险：仅限局域网 Mac mini，可接受
            mixedContentMode = WebSettings.MIXED_CONTENT_COMPATIBILITY_MODE

            // 视口适配商米 POS 屏幕（1280×800 / 1920×1080）
            useWideViewPort = true
            loadWithOverviewMode = true

            // 禁用文字自动缩放（POS UI 已做触控优化）
            textZoom = 100
        }

        // 注册 JS Bridge（window.TXBridge）
        webView.addJavascriptInterface(txBridge, JS_BRIDGE_NAME)
        Log.d(TAG, "TXBridge registered as window.$JS_BRIDGE_NAME")

        webView.webViewClient = TXWebViewClient()

        Log.d(TAG, "WebView setup complete")
    }

    /**
     * 根据网络状态决定加载在线或离线版本。
     */
    private fun loadApp() {
        if (isNetworkAvailable()) {
            Log.d(TAG, "Network available, loading: $WEB_APP_URL")
            webView.loadUrl(WEB_APP_URL)
        } else {
            Log.w(TAG, "Network unavailable, loading offline fallback: $OFFLINE_FALLBACK_URL")
            webView.loadUrl(OFFLINE_FALLBACK_URL)
        }
    }

    /**
     * 检查当前设备是否有可用网络连接。
     */
    private fun isNetworkAvailable(): Boolean {
        val cm = getSystemService(CONNECTIVITY_SERVICE) as ConnectivityManager
        val network = cm.activeNetwork ?: return false
        val caps = cm.getNetworkCapabilities(network) ?: return false
        return caps.hasCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET)
    }

    // ─── WebViewClient ────────────────────────────────────────────────────

    inner class TXWebViewClient : WebViewClient() {

        /**
         * 拦截 URL 跳转：
         * - localhost:3000 及其路径：允许（React Router SPA 路由）
         * - 外部 URL：记录警告，阻止跳转（POS 设备不应打开外部浏览器）
         */
        override fun shouldOverrideUrlLoading(
            view: WebView,
            request: WebResourceRequest
        ): Boolean {
            val url = request.url.toString()
            val isLocalApp = url.startsWith("http://localhost:3000") ||
                             url.startsWith("file:///android_asset/")

            return if (isLocalApp) {
                Log.d(TAG, "shouldOverrideUrlLoading: allow → $url")
                false // WebView 自行处理
            } else {
                Log.w(TAG, "shouldOverrideUrlLoading: blocked external URL → $url")
                true  // 阻止跳转
            }
        }

        override fun onPageStarted(view: WebView, url: String, favicon: Bitmap?) {
            Log.d(TAG, "onPageStarted: $url")
        }

        override fun onPageFinished(view: WebView, url: String) {
            Log.d(TAG, "onPageFinished: $url")
        }

        /**
         * 网络加载失败时回退到 assets 离线版本。
         * 仅在非 assets URL 加载失败时触发回退（避免递归）。
         */
        override fun onReceivedError(
            view: WebView,
            request: WebResourceRequest,
            error: WebResourceError
        ) {
            val failedUrl = request.url.toString()
            val errorCode = error.errorCode
            val description = error.description

            Log.e(TAG, "onReceivedError: code=$errorCode desc=$description url=$failedUrl")

            // 只对主框架请求触发回退，避免子资源错误导致重复加载
            if (request.isForMainFrame && !failedUrl.startsWith("file://")) {
                Log.w(TAG, "Main frame load failed, falling back to offline assets")
                view.loadUrl(OFFLINE_FALLBACK_URL)
            }
        }
    }

    // ─── 生命周期 ─────────────────────────────────────────────────────────

    override fun onResume() {
        super.onResume()
        webView.onResume()
        Log.d(TAG, "onResume")
    }

    override fun onPause() {
        super.onPause()
        webView.onPause()
        Log.d(TAG, "onPause")
    }

    override fun onDestroy() {
        webView.removeJavascriptInterface(JS_BRIDGE_NAME)
        webView.destroy()
        Log.d(TAG, "onDestroy: WebView destroyed")
        super.onDestroy()
    }

    /**
     * 返回键行为：WebView 有历史记录时后退，否则不退出（POS 设备应保持运行）。
     */
    @Deprecated("Deprecated in Java")
    override fun onBackPressed() {
        if (webView.canGoBack()) {
            webView.goBack()
            Log.d(TAG, "onBackPressed: WebView go back")
        } else {
            Log.d(TAG, "onBackPressed: no back history, staying in app")
            // 不调用 super.onBackPressed()，防止 POS 意外退出应用
        }
    }
}
