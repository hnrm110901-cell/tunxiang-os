package com.tunxiang.pos

import android.app.Application
import android.content.Context
import androidx.room.Room
import androidx.work.Configuration
import androidx.work.WorkManager
import com.tunxiang.pos.data.local.ALL_MIGRATIONS
import com.tunxiang.pos.data.local.TunxiangDatabase
import com.tunxiang.pos.data.remote.ApiClient
import com.tunxiang.pos.sync.SyncManager

/**
 * TunxiangPOSApp - Application class for Tunxiang POS
 *
 * Initializes:
 * - Room database (offline-first)
 * - Retrofit API client
 * - WorkManager for background sync
 * - SyncManager for online/offline state
 */
class TunxiangPOSApp : Application(), Configuration.Provider {

    lateinit var database: TunxiangDatabase
        private set

    lateinit var apiClient: ApiClient
        private set

    lateinit var syncManager: SyncManager
        private set

    override fun onCreate() {
        super.onCreate()
        instance = this

        // Room Database - main offline storage
        // V4 sprint D2 (2026-05-07): proper Migration replaces destructive fallback
        // (fallbackToDestructiveMigration would silently drop all data on schema change,
        // unacceptable for hot path Tier 1 surfaces).
        //
        // ⚠️ MIGRATION FAILURE PROTOCOL (W1 review 2026-05-07):
        // If MIGRATION_1_2 throws (e.g. table name mismatch, column type clash),
        // Room throws IllegalStateException here — App will crash on every boot
        // (no data loss but POS is dead). Emergency recovery on-site:
        //   adb shell pm clear com.tunxiang.pos   (wipes DB, requires re-onboard)
        // D6 真机回归 MUST include a migration failure drill on 商米 T2.
        database = Room.databaseBuilder(
            applicationContext,
            TunxiangDatabase::class.java,
            "tunxiang_pos.db"
        )
            .addMigrations(*ALL_MIGRATIONS)
            .build()

        // API Client
        // V4 sprint D2 (2026-05-07): mac-station local API as truth source per CLAUDE.md §八 路线 C.
        // Resolution order: SharedPreferences override (set by D4 mDNS discovery) →
        // BuildConfig fallback (cloud TX_CORE_BASE_URL during pre-D4 transition).
        //
        // ⚠️ KNOWN LIMITATION (B2 review 2026-05-07): baseUrl is resolved ONCE at
        // process start and frozen into the ApiClient instance. D4 mDNS discovery
        // writes to SharedPreferences but this instance will NOT pick it up until
        // App restart. D3 MUST rework ApiClient to support runtime baseUrl override
        // (e.g. via OkHttp Interceptor reading prefs each request) before
        // SyncManager target switch is wired up — otherwise D3 联调第一天会因为
        // "mac-station URL 写进去了但 ApiClient 还在用旧地址" 消耗大量排查时间.
        apiClient = ApiClient(
            baseUrl = resolveApiBaseUrl(),
            context = applicationContext
        )

        // Sync Manager - monitors connectivity and drives sync
        syncManager = SyncManager(
            context = applicationContext,
            database = database,
            api = apiClient.txCoreApi
        )
        syncManager.startMonitoring()
    }

    override val workManagerConfiguration: Configuration
        get() = Configuration.Builder()
            .setMinimumLoggingLevel(android.util.Log.INFO)
            .build()

    /**
     * Resolve API base URL with mac-station priority.
     *
     * V4 sprint D2 (2026-05-07): hybrid architecture per CLAUDE.md §八 路线 C —
     * Mac mini local PG is the truth source; android-pos talks to mac-station,
     * mac-station internally syncs to cloud (300s/round).
     *
     * Resolution order:
     *   1. SharedPreferences "tx_mac_station/base_url" — set at runtime by:
     *      a. D4 mDNS / link-local discovery
     *      b. Operator manual config in settings UI
     *   2. BuildConfig.TX_CORE_BASE_URL — pre-D4 fallback to cloud direct
     *      (preserves boot-up while mac-station discovery is being built).
     *
     * NOTE: D6 real-device regression must verify that mac-station resolution
     *       works under both happy path (LAN online) and degraded path
     *       (mac-station unreachable → 4h Room cache serves stale reads).
     */
    private fun resolveApiBaseUrl(): String {
        val macPrefs = applicationContext
            .getSharedPreferences("tx_mac_station", Context.MODE_PRIVATE)
        val configured = macPrefs.getString("base_url", null)
        return when {
            !configured.isNullOrBlank() -> configured
            else -> BuildConfig.TX_CORE_BASE_URL  // pre-D4 fallback
        }
    }

    companion object {
        lateinit var instance: TunxiangPOSApp
            private set
    }
}
