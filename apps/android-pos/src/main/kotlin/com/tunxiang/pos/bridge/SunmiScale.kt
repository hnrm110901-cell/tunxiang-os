package com.tunxiang.pos.bridge

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.util.Log
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow

/**
 * SunmiScale - Wrapper for Sunmi built-in electronic scale.
 *
 * Listens for weight data from the Sunmi T2 integrated scale.
 * Emits weight values via StateFlow for Compose UI observation.
 *
 * Weight unit: grams (Int).
 * For pricing: price is per 500g (jin), so: amount = price * weight / 500
 */
class SunmiScale(private val context: Context) {

    companion object {
        private const val TAG = "SunmiScale"
        // Sunmi scale broadcast actions
        private const val ACTION_SCALE_DATA = "com.sunmi.scale.DATA"
        private const val EXTRA_WEIGHT = "weight"
        private const val EXTRA_STABLE = "stable"
        private const val EXTRA_UNIT = "unit"
    }

    private val _weight = MutableStateFlow(0)
    val weight: StateFlow<Int> = _weight.asStateFlow()

    private val _isStable = MutableStateFlow(false)
    val isStable: StateFlow<Boolean> = _isStable.asStateFlow()

    private val _isListening = MutableStateFlow(false)
    val isListening: StateFlow<Boolean> = _isListening.asStateFlow()

    private var onWeightChanged: ((Int, Boolean) -> Unit)? = null

    private val scaleReceiver = object : BroadcastReceiver() {
        override fun onReceive(context: Context?, intent: Intent?) {
            if (intent?.action == ACTION_SCALE_DATA) {
                val weightGram = intent.getIntExtra(EXTRA_WEIGHT, 0)
                val stable = intent.getBooleanExtra(EXTRA_STABLE, false)

                _weight.value = weightGram
                _isStable.value = stable

                onWeightChanged?.invoke(weightGram, stable)

                Log.d(TAG, "Scale: ${weightGram}g, stable=$stable")
            }
        }
    }

    /**
     * Start listening for scale data.
     * Register broadcast receiver for Sunmi scale events.
     */
    fun startListening(callback: ((weight: Int, stable: Boolean) -> Unit)? = null) {
        onWeightChanged = callback
        try {
            val filter = IntentFilter(ACTION_SCALE_DATA)
            context.registerReceiver(scaleReceiver, filter)
            _isListening.value = true
            Log.i(TAG, "Scale listening started")
        } catch (e: Exception) {
            Log.w(TAG, "Scale not available: ${e.message}")
        }
    }

    /**
     * Stop listening for scale data.
     */
    fun stopListening() {
        try {
            context.unregisterReceiver(scaleReceiver)
        } catch (_: Exception) { }
        _isListening.value = false
        onWeightChanged = null
        Log.i(TAG, "Scale listening stopped")
    }

    /**
     * Zero/tare the scale.
     */
    fun tare() {
        try {
            val intent = Intent("com.sunmi.scale.TARE")
            context.sendBroadcast(intent)
            Log.i(TAG, "Scale tare command sent")
        } catch (e: Exception) {
            Log.w(TAG, "Scale tare failed: ${e.message}")
        }
    }

    /**
     * Calculate price for weighted item.
     *
     * @param pricePerJin Price per 500g in cents
     * @param weightGram Weight in grams
     * @return Total price in cents
     */
    fun calculatePrice(pricePerJin: Long, weightGram: Int): Long {
        return (pricePerJin * weightGram) / 500
    }
}
