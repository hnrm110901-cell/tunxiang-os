package com.tunxiang.pos.data.remote

import com.google.gson.JsonObject
import retrofit2.Response
import retrofit2.http.*

/**
 * TxCoreApi - Retrofit interface for tx-core backend.
 *
 * Matches the Sprint 1-2 API endpoints from dev-plan-2030-merged.
 * All responses follow: { "ok": bool, "data": {}, "error": {} }
 */
interface TxCoreApi {

    // ─── Orders ───

    @POST("/api/v1/orders")
    suspend fun createOrder(
        @Body body: CreateOrderRequest
    ): Response<ApiResponse<OrderResponse>>

    @GET("/api/v1/orders/{id}")
    suspend fun getOrder(
        @Path("id") orderId: String
    ): Response<ApiResponse<OrderResponse>>

    @POST("/api/v1/orders/{id}/items")
    suspend fun addItems(
        @Path("id") orderId: String,
        @Body body: AddItemsRequest
    ): Response<ApiResponse<OrderResponse>>

    @PUT("/api/v1/orders/{id}/items/{itemId}")
    suspend fun updateItem(
        @Path("id") orderId: String,
        @Path("itemId") itemId: String,
        @Body body: UpdateItemRequest
    ): Response<ApiResponse<OrderItemResponse>>

    @DELETE("/api/v1/orders/{id}/items/{itemId}")
    suspend fun deleteItem(
        @Path("id") orderId: String,
        @Path("itemId") itemId: String
    ): Response<ApiResponse<Unit>>

    @POST("/api/v1/orders/{id}/discount")
    suspend fun applyDiscount(
        @Path("id") orderId: String,
        @Body body: DiscountRequest
    ): Response<ApiResponse<OrderResponse>>

    @POST("/api/v1/orders/{id}/settle")
    suspend fun settleOrder(
        @Path("id") orderId: String,
        @Body body: SettleRequest
    ): Response<ApiResponse<SettleResponse>>

    @POST("/api/v1/orders/{id}/cancel")
    suspend fun cancelOrder(
        @Path("id") orderId: String,
        @Body body: CancelRequest?
    ): Response<ApiResponse<Unit>>

    // ─── Tables ───

    @GET("/api/v1/tables")
    suspend fun getTables(
        @Query("store_id") storeId: String
    ): Response<ApiResponse<List<TableResponse>>>

    @PUT("/api/v1/tables/{id}/status")
    suspend fun updateTableStatus(
        @Path("id") tableId: String,
        @Body body: UpdateTableStatusRequest
    ): Response<ApiResponse<TableResponse>>

    // ─── Dishes ───

    @GET("/api/v1/dishes")
    suspend fun getDishes(
        @Query("store_id") storeId: String,
        @Query("updated_after") updatedAfter: Long? = null,
        @Query("page") page: Int = 1,
        @Query("size") size: Int = 500
    ): Response<ApiResponse<PaginatedResponse<DishResponse>>>

    // ─── Shift / Daily ───

    @POST("/api/v1/shifts/handover")
    suspend fun submitShiftHandover(
        @Body body: ShiftHandoverRequest
    ): Response<ApiResponse<ShiftHandoverResponse>>

    @GET("/api/v1/daily-settlement")
    suspend fun getDailySettlement(
        @Query("store_id") storeId: String,
        @Query("date") date: String
    ): Response<ApiResponse<DailySettlementResponse>>

    @POST("/api/v1/daily-settlement/confirm")
    suspend fun confirmDailySettlement(
        @Body body: ConfirmDailySettlementRequest
    ): Response<ApiResponse<Unit>>

    // ─── Generic sync endpoint ───

    @POST("/api/v1/sync")
    suspend fun syncAction(
        @Body body: JsonObject
    ): Response<ApiResponse<JsonObject>>
}

// ─── Request/Response DTOs ───

data class ApiResponse<T>(
    val ok: Boolean,
    val data: T? = null,
    val error: ApiError? = null,
)

data class ApiError(
    val code: String,
    val message: String,
)

data class PaginatedResponse<T>(
    val items: List<T>,
    val total: Int,
)

// Orders
data class CreateOrderRequest(
    val store_id: String,
    val table_id: String?,
    val order_type: String,         // dine_in / takeaway
    val guest_count: Int,
    val cashier_id: String,
    val cashier_name: String,
)

data class OrderResponse(
    val id: String,
    val order_number: String,
    val table_id: String?,
    val status: String,
    val items: List<OrderItemResponse>?,
    val subtotal: Long,
    val discount_amount: Long,
    val total_amount: Long,
    val paid_amount: Long,
    val created_at: String,
)

data class OrderItemResponse(
    val id: String,
    val dish_id: String,
    val dish_name: String,
    val pricing_type: String,
    val unit_price: Long,
    val quantity: Int,
    val weight_gram: Int?,
    val amount: Long,
    val discount_amount: Long,
    val final_amount: Long,
    val note: String?,
    val status: String,
)

data class AddItemsRequest(
    val items: List<AddItemEntry>,
)

data class AddItemEntry(
    val dish_id: String,
    val quantity: Int = 1,
    val weight_gram: Int? = null,
    val unit_price: Long? = null,     // For market price override
    val note: String? = null,
)

data class UpdateItemRequest(
    val quantity: Int? = null,
    val note: String? = null,
    val weight_gram: Int? = null,
    val unit_price: Long? = null,
)

// Discount
data class DiscountRequest(
    val type: String,                 // percent / amount / free_item / member
    val value: Long,                  // percent: 85 = 85% / amount: cents / free_item: item_id
    val item_id: String? = null,      // For per-item discount
    val reason: String? = null,
)

// Settlement
data class SettleRequest(
    val payments: List<PaymentEntry>,
)

data class PaymentEntry(
    val method: String,
    val amount: Long,
    val trade_no: String? = null,
    val received_amount: Long? = null,
)

data class SettleResponse(
    val order_id: String,
    val status: String,
    val total_paid: Long,
    val change_amount: Long,
    val receipt_data: String?,
)

data class CancelRequest(
    val reason: String?,
)

// Tables
data class TableResponse(
    val id: String,
    val table_number: String,
    val table_name: String,
    val area: String,
    val capacity: Int,
    val status: String,
    val current_order_id: String?,
    val guest_count: Int?,
    val opened_at: String?,
    val order_amount: Long?,
    val sort_order: Int,
)

data class UpdateTableStatusRequest(
    val status: String,
    val order_id: String? = null,
    val guest_count: Int? = null,
)

// Dishes
data class DishResponse(
    val id: String,
    val name: String,
    val short_name: String?,
    val category: String,
    val category_sort: Int,
    val pricing_type: String,
    val price: Long,
    val member_price: Long?,
    val cost: Long?,
    val image_url: String?,
    val description: String?,
    val unit: String,
    val min_order_qty: Int,
    val status: String,
    val tags: List<String>?,
    val updated_at: String,
)

// Shift
data class ShiftHandoverRequest(
    val store_id: String,
    val cashier_id: String,
    val shift_start: String,
    val shift_end: String,
    val cash_counted: Long,            // Actual cash counted in cents
    val denomination_breakdown: Map<String, Int>?,  // "100": 5, "50": 3, etc.
    val notes: String?,
)

data class ShiftHandoverResponse(
    val id: String,
    val revenue: Long,
    val order_count: Int,
    val avg_check: Long,
    val cash_expected: Long,
    val cash_counted: Long,
    val variance: Long,
    val status: String,
)

// Daily Settlement
data class DailySettlementResponse(
    val date: String,
    val store_id: String,
    val revenue: Long,
    val cost: Long,
    val cost_rate: Double,
    val covers: Int,
    val avg_check: Long,
    val table_turnover: Double,
    val order_count: Int,
    val cancelled_count: Int,
    val discount_total: Long,
    val payment_breakdown: Map<String, Long>,
    val status: String,
)

data class ConfirmDailySettlementRequest(
    val store_id: String,
    val date: String,
    val manager_comment: String?,
)
