package com.tunxiang.pos.service

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.util.Log

/**
 * SunmiScanService -- 商米扫码 SDK 封装
 *
 * 职责：
 * 1. 商米内置扫码头控制（T2 红外扫码器 / V2 摄像头扫码）
 * 2. 扫码结果广播接收
 * 3. 相机扫码降级（非商米设备或扫码头不可用时）
 *
 * 商米扫码 SDK 通过广播机制返回结果：
 * - Action: com.sunmi.scanner.ACTION_DATA_CODE_RECEIVED
 * - Extra: data (String) -- 扫码内容
 *
 * 本类不含业务逻辑，仅做 SDK 桥接。
 */
class SunmiScanService(private val context: Context) {

    companion object {
        private const val TAG = "SunmiScanService"

        /** 商米扫码结果广播 Action */
        private const val ACTION_SCAN_RESULT = "com.sunmi.scanner.ACTION_DATA_CODE_RECEIVED"

        /** 商米扫码结果 Extra Key */
        private const val EXTRA_SCAN_DATA = "data"

        /** 商米扫码类型 Extra Key */
        private const val EXTRA_SCAN_TYPE = "source_byte"
    }

    /** 扫码结果回调 */
    private var onScanResult: ((String) -> Unit)? = null

    /** 广播接收器 */
    private var scanReceiver: BroadcastReceiver? = null

    /** 是否已注册广播 */
    private var isRegistered = false

    // ── 生命周期 ─────────────────────────────────────────────────────────

    /**
     * 注册扫码广播接收器。在 Activity.onCreate 中调用。
     */
    fun register() {
        if (isRegistered) {
            Log.w(TAG, "register() already registered, skipping")
            return
        }

        scanReceiver = object : BroadcastReceiver() {
            override fun onReceive(ctx: Context, intent: Intent) {
                val barcode = intent.getStringExtra(EXTRA_SCAN_DATA)
                val sourceType = intent.getByteArrayExtra(EXTRA_SCAN_TYPE)

                if (barcode.isNullOrBlank()) {
                    Log.w(TAG, "onReceive() empty barcode, ignoring")
                    return
                }

                Log.d(TAG, "onReceive() barcode=$barcode, sourceType=${sourceType?.contentToString()}")
                onScanResult?.invoke(barcode)
            }
        }

        val filter = IntentFilter(ACTION_SCAN_RESULT)
        // TODO: 商米扫码广播注册
        // context.registerReceiver(scanReceiver, filter)
        isRegistered = true
        Log.d(TAG, "register() -> 商米扫码广播已注册（SDK 待接入）")
    }

    /**
     * 注销扫码广播接收器。在 Activity.onDestroy 中调用。
     */
    fun unregister() {
        if (!isRegistered) return

        try {
            scanReceiver?.let {
                // TODO: context.unregisterReceiver(it)
            }
        } catch (e: IllegalArgumentException) {
            Log.w(TAG, "unregister() receiver not registered: ${e.message}")
        }

        scanReceiver = null
        isRegistered = false
        onScanResult = null
        Log.d(TAG, "unregister() -> 扫码广播已注销")
    }

    // ── 扫码控制 ─────────────────────────────────────────────────────────

    /**
     * 启动扫码。
     * 商米 T2：触发红外扫码头
     * 商米 V2：启动摄像头扫码界面
     */
    fun startScan() {
        Log.d(TAG, "startScan() called")
        try {
            // TODO: 接入商米扫码 SDK
            // 方式一：商米扫码头（T2 内置红外扫码器）
            // val intent = Intent("com.sunmi.scanner.ACTION_START_SCAN")
            // context.sendBroadcast(intent)

            // 方式二：商米扫码 Activity（V2 摄像头扫码）
            // val intent = Intent(context, SunmiScanActivity::class.java)
            // (context as? Activity)?.startActivityForResult(intent, REQUEST_CODE_SCAN)

            Log.d(TAG, "startScan() -> 商米扫码 SDK 待接入")
        } catch (e: SecurityException) {
            Log.e(TAG, "startScan() 权限不足: ${e.message}", e)
            fallbackToCameraScan()
        } catch (e: IllegalStateException) {
            Log.e(TAG, "startScan() 扫码器不可用: ${e.message}", e)
            fallbackToCameraScan()
        }
    }

    /**
     * 设置扫码结果回调。
     *
     * @param callback 扫码完成后的回调，参数为条码/二维码内容字符串
     */
    fun setOnScanResult(callback: (String) -> Unit) {
        onScanResult = callback
        Log.d(TAG, "setOnScanResult() callback registered")
    }

    // ── 相机扫码降级 ─────────────────────────────────────────────────────

    /**
     * 降级到相机扫码（商米内置扫码头不可用时）。
     * 使用 Android Camera2 API + ZXing 解码。
     */
    private fun fallbackToCameraScan() {
        Log.w(TAG, "fallbackToCameraScan() -> 降级到相机扫码")
        // TODO: 启动相机扫码 Activity
        // 依赖 ZXing 或 ML Kit Barcode Scanning
        // val intent = Intent(context, CameraScanActivity::class.java)
        // (context as? Activity)?.startActivityForResult(intent, REQUEST_CODE_CAMERA_SCAN)
        Log.d(TAG, "fallbackToCameraScan() -> 相机扫码待实现")
    }
}
