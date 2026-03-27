package com.tunxiang.pos.ui.screens

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.grid.GridCells
import androidx.compose.foundation.lazy.grid.LazyVerticalGrid
import androidx.compose.foundation.lazy.grid.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.material3.pulltorefresh.PullToRefreshBox
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.lifecycle.viewmodel.compose.viewModel
import com.tunxiang.pos.TunxiangPOSApp
import com.tunxiang.pos.data.local.entity.LocalTableState
import com.tunxiang.pos.data.repository.OrderRepository
import com.tunxiang.pos.data.repository.TableRepository
import com.tunxiang.pos.ui.components.TableCard
import com.tunxiang.pos.ui.theme.*
import kotlinx.coroutines.launch

/**
 * TableMapScreen (开台页) - Grid of tables with status colors.
 *
 * Features:
 * - Table grid with status colors (green=free, red=occupied, yellow=reserved, gray=disabled)
 * - Tap free table -> dialog: guest count + order type -> create order
 * - Tap occupied table -> navigate to existing order
 * - Pull-to-refresh
 * - Area filter tabs
 * - Shift/DailyClose nav buttons
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun TableMapScreen(
    onTableOpened: (orderId: String, tableId: String) -> Unit,
    onNavigateToShift: () -> Unit,
    onNavigateToDailyClose: () -> Unit,
) {
    val app = TunxiangPOSApp.instance
    val storeId = app.apiClient.getStoreId()
    val scope = rememberCoroutineScope()

    val tableRepo = remember {
        TableRepository(app.database.tableDao(), app.apiClient.txCoreApi, app.syncManager)
    }
    val orderRepo = remember {
        OrderRepository(
            app.database.orderDao(), app.database.tableDao(),
            app.database.syncQueueDao(), app.apiClient.txCoreApi, app.syncManager
        )
    }

    val tables by tableRepo.observeAllTables(storeId).collectAsState(initial = emptyList())
    val areas by tableRepo.observeAreas(storeId).collectAsState(initial = emptyList())
    val isOnline by app.syncManager.isOnlineFlow.collectAsState()

    var selectedArea by remember { mutableStateOf<String?>(null) }
    var isRefreshing by remember { mutableStateOf(false) }
    var showOpenDialog by remember { mutableStateOf<LocalTableState?>(null) }

    // Initial load
    LaunchedEffect(storeId) {
        if (storeId.isNotEmpty()) {
            tableRepo.refreshTables(storeId)
        }
    }

    val filteredTables = if (selectedArea != null) {
        tables.filter { it.area == selectedArea }
    } else {
        tables
    }

    Scaffold(
        topBar = {
            TopAppBar(
                title = {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Text(
                            text = "桌台",
                            style = MaterialTheme.typography.headlineMedium,
                            fontWeight = FontWeight.Bold,
                        )
                        Spacer(modifier = Modifier.width(12.dp))
                        // Online/offline indicator
                        Surface(
                            color = if (isOnline) PaySuccess else PayFailed,
                            shape = MaterialTheme.shapes.small,
                        ) {
                            Text(
                                text = if (isOnline) "在线" else "离线",
                                modifier = Modifier.padding(horizontal = 8.dp, vertical = 2.dp),
                                style = MaterialTheme.typography.labelSmall,
                                color = TxWhite,
                            )
                        }
                    }
                },
                actions = {
                    // Shift handover
                    IconButton(onClick = onNavigateToShift) {
                        Icon(Icons.Default.SwapHoriz, "交接班", tint = TxGrayLight)
                    }
                    // Daily close
                    IconButton(onClick = onNavigateToDailyClose) {
                        Icon(Icons.Default.Summarize, "日结", tint = TxGrayLight)
                    }
                },
                colors = TopAppBarDefaults.topAppBarColors(
                    containerColor = TxDarkBg,
                ),
            )
        },
    ) { padding ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(padding),
        ) {
            // Area filter tabs
            if (areas.isNotEmpty()) {
                ScrollableTabRow(
                    selectedTabIndex = if (selectedArea == null) 0 else areas.indexOf(selectedArea) + 1,
                    containerColor = TxDarkSurface,
                    contentColor = TxOrange,
                    edgePadding = 8.dp,
                ) {
                    Tab(
                        selected = selectedArea == null,
                        onClick = { selectedArea = null },
                        text = { Text("全部") },
                    )
                    areas.forEach { area ->
                        Tab(
                            selected = selectedArea == area,
                            onClick = { selectedArea = area },
                            text = { Text(area) },
                        )
                    }
                }
            }

            // Table grid with pull-to-refresh
            PullToRefreshBox(
                isRefreshing = isRefreshing,
                onRefresh = {
                    scope.launch {
                        isRefreshing = true
                        tableRepo.refreshTables(storeId)
                        isRefreshing = false
                    }
                },
                modifier = Modifier
                    .fillMaxSize()
                    .padding(horizontal = 12.dp, vertical = 8.dp),
            ) {
                if (filteredTables.isEmpty()) {
                    Box(
                        modifier = Modifier.fillMaxSize(),
                        contentAlignment = Alignment.Center,
                    ) {
                        Column(horizontalAlignment = Alignment.CenterHorizontally) {
                            Icon(
                                Icons.Default.TableRestaurant,
                                contentDescription = null,
                                tint = TxGray,
                                modifier = Modifier.size(64.dp),
                            )
                            Spacer(modifier = Modifier.height(12.dp))
                            Text("暂无桌台数据", color = TxGray)
                            Text("请检查网络连接或下拉刷新", style = MaterialTheme.typography.bodySmall, color = TxGray)
                        }
                    }
                } else {
                    LazyVerticalGrid(
                        columns = GridCells.Adaptive(minSize = 120.dp),
                        horizontalArrangement = Arrangement.spacedBy(8.dp),
                        verticalArrangement = Arrangement.spacedBy(8.dp),
                        contentPadding = PaddingValues(bottom = 16.dp),
                    ) {
                        items(filteredTables, key = { it.id }) { table ->
                            TableCard(
                                table = table,
                                onClick = {
                                    when (table.status) {
                                        "free" -> showOpenDialog = table
                                        "occupied" -> {
                                            if (table.currentOrderId != null) {
                                                onTableOpened(table.currentOrderId, table.id)
                                            }
                                        }
                                        "reserved" -> showOpenDialog = table
                                    }
                                },
                            )
                        }
                    }
                }
            }
        }
    }

    // Open table dialog
    showOpenDialog?.let { table ->
        OpenTableDialog(
            table = table,
            onDismiss = { showOpenDialog = null },
            onConfirm = { guestCount, orderType ->
                scope.launch {
                    val result = orderRepo.createOrder(
                        tableId = table.id,
                        orderType = orderType,
                        guestCount = guestCount,
                    )
                    result.onSuccess { order ->
                        showOpenDialog = null
                        onTableOpened(order.id, table.id)
                    }
                }
            },
        )
    }
}

@Composable
private fun OpenTableDialog(
    table: LocalTableState,
    onDismiss: () -> Unit,
    onConfirm: (guestCount: Int, orderType: String) -> Unit,
) {
    var guestCount by remember { mutableIntStateOf(2) }
    var orderType by remember { mutableStateOf("dine_in") }

    AlertDialog(
        onDismissRequest = onDismiss,
        containerColor = TxDarkBg,
        title = {
            Text("开台 - ${table.tableName}")
        },
        text = {
            Column {
                // Guest count
                Text("就餐人数", style = MaterialTheme.typography.labelLarge)
                Spacer(modifier = Modifier.height(8.dp))
                Row(
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.spacedBy(12.dp),
                ) {
                    IconButton(
                        onClick = { if (guestCount > 1) guestCount-- },
                    ) {
                        Icon(Icons.Default.Remove, "减少", tint = TxOrange)
                    }
                    Text(
                        text = "$guestCount",
                        style = MaterialTheme.typography.headlineMedium,
                        fontWeight = FontWeight.Bold,
                    )
                    IconButton(
                        onClick = { if (guestCount < table.capacity) guestCount++ },
                    ) {
                        Icon(Icons.Default.Add, "增加", tint = TxOrange)
                    }
                    Text(
                        text = "/ ${table.capacity}座",
                        style = MaterialTheme.typography.bodySmall,
                        color = TxGray,
                    )
                }

                Spacer(modifier = Modifier.height(16.dp))

                // Order type
                Text("用餐方式", style = MaterialTheme.typography.labelLarge)
                Spacer(modifier = Modifier.height(8.dp))
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    FilterChip(
                        selected = orderType == "dine_in",
                        onClick = { orderType = "dine_in" },
                        label = { Text("堂食") },
                        colors = FilterChipDefaults.filterChipColors(
                            selectedContainerColor = TxOrange.copy(alpha = 0.2f),
                            selectedLabelColor = TxOrange,
                        ),
                    )
                    FilterChip(
                        selected = orderType == "takeaway",
                        onClick = { orderType = "takeaway" },
                        label = { Text("外带") },
                        colors = FilterChipDefaults.filterChipColors(
                            selectedContainerColor = TxOrange.copy(alpha = 0.2f),
                            selectedLabelColor = TxOrange,
                        ),
                    )
                }
            }
        },
        confirmButton = {
            Button(
                onClick = { onConfirm(guestCount, orderType) },
                colors = ButtonDefaults.buttonColors(containerColor = TxOrange),
            ) {
                Text("开台", fontWeight = FontWeight.Bold)
            }
        },
        dismissButton = {
            TextButton(onClick = onDismiss) {
                Text("取消", color = TxGray)
            }
        },
    )
}
