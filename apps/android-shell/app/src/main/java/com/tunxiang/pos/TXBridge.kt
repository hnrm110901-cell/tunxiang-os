package com.tunxiang.pos

import android.content.BroadcastReceiver
import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.content.ServiceConnection
import android.os.Build
import android.os.IBinder
import android.os.RemoteException
import android.util.Log
import android.webkit.JavascriptInterface
import android.webkit.WebView
import org.json.JSONObject
import woyou.aidlservice.jiuiv5.IWoyouService

/**
 * TXBridge — JS Bridge 暴露给 React Web App
 *
 * React 通过 window.TXBridge.* 调用原生能力。
 * 仅做桥接，不写业务逻辑。商米 T2/V2 设备专用。
 *
 * 打印：商米 AIDL 内部服务 (IWoyouService)
 * 扫码：系统广播 com.sunmi.scanner.ACTION_DATA_CODE_RECEIVED
 * 称重：商米称重广播（USB serial）
 * 钱箱：打印服务 openDrawer()
 */
class TXBridge(
    private val context: Context,
    private val webView: WebView,
    private val macMiniUrl: String,
) {
    companion object {
        private const val TAG = "TXBridge"
        private const val SUNMI_PRINTER_ACTION = "woyou.aidlservice.jiuv5.action.MAIN_SERVICE"
        private const val SUNMI_PRINTER_PACKAGE = "woyou.aidlservice.jiuiv5"
        private const val SCAN_ACTION = "com.sunmi.scanner.ACTION_DATA_CODE_RECEIVED"
        private const val SCALE_ACTION = "com.sunmi.scale.DATA_RECEIVED"
    }

    private var printerService: IWoyouService? = null
    private var scanCallback: String? = null
    private var scaleCallback: String? = null

    // ─── 打印服务连接 ─────────────────────────────────────────────────────────

    private val printerConnection = object : ServiceConnection {
        override fun onServiceConnected(name: ComponentName, service: IBinder) {
            printerService = IWoyouService.Stub.asInterface(service)
            Log.i(TAG, "Sunmi printer service connected")
        }
        override fun onServiceDisconnected(name: ComponentName) {
            printerService = null
            Log.w(TAG, "Sunmi printer service disconnected, reconnecting...")
            bindPrinterService()
        }
    }

    fun bindPrinterService() {
        try {
            val intent = Intent(SUNMI_PRINTER_ACTION).apply {
                setPackage(SUNMI_PRINTER_PACKAGE)
            }
            context.bindService(intent, printerConnection, Context.BIND_AUTO_CREATE)
        } catch (e: Exception) {
            Log.e(TAG, "Failed to bind printer service: ${e.message}")
        }
    }

    fun unbindPrinterService() {
        try {
            context.unbindService(printerConnection)
        } catch (e: Exception) {
            Log.w(TAG, "Unbind printer service: ${e.message}")
        }
    }

    // ─── 扫码广播接收器 ────────────────────────────────────────────────────────

    val scanReceiver = object : BroadcastReceiver() {
        override fun onReceive(ctx: Context, intent: Intent) {
            val data = intent.getStringExtra("data") ?: return
            Log.i(TAG, "Scan result: $data")
            val cb = scanCallback ?: return
            webView.post {
                val escaped = data.replace("'", "\\'")
                webView.evaluateJavascript("$cb('$escaped')", null)
            }
        }
    }

    val scaleReceiver = object : BroadcastReceiver() {
        override fun onReceive(ctx: Context, intent: Intent) {
            val weight = intent.getStringExtra("weight") ?: "0.00"
            Log.i(TAG, "Scale data: $weight")
            val cb = scaleCallback ?: return
            webView.post {
                webView.evaluateJavascript("$cb('$weight')", null)
            }
        }
    }

    fun registerReceivers() {
        try {
            context.registerReceiver(scanReceiver, IntentFilter(SCAN_ACTION))
            context.registerReceiver(scaleReceiver, IntentFilter(SCALE_ACTION))
        } catch (e: Exception) {
            Log.e(TAG, "Failed to register receivers: ${e.message}")
        }
    }

    fun unregisterReceivers() {
        try {
            context.unregisterReceiver(scanReceiver)
            context.unregisterReceiver(scaleReceiver)
        } catch (e: Exception) {
            Log.w(TAG, "Unregister receivers: ${e.message}")
        }
    }

    // ─── 打印 ────────────────────────────────────────────────────────────────

    @JavascriptInterface
    fun print(content: String) {
        val svc = printerService
        if (svc == null) {
            Log.w(TAG, "print: printer service not connected, queuing...")
            // TODO: 实现离线打印队列
            return
        }
        try {
            // ESC/POS 原始字节流打印
            val bytes = content.toByteArray(Charsets.ISO_8859_1)
            svc.sendRAWData(bytes, null)
            svc.lineWrap(3, null)
            Log.i(TAG, "print: sent ${bytes.size} bytes")
        } catch (e: RemoteException) {
            Log.e(TAG, "print: RemoteException: ${e.message}")
        }
    }

    @JavascriptInterface
    fun printText(text: String, fontSize: Int = 24, bold: Boolean = false) {
        val svc = printerService ?: run {
            Log.w(TAG, "printText: printer service not connected")
            return
        }
        try {
            svc.setFontSize(fontSize.toFloat(), null)
            if (bold) svc.sendRAWData(byteArrayOf(0x1B, 0x45, 0x01), null) // ESC E 1
            svc.printText(text + "\n", null)
            if (bold) svc.sendRAWData(byteArrayOf(0x1B, 0x45, 0x00), null) // ESC E 0
        } catch (e: RemoteException) {
            Log.e(TAG, "printText: ${e.message}")
        }
    }

    @JavascriptInterface
    fun openCashBox() {
        val svc = printerService ?: run {
            Log.w(TAG, "openCashBox: printer service not connected")
            return
        }
        try {
            svc.openDrawer(null)
            Log.i(TAG, "openCashBox: sent")
        } catch (e: RemoteException) {
            Log.e(TAG, "openCashBox: ${e.message}")
        }
    }

    // ─── 称重 ────────────────────────────────────────────────────────────────

    @JavascriptInterface
    fun startScale() {
        // 商米称重通过广播接收，注册后自动接收数据
        Log.i(TAG, "startScale: listening for SCALE_ACTION broadcasts")
    }

    @JavascriptInterface
    fun onScaleData(callback: String) {
        scaleCallback = callback
        Log.i(TAG, "onScaleData: callback registered = $callback")
    }

    // ─── 扫码 ────────────────────────────────────────────────────────────────

    @JavascriptInterface
    fun scan() {
        // 触发商米扫码（内置扫码头）
        try {
            val intent = Intent("com.sunmi.scanner.SCAN")
            context.sendBroadcast(intent)
            Log.i(TAG, "scan: broadcast sent")
        } catch (e: Exception) {
            Log.e(TAG, "scan: ${e.message}")
        }
    }

    @JavascriptInterface
    fun onScanResult(callback: String) {
        scanCallback = callback
        Log.i(TAG, "onScanResult: callback registered = $callback")
    }

    // ─── 设备信息 ────────────────────────────────────────────────────────────

    @JavascriptInterface
    fun getDeviceInfo(): String {
        return try {
            val versionName = context.packageManager
                .getPackageInfo(context.packageName, 0).versionName ?: "unknown"
            JSONObject().apply {
                put("model", Build.MODEL)
                put("brand", Build.BRAND)
                put("serial", if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O)
                    Build.getSerial() else @Suppress("DEPRECATION") Build.SERIAL)
                put("sdk", Build.VERSION.SDK_INT)
                put("app_version", versionName)
                put("os_version", Build.VERSION.RELEASE)
                put("device_type", "android_pos")
            }.toString()
        } catch (e: Exception) {
            JSONObject().apply {
                put("model", Build.MODEL)
                put("app_version", "unknown")
                put("error", e.message)
            }.toString()
        }
    }

    // ─── Mac mini 通信 ───────────────────────────────────────────────────────

    @JavascriptInterface
    fun getMacMiniUrl(): String = macMiniUrl

    // ─── 心跳上报（供 React 定时调用）───────────────────────────────────────

    @JavascriptInterface
    fun reportHeartbeat() {
        // React 定时调用此方法，Android 原生向 Mac mini 上报心跳
        // 实际实现中通过 OkHttp 在后台线程发请求
        Log.i(TAG, "reportHeartbeat: called from JS")
        // TODO: 实现 OkHttp 心跳上报到 Mac mini heartbeat endpoint
    }
}
