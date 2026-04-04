package com.tunxiang.pos.bridge

import android.util.Log
import android.webkit.JavascriptInterface
import android.webkit.WebView
import com.tunxiang.pos.service.SunmiScanService

/**
 * ScanBridge -- 扫码桥接
 *
 * 将 JS Bridge 扫码调用转发到 SunmiScanService。
 * 扫码结果通过 evaluateJavascript 回调给 WebView。
 *
 * 支持：
 * - 商米内置扫码器（T2 红外 / V2 摄像头）
 * - 相机扫码降级（非商米设备）
 * - 结果通过 window.__txScanCallback(barcode) 回调给 JS
 *
 * 本类不含业务逻辑。
 */
class ScanBridge(
    private val scanService: SunmiScanService,
    private val webView: WebView
) {

    companion object {
        private const val TAG = "ScanBridge"

        /** 默认 JS 回调函数名 */
        private const val DEFAULT_CALLBACK = "window.__txScanCallback"
    }

    /** 当前注册的 JS 回调函数名 */
    private var jsCallback: String = DEFAULT_CALLBACK

    init {
        // 注册扫码结果回调：将结果转发到 WebView JS 层
        scanService.setOnScanResult { barcode ->
            notifyWebView(barcode)
        }
    }

    // ── JS Bridge 方法 ──────────────────────────────────────────────────

    /**
     * 启动扫码。
     * 扫码结果通过之前注册的回调函数返回。
     */
    @JavascriptInterface
    fun scan() {
        Log.d(TAG, "scan() called")
        try {
            scanService.startScan()
        } catch (e: SecurityException) {
            Log.e(TAG, "scan() 权限不足: ${e.message}", e)
        } catch (e: IllegalStateException) {
            Log.e(TAG, "scan() 扫码器不可用: ${e.message}", e)
        }
    }

    /**
     * 注册扫码结果回调函数名。
     *
     * @param callback JS 全局函数名，如 "window.__onScanResult"
     */
    @JavascriptInterface
    fun onScanResult(callback: String) {
        Log.d(TAG, "onScanResult() registered callback='$callback'")
        if (callback.isBlank()) {
            Log.w(TAG, "onScanResult() empty callback, using default")
            return
        }
        jsCallback = callback
    }

    // ── WebView 回调 ────────────────────────────────────────────────────

    /**
     * 将扫码结果通过 evaluateJavascript 发送回 WebView。
     * 必须在主线程调用。
     */
    private fun notifyWebView(barcode: String) {
        val escapedBarcode = barcode.replace("'", "\\'").replace("\"", "\\\"")
        val js = "$jsCallback('$escapedBarcode')"
        Log.d(TAG, "notifyWebView() -> $js")

        webView.post {
            webView.evaluateJavascript(js, null)
        }
    }
}
