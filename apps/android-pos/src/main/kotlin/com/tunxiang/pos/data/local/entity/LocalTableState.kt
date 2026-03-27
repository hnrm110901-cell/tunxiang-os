package com.tunxiang.pos.data.local.entity

import androidx.room.ColumnInfo
import androidx.room.Entity
import androidx.room.Index
import androidx.room.PrimaryKey

/**
 * LocalTableState - Cached table status for the table map screen.
 *
 * Refreshed on app open and pull-to-refresh.
 * Status colors: free=green, occupied=red, reserved=yellow, disabled=gray.
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
    val id: String,                              // Table UUID

    @ColumnInfo(name = "tenant_id")
    val tenantId: String,

    @ColumnInfo(name = "store_id")
    val storeId: String,

    @ColumnInfo(name = "table_number")
    val tableNumber: String,                     // Display number e.g. "A1", "B3"

    @ColumnInfo(name = "table_name")
    val tableName: String,                       // Display name e.g. "大厅1号桌"

    @ColumnInfo(name = "area")
    val area: String = "大厅",                   // Area/zone: 大厅/包间/露台

    @ColumnInfo(name = "capacity")
    val capacity: Int = 4,                       // Max seats

    @ColumnInfo(name = "status")
    val status: String = "free",                 // free / occupied / reserved / disabled

    @ColumnInfo(name = "current_order_id")
    val currentOrderId: String? = null,          // Active order on this table

    @ColumnInfo(name = "guest_count")
    val guestCount: Int? = null,                 // Current guests at table

    @ColumnInfo(name = "opened_at")
    val openedAt: Long? = null,                  // When table was opened (for duration calc)

    @ColumnInfo(name = "order_amount")
    val orderAmount: Long? = null,               // Current order subtotal in cents

    @ColumnInfo(name = "sort_order")
    val sortOrder: Int = 0,                      // Display sort order

    @ColumnInfo(name = "updated_at")
    val updatedAt: Long = System.currentTimeMillis(),
)
