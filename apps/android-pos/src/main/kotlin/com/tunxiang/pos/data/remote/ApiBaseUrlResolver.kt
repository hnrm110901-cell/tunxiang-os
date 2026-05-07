package com.tunxiang.pos.data.remote

import android.content.Context
import android.content.SharedPreferences
import com.tunxiang.pos.BuildConfig

/**
 * ApiBaseUrlResolver - mac-station base URL discovery + reactive propagation.
 *
 * V4 sprint D3 (2026-05-07): introduced per B2 review of D2.
 *
 * Owns the SharedPreferences("tx_mac_station") namespace and propagates
 * any base_url change to the singleton ApiClient instance, so D4 mDNS
 * discovery / operator manual config in settings UI takes effect on
 * the very next network request — no App restart required.
 *
 * Resolution order (high → low priority):
 *   1. SharedPreferences "tx_mac_station/base_url"
 *      - written by D4 mDNS discovery
 *      - written by operator manual config in settings
 *   2. BuildConfig.TX_CORE_BASE_URL — pre-D4 cloud fallback
 *
 * Wiring (TunxiangPOSApp.onCreate):
 *   val initial = ApiBaseUrlResolver.resolveInitialUrl(this)
 *   apiClient = ApiClient(baseUrl = initial, context = this)
 *   ApiBaseUrlResolver.attachReactivePropagation(this, apiClient)
 *
 * NOTE: Listener uses a strong reference held by this singleton (Kotlin
 * `object`) so the system's weak SharedPreferences listener registry won't
 * GC it. The listener leaks for the lifetime of the App process — that's
 * intentional and matches Application's own lifetime.
 */
object ApiBaseUrlResolver {
    private const val PREFS_NAME = "tx_mac_station"
    private const val KEY_BASE_URL = "base_url"

    @Volatile
    private var listener: SharedPreferences.OnSharedPreferenceChangeListener? = null

    /**
     * Returns the URL the App should boot with. Synchronous SharedPreferences
     * read; in practice < 5ms but called only once at Application.onCreate().
     */
    fun resolveInitialUrl(context: Context): String {
        val prefs = prefs(context)
        return prefs.getString(KEY_BASE_URL, null)
            ?.takeIf { it.isNotBlank() }
            ?: BuildConfig.TX_CORE_BASE_URL
    }

    /**
     * Wire SharedPreferences change → ApiClient.setBaseUrl propagation.
     *
     * Must be called exactly once after [ApiClient] is constructed. Calling
     * twice is a programming error (would leak two listeners).
     */
    @Synchronized
    fun attachReactivePropagation(context: Context, apiClient: ApiClient) {
        check(listener == null) {
            "attachReactivePropagation() called twice — only one ApiClient " +
                "should react to base_url changes"
        }
        val prefs = prefs(context)
        val l = SharedPreferences.OnSharedPreferenceChangeListener { p, key ->
            if (key != KEY_BASE_URL) return@OnSharedPreferenceChangeListener
            val newUrl = p.getString(KEY_BASE_URL, null)
            if (!newUrl.isNullOrBlank()) {
                runCatching { apiClient.setBaseUrl(normalize(newUrl)) }
            }
        }
        prefs.registerOnSharedPreferenceChangeListener(l)
        listener = l
    }

    /**
     * Update the persisted mac-station URL. Triggers the registered listener,
     * which in turn calls [ApiClient.setBaseUrl] — the next network call
     * uses the new URL.
     *
     * Used by:
     *   - D4 mDNS discovery (auto)
     *   - Operator manual config in settings UI
     */
    fun setBaseUrl(context: Context, newUrl: String) {
        require(newUrl.isNotBlank()) { "newUrl must not be blank" }
        prefs(context).edit().putString(KEY_BASE_URL, normalize(newUrl)).apply()
    }

    /**
     * Clear the override. The next [resolveInitialUrl] call (i.e. next App
     * boot) will fall back to BuildConfig.TX_CORE_BASE_URL.
     *
     * Note: existing ApiClient instance keeps its current URL until next
     * setBaseUrl — clearing alone won't downgrade the live client. If you
     * need to immediately revert, call setBaseUrl(BuildConfig.TX_CORE_BASE_URL).
     */
    fun clearOverride(context: Context) {
        prefs(context).edit().remove(KEY_BASE_URL).apply()
    }

    /** Retrofit requires baseUrl to end with '/'. Normalize defensively. */
    private fun normalize(url: String): String =
        if (url.endsWith("/")) url else "$url/"

    private fun prefs(context: Context): SharedPreferences =
        context.applicationContext
            .getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
}
