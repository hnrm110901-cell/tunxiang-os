package com.tunxiang.pos.data.repository

import android.util.Log
import com.tunxiang.pos.data.local.dao.DishDao
import com.tunxiang.pos.data.local.entity.LocalDishCache
import com.tunxiang.pos.data.remote.TxCoreApi
import com.tunxiang.pos.sync.SyncManager
import kotlinx.coroutines.flow.Flow

/**
 * DishRepository - Full cache + 5-minute incremental sync.
 *
 * Strategy:
 * - On startup: full pull if cache is empty, else incremental
 * - Every 5 minutes: incremental (updated_after = last sync timestamp)
 * - Always serve from Room cache for instant UI
 */
class DishRepository(
    private val dishDao: DishDao,
    private val api: TxCoreApi,
    private val syncManager: SyncManager,
) {
    companion object {
        private const val TAG = "DishRepository"
    }

    /**
     * Sync dishes from server. Full pull if empty, incremental otherwise.
     */
    suspend fun syncDishes(storeId: String) {
        if (!syncManager.isOnline()) {
            Log.d(TAG, "Offline, skipping dish sync")
            return
        }

        try {
            val lastUpdated = dishDao.getLastUpdated(storeId)
            val count = dishDao.countOnSale(storeId)

            if (count == 0 || lastUpdated == null) {
                // Full pull
                fullSync(storeId)
            } else {
                // Incremental: only dishes updated after last sync
                incrementalSync(storeId, lastUpdated)
            }
        } catch (e: Exception) {
            Log.e(TAG, "Dish sync failed", e)
        }
    }

    private suspend fun fullSync(storeId: String) {
        Log.i(TAG, "Full dish sync for store $storeId")
        var page = 1
        val allDishes = mutableListOf<LocalDishCache>()

        while (true) {
            val response = api.getDishes(storeId = storeId, page = page, size = 500)
            if (!response.isSuccessful || response.body()?.ok != true) break

            val paginated = response.body()!!.data ?: break
            val dishes = paginated.items.map { it.toLocal(storeId) }
            allDishes.addAll(dishes)

            if (allDishes.size >= paginated.total) break
            page++
        }

        if (allDishes.isNotEmpty()) {
            dishDao.clearStore(storeId)
            dishDao.insertAll(allDishes)
            Log.i(TAG, "Full sync complete: ${allDishes.size} dishes")
        }
    }

    private suspend fun incrementalSync(storeId: String, updatedAfter: Long) {
        Log.d(TAG, "Incremental dish sync after $updatedAfter")
        val response = api.getDishes(
            storeId = storeId,
            updatedAfter = updatedAfter,
            page = 1,
            size = 500
        )
        if (response.isSuccessful && response.body()?.ok == true) {
            val dishes = response.body()!!.data?.items?.map { it.toLocal(storeId) } ?: emptyList()
            if (dishes.isNotEmpty()) {
                dishDao.insertAll(dishes)  // REPLACE on conflict
                Log.d(TAG, "Incremental sync: ${dishes.size} dishes updated")
            }
        }
    }

    // ─── Observation (always from local cache) ───

    fun observeAllDishes(storeId: String): Flow<List<LocalDishCache>> =
        dishDao.observeAllDishes(storeId)

    fun observeByCategory(storeId: String, category: String): Flow<List<LocalDishCache>> =
        dishDao.observeByCategory(storeId, category)

    fun searchDishes(storeId: String, query: String): Flow<List<LocalDishCache>> =
        dishDao.searchDishes(storeId, query)

    fun observeCategories(storeId: String): Flow<List<String>> =
        dishDao.observeCategories(storeId)

    suspend fun getDish(dishId: String): LocalDishCache? =
        dishDao.getDish(dishId)
}

// ─── Mapping ───

private fun com.tunxiang.pos.data.remote.DishResponse.toLocal(storeId: String): LocalDishCache {
    return LocalDishCache(
        id = id,
        tenantId = "", // Set from auth context
        storeId = storeId,
        name = name,
        shortName = short_name,
        category = category,
        categorySort = category_sort,
        pricingType = pricing_type,
        price = price,
        memberPrice = member_price,
        cost = cost,
        imageUrl = image_url,
        description = description,
        unit = unit,
        minOrderQty = min_order_qty,
        status = status,
        tags = tags?.joinToString(","),
        updatedAt = System.currentTimeMillis(),
    )
}
