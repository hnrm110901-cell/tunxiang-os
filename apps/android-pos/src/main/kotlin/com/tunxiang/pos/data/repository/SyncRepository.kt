package com.tunxiang.pos.data.repository

import android.util.Log
import com.google.gson.Gson
import com.google.gson.JsonObject
import com.google.gson.JsonParser
import com.tunxiang.pos.data.local.dao.SyncQueueDao
import com.tunxiang.pos.data.local.entity.SyncQueueEntry
import com.tunxiang.pos.data.remote.TxCoreApi
import kotlinx.coroutines.flow.Flow

/**
 * SyncRepository - FIFO processor for the sync queue.
 *
 * Processes pending entries one at a time in creation order.
 * Max 3 retries with exponential backoff handled by WorkManager.
 * Failed entries after 3 retries are marked 'failed' for manual review.
 */
class SyncRepository(
    private val syncQueueDao: SyncQueueDao,
    private val api: TxCoreApi,
) {
    companion object {
        private const val TAG = "SyncRepository"
    }

    /**
     * Process all pending sync entries in FIFO order.
     * Returns number of successfully synced entries.
     */
    suspend fun processQueue(): Int {
        var synced = 0
        while (true) {
            val entry = syncQueueDao.peekNext() ?: break
            syncQueueDao.markProcessing(entry.id)

            val success = processEntry(entry)
            if (success) {
                syncQueueDao.markSynced(entry.id)
                synced++
            } else {
                // markRetry auto-fails after 3 retries
                syncQueueDao.markRetry(entry.id, "Sync failed")
                if (entry.retryCount >= 2) {
                    Log.e(TAG, "Entry ${entry.id} failed permanently: ${entry.action}")
                }
                break // Stop processing on failure (FIFO ordering matters)
            }
        }

        // Cleanup old synced entries (older than 24 hours)
        val cutoff = System.currentTimeMillis() - 24 * 60 * 60 * 1000
        syncQueueDao.cleanupSynced(cutoff)

        return synced
    }

    private suspend fun processEntry(entry: SyncQueueEntry): Boolean {
        return try {
            val payload = JsonParser.parseString(entry.payload).asJsonObject
            val response = api.syncAction(payload)
            response.isSuccessful && response.body()?.ok == true
        } catch (e: Exception) {
            Log.e(TAG, "Sync entry ${entry.id} failed: ${e.message}")
            false
        }
    }

    fun observePendingCount(): Flow<Int> = syncQueueDao.observePendingCount()

    suspend fun getPendingCount(): Int = syncQueueDao.getPendingCount()

    suspend fun getFailedEntries(): List<SyncQueueEntry> = syncQueueDao.getFailedEntries()

    suspend fun retryFailed(entryId: Long) {
        syncQueueDao.resetEntry(entryId)
    }
}
