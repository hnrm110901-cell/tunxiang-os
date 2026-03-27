package com.tunxiang.pos.ui.screens

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.grid.GridCells
import androidx.compose.foundation.lazy.grid.LazyVerticalGrid
import androidx.compose.foundation.lazy.grid.items
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.tunxiang.pos.TunxiangPOSApp
import com.tunxiang.pos.data.local.entity.LocalDishCache
import com.tunxiang.pos.data.local.entity.LocalOrderItem
import com.tunxiang.pos.data.repository.CartItem
import com.tunxiang.pos.data.repository.DishRepository
import com.tunxiang.pos.data.repository.OrderRepository
import com.tunxiang.pos.ui.components.CartPanel
import com.tunxiang.pos.ui.components.DishCard
import com.tunxiang.pos.ui.components.WeighDialog
import com.tunxiang.pos.ui.theme.*
import kotlinx.coroutines.launch
import java.util.UUID

/**
 * OrderScreen (点单页) - Three-panel order interface.
 *
 * Layout:
 * - Left panel: dish category tabs (vertical)
 * - Center panel: dish grid with search bar
 * - Right panel: cart with quantity controls, notes, send-to-kitchen
 *
 * Supports:
 * - Fixed price items (tap to add)
 * - Weighted items (opens WeighDialog with SunmiScale)
 * - Market price items (opens price input)
 * - Dish search
 * - Floating dish count badge
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun OrderScreen(
    orderId: String,
    tableId: String,
    onSettle: () -> Unit,
    onBack: () -> Unit,
) {
    val app = TunxiangPOSApp.instance
    val storeId = app.apiClient.getStoreId()
    val scope = rememberCoroutineScope()

    val dishRepo = remember {
        DishRepository(app.database.dishDao(), app.apiClient.txCoreApi, app.syncManager)
    }
    val orderRepo = remember {
        OrderRepository(
            app.database.orderDao(), app.database.tableDao(),
            app.database.syncQueueDao(), app.apiClient.txCoreApi, app.syncManager
        )
    }

    val order by orderRepo.observeOrder(orderId).collectAsState(initial = null)
    val orderItems by orderRepo.observeOrderItems(orderId).collectAsState(initial = emptyList())
    val categories by dishRepo.observeCategories(storeId).collectAsState(initial = emptyList())

    var selectedCategory by remember { mutableStateOf<String?>(null) }
    var searchQuery by remember { mutableStateOf("") }
    var showWeighDialog by remember { mutableStateOf<LocalDishCache?>(null) }
    var showNoteDialog by remember { mutableStateOf<LocalOrderItem?>(null) }

    // Dishes - filter by category or search
    val dishes by (
        if (searchQuery.isNotBlank()) {
            dishRepo.searchDishes(storeId, searchQuery)
        } else if (selectedCategory != null) {
            dishRepo.observeByCategory(storeId, selectedCategory!!)
        } else {
            dishRepo.observeAllDishes(storeId)
        }
    ).collectAsState(initial = emptyList())

    // Sync dishes on load
    LaunchedEffect(storeId) {
        dishRepo.syncDishes(storeId)
    }

    // Category display names
    val categoryLabels = mapOf(
        "hot" to "热菜", "cold" to "凉菜", "soup" to "汤",
        "staple" to "主食", "drink" to "酒水", "special" to "特价",
    )

    Scaffold(
        topBar = {
            TopAppBar(
                title = {
                    Text(
                        text = order?.let { "点单 - ${it.orderNumber}" } ?: "点单",
                        fontWeight = FontWeight.Bold,
                    )
                },
                navigationIcon = {
                    IconButton(onClick = onBack) {
                        Icon(Icons.Default.ArrowBack, "返回")
                    }
                },
                colors = TopAppBarDefaults.topAppBarColors(containerColor = TxDarkBg),
            )
        },
    ) { padding ->
        Row(
            modifier = Modifier
                .fillMaxSize()
                .padding(padding),
        ) {
            // LEFT: Category tabs (vertical)
            Column(
                modifier = Modifier
                    .width(80.dp)
                    .fillMaxHeight()
                    .background(TxDarkSurface),
            ) {
                // "All" category
                CategoryTab(
                    label = "全部",
                    isSelected = selectedCategory == null,
                    onClick = { selectedCategory = null; searchQuery = "" },
                )

                LazyColumn {
                    items(categories) { category ->
                        CategoryTab(
                            label = categoryLabels[category] ?: category,
                            isSelected = selectedCategory == category,
                            onClick = { selectedCategory = category; searchQuery = "" },
                        )
                    }
                }
            }

            // CENTER: Dish grid with search
            Column(
                modifier = Modifier
                    .weight(1f)
                    .fillMaxHeight()
                    .padding(horizontal = 8.dp),
            ) {
                // Search bar
                OutlinedTextField(
                    value = searchQuery,
                    onValueChange = {
                        searchQuery = it
                        if (it.isNotBlank()) selectedCategory = null
                    },
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(vertical = 8.dp),
                    placeholder = { Text("搜索菜品...") },
                    leadingIcon = { Icon(Icons.Default.Search, "搜索") },
                    trailingIcon = {
                        if (searchQuery.isNotEmpty()) {
                            IconButton(onClick = { searchQuery = "" }) {
                                Icon(Icons.Default.Clear, "清除")
                            }
                        }
                    },
                    singleLine = true,
                    shape = RoundedCornerShape(8.dp),
                    colors = OutlinedTextFieldDefaults.colors(
                        focusedBorderColor = TxOrange,
                        unfocusedBorderColor = TxGray.copy(alpha = 0.3f),
                        cursorColor = TxOrange,
                    ),
                )

                // Dish grid
                LazyVerticalGrid(
                    columns = GridCells.Adaptive(minSize = 140.dp),
                    horizontalArrangement = Arrangement.spacedBy(6.dp),
                    verticalArrangement = Arrangement.spacedBy(6.dp),
                    contentPadding = PaddingValues(bottom = 16.dp),
                ) {
                    items(dishes, key = { it.id }) { dish ->
                        DishCard(
                            dish = dish,
                            onAdd = {
                                when (dish.pricingType) {
                                    "fixed" -> {
                                        // Add directly to cart
                                        scope.launch {
                                            orderRepo.addItems(
                                                orderId = orderId,
                                                items = listOf(
                                                    CartItem(
                                                        dishId = dish.id,
                                                        dishName = dish.name,
                                                        category = dish.category,
                                                        pricingType = "fixed",
                                                        unitPrice = dish.price,
                                                        quantity = 1,
                                                        amount = dish.price,
                                                    )
                                                ),
                                            )
                                        }
                                    }
                                    "weighted", "market" -> {
                                        showWeighDialog = dish
                                    }
                                }
                            },
                        )
                    }
                }
            }

            // RIGHT: Cart panel
            CartPanel(
                items = orderItems,
                onQuantityChange = { item, newQty ->
                    scope.launch {
                        if (newQty <= 0) {
                            app.database.orderDao().cancelItem(item.id)
                        } else {
                            val newAmount = item.unitPrice * newQty
                            app.database.orderDao().updateItemQuantity(
                                item.id, newQty, newAmount, newAmount - item.discountAmount
                            )
                        }
                        orderRepo.recalculateOrderTotal(orderId)
                    }
                },
                onDelete = { item ->
                    scope.launch {
                        app.database.orderDao().cancelItem(item.id)
                        orderRepo.recalculateOrderTotal(orderId)
                    }
                },
                onEditNote = { item ->
                    showNoteDialog = item
                },
                onSendToKitchen = {
                    scope.launch {
                        orderRepo.sendToKitchen(orderId)
                    }
                },
                onSettle = onSettle,
                modifier = Modifier.width(260.dp),
            )
        }
    }

    // Weigh/Market price dialog
    showWeighDialog?.let { dish ->
        WeighDialog(
            dish = dish,
            currentWeight = 0,  // In production: collectAsState from SunmiScale
            isStable = false,
            onTare = { /* SunmiScale.tare() */ },
            onConfirm = { weightGram, unitPrice, amount ->
                scope.launch {
                    orderRepo.addItems(
                        orderId = orderId,
                        items = listOf(
                            CartItem(
                                dishId = dish.id,
                                dishName = dish.name,
                                category = dish.category,
                                pricingType = dish.pricingType,
                                unitPrice = unitPrice,
                                quantity = 1,
                                weightGram = weightGram,
                                amount = amount,
                            )
                        ),
                    )
                }
                showWeighDialog = null
            },
            onDismiss = { showWeighDialog = null },
        )
    }

    // Note edit dialog
    showNoteDialog?.let { item ->
        NoteEditDialog(
            currentNote = item.note ?: "",
            onDismiss = { showNoteDialog = null },
            onConfirm = { note ->
                scope.launch {
                    app.database.orderDao().updateItem(item.copy(note = note))
                }
                showNoteDialog = null
            },
        )
    }
}

@Composable
private fun CategoryTab(
    label: String,
    isSelected: Boolean,
    onClick: () -> Unit,
) {
    Surface(
        modifier = Modifier
            .fillMaxWidth()
            .clickable { onClick() },
        color = if (isSelected) TxOrange.copy(alpha = 0.15f) else TxDarkSurface,
    ) {
        Box(
            modifier = Modifier.padding(vertical = 14.dp, horizontal = 8.dp),
            contentAlignment = Alignment.Center,
        ) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                if (isSelected) {
                    Box(
                        modifier = Modifier
                            .width(3.dp)
                            .height(20.dp)
                            .background(TxOrange, RoundedCornerShape(2.dp))
                    )
                    Spacer(modifier = Modifier.width(6.dp))
                }
                Text(
                    text = label,
                    style = MaterialTheme.typography.labelLarge,
                    color = if (isSelected) TxOrange else TxGrayLight,
                    fontWeight = if (isSelected) FontWeight.Bold else FontWeight.Normal,
                )
            }
        }
    }
}

@Composable
private fun NoteEditDialog(
    currentNote: String,
    onDismiss: () -> Unit,
    onConfirm: (String) -> Unit,
) {
    var note by remember { mutableStateOf(currentNote) }

    // Quick note options
    val quickNotes = listOf("微辣", "中辣", "特辣", "不辣", "少盐", "加辣", "打包", "先上", "不要葱", "不要香菜")

    AlertDialog(
        onDismissRequest = onDismiss,
        containerColor = TxDarkBg,
        title = { Text("菜品备注") },
        text = {
            Column {
                OutlinedTextField(
                    value = note,
                    onValueChange = { note = it },
                    modifier = Modifier.fillMaxWidth(),
                    placeholder = { Text("输入备注...") },
                    shape = RoundedCornerShape(8.dp),
                    colors = OutlinedTextFieldDefaults.colors(
                        focusedBorderColor = TxOrange,
                        cursorColor = TxOrange,
                    ),
                )

                Spacer(modifier = Modifier.height(12.dp))

                // Quick note chips
                FlowRow(
                    horizontalArrangement = Arrangement.spacedBy(6.dp),
                    verticalArrangement = Arrangement.spacedBy(6.dp),
                ) {
                    quickNotes.forEach { qn ->
                        SuggestionChip(
                            onClick = {
                                note = if (note.isEmpty()) qn else "$note $qn"
                            },
                            label = { Text(qn, style = MaterialTheme.typography.labelSmall) },
                            colors = SuggestionChipDefaults.suggestionChipColors(
                                containerColor = TxDarkCard,
                            ),
                        )
                    }
                }
            }
        },
        confirmButton = {
            Button(
                onClick = { onConfirm(note) },
                colors = ButtonDefaults.buttonColors(containerColor = TxOrange),
            ) {
                Text("确认")
            }
        },
        dismissButton = {
            TextButton(onClick = onDismiss) { Text("取消", color = TxGray) }
        },
    )
}
