package com.tunxiang.pos.data.local

/**
 * SyncSource - allowed values for the entity `source` column.
 *
 * V4 sprint D3 (2026-05-07): introduced per W3 review of D2.
 * Replaces scattered string literals "remote" / "local-pending" / "local-synced"
 * with named constants to prevent typo-induced silent data loss.
 *
 * Lifecycle:
 *   ┌─────────────────────────────────────────────────────────────────┐
 *   │  Repository.write()                                              │
 *   │    └─► try mac-station HTTP                                      │
 *   │           ├─► success: insert with source = REMOTE              │
 *   │           └─► failure: insert with source = LOCAL_PENDING        │
 *   │                          + enqueue SyncQueue                     │
 *   └─────────────────────────────────────────────────────────────────┘
 *   ┌─────────────────────────────────────────────────────────────────┐
 *   │  SyncWorker.flushPending()                                       │
 *   │    └─► WHERE source = LOCAL_PENDING                              │
 *   │           └─► POST mac-station                                   │
 *   │                  └─► success: UPDATE source = LOCAL_SYNCED       │
 *   │                                + synced_at = now                 │
 *   └─────────────────────────────────────────────────────────────────┘
 *   ┌─────────────────────────────────────────────────────────────────┐
 *   │  Repository.read()                                               │
 *   │    └─► try mac-station HTTP                                      │
 *   │           ├─► success: UPSERT with source = REMOTE               │
 *   │           │            + expires_at = now + 4h                   │
 *   │           └─► failure: SELECT WHERE                              │
 *   │                          source IN (REMOTE, LOCAL_SYNCED)        │
 *   │                          AND (expires_at IS NULL OR > now)       │
 *   └─────────────────────────────────────────────────────────────────┘
 *
 * D3/D4 must use these constants exclusively in DAO @Query strings,
 * Repository write paths, and SyncWorker selection predicates.
 */
object SyncSource {
    /** Row originated from mac-station (truth source). Read-cache rows are also REMOTE. */
    const val REMOTE = "remote"

    /** Row was created locally during a network outage and has NOT yet reached mac-station. */
    const val LOCAL_PENDING = "local-pending"

    /** Row was originally LOCAL_PENDING but has since been successfully synced to mac-station. */
    const val LOCAL_SYNCED = "local-synced"

    /** All known source values; useful for `WHERE source IN (...)` validation in tests. */
    val ALL: Set<String> = setOf(REMOTE, LOCAL_PENDING, LOCAL_SYNCED)
}
