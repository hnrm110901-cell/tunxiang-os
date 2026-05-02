package com.tunxiang.pos.data.local.entity

import androidx.room.ColumnInfo
import androidx.room.Entity
import androidx.room.Index
import androidx.room.PrimaryKey

/**
 * LocalTableState — Cached table status for the table map.
 *
 * Refreshed on app open and pull-to-refresh.
 * Status: free / occupied / reserved / disabled.
 */
@Entity(
    tableName = "table_states",
    indices = [
        Index(value = ["store_id"]),
        Index(value = ["status"]),
        Index(value = ["area"]),
    ]
)
data class LocalTableState(
    @PrimaryKey
    val id: String,

    @ColumnInfo(name = "tenant_id")
    val tenantId: String,

    @ColumnInfo(name = "store_id")
    val storeId: String,

    @ColumnInfo(name = "table_number")
    val tableNumber: String,

    @ColumnInfo(name = "table_name")
    val tableName: String,

    @ColumnInfo(name = "area")
    val area: String = "大厅",

    @ColumnInfo(name = "capacity")
    val capacity: Int = 4,

    @ColumnInfo(name = "status")
    val status: String = "free",

    @ColumnInfo(name = "current_order_id")
    val currentOrderId: String? = null,

    @ColumnInfo(name = "guest_count")
    val guestCount: Int? = null,

    @ColumnInfo(name = "opened_at")
    val openedAt: Long? = null,

    @ColumnInfo(name = "order_amount")
    val orderAmount: Long? = null,

    @ColumnInfo(name = "sort_order")
    val sortOrder: Int = 0,

    @ColumnInfo(name = "updated_at")
    val updatedAt: Long = System.currentTimeMillis(),
)
