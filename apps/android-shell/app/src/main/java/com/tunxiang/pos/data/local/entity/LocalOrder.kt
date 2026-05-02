package com.tunxiang.pos.data.local.entity

import androidx.room.ColumnInfo
import androidx.room.Entity
import androidx.room.Index
import androidx.room.PrimaryKey

/**
 * LocalOrder — Room entity for orders cached offline.
 *
 * Maps to the server-side Order entity.
 * Offline-created orders get a UUID primary key and sync via SyncQueue.
 * All amounts in cents (fen).
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
    val id: String,

    @ColumnInfo(name = "tenant_id")
    val tenantId: String,

    @ColumnInfo(name = "store_id")
    val storeId: String,

    @ColumnInfo(name = "table_id")
    val tableId: String?,

    @ColumnInfo(name = "order_number")
    val orderNumber: String,

    @ColumnInfo(name = "order_type")
    val orderType: String,

    @ColumnInfo(name = "guest_count")
    val guestCount: Int = 1,

    @ColumnInfo(name = "status")
    val status: String = "open",

    @ColumnInfo(name = "subtotal")
    val subtotal: Long = 0,

    @ColumnInfo(name = "discount_amount")
    val discountAmount: Long = 0,

    @ColumnInfo(name = "total_amount")
    val totalAmount: Long = 0,

    @ColumnInfo(name = "paid_amount")
    val paidAmount: Long = 0,

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
    val synced: Boolean = false,

    @ColumnInfo(name = "server_id")
    val serverId: String? = null,
)
