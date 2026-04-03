package com.tunxiang.pos.bridge

import android.content.Context
import android.util.Log
import android.webkit.JavascriptInterface
import org.json.JSONObject

/**
 * TXBridge — 商米 POS 安卓壳层 JS Bridge
 *
 * React Web App 通过 window.TXBridge.* 调用本层暴露的原生能力。
 * 本类只做桥接，不含业务逻辑。所有外设调用均需对接商米 SDK（见各方法 TODO）。
 *
 * 商米目标机型：T2 / V2
 * 商米 SDK 文档：https://developer.sunmi.com/docs/zh-CN/
 */
class TXBridge(private val context: Context) {

    companion object {
        private const val TAG = "TXBridge"

        // Mac mini 本地服务地址（由门店部署时配置，默认开发地址）
        private const val DEFAULT_MAC_MINI_URL = "http://mac-mini.local:8000"
    }

    // ─── 打印 ─────────────────────────────────────────────────────────────

    /**
     * ESC/POS 打印：小票 / 厨房单。
     *
     * @param content ESC/POS 格式字符串或 JSON 打印指令，由 React 层生成。
     */
    @JavascriptInterface
    fun print(content: String) {
        Log.d(TAG, "print() called, content length=${content.length}")
        try {
            // TODO: 接入商米 InnerPrinterManager SDK
            // val printerManager = InnerPrinterManager.getInstance()
            // printerManager.bindService(context, innerPrinterCallback)
            // printerManager.printText(content, ...)
            Log.d(TAG, "print() → 商米打印 SDK 待接入")
        } catch (e: Exception) {
            Log.e(TAG, "print() 失败: ${e.message}", e)
        }
    }

    /**
     * 弹出钱箱。
     * 商米 T2 通过打印机接口驱动钱箱，V2 通过 Cash Drawer API。
     */
    @JavascriptInterface
    fun openCashBox() {
        Log.d(TAG, "openCashBox() called")
        try {
            // TODO: 接入商米 Cash Drawer SDK
            // SunmiCashDrawer.open(context)
            Log.d(TAG, "openCashBox() → 商米钱箱 SDK 待接入")
        } catch (e: Exception) {
            Log.e(TAG, "openCashBox() 失败: ${e.message}", e)
        }
    }

    // ─── 称重 ─────────────────────────────────────────────────────────────

    /**
     * 开始监听电子秤数据流。
     * 称重数据通过 [onScaleData] 注册的回调函数返回给 Web 层。
     */
    @JavascriptInterface
    fun startScale() {
        Log.d(TAG, "startScale() called")
        try {
            // TODO: 接入商米电子秤 SDK（串口/USB）
            // ScaleManager.getInstance().startListening()
            Log.d(TAG, "startScale() → 商米电子秤 SDK 待接入")
        } catch (e: Exception) {
            Log.e(TAG, "startScale() 失败: ${e.message}", e)
        }
    }

    /**
     * 注册称重数据回调。
     * 商米 SDK 返回数据后，通过 evaluateJavascript 调用此回调函数名。
     *
     * @param callback Web 层全局函数名，如 "window.__onScaleData"。
     *                 商米 SDK 回调时调用：webView.evaluateJavascript("$callback(weight)", null)
     */
    @JavascriptInterface
    fun onScaleData(callback: String) {
        Log.d(TAG, "onScaleData() registered callback='$callback'")
        try {
            // TODO: 将 callback 名称存储，在商米秤数据回调中调用：
            // webView.post {
            //     webView.evaluateJavascript("$callback(${scaleWeight})", null)
            // }
            Log.d(TAG, "onScaleData() → 回调已注册，商米电子秤 SDK 待接入")
        } catch (e: Exception) {
            Log.e(TAG, "onScaleData() 失败: ${e.message}", e)
        }
    }

    // ─── 扫码 ─────────────────────────────────────────────────────────────

    /**
     * 启动扫码（调用商米内置扫码头或摄像头扫码）。
     * 扫码结果通过 [onScanResult] 注册的回调返回。
     */
    @JavascriptInterface
    fun scan() {
        Log.d(TAG, "scan() called")
        try {
            // TODO: 接入商米扫码 SDK
            // val intent = Intent(context, ScanActivity::class.java)
            // context.startActivity(intent)
            // 或使用广播方式触发商米扫码头：
            // SunmiScanHead.getInstance().startScan()
            Log.d(TAG, "scan() → 商米扫码 SDK 待接入")
        } catch (e: Exception) {
            Log.e(TAG, "scan() 失败: ${e.message}", e)
        }
    }

    /**
     * 注册扫码结果回调。
     *
     * @param callback Web 层全局函数名，如 "window.__onScanResult"。
     *                 扫码完成后调用：webView.evaluateJavascript("$callback(barcode)", null)
     */
    @JavascriptInterface
    fun onScanResult(callback: String) {
        Log.d(TAG, "onScanResult() registered callback='$callback'")
        try {
            // TODO: 将 callback 名称存储，在商米扫码广播 BroadcastReceiver 中调用：
            // webView.post {
            //     webView.evaluateJavascript("$callback('$barcodeData')", null)
            // }
            Log.d(TAG, "onScanResult() → 回调已注册，商米扫码 SDK 待接入")
        } catch (e: Exception) {
            Log.e(TAG, "onScanResult() 失败: ${e.message}", e)
        }
    }

    // ─── 设备信息 ─────────────────────────────────────────────────────────

    /**
     * 返回设备基础信息（型号、序列号、系统版本）。
     *
     * @return JSON 字符串，如 {"model":"T2","serial":"SN123","osVersion":"8.1.0"}
     */
    @JavascriptInterface
    fun getDeviceInfo(): String {
        Log.d(TAG, "getDeviceInfo() called")
        return try {
            val info = JSONObject().apply {
                put("model", android.os.Build.MODEL)
                put("serial", android.os.Build.SERIAL)          // 需要 READ_PHONE_STATE 权限（API 28+）
                put("osVersion", android.os.Build.VERSION.RELEASE)
                put("sdkInt", android.os.Build.VERSION.SDK_INT)
                put("manufacturer", android.os.Build.MANUFACTURER)
                // TODO: 补充商米设备序列号（通过 SunmiDevice.getSerial()）
            }
            Log.d(TAG, "getDeviceInfo() → $info")
            info.toString()
        } catch (e: Exception) {
            Log.e(TAG, "getDeviceInfo() 失败: ${e.message}", e)
            JSONObject().apply { put("error", e.message) }.toString()
        }
    }

    // ─── Mac mini 通信 ────────────────────────────────────────────────────

    /**
     * 返回局域网内 Mac mini 边缘服务地址。
     * 实际地址可通过 SharedPreferences 或 mDNS 发现写入。
     *
     * @return URL 字符串，如 "http://192.168.1.100:8000"
     */
    @JavascriptInterface
    fun getMacMiniUrl(): String {
        Log.d(TAG, "getMacMiniUrl() called")
        return try {
            // TODO: 从 SharedPreferences 读取运维配置的 Mac mini 地址：
            // val prefs = context.getSharedPreferences("tx_config", Context.MODE_PRIVATE)
            // prefs.getString("mac_mini_url", DEFAULT_MAC_MINI_URL) ?: DEFAULT_MAC_MINI_URL
            val url = DEFAULT_MAC_MINI_URL
            Log.d(TAG, "getMacMiniUrl() → $url")
            url
        } catch (e: Exception) {
            Log.e(TAG, "getMacMiniUrl() 失败: ${e.message}", e)
            DEFAULT_MAC_MINI_URL
        }
    }
}
