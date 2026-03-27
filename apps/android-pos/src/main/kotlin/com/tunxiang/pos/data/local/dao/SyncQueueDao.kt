package com.tunxiang.pos.data.local.dao

import androidx.room.*
import com.tunxiang.pos.data.local.entity.SyncQueueEntry
import kotlinx.coroutines.flow.Flow

@Dao
interface SyncQueueDao {

    @Insert
    suspend fun enqueue(entry: SyncQueueEntry): Long

    @Update
    suspend fun update(entry: SyncQueueEntry)

    @Query("SELECT * FROM sync_queue WHERE status = 'pending' ORDER BY created_at ASC LIMIT 1")
    suspend fun peekNext(): SyncQueueEntry?

    @Query("SELECT * FROM sync_queue WHERE status = 'pending' ORDER BY created_at ASC")
    suspend fun getAllPending(): List<SyncQueueEntry>

    @Query("SELECT * FROM sync_queue WHERE status IN ('pending', 'processing') ORDER BY created_at ASC")
    fun observePending(): Flow<List<SyncQueueEntry>>

    @Query("SELECT COUNT(*) FROM sync_queue WHERE status = 'pending'")
    fun observePendingCount(): Flow<Int>

    @Query("SELECT COUNT(*) FROM sync_queue WHERE status = 'pending'")
    suspend fun getPendingCount(): Int

    @Query("UPDATE sync_queue SET status = 'processing' WHERE id = :id")
    suspend fun markProcessing(id: Long)

    @Query("""
        UPDATE sync_queue SET
            status = 'synced',
            synced_at = :now
        WHERE id = :id
    """)
    suspend fun markSynced(id: Long, now: Long = System.currentTimeMillis())

    @Query("""
        UPDATE sync_queue SET
            status = CASE WHEN retry_count >= 2 THEN 'failed' ELSE 'pending' END,
            retry_count = retry_count + 1,
            error_message = :error
        WHERE id = :id
    """)
    suspend fun markRetry(id: Long, error: String)

    @Query("DELETE FROM sync_queue WHERE status = 'synced' AND synced_at < :before")
    suspend fun cleanupSynced(before: Long)

    @Query("SELECT * FROM sync_queue WHERE status = 'failed' ORDER BY created_at DESC")
    suspend fun getFailedEntries(): List<SyncQueueEntry>

    @Query("UPDATE sync_queue SET status = 'pending', retry_count = 0, error_message = NULL WHERE id = :id")
    suspend fun resetEntry(id: Long)
}
