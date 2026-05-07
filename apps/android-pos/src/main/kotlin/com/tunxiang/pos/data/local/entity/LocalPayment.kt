package com.tunxiang.pos.data.local.entity

import androidx.room.ColumnInfo
import androidx.room.Entity
import androidx.room.ForeignKey
import androidx.room.Index
import androidx.room.PrimaryKey

/**
 * LocalPayment - Payment record for an order.
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
            onDelete = ForeignKey.CASCADE
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
    val id: String,                              // UUID

    @ColumnInfo(name = "order_id")
    val orderId: String,

    @ColumnInfo(name = "method")
    val method: String,                          // cash / wechat / alipay / unionpay / member / credit

    @ColumnInfo(name = "amount")
    val amount: Long,                            // Payment amount in cents

    @ColumnInfo(name = "received_amount")
    val receivedAmount: Long? = null,            // For cash: actual amount received

    @ColumnInfo(name = "change_amount")
    val changeAmount: Long? = null,              // For cash: change given

    @ColumnInfo(name = "trade_no")
    val tradeNo: String? = null,                 // Third-party transaction number

    @ColumnInfo(name = "status")
    val status: String = "pending",              // pending / success / failed / refunded

    @ColumnInfo(name = "paid_at")
    val paidAt: Long? = null,

    @ColumnInfo(name = "created_at")
    val createdAt: Long = System.currentTimeMillis(),

    @ColumnInfo(name = "synced")
    val synced: Boolean = false,

    // ─── V4 sprint D2 (2026-05-07): hybrid architecture sync metadata ───

    @ColumnInfo(name = "expires_at")
    val expiresAt: Long? = null,                 // Cache expiry timestamp ms (4h TTL for read-cache)

    @ColumnInfo(name = "source")
    val source: String = "remote",               // "remote" / "local-pending" / "local-synced"

    @ColumnInfo(name = "synced_at")
    val syncedAt: Long? = null,                  // Last successful sync timestamp ms
)
