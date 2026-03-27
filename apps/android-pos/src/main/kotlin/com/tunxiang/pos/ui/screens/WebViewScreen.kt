package com.tunxiang.pos.ui.screens

import android.annotation.SuppressLint
import android.webkit.WebChromeClient
import android.webkit.WebSettings
import android.webkit.WebView
import android.webkit.WebViewClient
import androidx.compose.foundation.layout.*
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.ArrowBack
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.viewinterop.AndroidView
import com.tunxiang.pos.TunxiangPOSApp
import com.tunxiang.pos.bridge.*
import com.tunxiang.pos.ui.theme.*

/**
 * WebViewScreen - Fallback for non-core pages.
 *
 * Loads React Web App pages that are not part of the 5 core Compose screens.
 * Injects TXBridge for backward compatibility with V3 JS Bridge interface.
 *
 * Examples: member management, inventory, reports, settings
 */
@OptIn(ExperimentalMaterial3Api::class)
@SuppressLint("SetJavaScriptEnabled")
@Composable
fun WebViewScreen(
    url: String,
    onBack: () -> Unit,
) {
    val app = TunxiangPOSApp.instance
    var webView by remember { mutableStateOf<WebView?>(null) }
    var pageTitle by remember { mutableStateOf("加载中...") }
    var isLoading by remember { mutableStateOf(true) }

    Scaffold(
        topBar = {
            TopAppBar(
                title = {
                    Text(
                        text = pageTitle,
                        style = MaterialTheme.typography.titleMedium,
                        fontWeight = FontWeight.Bold,
                        maxLines = 1,
                    )
                },
                navigationIcon = {
                    IconButton(onClick = {
                        if (webView?.canGoBack() == true) {
                            webView?.goBack()
                        } else {
                            onBack()
                        }
                    }) {
                        Icon(Icons.Default.ArrowBack, "返回")
                    }
                },
                actions = {
                    IconButton(onClick = { webView?.reload() }) {
                        Icon(Icons.Default.Refresh, "刷新", tint = TxGrayLight)
                    }
                },
                colors = TopAppBarDefaults.topAppBarColors(containerColor = TxDarkBg),
            )
        },
    ) { padding ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(padding),
        ) {
            // Loading indicator
            if (isLoading) {
                LinearProgressIndicator(
                    modifier = Modifier.fillMaxWidth(),
                    color = TxOrange,
                    trackColor = TxDarkSurface,
                )
            }

            // WebView
            AndroidView(
                factory = { context ->
                    WebView(context).apply {
                        settings.apply {
                            javaScriptEnabled = true
                            domStorageEnabled = true
                            databaseEnabled = true
                            allowFileAccess = true
                            mixedContentMode = WebSettings.MIXED_CONTENT_ALWAYS_ALLOW
                            cacheMode = WebSettings.LOAD_DEFAULT
                            useWideViewPort = true
                            loadWithOverviewMode = true
                            setSupportZoom(false)
                        }

                        webViewClient = object : WebViewClient() {
                            override fun onPageFinished(view: WebView?, url: String?) {
                                isLoading = false
                            }
                        }

                        webChromeClient = object : WebChromeClient() {
                            override fun onReceivedTitle(view: WebView?, title: String?) {
                                pageTitle = title ?: "屯象"
                            }
                        }

                        // Inject TXBridge for V3 compatibility
                        val printer = SunmiPrinter(context)
                        val scale = SunmiScale(context)
                        val scanner = SunmiScanner(context)
                        val cashBox = SunmiCashBox(context)

                        addJavascriptInterface(
                            TXBridge(context, this, printer, scale, scanner, cashBox),
                            "TXBridge"
                        )

                        loadUrl(url)
                        webView = this
                    }
                },
                modifier = Modifier.fillMaxSize(),
            )
        }
    }

    // Cleanup
    DisposableEffect(Unit) {
        onDispose {
            webView?.destroy()
        }
    }
}
