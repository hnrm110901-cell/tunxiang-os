package com.tunxiang.pos.data.remote

import android.content.Context
import android.content.SharedPreferences
import com.tunxiang.pos.BuildConfig
import okhttp3.Interceptor
import okhttp3.OkHttpClient
import okhttp3.logging.HttpLoggingInterceptor
import retrofit2.Retrofit
import retrofit2.converter.gson.GsonConverterFactory
import java.util.concurrent.TimeUnit

/**
 * ApiClient - OkHttp + Retrofit client with auth interceptor.
 *
 * Handles:
 * - Bearer token authentication
 * - X-Tenant-ID header injection
 * - Request/response logging (debug builds)
 * - Timeout configuration for POS network conditions
 */
class ApiClient(
    baseUrl: String,
    context: Context,
) {
    private val prefs: SharedPreferences =
        context.getSharedPreferences("tx_pos_auth", Context.MODE_PRIVATE)

    private val authInterceptor = Interceptor { chain ->
        val token = prefs.getString("access_token", null)
        val tenantId = prefs.getString("tenant_id", null)
        val storeId = prefs.getString("store_id", null)

        val requestBuilder = chain.request().newBuilder()
            .addHeader("Content-Type", "application/json")
            .addHeader("Accept", "application/json")

        if (token != null) {
            requestBuilder.addHeader("Authorization", "Bearer $token")
        }
        if (tenantId != null) {
            requestBuilder.addHeader("X-Tenant-ID", tenantId)
        }
        if (storeId != null) {
            requestBuilder.addHeader("X-Store-ID", storeId)
        }

        chain.proceed(requestBuilder.build())
    }

    private val loggingInterceptor = HttpLoggingInterceptor().apply {
        level = if (BuildConfig.DEBUG) {
            HttpLoggingInterceptor.Level.BODY
        } else {
            HttpLoggingInterceptor.Level.BASIC  // 生产环境只记录请求行，省 5-10ms
        }
    }

    private val okHttpClient = OkHttpClient.Builder()
        .addInterceptor(authInterceptor)
        .addInterceptor(loggingInterceptor)
        .connectTimeout(5, TimeUnit.SECONDS)
        .readTimeout(15, TimeUnit.SECONDS)
        .writeTimeout(10, TimeUnit.SECONDS)
        .retryOnConnectionFailure(true)
        .connectionPool(okhttp3.ConnectionPool(10, 5, TimeUnit.MINUTES))  // 复用连接
        .build()

    private val retrofit = Retrofit.Builder()
        .baseUrl(baseUrl)
        .client(okHttpClient)
        .addConverterFactory(GsonConverterFactory.create())
        .build()

    val txCoreApi: TxCoreApi = retrofit.create(TxCoreApi::class.java)

    // ─── Auth helpers ───

    fun saveAuth(token: String, tenantId: String, storeId: String, cashierId: String, cashierName: String) {
        prefs.edit()
            .putString("access_token", token)
            .putString("tenant_id", tenantId)
            .putString("store_id", storeId)
            .putString("cashier_id", cashierId)
            .putString("cashier_name", cashierName)
            .apply()
    }

    fun getStoreId(): String = prefs.getString("store_id", "") ?: ""
    fun getTenantId(): String = prefs.getString("tenant_id", "") ?: ""
    fun getCashierId(): String = prefs.getString("cashier_id", "") ?: ""
    fun getCashierName(): String = prefs.getString("cashier_name", "") ?: ""
    fun isAuthenticated(): Boolean = prefs.getString("access_token", null) != null

    fun clearAuth() {
        prefs.edit().clear().apply()
    }
}
