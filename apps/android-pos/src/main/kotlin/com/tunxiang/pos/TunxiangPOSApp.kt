package com.tunxiang.pos

import android.app.Application
import androidx.room.Room
import androidx.work.Configuration
import androidx.work.WorkManager
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
        database = Room.databaseBuilder(
            applicationContext,
            TunxiangDatabase::class.java,
            "tunxiang_pos.db"
        )
            .fallbackToDestructiveMigration()
            .build()

        // API Client
        apiClient = ApiClient(
            baseUrl = BuildConfig.TX_CORE_BASE_URL,
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

    companion object {
        lateinit var instance: TunxiangPOSApp
            private set
    }
}
