package com.tunxiang.pos.data.local.dao

import androidx.room.*
import com.tunxiang.pos.data.local.entity.LocalTableState
import kotlinx.coroutines.flow.Flow

@Dao
interface TableDao {

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun insertAll(tables: List<LocalTableState>)

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun insert(table: LocalTableState)

    @Update
    suspend fun update(table: LocalTableState)

    @Query("SELECT * FROM table_states WHERE store_id = :storeId ORDER BY area, sort_order, table_number")
    fun observeAllTables(storeId: String): Flow<List<LocalTableState>>

    @Query("SELECT * FROM table_states WHERE store_id = :storeId AND area = :area ORDER BY sort_order, table_number")
    fun observeByArea(storeId: String, area: String): Flow<List<LocalTableState>>

    @Query("SELECT * FROM table_states WHERE id = :tableId")
    suspend fun getTable(tableId: String): LocalTableState?

    @Query("SELECT DISTINCT area FROM table_states WHERE store_id = :storeId ORDER BY area")
    fun observeAreas(storeId: String): Flow<List<String>>

    @Query("""
        UPDATE table_states SET
            status = :status,
            current_order_id = :orderId,
            guest_count = :guestCount,
            opened_at = :openedAt,
            updated_at = :now
        WHERE id = :tableId
    """)
    suspend fun updateTableStatus(
        tableId: String,
        status: String,
        orderId: String?,
        guestCount: Int?,
        openedAt: Long?,
        now: Long = System.currentTimeMillis()
    )

    @Query("UPDATE table_states SET order_amount = :amount, updated_at = :now WHERE id = :tableId")
    suspend fun updateOrderAmount(tableId: String, amount: Long, now: Long = System.currentTimeMillis())

    @Query("""
        UPDATE table_states SET
            status = 'free',
            current_order_id = NULL,
            guest_count = NULL,
            opened_at = NULL,
            order_amount = NULL,
            updated_at = :now
        WHERE id = :tableId
    """)
    suspend fun clearTable(tableId: String, now: Long = System.currentTimeMillis())

    @Query("DELETE FROM table_states WHERE store_id = :storeId")
    suspend fun clearStore(storeId: String)

    @Query("SELECT COUNT(*) FROM table_states WHERE store_id = :storeId AND status = 'occupied'")
    suspend fun countOccupied(storeId: String): Int

    @Query("SELECT COUNT(*) FROM table_states WHERE store_id = :storeId AND status = 'free'")
    suspend fun countFree(storeId: String): Int
}
