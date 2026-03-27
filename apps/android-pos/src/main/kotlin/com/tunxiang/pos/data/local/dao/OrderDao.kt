package com.tunxiang.pos.data.local.dao

import androidx.room.*
import com.tunxiang.pos.data.local.entity.LocalOrder
import com.tunxiang.pos.data.local.entity.LocalOrderItem
import com.tunxiang.pos.data.local.entity.LocalPayment
import kotlinx.coroutines.flow.Flow

@Dao
interface OrderDao {

    // ─── Orders ───

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun insertOrder(order: LocalOrder)

    @Update
    suspend fun updateOrder(order: LocalOrder)

    @Query("SELECT * FROM orders WHERE id = :orderId")
    suspend fun getOrder(orderId: String): LocalOrder?

    @Query("SELECT * FROM orders WHERE id = :orderId")
    fun observeOrder(orderId: String): Flow<LocalOrder?>

    @Query("SELECT * FROM orders WHERE store_id = :storeId AND status IN ('open', 'serving') ORDER BY created_at DESC")
    fun observeActiveOrders(storeId: String): Flow<List<LocalOrder>>

    @Query("SELECT * FROM orders WHERE store_id = :storeId AND status = 'settled' AND settled_at >= :startOfDay ORDER BY settled_at DESC")
    fun observeSettledOrdersToday(storeId: String, startOfDay: Long): Flow<List<LocalOrder>>

    @Query("SELECT * FROM orders WHERE synced = 0 ORDER BY created_at ASC")
    suspend fun getUnsyncedOrders(): List<LocalOrder>

    @Query("UPDATE orders SET synced = 1, server_id = :serverId WHERE id = :orderId")
    suspend fun markSynced(orderId: String, serverId: String)

    @Query("UPDATE orders SET status = :status, updated_at = :now WHERE id = :orderId")
    suspend fun updateStatus(orderId: String, status: String, now: Long = System.currentTimeMillis())

    @Query("""
        UPDATE orders SET
            subtotal = :subtotal,
            discount_amount = :discount,
            total_amount = :total,
            updated_at = :now
        WHERE id = :orderId
    """)
    suspend fun updateAmounts(
        orderId: String,
        subtotal: Long,
        discount: Long,
        total: Long,
        now: Long = System.currentTimeMillis()
    )

    // ─── Order Items ───

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun insertItem(item: LocalOrderItem)

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun insertItems(items: List<LocalOrderItem>)

    @Update
    suspend fun updateItem(item: LocalOrderItem)

    @Delete
    suspend fun deleteItem(item: LocalOrderItem)

    @Query("SELECT * FROM order_items WHERE order_id = :orderId ORDER BY created_at ASC")
    fun observeOrderItems(orderId: String): Flow<List<LocalOrderItem>>

    @Query("SELECT * FROM order_items WHERE order_id = :orderId ORDER BY created_at ASC")
    suspend fun getOrderItems(orderId: String): List<LocalOrderItem>

    @Query("SELECT * FROM order_items WHERE order_id = :orderId AND status != 'cancelled'")
    suspend fun getActiveOrderItems(orderId: String): List<LocalOrderItem>

    @Query("UPDATE order_items SET quantity = :qty, amount = :amount, final_amount = :finalAmount WHERE id = :itemId")
    suspend fun updateItemQuantity(itemId: String, qty: Int, amount: Long, finalAmount: Long)

    @Query("UPDATE order_items SET status = 'sent_to_kitchen', sent_to_kitchen_at = :now WHERE order_id = :orderId AND status = 'pending'")
    suspend fun sendToKitchen(orderId: String, now: Long = System.currentTimeMillis())

    @Query("UPDATE order_items SET status = 'cancelled' WHERE id = :itemId")
    suspend fun cancelItem(itemId: String)

    // ─── Payments ───

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun insertPayment(payment: LocalPayment)

    @Query("SELECT * FROM payments WHERE order_id = :orderId ORDER BY created_at ASC")
    fun observePayments(orderId: String): Flow<List<LocalPayment>>

    @Query("SELECT * FROM payments WHERE order_id = :orderId AND status = 'success'")
    suspend fun getSuccessfulPayments(orderId: String): List<LocalPayment>

    @Query("SELECT SUM(amount) FROM payments WHERE order_id = :orderId AND status = 'success'")
    suspend fun getTotalPaid(orderId: String): Long?

    // ─── Shift/Daily aggregations ───

    @Query("""
        SELECT COUNT(*) FROM orders
        WHERE store_id = :storeId AND status = 'settled'
        AND settled_at >= :from AND settled_at < :to
    """)
    suspend fun countSettledOrders(storeId: String, from: Long, to: Long): Int

    @Query("""
        SELECT COALESCE(SUM(total_amount), 0) FROM orders
        WHERE store_id = :storeId AND status = 'settled'
        AND settled_at >= :from AND settled_at < :to
    """)
    suspend fun sumRevenue(storeId: String, from: Long, to: Long): Long

    @Query("""
        SELECT COALESCE(SUM(discount_amount), 0) FROM orders
        WHERE store_id = :storeId AND status = 'settled'
        AND settled_at >= :from AND settled_at < :to
    """)
    suspend fun sumDiscounts(storeId: String, from: Long, to: Long): Long

    @Query("""
        SELECT COALESCE(SUM(guest_count), 0) FROM orders
        WHERE store_id = :storeId AND status = 'settled'
        AND settled_at >= :from AND settled_at < :to
    """)
    suspend fun sumCovers(storeId: String, from: Long, to: Long): Int

    @Query("""
        SELECT COALESCE(SUM(p.amount), 0) FROM payments p
        INNER JOIN orders o ON p.order_id = o.id
        WHERE o.store_id = :storeId AND o.status = 'settled'
        AND o.settled_at >= :from AND o.settled_at < :to
        AND p.status = 'success' AND p.method = :method
    """)
    suspend fun sumByPaymentMethod(storeId: String, from: Long, to: Long, method: String): Long

    @Query("""
        SELECT * FROM orders
        WHERE store_id = :storeId AND status = 'cancelled'
        AND created_at >= :from AND created_at < :to
        ORDER BY created_at DESC
    """)
    suspend fun getCancelledOrders(storeId: String, from: Long, to: Long): List<LocalOrder>
}
