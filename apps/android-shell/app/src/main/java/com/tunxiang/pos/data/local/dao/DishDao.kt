package com.tunxiang.pos.data.local.dao

import androidx.room.*
import com.tunxiang.pos.data.local.entity.LocalDishCache
import kotlinx.coroutines.flow.Flow

@Dao
interface DishDao {

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun insertAll(dishes: List<LocalDishCache>)

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun insert(dish: LocalDishCache)

    @Query("SELECT * FROM dish_cache WHERE store_id = :storeId AND status = 'on_sale' ORDER BY category_sort, name")
    fun observeAllDishes(storeId: String): Flow<List<LocalDishCache>>

    @Query("SELECT * FROM dish_cache WHERE store_id = :storeId AND category = :category AND status = 'on_sale' ORDER BY category_sort, name")
    fun observeByCategory(storeId: String, category: String): Flow<List<LocalDishCache>>

    @Query("SELECT * FROM dish_cache WHERE store_id = :storeId AND status = 'on_sale' AND name LIKE '%' || :query || '%' ORDER BY name")
    fun searchDishes(storeId: String, query: String): Flow<List<LocalDishCache>>

    @Query("SELECT * FROM dish_cache WHERE id = :dishId")
    suspend fun getDish(dishId: String): LocalDishCache?

    @Query("SELECT DISTINCT category FROM dish_cache WHERE store_id = :storeId AND status = 'on_sale' ORDER BY category_sort")
    fun observeCategories(storeId: String): Flow<List<String>>

    @Query("SELECT MAX(updated_at) FROM dish_cache WHERE store_id = :storeId")
    suspend fun getLastUpdated(storeId: String): Long?

    @Query("DELETE FROM dish_cache WHERE store_id = :storeId")
    suspend fun clearStore(storeId: String)

    @Query("SELECT COUNT(*) FROM dish_cache WHERE store_id = :storeId AND status = 'on_sale'")
    suspend fun countOnSale(storeId: String): Int
}
