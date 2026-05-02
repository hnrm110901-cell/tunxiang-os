package com.tunxiang.pos.sync

import android.content.Context
import android.util.Log
import androidx.work.CoroutineWorker
import androidx.work.WorkerParameters
import com.tunxiang.pos.PosApp
import com.tunxiang.pos.data.repository.DishRepository
import com.tunxiang.pos.data.repository.SyncRepository

/**
 * SyncWorker - WorkManager worker for processing the sync queue.
 *
 * Runs FIFO through SyncQueueEntry records, sending each to the server.
 * Exponential backoff retry is handled by WorkManager (max 3 attempts).
 */
class SyncWorker(
    context: Context,
    params: WorkerParameters,
) : CoroutineWorker(context, params) {

    companion object {
        private const val TAG = "SyncWorker"
    }

    override suspend fun doWork(): Result {
        Log.i(TAG, "SyncWorker starting, attempt ${runAttemptCount + 1}")

        val app = PosApp.instance
        val syncRepo = SyncRepository(
            syncQueueDao = app.database.syncQueueDao(),
            api = app.apiClient.txCoreApi,
        )

        return try {
            val synced = syncRepo.processQueue()
            Log.i(TAG, "SyncWorker completed: $synced entries synced")

            val remaining = syncRepo.getPendingCount()
            if (remaining > 0) {
                Log.w(TAG, "$remaining entries still pending")
                Result.retry()
            } else {
                Result.success()
            }
        } catch (e: Exception) {
            Log.e(TAG, "SyncWorker failed", e)
            if (runAttemptCount < 3) {
                Result.retry()
            } else {
                Result.failure()
            }
        }
    }
}

/**
 * DishSyncWorker - Periodic dish cache sync (incremental).
 */
class DishSyncWorker(
    context: Context,
    params: WorkerParameters,
) : CoroutineWorker(context, params) {

    companion object {
        private const val TAG = "DishSyncWorker"
    }

    override suspend fun doWork(): Result {
        Log.i(TAG, "DishSyncWorker starting")

        val app = PosApp.instance
        val dishRepo = DishRepository(
            dishDao = app.database.dishDao(),
            api = app.apiClient.txCoreApi,
            syncManager = app.syncManager,
        )

        return try {
            val storeId = app.apiClient.getStoreId()
            if (storeId.isNotEmpty()) {
                dishRepo.syncDishes(storeId)
            }
            Result.success()
        } catch (e: Exception) {
            Log.e(TAG, "DishSyncWorker failed", e)
            Result.retry()
        }
    }
}
