package com.tunxiang.pos.bridge

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.util.Log
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.asSharedFlow

/**
 * SunmiScanner - Wrapper for Sunmi barcode/QR scanner.
 *
 * Handles both:
 * - Built-in camera scanner (Sunmi T2)
 * - External USB barcode scanner (acts as keyboard input)
 *
 * Used for:
 * - Scan-to-pay (WeChat/Alipay payment barcodes)
 * - Member card scanning
 * - Coupon code scanning
 */
class SunmiScanner(private val context: Context) {

    companion object {
        private const val TAG = "SunmiScanner"
        // Sunmi scanner broadcast actions
        private const val ACTION_SCAN_RESULT = "com.sunmi.scanner.ACTION_DATA_CODE_RECEIVED"
        private const val EXTRA_SCAN_DATA = "data"
        private const val EXTRA_SCAN_TYPE = "source"
    }

    private val _scanResults = MutableSharedFlow<ScanResult>(extraBufferCapacity = 10)
    val scanResults: SharedFlow<ScanResult> = _scanResults.asSharedFlow()

    private var onScanResult: ((ScanResult) -> Unit)? = null

    private val scanReceiver = object : BroadcastReceiver() {
        override fun onReceive(context: Context?, intent: Intent?) {
            if (intent?.action == ACTION_SCAN_RESULT) {
                val data = intent.getStringExtra(EXTRA_SCAN_DATA) ?: return
                val source = intent.getStringExtra(EXTRA_SCAN_TYPE) ?: "unknown"

                val result = ScanResult(
                    data = data,
                    type = classifyScanData(data),
                    source = source,
                    timestamp = System.currentTimeMillis(),
                )

                _scanResults.tryEmit(result)
                onScanResult?.invoke(result)

                Log.i(TAG, "Scan result: type=${result.type}, data=${data.take(20)}...")
            }
        }
    }

    /**
     * Start listening for scan results.
     */
    fun startListening(callback: ((ScanResult) -> Unit)? = null) {
        onScanResult = callback
        try {
            val filter = IntentFilter(ACTION_SCAN_RESULT)
            context.registerReceiver(scanReceiver, filter)
            Log.i(TAG, "Scanner listening started")
        } catch (e: Exception) {
            Log.w(TAG, "Scanner not available: ${e.message}")
        }
    }

    /**
     * Stop listening for scan results.
     */
    fun stopListening() {
        try {
            context.unregisterReceiver(scanReceiver)
        } catch (_: Exception) { }
        onScanResult = null
    }

    /**
     * Trigger active scan via Sunmi camera scanner.
     */
    fun triggerScan() {
        try {
            val intent = Intent("com.sunmi.scanner.ACTION_SCAN")
            context.sendBroadcast(intent)
            Log.i(TAG, "Camera scan triggered")
        } catch (e: Exception) {
            Log.w(TAG, "Camera scan not available: ${e.message}")
        }
    }

    /**
     * Classify the scanned data to determine its type.
     */
    private fun classifyScanData(data: String): ScanType {
        return when {
            // WeChat pay barcode: starts with 10/11/12/13/14/15
            data.length == 18 && data.matches(Regex("^1[0-5]\\d{16}$")) -> ScanType.WECHAT_PAY
            // Alipay barcode: starts with 25/26/27/28/29/30
            data.length in 16..24 && data.matches(Regex("^2[5-9]\\d+$|^30\\d+$")) -> ScanType.ALIPAY_PAY
            // UnionPay QR: starts with 62
            data.startsWith("62") && data.length in 16..19 -> ScanType.UNIONPAY_PAY
            // URL (possibly member QR)
            data.startsWith("http") -> ScanType.URL
            // Member card
            data.startsWith("TX") -> ScanType.MEMBER_CARD
            // Generic barcode
            else -> ScanType.BARCODE
        }
    }
}

data class ScanResult(
    val data: String,
    val type: ScanType,
    val source: String,
    val timestamp: Long,
)

enum class ScanType {
    WECHAT_PAY,
    ALIPAY_PAY,
    UNIONPAY_PAY,
    MEMBER_CARD,
    BARCODE,
    URL,
}
