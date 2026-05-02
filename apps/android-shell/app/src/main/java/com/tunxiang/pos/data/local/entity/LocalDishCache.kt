package com.tunxiang.pos.data.local.entity

import androidx.room.ColumnInfo
import androidx.room.Entity
import androidx.room.Index
import androidx.room.PrimaryKey

/**
 * LocalDishCache — Full menu cache for offline ordering.
 *
 * Sync strategy:
 * - Full pull on app startup if cache empty
 * - Incremental sync via updated_at > last sync timestamp
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
    val id: String,

    @ColumnInfo(name = "tenant_id")
    val tenantId: String,

    @ColumnInfo(name = "store_id")
    val storeId: String,

    @ColumnInfo(name = "name")
    val name: String,

    @ColumnInfo(name = "short_name")
    val shortName: String? = null,

    @ColumnInfo(name = "category")
    val category: String,

    @ColumnInfo(name = "category_sort")
    val categorySort: Int = 0,

    @ColumnInfo(name = "pricing_type")
    val pricingType: String = "fixed",

    @ColumnInfo(name = "price")
    val price: Long,

    @ColumnInfo(name = "member_price")
    val memberPrice: Long? = null,

    @ColumnInfo(name = "cost")
    val cost: Long? = null,

    @ColumnInfo(name = "image_url")
    val imageUrl: String? = null,

    @ColumnInfo(name = "description")
    val description: String? = null,

    @ColumnInfo(name = "unit")
    val unit: String = "份",

    @ColumnInfo(name = "min_order_qty")
    val minOrderQty: Int = 1,

    @ColumnInfo(name = "status")
    val status: String = "on_sale",

    @ColumnInfo(name = "tags")
    val tags: String? = null,

    @ColumnInfo(name = "specs")
    val specs: String? = null,

    @ColumnInfo(name = "updated_at")
    val updatedAt: Long = System.currentTimeMillis(),
)
