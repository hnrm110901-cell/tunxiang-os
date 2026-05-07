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
/**
 * Per-table source default rationale (B1 review fix, 2026-05-07):
 *   - WRITE tables (orders / order_items / payments)    → 'local-pending'
 *     Any pre-existing v1 row is by definition a write that pre-dates
 *     mac-station integration; treating it as 'remote' would let the
 *     "cloud-wins" CRDT strategy silently overwrite legitimate offline
 *     orders during the next sync. CLAUDE.md §二十二 W8 demo gate:
 *     "断网恢复 4h 无数据丢失".
 *   - READ-only caches (table_states / dish_cache)      → 'remote'
 *     These are cache-only; no concept of "local write".
 *
 * Note: Room wraps migrate() in a transaction automatically (W4 review),
 * so the multi-statement migration is atomic — partial failure rolls back.
 *
 * Migration failure recovery (W1 review): if any ALTER fails, Room throws
 * IllegalStateException at Application.onCreate() Room.build(); App will
 * crash on every boot. Emergency: `adb shell pm clear com.tunxiang.pos`
 * (wipes DB, requires re-onboarding). D6 真机回归 must include a migration
 * failure drill on 商米 T2.
 */
val MIGRATION_1_2 = object : Migration(1, 2) {
    override fun migrate(db: SupportSQLiteDatabase) {
        // Write tables: source default = 'local-pending' (existing v1 rows
        // become pending-sync candidates).
        for (t in listOf("orders", "order_items", "payments")) {
            db.execSQL("ALTER TABLE $t ADD COLUMN expires_at INTEGER")
            db.execSQL("ALTER TABLE $t ADD COLUMN source TEXT NOT NULL DEFAULT 'local-pending'")
            db.execSQL("ALTER TABLE $t ADD COLUMN synced_at INTEGER")
        }
        // Read-only cache tables: source default = 'remote' (cache origin).
        for (t in listOf("table_states", "dish_cache")) {
            db.execSQL("ALTER TABLE $t ADD COLUMN expires_at INTEGER")
            db.execSQL("ALTER TABLE $t ADD COLUMN source TEXT NOT NULL DEFAULT 'remote'")
            db.execSQL("ALTER TABLE $t ADD COLUMN synced_at INTEGER")
        }
    }
}

val ALL_MIGRATIONS: Array<Migration> = arrayOf(
    MIGRATION_1_2,
)
