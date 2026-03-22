package com.tunxiang.pos

import android.content.Context
import android.os.Build
import android.webkit.JavascriptInterface
import android.webkit.WebView
import org.json.JSONObject

/**
 * TXBridge — JS Bridge 暴露给 React Web App
 *
 * React 通过 window.TXBridge.* 调用原生能力。
 * 仅做桥接，不写业务逻辑。
 */
class TXBridge(
    private val context: Context,
    private val webView: WebView,
    private val macMiniUrl: String,
) {
    // ─── 打印 ───

    @JavascriptInterface
    fun print(content: String) {
        // 调用商米打印 SDK
        // SunmiPrinterHelper.sendRawData(content.toByteArray(Charsets.UTF_8))
        android.util.Log.i("TXBridge", "print: ${content.take(100)}...")
    }

    @JavascriptInterface
    fun openCashBox() {
        // 调用商米钱箱 SDK
        // SunmiPrinterHelper.openCashDrawer()
        android.util.Log.i("TXBridge", "openCashBox")
    }

    // ─── 称重 ───

    @JavascriptInterface
    fun startScale() {
        // 启动电子秤监听
        // SunmiScaleHelper.startListening()
        android.util.Log.i("TXBridge", "startScale")
    }

    @JavascriptInterface
    fun onScaleData(callback: String) {
        // 称重数据回调到 JS
        // 实际实现中通过 ScaleListener 回调
        webView.post {
            webView.evaluateJavascript("$callback('0.00')", null)
        }
    }

    // ─── 扫码 ───

    @JavascriptInterface
    fun scan() {
        // 启动商米扫码
        // SunmiScanHelper.scan()
        android.util.Log.i("TXBridge", "scan")
    }

    @JavascriptInterface
    fun onScanResult(callback: String) {
        // 扫码结果回调到 JS
        // 实际实现中通过 BroadcastReceiver 回调
        webView.post {
            webView.evaluateJavascript("$callback('')", null)
        }
    }

    // ─── 设备信息 ───

    @JavascriptInterface
    fun getDeviceInfo(): String {
        val info = JSONObject().apply {
            put("model", Build.MODEL)
            put("brand", Build.BRAND)
            put("serial", Build.SERIAL ?: "unknown")
            put("sdk", Build.VERSION.SDK_INT)
            put("app_version", "3.0.0")
        }
        return info.toString()
    }

    // ─── Mac mini 通信 ───

    @JavascriptInterface
    fun getMacMiniUrl(): String {
        return macMiniUrl
    }
}
