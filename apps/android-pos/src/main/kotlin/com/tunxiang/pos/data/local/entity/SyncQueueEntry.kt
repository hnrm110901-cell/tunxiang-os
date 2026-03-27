package com.tunxiang.pos.data.local.entity

import androidx.room.ColumnInfo
import androidx.room.Entity
import androidx.room.Index
import androidx.room.PrimaryKey

/**
 * SyncQueueEntry - FIFO queue for offline operations pending sync.
 *
 * Every mutation that happens offline is enqueued here.
 * SyncWorker processes entries in FIFO order when connectivity is restored.
 * Max 3 retries with exponential backoff.
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
    val action: String,                          // CREATE_ORDER / ADD_ITEMS / SETTLE / UPDATE_TABLE / etc.

    @ColumnInfo(name = "endpoint")
    val endpoint: String,                        // API endpoint e.g. "/api/v1/orders"

    @ColumnInfo(name = "method")
    val method: String = "POST",                 // HTTP method

    @ColumnInfo(name = "payload")
    val payload: String,                         // JSON payload

    @ColumnInfo(name = "entity_id")
    val entityId: String? = null,                // Related entity UUID for deduplication

    @ColumnInfo(name = "status")
    val status: String = "pending",              // pending / processing / synced / failed

    @ColumnInfo(name = "retry_count")
    val retryCount: Int = 0,                     // Max 3

    @ColumnInfo(name = "error_message")
    val errorMessage: String? = null,            // Last error

    @ColumnInfo(name = "created_at")
    val createdAt: Long = System.currentTimeMillis(),

    @ColumnInfo(name = "synced_at")
    val syncedAt: Long? = null,
)
