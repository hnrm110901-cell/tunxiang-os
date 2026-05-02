package com.tunxiang.pos.data.local.entity

import androidx.room.ColumnInfo
import androidx.room.Entity
import androidx.room.ForeignKey
import androidx.room.Index
import androidx.room.PrimaryKey

/**
 * LocalPayment — Payment record for an order.
 *
 * Supports multi-payment split: one order can have multiple payment records.
 * All amounts in cents (fen).
 */
@Entity(
    tableName = "payments",
    foreignKeys = [
        ForeignKey(
            entity = LocalOrder::class,
            parentColumns = ["id"],
            childColumns = ["order_id"],
            onDelete = ForeignKey.CASCADE,
        )
    ],
    indices = [
        Index(value = ["order_id"]),
        Index(value = ["method"]),
        Index(value = ["trade_no"]),
    ]
)
data class LocalPayment(
    @PrimaryKey
    val id: String,

    @ColumnInfo(name = "order_id")
    val orderId: String,

    @ColumnInfo(name = "method")
    val method: String,

    @ColumnInfo(name = "amount")
    val amount: Long,

    @ColumnInfo(name = "received_amount")
    val receivedAmount: Long? = null,

    @ColumnInfo(name = "change_amount")
    val changeAmount: Long? = null,

    @ColumnInfo(name = "trade_no")
    val tradeNo: String? = null,

    @ColumnInfo(name = "status")
    val status: String = "pending",

    @ColumnInfo(name = "paid_at")
    val paidAt: Long? = null,

    @ColumnInfo(name = "created_at")
    val createdAt: Long = System.currentTimeMillis(),

    @ColumnInfo(name = "synced")
    val synced: Boolean = false,
)
