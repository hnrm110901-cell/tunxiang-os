package com.tunxiang.pos

import android.annotation.SuppressLint
import android.os.Bundle
import android.view.View
import android.view.WindowManager
import android.webkit.WebChromeClient
import android.webkit.WebResourceRequest
import android.webkit.WebSettings
import android.webkit.WebView
import android.webkit.WebViewClient
import androidx.appcompat.app.AppCompatActivity

/**
 * MainActivity — WebView 壳层加载 React Web App
 *
 * 职责：
 * 1. 全屏 WebView 加载 web-pos React App
 * 2. 注入 TXBridge JS Bridge
 * 3. 绑定商米打印服务 + 注册广播接收器
 * 4. 处理返回键（WebView 历史回退）
 *
 * 不写业务逻辑。
 */
class MainActivity : AppCompatActivity() {

    private lateinit var webView: WebView
    private lateinit var bridge: TXBridge

    @SuppressLint("SetJavaScriptEnabled")
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        // 全屏沉浸模式（POS 机不需要状态栏/导航栏）
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        @Suppress("DEPRECATION")
        window.decorView.systemUiVisibility = (
            View.SYSTEM_UI_FLAG_FULLSCREEN
            or View.SYSTEM_UI_FLAG_HIDE_NAVIGATION
            or View.SYSTEM_UI_FLAG_IMMERSIVE_STICKY
        )

        // WebView 初始化
        webView = WebView(this).apply {
            settings.apply {
                javaScriptEnabled = true
                domStorageEnabled = true
                databaseEnabled = true
                allowFileAccess = true
                mixedContentMode = WebSettings.MIXED_CONTENT_ALWAYS_ALLOW
                cacheMode = WebSettings.LOAD_DEFAULT
                // 适配触控
                useWideViewPort = true
                loadWithOverviewMode = true
                setSupportZoom(false)
            }

            webChromeClient = WebChromeClient()
            webViewClient = object : WebViewClient() {
                override fun shouldOverrideUrlLoading(
                    view: WebView,
                    request: WebResourceRequest,
                ): Boolean = false
            }
        }

        setContentView(webView)

        // 从 intent extra 读取地址，降级到 BuildConfig
        val macMiniUrl = intent.getStringExtra("MAC_MINI_URL") ?: BuildConfig.MAC_MINI_URL

        // 初始化 TXBridge 并注入到 WebView
        bridge = TXBridge(this, webView, macMiniUrl)
        webView.addJavascriptInterface(bridge, "TXBridge")

        // 绑定商米打印 AIDL 服务 + 注册广播接收器
        bridge.bindPrinterService()
        bridge.registerReceivers()

        // 加载 React Web App（intent extra 优先，降级到 BuildConfig）
        val appUrl = intent.getStringExtra("APP_URL") ?: BuildConfig.WEB_APP_URL
        webView.loadUrl(appUrl)
    }

    override fun onBackPressed() {
        if (webView.canGoBack()) {
            webView.goBack()
        } else {
            // POS 机不允许退出应用（生产模式）
            // super.onBackPressed()
        }
    }

    override fun onDestroy() {
        bridge.unbindPrinterService()
        bridge.unregisterReceivers()
        webView.destroy()
        super.onDestroy()
    }
}
