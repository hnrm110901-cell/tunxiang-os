package com.tunxiang.pos.data.local

import androidx.room.Database
import androidx.room.RoomDatabase
import com.tunxiang.pos.data.local.dao.*
import com.tunxiang.pos.data.local.entity.*

/**
 * TunxiangDatabase - Room database for offline-first POS operations.
 *
 * Contains:
 * - orders + order_items + payments: transaction data
 * - table_states: cached table map
 * - dish_cache: full menu cache (incremental sync every 5min)
 * - sync_queue: FIFO queue for pending server sync
 */
@Database(
    entities = [
        LocalOrder::class,
        LocalOrderItem::class,
        LocalPayment::class,
        LocalTableState::class,
        LocalDishCache::class,
        SyncQueueEntry::class,
    ],
    version = 1,
    exportSchema = true,
)
abstract class TunxiangDatabase : RoomDatabase() {
    abstract fun orderDao(): OrderDao
    abstract fun dishDao(): DishDao
    abstract fun tableDao(): TableDao
    abstract fun syncQueueDao(): SyncQueueDao
}
