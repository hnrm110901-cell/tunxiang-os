package com.tunxiang.pos.bridge

import android.util.Log
import android.webkit.JavascriptInterface
import android.webkit.WebView

/**
 * ScaleBridge -- 称重桥接
 *
 * 将 JS Bridge 称重调用转发到商米电子秤 SDK。
 * 称重数据通过 evaluateJavascript 实时回调给 WebView。
 *
 * 商米电子秤通过串口/USB 连接 POS 主机，SDK 提供持续重量数据流。
 *
 * 本类不含业务逻辑。
 */
class ScaleBridge(private val webView: WebView) {

    companion object {
        private const val TAG = "ScaleBridge"
        private const val DEFAULT_CALLBACK = "window.__txScaleCallback"
    }

    /** 当前注册的 JS 回调函数名 */
    private var jsCallback: String = DEFAULT_CALLBACK

    /** 是否正在监听称重数据 */
    @Volatile
    private var isListening = false

    // ── JS Bridge 方法 ──────────────────────────────────────────────────

    /**
     * 开始监听电子秤数据流。
     * 数据通过 onScaleData 注册的回调持续返回。
     */
    @JavascriptInterface
    fun startScale() {
        Log.d(TAG, "startScale() called")
        if (isListening) {
            Log.w(TAG, "startScale() already listening, skipping")
            return
        }

        try {
            isListening = true
            // TODO: 接入商米电子秤 SDK
            // ScaleManager.getInstance().startListening(object : ScaleDataListener {
            //     override fun onWeightChanged(weight: Double, unit: String, stable: Boolean) {
            //         notifyWebView(weight, unit, stable)
            //     }
            //     override fun onError(errorCode: Int, message: String) {
            //         Log.e(TAG, "Scale error: code=$errorCode msg=$message")
            //         isListening = false
            //     }
            // })
            Log.d(TAG, "startScale() -> 商米电子秤 SDK 待接入")
        } catch (e: SecurityException) {
            Log.e(TAG, "startScale() 权限不足: ${e.message}", e)
            isListening = false
        } catch (e: IllegalStateException) {
            Log.e(TAG, "startScale() 电子秤不可用: ${e.message}", e)
            isListening = false
        }
    }

    /**
     * 停止监听电子秤数据流。
     */
    @JavascriptInterface
    fun stopScale() {
        Log.d(TAG, "stopScale() called")
        try {
            // TODO: ScaleManager.getInstance().stopListening()
            isListening = false
            Log.d(TAG, "stopScale() -> 已停止监听")
        } catch (e: IllegalStateException) {
            Log.e(TAG, "stopScale() 异常: ${e.message}", e)
        }
    }

    /**
     * 注册称重数据回调函数名。
     *
     * @param callback JS 全局函数名，如 "window.__onScaleData"
     *                 回调参数格式: callback({ weight: 1.25, unit: "kg", stable: true })
     */
    @JavascriptInterface
    fun onScaleData(callback: String) {
        Log.d(TAG, "onScaleData() registered callback='$callback'")
        if (callback.isBlank()) {
            Log.w(TAG, "onScaleData() empty callback, using default")
            return
        }
        jsCallback = callback
    }

    /**
     * 手动置零（去皮）。
     */
    @JavascriptInterface
    fun tare() {
        Log.d(TAG, "tare() called")
        try {
            // TODO: ScaleManager.getInstance().tare()
            Log.d(TAG, "tare() -> 商米电子秤去皮 SDK 待接入")
        } catch (e: IllegalStateException) {
            Log.e(TAG, "tare() 异常: ${e.message}", e)
        }
    }

    // ── WebView 回调 ────────────────────────────────────────────────────

    /**
     * 将称重数据通过 evaluateJavascript 发送回 WebView。
     */
    @Suppress("unused") // 将在商米 SDK 回调中使用
    private fun notifyWebView(weight: Double, unit: String, stable: Boolean) {
        val js = "$jsCallback({weight:$weight,unit:'$unit',stable:$stable})"
        Log.d(TAG, "notifyWebView() -> $js")

        webView.post {
            webView.evaluateJavascript(js, null)
        }
    }
}
