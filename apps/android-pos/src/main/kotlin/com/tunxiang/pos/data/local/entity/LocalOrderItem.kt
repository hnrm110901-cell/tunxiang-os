package com.tunxiang.pos.data.local.entity

import androidx.room.ColumnInfo
import androidx.room.Entity
import androidx.room.ForeignKey
import androidx.room.Index
import androidx.room.PrimaryKey

/**
 * LocalOrderItem - Individual dish/item within an order.
 *
 * Supports: fixed price, weighted (by gram), market price (manual input).
 * Prices stored in cents (fen).
 */
@Entity(
    tableName = "order_items",
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
        Index(value = ["dish_id"]),
    ]
)
data class LocalOrderItem(
    @PrimaryKey
    val id: String,                              // UUID

    @ColumnInfo(name = "order_id")
    val orderId: String,

    @ColumnInfo(name = "dish_id")
    val dishId: String,

    @ColumnInfo(name = "dish_name")
    val dishName: String,

    @ColumnInfo(name = "category")
    val category: String,                        // hot / cold / soup / staple / drink / special

    @ColumnInfo(name = "pricing_type")
    val pricingType: String = "fixed",           // fixed / weighted / market

    @ColumnInfo(name = "unit_price")
    val unitPrice: Long,                         // Price per unit in cents

    @ColumnInfo(name = "quantity")
    val quantity: Int = 1,                       // Quantity (fixed price: count)

    @ColumnInfo(name = "weight_gram")
    val weightGram: Int? = null,                 // Weight in grams (weighted items)

    @ColumnInfo(name = "amount")
    val amount: Long,                            // Line total in cents

    @ColumnInfo(name = "discount_amount")
    val discountAmount: Long = 0,                // Discount on this item in cents

    @ColumnInfo(name = "final_amount")
    val finalAmount: Long,                       // amount - discountAmount

    @ColumnInfo(name = "note")
    val note: String? = null,                    // Special instructions (e.g. "less spicy")

    @ColumnInfo(name = "status")
    val status: String = "pending",              // pending / sent_to_kitchen / cooking / served / cancelled

    @ColumnInfo(name = "sent_to_kitchen_at")
    val sentToKitchenAt: Long? = null,

    @ColumnInfo(name = "created_at")
    val createdAt: Long = System.currentTimeMillis(),

    @ColumnInfo(name = "synced")
    val synced: Boolean = false,
)
