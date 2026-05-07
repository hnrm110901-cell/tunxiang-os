package com.tunxiang.pos

import android.app.Application
import androidx.room.Room
import androidx.work.Configuration
import androidx.work.WorkManager
import com.tunxiang.pos.data.local.ALL_MIGRATIONS
import com.tunxiang.pos.data.local.TunxiangDatabase
import com.tunxiang.pos.data.remote.ApiBaseUrlResolver
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
        // V4 sprint D2/D3 (2026-05-07): mac-station local API as truth source per CLAUDE.md §八 路线 C.
        // Resolution order: SharedPreferences override (set by D4 mDNS discovery) →
        // BuildConfig fallback (cloud TX_CORE_BASE_URL during pre-D4 transition).
        //
        // D3 (B2 review fix): ApiClient now supports runtime baseUrl override via
        // ApiClient.setBaseUrl(). ApiBaseUrlResolver wires SharedPreferences change
        // → ApiClient propagation, so D4 mDNS discovery / operator manual config
        // takes effect on the very next network call without App restart.
        apiClient = ApiClient(
            baseUrl = ApiBaseUrlResolver.resolveInitialUrl(this),
            context = applicationContext
        )
        ApiBaseUrlResolver.attachReactivePropagation(this, apiClient)

        // Sync Manager - monitors connectivity and drives sync
        // V4 sprint D3 hotfix (B1 review 2026-05-07): pass ApiClient instance
        // (not txCoreApi proxy) so SyncManager always reads the latest proxy
        // via apiClient.txCoreApi getter — survives D4 mDNS-driven setBaseUrl.
        syncManager = SyncManager(
            context = applicationContext,
            database = database,
            apiClient = apiClient
        )
        syncManager.startMonitoring()
    }

    override val workManagerConfiguration: Configuration
        get() = Configuration.Builder()
            .setMinimumLoggingLevel(android.util.Log.INFO)
            .build()

    companion object {
        lateinit var instance: TunxiangPOSApp
            private set
    }
}
