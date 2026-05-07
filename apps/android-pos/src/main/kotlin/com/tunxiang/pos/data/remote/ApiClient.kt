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
 *
 * V4 sprint D3 (2026-05-07): supports runtime baseUrl override (B2 review fix
 * of D2). When mac-station is discovered (D4 mDNS) or operator changes the
 * server address in settings, call [setBaseUrl] and the next network call
 * uses the new URL — no App restart required. The shared OkHttpClient
 * connection pool is preserved across rebuilds.
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

    /** Current base URL. Volatile because [setBaseUrl] mutates from arbitrary thread. */
    @Volatile
    private var currentBaseUrl: String = baseUrl

    /** Current Retrofit instance. Rebuilt by [setBaseUrl]. Always read via [txCoreApi]. */
    @Volatile
    private var retrofit: Retrofit = buildRetrofit(baseUrl)

    @Volatile
    private var _txCoreApi: TxCoreApi = retrofit.create(TxCoreApi::class.java)

    /**
     * Active TxCoreApi proxy. Always reflects the most recent [setBaseUrl].
     * Pattern: read once per network call (don't cache across long suspensions).
     */
    val txCoreApi: TxCoreApi get() = _txCoreApi

    /** For diagnostics / settings UI: returns the URL the next request will use. */
    fun getBaseUrl(): String = currentBaseUrl

    /**
     * Switch the API base URL at runtime. Idempotent: no-op if [newBaseUrl]
     * equals the current value.
     *
     * Thread-safety: synchronized so concurrent mDNS rediscovery + operator
     * manual change don't race. The OkHttpClient (and its connection pool)
     * is reused across rebuilds — only Retrofit + the API proxy regenerate.
     *
     * Caller responsibility (D3/D4): after a successful switch, re-trigger
     * any in-flight or queued sync operations so they pick up the new URL.
     */
    @Synchronized
    fun setBaseUrl(newBaseUrl: String) {
        require(newBaseUrl.isNotBlank()) { "newBaseUrl must not be blank" }
        require(newBaseUrl.endsWith("/")) {
            "Retrofit baseUrl must end with '/' — got: $newBaseUrl"
        }
        if (newBaseUrl == currentBaseUrl) return
        currentBaseUrl = newBaseUrl
        retrofit = buildRetrofit(newBaseUrl)
        _txCoreApi = retrofit.create(TxCoreApi::class.java)
    }

    private fun buildRetrofit(baseUrl: String): Retrofit =
        Retrofit.Builder()
            .baseUrl(baseUrl)
            .client(okHttpClient)
            .addConverterFactory(GsonConverterFactory.create())
            .build()

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
