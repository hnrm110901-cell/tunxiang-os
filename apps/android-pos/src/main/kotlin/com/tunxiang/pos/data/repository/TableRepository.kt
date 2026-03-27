package com.tunxiang.pos.data.repository

import android.util.Log
import com.tunxiang.pos.data.local.dao.TableDao
import com.tunxiang.pos.data.local.entity.LocalTableState
import com.tunxiang.pos.data.remote.TxCoreApi
import com.tunxiang.pos.sync.SyncManager
import kotlinx.coroutines.flow.Flow

/**
 * TableRepository - Table state management.
 *
 * Strategy:
 * - Cached locally, refreshed on open and pull-to-refresh
 * - Local mutations for table open/close update Room immediately
 * - Server sync happens in background
 */
class TableRepository(
    private val tableDao: TableDao,
    private val api: TxCoreApi,
    private val syncManager: SyncManager,
) {
    companion object {
        private const val TAG = "TableRepository"
    }

    /**
     * Refresh table states from server.
     */
    suspend fun refreshTables(storeId: String) {
        if (!syncManager.isOnline()) {
            Log.d(TAG, "Offline, serving cached tables")
            return
        }

        try {
            val response = api.getTables(storeId)
            if (response.isSuccessful && response.body()?.ok == true) {
                val tables = response.body()!!.data?.map { it.toLocal(storeId) } ?: emptyList()
                if (tables.isNotEmpty()) {
                    tableDao.clearStore(storeId)
                    tableDao.insertAll(tables)
                    Log.i(TAG, "Refreshed ${tables.size} tables")
                }
            }
        } catch (e: Exception) {
            Log.e(TAG, "Table refresh failed", e)
        }
    }

    fun observeAllTables(storeId: String): Flow<List<LocalTableState>> =
        tableDao.observeAllTables(storeId)

    fun observeByArea(storeId: String, area: String): Flow<List<LocalTableState>> =
        tableDao.observeByArea(storeId, area)

    fun observeAreas(storeId: String): Flow<List<String>> =
        tableDao.observeAreas(storeId)

    suspend fun getTable(tableId: String): LocalTableState? =
        tableDao.getTable(tableId)

    suspend fun countOccupied(storeId: String): Int =
        tableDao.countOccupied(storeId)

    suspend fun countFree(storeId: String): Int =
        tableDao.countFree(storeId)
}

private fun com.tunxiang.pos.data.remote.TableResponse.toLocal(storeId: String): LocalTableState {
    return LocalTableState(
        id = id,
        tenantId = "",
        storeId = storeId,
        tableNumber = table_number,
        tableName = table_name,
        area = area,
        capacity = capacity,
        status = status,
        currentOrderId = current_order_id,
        guestCount = guest_count,
        openedAt = opened_at?.let {
            try { java.text.SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss", java.util.Locale.US).parse(it)?.time }
            catch (_: Exception) { null }
        },
        orderAmount = order_amount,
        sortOrder = sort_order,
    )
}
