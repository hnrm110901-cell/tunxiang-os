package com.tunxiang.pos.data.local.entity

import androidx.room.ColumnInfo
import androidx.room.Entity
import androidx.room.Index
import androidx.room.PrimaryKey

/**
 * LocalOrder - Room entity for orders cached offline.
 *
 * Maps to the server-side Order entity.
 * Offline-created orders get a UUID primary key and sync via SyncQueue.
 */
@Entity(
    tableName = "orders",
    indices = [
        Index(value = ["tenant_id"]),
        Index(value = ["store_id"]),
        Index(value = ["table_id"]),
        Index(value = ["status"]),
        Index(value = ["created_at"]),
    ]
)
data class LocalOrder(
    @PrimaryKey
    val id: String,                              // UUID, generated client-side if offline

    @ColumnInfo(name = "tenant_id")
    val tenantId: String,

    @ColumnInfo(name = "store_id")
    val storeId: String,

    @ColumnInfo(name = "table_id")
    val tableId: String?,                        // null for takeaway

    @ColumnInfo(name = "order_number")
    val orderNumber: String,                     // Display number e.g. "A001"

    @ColumnInfo(name = "order_type")
    val orderType: String,                       // dine_in / takeaway / delivery

    @ColumnInfo(name = "guest_count")
    val guestCount: Int = 1,

    @ColumnInfo(name = "status")
    val status: String = "open",                 // open / serving / settling / settled / cancelled

    @ColumnInfo(name = "subtotal")
    val subtotal: Long = 0,                      // Amount in cents (fen)

    @ColumnInfo(name = "discount_amount")
    val discountAmount: Long = 0,                // Total discount in cents

    @ColumnInfo(name = "total_amount")
    val totalAmount: Long = 0,                   // Final amount in cents

    @ColumnInfo(name = "paid_amount")
    val paidAmount: Long = 0,                    // Amount already paid in cents

    @ColumnInfo(name = "cashier_id")
    val cashierId: String,

    @ColumnInfo(name = "cashier_name")
    val cashierName: String,

    @ColumnInfo(name = "remark")
    val remark: String? = null,

    @ColumnInfo(name = "created_at")
    val createdAt: Long = System.currentTimeMillis(),

    @ColumnInfo(name = "updated_at")
    val updatedAt: Long = System.currentTimeMillis(),

    @ColumnInfo(name = "settled_at")
    val settledAt: Long? = null,

    @ColumnInfo(name = "synced")
    val synced: Boolean = false,                 // Whether synced to server

    @ColumnInfo(name = "server_id")
    val serverId: String? = null,                // Server-assigned ID after sync
)
