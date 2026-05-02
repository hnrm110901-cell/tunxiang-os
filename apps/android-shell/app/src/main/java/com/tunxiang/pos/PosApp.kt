package com.tunxiang.pos

import android.app.Application
import androidx.room.Room
import androidx.work.Configuration
import com.tunxiang.pos.data.local.TunxiangDatabase
import com.tunxiang.pos.data.remote.ApiClient
import com.tunxiang.pos.sync.SyncManager

/**
 * PosApp — Application class for Tunxiang POS WebView shell.
 *
 * Merges the WebView shell with the offline-first data layer:
 * - Room database for offline POS operations
 * - Retrofit API client for cloud communication
 * - WorkManager for background sync processing
 */
class PosApp : Application(), Configuration.Provider {

    lateinit var database: TunxiangDatabase
        private set

    lateinit var apiClient: ApiClient
        private set

    lateinit var syncManager: SyncManager
        private set

    override fun onCreate() {
        super.onCreate()
        instance = this

        database = Room.databaseBuilder(
            applicationContext,
            TunxiangDatabase::class.java,
            "tunxiang_pos.db"
        )
            .fallbackToDestructiveMigration()
            .build()

        apiClient = ApiClient(
            baseUrl = BuildConfig.TX_CORE_BASE_URL,
            context = applicationContext
        )

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
        lateinit var instance: PosApp
            private set
    }
}
