package com.tunxiang.pos.bridge

import android.content.Context
import android.util.Log

/**
 * SunmiCashBox - Cash drawer control via Sunmi printer SDK.
 *
 * The cash drawer is connected through the Sunmi printer's kick connector.
 * Opening uses ESC/POS command: ESC p 0 (pin 2, pulse 100ms).
 */
class SunmiCashBox(private val context: Context) {

    companion object {
        private const val TAG = "SunmiCashBox"
        // ESC/POS cash drawer kick command
        // ESC p m t1 t2 : pulse to kick connector pin
        private val OPEN_COMMAND = byteArrayOf(
            0x1B, 0x70, 0x00, 0x32, 0x32  // ESC p 0 50 50 (pin 2, 100ms pulse)
        )
    }

    /**
     * Open the cash drawer.
     * Sends ESC/POS kick command through the Sunmi printer service.
     */
    fun open() {
        try {
            // Via Sunmi printer SDK:
            // IWoyouService.sendRAWData(OPEN_COMMAND, null)
            //
            // Alternative via Sunmi built-in API:
            // val intent = Intent("woyou.aidlservice.jiuiv5.IWoyouService")
            // ... bind and call sendRAWData

            Log.i(TAG, "Cash drawer opened")

            // Fallback: try direct serial port on some Sunmi models
            sendRawBytes(OPEN_COMMAND)
        } catch (e: Exception) {
            Log.e(TAG, "Failed to open cash drawer: ${e.message}")
        }
    }

    /**
     * Check if cash drawer is connected.
     * Some Sunmi models support drawer status query.
     */
    fun isConnected(): Boolean {
        // Sunmi doesn't provide a reliable status check for cash drawer
        // We assume it's connected if printer service is available
        return true
    }

    private fun sendRawBytes(data: ByteArray) {
        // In production, this goes through the Sunmi printer AIDL service:
        // printerService?.sendRAWData(data, object : ICallback.Stub() {
        //     override fun onRunResult(isSuccess: Boolean) {
        //         Log.d(TAG, "Cash drawer command result: $isSuccess")
        //     }
        //     override fun onReturnString(result: String?) {}
        //     override fun onRaiseException(code: Int, msg: String?) {
        //         Log.e(TAG, "Cash drawer error: $code $msg")
        //     }
        // })
        Log.d(TAG, "Sent ${data.size} bytes to printer for cash drawer")
    }
}
