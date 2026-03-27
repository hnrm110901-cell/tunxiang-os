package com.tunxiang.pos.data.repository

import com.google.gson.Gson
import com.tunxiang.pos.TunxiangPOSApp
import com.tunxiang.pos.data.local.dao.OrderDao
import com.tunxiang.pos.data.local.dao.SyncQueueDao
import com.tunxiang.pos.data.local.dao.TableDao
import com.tunxiang.pos.data.local.entity.*
import com.tunxiang.pos.data.remote.*
import com.tunxiang.pos.sync.SyncManager
import kotlinx.coroutines.flow.Flow
import java.util.UUID

/**
 * OrderRepository - Online-first with offline fallback.
 *
 * Strategy:
 * 1. Try API call first
 * 2. On success: save to Room + return
 * 3. On failure (network): save to Room + enqueue SyncQueue + return local data
 */
class OrderRepository(
    private val orderDao: OrderDao,
    private val tableDao: TableDao,
    private val syncQueueDao: SyncQueueDao,
    private val api: TxCoreApi,
    private val syncManager: SyncManager,
) {
    private val gson = Gson()
    private val app get() = TunxiangPOSApp.instance

    /**
     * Create a new order (open table).
     * Online-first: POST /api/v1/orders, fallback to local-only.
     */
    suspend fun createOrder(
        tableId: String?,
        orderType: String,
        guestCount: Int,
    ): Result<LocalOrder> {
        val localId = UUID.randomUUID().toString()
        val storeId = app.apiClient.getStoreId()
        val tenantId = app.apiClient.getTenantId()
        val cashierId = app.apiClient.getCashierId()
        val cashierName = app.apiClient.getCashierName()

        val localOrder = LocalOrder(
            id = localId,
            tenantId = tenantId,
            storeId = storeId,
            tableId = tableId,
            orderNumber = generateOrderNumber(),
            orderType = orderType,
            guestCount = guestCount,
            status = "open",
            cashierId = cashierId,
            cashierName = cashierName,
        )

        return if (syncManager.isOnline()) {
            try {
                val response = api.createOrder(
                    CreateOrderRequest(
                        store_id = storeId,
                        table_id = tableId,
                        order_type = orderType,
                        guest_count = guestCount,
                        cashier_id = cashierId,
                        cashier_name = cashierName,
                    )
                )
                if (response.isSuccessful && response.body()?.ok == true) {
                    val serverOrder = response.body()!!.data!!
                    val synced = localOrder.copy(
                        id = serverOrder.id,
                        orderNumber = serverOrder.order_number,
                        synced = true,
                        serverId = serverOrder.id,
                    )
                    orderDao.insertOrder(synced)
                    // Update table status
                    if (tableId != null) {
                        tableDao.updateTableStatus(
                            tableId = tableId,
                            status = "occupied",
                            orderId = synced.id,
                            guestCount = guestCount,
                            openedAt = System.currentTimeMillis(),
                        )
                    }
                    Result.success(synced)
                } else {
                    // API error - save locally
                    saveOfflineOrder(localOrder, tableId, guestCount)
                }
            } catch (e: Exception) {
                saveOfflineOrder(localOrder, tableId, guestCount)
            }
        } else {
            saveOfflineOrder(localOrder, tableId, guestCount)
        }
    }

    private suspend fun saveOfflineOrder(
        order: LocalOrder,
        tableId: String?,
        guestCount: Int,
    ): Result<LocalOrder> {
        orderDao.insertOrder(order)
        if (tableId != null) {
            tableDao.updateTableStatus(
                tableId = tableId,
                status = "occupied",
                orderId = order.id,
                guestCount = guestCount,
                openedAt = System.currentTimeMillis(),
            )
        }
        // Enqueue sync
        syncQueueDao.enqueue(
            SyncQueueEntry(
                action = "CREATE_ORDER",
                endpoint = "/api/v1/orders",
                method = "POST",
                payload = gson.toJson(
                    CreateOrderRequest(
                        store_id = order.storeId,
                        table_id = tableId,
                        order_type = order.orderType,
                        guest_count = order.guestCount,
                        cashier_id = order.cashierId,
                        cashier_name = order.cashierName,
                    )
                ),
                entityId = order.id,
            )
        )
        return Result.success(order)
    }

    /**
     * Add items to an order.
     */
    suspend fun addItems(
        orderId: String,
        items: List<CartItem>,
    ): Result<Unit> {
        // Save locally first
        val orderItems = items.map { cart ->
            LocalOrderItem(
                id = UUID.randomUUID().toString(),
                orderId = orderId,
                dishId = cart.dishId,
                dishName = cart.dishName,
                category = cart.category,
                pricingType = cart.pricingType,
                unitPrice = cart.unitPrice,
                quantity = cart.quantity,
                weightGram = cart.weightGram,
                amount = cart.amount,
                discountAmount = 0,
                finalAmount = cart.amount,
                note = cart.note,
            )
        }
        orderDao.insertItems(orderItems)
        recalculateOrderTotal(orderId)

        if (syncManager.isOnline()) {
            try {
                val response = api.addItems(
                    orderId,
                    AddItemsRequest(
                        items = items.map { cart ->
                            AddItemEntry(
                                dish_id = cart.dishId,
                                quantity = cart.quantity,
                                weight_gram = cart.weightGram,
                                unit_price = if (cart.pricingType == "market") cart.unitPrice else null,
                                note = cart.note,
                            )
                        }
                    )
                )
                if (response.isSuccessful && response.body()?.ok == true) {
                    return Result.success(Unit)
                }
            } catch (_: Exception) { }
        }

        // Enqueue for sync
        syncQueueDao.enqueue(
            SyncQueueEntry(
                action = "ADD_ITEMS",
                endpoint = "/api/v1/orders/$orderId/items",
                method = "POST",
                payload = gson.toJson(
                    AddItemsRequest(
                        items = items.map {
                            AddItemEntry(it.dishId, it.quantity, it.weightGram,
                                if (it.pricingType == "market") it.unitPrice else null, it.note)
                        }
                    )
                ),
                entityId = orderId,
            )
        )
        return Result.success(Unit)
    }

    /**
     * Send pending items to kitchen (batch).
     */
    suspend fun sendToKitchen(orderId: String): Result<Unit> {
        orderDao.sendToKitchen(orderId)
        orderDao.updateStatus(orderId, "serving")
        return Result.success(Unit)
    }

    /**
     * Settle an order with payments.
     */
    suspend fun settleOrder(
        orderId: String,
        payments: List<PaymentInfo>,
    ): Result<SettleResult> {
        val order = orderDao.getOrder(orderId) ?: return Result.failure(Exception("Order not found"))

        // Save payments locally
        var totalPaid = 0L
        for (p in payments) {
            val payment = LocalPayment(
                id = UUID.randomUUID().toString(),
                orderId = orderId,
                method = p.method,
                amount = p.amount,
                receivedAmount = p.receivedAmount,
                changeAmount = if (p.receivedAmount != null) p.receivedAmount - p.amount else null,
                tradeNo = p.tradeNo,
                status = "success",
                paidAt = System.currentTimeMillis(),
            )
            orderDao.insertPayment(payment)
            totalPaid += p.amount
        }

        val changeAmount = if (totalPaid > order.totalAmount) totalPaid - order.totalAmount else 0L
        val settledOrder = order.copy(
            status = "settled",
            paidAmount = totalPaid,
            settledAt = System.currentTimeMillis(),
            updatedAt = System.currentTimeMillis(),
        )
        orderDao.updateOrder(settledOrder)

        // Clear table
        if (order.tableId != null) {
            tableDao.clearTable(order.tableId)
        }

        // Sync settle to server
        if (syncManager.isOnline()) {
            try {
                api.settleOrder(
                    orderId,
                    SettleRequest(
                        payments = payments.map {
                            PaymentEntry(it.method, it.amount, it.tradeNo, it.receivedAmount)
                        }
                    )
                )
            } catch (_: Exception) {
                enqueueSyncSettle(orderId, payments)
            }
        } else {
            enqueueSyncSettle(orderId, payments)
        }

        return Result.success(SettleResult(orderId, totalPaid, changeAmount))
    }

    private suspend fun enqueueSyncSettle(orderId: String, payments: List<PaymentInfo>) {
        syncQueueDao.enqueue(
            SyncQueueEntry(
                action = "SETTLE_ORDER",
                endpoint = "/api/v1/orders/$orderId/settle",
                method = "POST",
                payload = gson.toJson(
                    SettleRequest(payments.map {
                        PaymentEntry(it.method, it.amount, it.tradeNo, it.receivedAmount)
                    })
                ),
                entityId = orderId,
            )
        )
    }

    /**
     * Recalculate order subtotal/total from items.
     */
    suspend fun recalculateOrderTotal(orderId: String) {
        val items = orderDao.getActiveOrderItems(orderId)
        val subtotal = items.sumOf { it.amount }
        val discount = items.sumOf { it.discountAmount }
        val total = subtotal - discount
        orderDao.updateAmounts(orderId, subtotal, discount, total)

        // Also update table display amount
        val order = orderDao.getOrder(orderId)
        if (order?.tableId != null) {
            tableDao.updateOrderAmount(order.tableId, total)
        }
    }

    // ─── Observation ───

    fun observeOrder(orderId: String): Flow<LocalOrder?> = orderDao.observeOrder(orderId)
    fun observeOrderItems(orderId: String): Flow<List<LocalOrderItem>> = orderDao.observeOrderItems(orderId)
    fun observePayments(orderId: String): Flow<List<LocalPayment>> = orderDao.observePayments(orderId)

    // ─── Shift/Daily queries ───

    suspend fun countSettledOrders(storeId: String, from: Long, to: Long) =
        orderDao.countSettledOrders(storeId, from, to)

    suspend fun sumRevenue(storeId: String, from: Long, to: Long) =
        orderDao.sumRevenue(storeId, from, to)

    suspend fun sumDiscounts(storeId: String, from: Long, to: Long) =
        orderDao.sumDiscounts(storeId, from, to)

    suspend fun sumCovers(storeId: String, from: Long, to: Long) =
        orderDao.sumCovers(storeId, from, to)

    suspend fun sumByPaymentMethod(storeId: String, from: Long, to: Long, method: String) =
        orderDao.sumByPaymentMethod(storeId, from, to, method)

    suspend fun getCancelledOrders(storeId: String, from: Long, to: Long) =
        orderDao.getCancelledOrders(storeId, from, to)

    private fun generateOrderNumber(): String {
        val ts = System.currentTimeMillis()
        val seq = (ts % 10000).toString().padStart(4, '0')
        return "A$seq"
    }
}

// ─── Helper data classes ───

data class CartItem(
    val dishId: String,
    val dishName: String,
    val category: String,
    val pricingType: String,
    val unitPrice: Long,
    val quantity: Int,
    val weightGram: Int? = null,
    val amount: Long,
    val note: String? = null,
)

data class PaymentInfo(
    val method: String,
    val amount: Long,
    val tradeNo: String? = null,
    val receivedAmount: Long? = null,
)

data class SettleResult(
    val orderId: String,
    val totalPaid: Long,
    val changeAmount: Long,
)
