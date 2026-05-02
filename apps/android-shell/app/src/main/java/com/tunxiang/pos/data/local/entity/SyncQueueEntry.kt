package com.tunxiang.pos.data.local.entity

import androidx.room.ColumnInfo
import androidx.room.Entity
import androidx.room.Index
import androidx.room.PrimaryKey

/**
 * SyncQueueEntry — FIFO queue for offline operations pending sync.
 *
 * Every mutation that happens offline is enqueued here.
 * SyncWorker processes entries in FIFO order when connectivity is restored.
 * Auto-fails after retry_count >= 3.
 */
@Entity(
    tableName = "sync_queue",
    indices = [
        Index(value = ["status"]),
        Index(value = ["created_at"]),
    ]
)
data class SyncQueueEntry(
    @PrimaryKey(autoGenerate = true)
    val id: Long = 0,

    @ColumnInfo(name = "action")
    val action: String,

    @ColumnInfo(name = "endpoint")
    val endpoint: String,

    @ColumnInfo(name = "method")
    val method: String = "POST",

    @ColumnInfo(name = "payload")
    val payload: String,

    @ColumnInfo(name = "entity_id")
    val entityId: String? = null,

    @ColumnInfo(name = "status")
    val status: String = "pending",

    @ColumnInfo(name = "retry_count")
    val retryCount: Int = 0,

    @ColumnInfo(name = "error_message")
    val errorMessage: String? = null,

    @ColumnInfo(name = "created_at")
    val createdAt: Long = System.currentTimeMillis(),

    @ColumnInfo(name = "synced_at")
    val syncedAt: Long? = null,
)
