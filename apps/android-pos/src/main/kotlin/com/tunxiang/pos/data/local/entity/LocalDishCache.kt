package com.tunxiang.pos.data.local.entity

import androidx.room.ColumnInfo
import androidx.room.Entity
import androidx.room.Index
import androidx.room.PrimaryKey

/**
 * LocalDishCache - Full menu cache for offline ordering.
 *
 * Sync strategy:
 * - Full pull on app startup
 * - Incremental sync every 5 minutes (via updated_at > lastSync)
 */
@Entity(
    tableName = "dish_cache",
    indices = [
        Index(value = ["store_id"]),
        Index(value = ["category"]),
        Index(value = ["status"]),
        Index(value = ["name"]),
        Index(value = ["updated_at"]),
    ]
)
data class LocalDishCache(
    @PrimaryKey
    val id: String,                              // Dish UUID

    @ColumnInfo(name = "tenant_id")
    val tenantId: String,

    @ColumnInfo(name = "store_id")
    val storeId: String,

    @ColumnInfo(name = "name")
    val name: String,                            // Dish name

    @ColumnInfo(name = "short_name")
    val shortName: String? = null,               // Abbreviated name for kitchen display

    @ColumnInfo(name = "category")
    val category: String,                        // hot / cold / soup / staple / drink / special

    @ColumnInfo(name = "category_sort")
    val categorySort: Int = 0,                   // Sort within category

    @ColumnInfo(name = "pricing_type")
    val pricingType: String = "fixed",           // fixed / weighted / market

    @ColumnInfo(name = "price")
    val price: Long,                             // Price in cents (for fixed); price per 500g (for weighted)

    @ColumnInfo(name = "member_price")
    val memberPrice: Long? = null,               // Member price in cents

    @ColumnInfo(name = "cost")
    val cost: Long? = null,                      // Cost in cents (for margin calculation)

    @ColumnInfo(name = "image_url")
    val imageUrl: String? = null,                // Dish photo URL

    @ColumnInfo(name = "description")
    val description: String? = null,

    @ColumnInfo(name = "unit")
    val unit: String = "份",                     // 份/斤/杯/瓶

    @ColumnInfo(name = "min_order_qty")
    val minOrderQty: Int = 1,

    @ColumnInfo(name = "status")
    val status: String = "on_sale",              // on_sale / sold_out / off_shelf

    @ColumnInfo(name = "tags")
    val tags: String? = null,                    // JSON array: ["招牌","辣","新品"]

    @ColumnInfo(name = "specs")
    val specs: String? = null,                   // JSON array of spec options

    @ColumnInfo(name = "updated_at")
    val updatedAt: Long = System.currentTimeMillis(),
)
