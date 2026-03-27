package com.tunxiang.pos.sync

import android.content.Context
import android.net.ConnectivityManager
import android.net.Network
import android.net.NetworkCapabilities
import android.net.NetworkRequest
import android.util.Log
import androidx.work.*
import com.tunxiang.pos.data.local.TunxiangDatabase
import com.tunxiang.pos.data.remote.TxCoreApi
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import java.util.concurrent.TimeUnit

/**
 * SyncManager - Online/offline state management + WorkManager scheduling.
 *
 * Monitors network connectivity and triggers sync workers:
 * - Periodic dish sync every 5 minutes
 * - Immediate queue processing when connectivity is restored
 * - Exponential backoff retry (max 3 attempts)
 */
class SyncManager(
    private val context: Context,
    private val database: TunxiangDatabase,
    private val api: TxCoreApi,
) {
    companion object {
        private const val TAG = "SyncManager"
        const val SYNC_WORK_NAME = "tx_pos_sync"
        const val DISH_SYNC_WORK_NAME = "tx_pos_dish_sync"
    }

    private val _isOnline = MutableStateFlow(false)
    val isOnlineFlow: StateFlow<Boolean> = _isOnline.asStateFlow()

    private val connectivityManager =
        context.getSystemService(Context.CONNECTIVITY_SERVICE) as ConnectivityManager

    fun isOnline(): Boolean = _isOnline.value

    /**
     * Start monitoring connectivity and schedule periodic sync.
     */
    fun startMonitoring() {
        // Check initial state
        _isOnline.value = checkConnectivity()

        // Listen for changes
        val networkCallback = object : ConnectivityManager.NetworkCallback() {
            override fun onAvailable(network: Network) {
                Log.i(TAG, "Network available")
                _isOnline.value = true
                triggerImmediateSync()
            }

            override fun onLost(network: Network) {
                Log.w(TAG, "Network lost")
                _isOnline.value = false
            }

            override fun onCapabilitiesChanged(network: Network, capabilities: NetworkCapabilities) {
                _isOnline.value = capabilities.hasCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET)
            }
        }

        val request = NetworkRequest.Builder()
            .addCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET)
            .build()
        connectivityManager.registerNetworkCallback(request, networkCallback)

        // Schedule periodic sync workers
        schedulePeriodic()
    }

    private fun checkConnectivity(): Boolean {
        val network = connectivityManager.activeNetwork ?: return false
        val capabilities = connectivityManager.getNetworkCapabilities(network) ?: return false
        return capabilities.hasCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET)
    }

    /**
     * Schedule periodic sync workers:
     * - Queue sync: every 15 minutes (WorkManager minimum)
     * - Dish sync: every 15 minutes (triggers incremental dish pull)
     */
    private fun schedulePeriodic() {
        val workManager = WorkManager.getInstance(context)

        // Queue sync worker - process pending offline operations
        val syncWork = PeriodicWorkRequestBuilder<SyncWorker>(
            15, TimeUnit.MINUTES
        )
            .setConstraints(
                Constraints.Builder()
                    .setRequiredNetworkType(NetworkType.CONNECTED)
                    .build()
            )
            .setBackoffCriteria(
                BackoffPolicy.EXPONENTIAL,
                WorkRequest.MIN_BACKOFF_MILLIS,
                TimeUnit.MILLISECONDS
            )
            .build()

        workManager.enqueueUniquePeriodicWork(
            SYNC_WORK_NAME,
            ExistingPeriodicWorkPolicy.KEEP,
            syncWork
        )

        // Dish sync worker - incremental menu sync
        val dishSyncWork = PeriodicWorkRequestBuilder<DishSyncWorker>(
            15, TimeUnit.MINUTES
        )
            .setConstraints(
                Constraints.Builder()
                    .setRequiredNetworkType(NetworkType.CONNECTED)
                    .build()
            )
            .build()

        workManager.enqueueUniquePeriodicWork(
            DISH_SYNC_WORK_NAME,
            ExistingPeriodicWorkPolicy.KEEP,
            dishSyncWork
        )

        Log.i(TAG, "Periodic sync workers scheduled")
    }

    /**
     * Trigger immediate sync when connectivity is restored.
     */
    fun triggerImmediateSync() {
        val workManager = WorkManager.getInstance(context)

        val immediateSync = OneTimeWorkRequestBuilder<SyncWorker>()
            .setConstraints(
                Constraints.Builder()
                    .setRequiredNetworkType(NetworkType.CONNECTED)
                    .build()
            )
            .build()

        workManager.enqueue(immediateSync)
        Log.i(TAG, "Immediate sync triggered")
    }
}
