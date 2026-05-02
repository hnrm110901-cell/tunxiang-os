package com.tunxiang.pos.data.local

import androidx.room.Database
import androidx.room.RoomDatabase
import com.tunxiang.pos.data.local.dao.DishDao
import com.tunxiang.pos.data.local.dao.OrderDao
import com.tunxiang.pos.data.local.dao.SyncQueueDao
import com.tunxiang.pos.data.local.dao.TableDao
import com.tunxiang.pos.data.local.entity.LocalDishCache
import com.tunxiang.pos.data.local.entity.LocalOrder
import com.tunxiang.pos.data.local.entity.LocalOrderItem
import com.tunxiang.pos.data.local.entity.LocalPayment
import com.tunxiang.pos.data.local.entity.LocalTableState
import com.tunxiang.pos.data.local.entity.SyncQueueEntry

/**
 * TunxiangDatabase — Room database for offline-first POS operations.
 *
 * Entities:
 * - orders + order_items + payments: transaction data
 * - table_states: cached table map
 * - dish_cache: full menu cache (incremental sync)
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
