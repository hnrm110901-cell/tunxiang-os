package com.tunxiang.pos.bridge

import android.content.Context
import android.os.Build
import android.util.Log
import android.webkit.JavascriptInterface
import android.webkit.WebView
import org.json.JSONObject

/**
 * TXBridge - JS Bridge for WebView fallback pages.
 *
 * Preserved from V3 android-shell for backward compatibility.
 * React pages loaded in WebView can call window.TXBridge.* for native features.
 *
 * In V4, the 5 core POS screens use Compose directly, so this bridge
 * is only used by non-core screens loaded via WebViewScreen.
 */
class TXBridge(
    private val context: Context,
    private val webView: WebView,
    private val printer: SunmiPrinter,
    private val scale: SunmiScale,
    private val scanner: SunmiScanner,
    private val cashBox: SunmiCashBox,
) {
    companion object {
        private const val TAG = "TXBridge"
    }

    // ─── Print ───

    @JavascriptInterface
    fun print(content: String) {
        Log.i(TAG, "print called from JS: ${content.take(100)}")
        // Parse JSON content and delegate to SunmiPrinter
        // For raw ESC/POS, pass through directly
    }

    @JavascriptInterface
    fun openCashBox() {
        Log.i(TAG, "openCashBox called from JS")
        cashBox.open()
    }

    // ─── Scale ───

    @JavascriptInterface
    fun startScale() {
        Log.i(TAG, "startScale called from JS")
        scale.startListening { weight, stable ->
            webView.post {
                webView.evaluateJavascript(
                    "window.dispatchEvent(new CustomEvent('txScaleData', {detail: {weight: $weight, stable: $stable}}))",
                    null
                )
            }
        }
    }

    @JavascriptInterface
    fun stopScale() {
        scale.stopListening()
    }

    @JavascriptInterface
    fun onScaleData(callback: String) {
        scale.startListening { weight, stable ->
            webView.post {
                webView.evaluateJavascript("$callback($weight, $stable)", null)
            }
        }
    }

    // ─── Scanner ───

    @JavascriptInterface
    fun scan() {
        Log.i(TAG, "scan called from JS")
        scanner.triggerScan()
        scanner.startListening { result ->
            webView.post {
                val json = JSONObject().apply {
                    put("data", result.data)
                    put("type", result.type.name)
                }
                webView.evaluateJavascript(
                    "window.dispatchEvent(new CustomEvent('txScanResult', {detail: ${json}}))",
                    null
                )
            }
        }
    }

    @JavascriptInterface
    fun onScanResult(callback: String) {
        scanner.startListening { result ->
            webView.post {
                webView.evaluateJavascript("$callback('${result.data}')", null)
            }
        }
    }

    // ─── Device Info ───

    @JavascriptInterface
    fun getDeviceInfo(): String {
        return JSONObject().apply {
            put("model", Build.MODEL)
            put("brand", Build.BRAND)
            put("serial", Build.SERIAL ?: "unknown")
            put("sdk", Build.VERSION.SDK_INT)
            put("app_version", "4.0.0")
            put("pos_type", "compose_native")
        }.toString()
    }

    @JavascriptInterface
    fun getMacMiniUrl(): String {
        // No longer needed in V4 (Room DB replaces Mac mini for POS)
        return ""
    }
}
