package com.tunxiang.pos

import android.annotation.SuppressLint
import android.os.Bundle
import android.view.View
import android.view.WindowManager
import android.webkit.WebChromeClient
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
 * 3. 处理返回键（WebView 历史回退）
 *
 * 不写业务逻辑。
 */
class MainActivity : AppCompatActivity() {

    private lateinit var webView: WebView

    @SuppressLint("SetJavaScriptEnabled")
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        // 全屏沉浸模式（POS 机不需要状态栏/导航栏）
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
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

            webViewClient = WebViewClient()
            webChromeClient = WebChromeClient()

            // 注入 TXBridge — React 通过 window.TXBridge.* 调用
            val macMiniUrl = BuildConfig.MAC_MINI_URL
            addJavascriptInterface(
                TXBridge(this@MainActivity, this, macMiniUrl),
                "TXBridge"
            )
        }

        setContentView(webView)

        // 加载 React Web App
        val webAppUrl = BuildConfig.WEB_APP_URL
        if (webAppUrl.startsWith("file://")) {
            webView.loadUrl(webAppUrl)
        } else {
            webView.loadUrl(webAppUrl)
        }
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
        webView.destroy()
        super.onDestroy()
    }
}
