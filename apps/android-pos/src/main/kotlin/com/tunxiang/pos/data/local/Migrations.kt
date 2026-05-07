package com.tunxiang.pos.data.local

import androidx.room.migration.Migration
import androidx.sqlite.db.SupportSQLiteDatabase

/**
 * Room migrations for tunxiang_pos.db
 *
 * V4 sprint D2 (2026-05-07): added hybrid-architecture sync metadata to
 * 5 cached entities. expires_at + source + synced_at allow Repository to
 * know whether a row came from mac-station (truth source) or was locally
 * created during the offline window, and when its 4h cache TTL ends.
 *
 * Replaces the prior fallbackToDestructiveMigration() configuration which
 * would silently drop all data on schema change — unacceptable for the
 * hot path Tier 1 surfaces.
 */
val MIGRATION_1_2 = object : Migration(1, 2) {
    override fun migrate(db: SupportSQLiteDatabase) {
        val tables = listOf("orders", "order_items", "payments", "table_states", "dish_cache")
        for (t in tables) {
            db.execSQL("ALTER TABLE $t ADD COLUMN expires_at INTEGER")
            db.execSQL("ALTER TABLE $t ADD COLUMN source TEXT NOT NULL DEFAULT 'remote'")
            db.execSQL("ALTER TABLE $t ADD COLUMN synced_at INTEGER")
        }
    }
}

val ALL_MIGRATIONS: Array<Migration> = arrayOf(
    MIGRATION_1_2,
)
