package com.tunxiang.pos.ui.screens

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextDecoration
import androidx.compose.ui.unit.dp
import com.tunxiang.pos.TunxiangPOSApp
import com.tunxiang.pos.bridge.ReceiptData
import com.tunxiang.pos.bridge.ReceiptItem
import com.tunxiang.pos.bridge.ReceiptPayment
import com.tunxiang.pos.bridge.SunmiCashBox
import com.tunxiang.pos.bridge.SunmiPrinter
import com.tunxiang.pos.data.local.entity.LocalOrder
import com.tunxiang.pos.data.local.entity.LocalOrderItem
import com.tunxiang.pos.data.repository.OrderRepository
import com.tunxiang.pos.data.repository.PaymentInfo
import com.tunxiang.pos.ui.components.PaymentDialog
import com.tunxiang.pos.ui.components.PaymentSelection
import com.tunxiang.pos.ui.theme.*
import kotlinx.coroutines.launch
import java.text.SimpleDateFormat
import java.util.*

/**
 * SettleScreen (结算页) - Order settlement with discounts and multi-payment.
 *
 * Features:
 * - Order summary: items list, subtotal, discounts, total
 * - Discount section: percent off / amount off / free item / member price
 * - Payment methods: cash/wechat/alipay/unionpay/member/credit
 * - Multi-payment split support
 * - Scan-to-pay via Sunmi scanner
 * - Print receipt via Sunmi printer
 * - Open cash drawer for cash payment
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun SettleScreen(
    orderId: String,
    onSettled: () -> Unit,
    onBack: () -> Unit,
) {
    val app = TunxiangPOSApp.instance
    val scope = rememberCoroutineScope()

    val orderRepo = remember {
        OrderRepository(
            app.database.orderDao(), app.database.tableDao(),
            app.database.syncQueueDao(), app.apiClient.txCoreApi, app.syncManager
        )
    }

    val order by orderRepo.observeOrder(orderId).collectAsState(initial = null)
    val orderItems by orderRepo.observeOrderItems(orderId).collectAsState(initial = emptyList())

    var showPaymentDialog by remember { mutableStateOf(false) }
    var showDiscountSheet by remember { mutableStateOf(false) }
    var isSettling by remember { mutableStateOf(false) }

    // Discount state
    var discountType by remember { mutableStateOf<String?>(null) }
    var discountValue by remember { mutableStateOf("") }

    val activeItems = orderItems.filter { it.status != "cancelled" }
    val currentOrder = order ?: return

    Scaffold(
        topBar = {
            TopAppBar(
                title = {
                    Text("结算 - ${currentOrder.orderNumber}", fontWeight = FontWeight.Bold)
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
                .padding(padding)
                .padding(16.dp),
        ) {
            // LEFT: Order items list
            Column(
                modifier = Modifier
                    .weight(1f)
                    .fillMaxHeight(),
            ) {
                Text(
                    text = "订单明细",
                    style = MaterialTheme.typography.titleMedium,
                    fontWeight = FontWeight.Bold,
                )
                Spacer(modifier = Modifier.height(8.dp))

                LazyColumn(
                    modifier = Modifier.weight(1f),
                    verticalArrangement = Arrangement.spacedBy(4.dp),
                ) {
                    items(activeItems, key = { it.id }) { item ->
                        SettleItemRow(item)
                    }
                }

                HorizontalDivider(
                    modifier = Modifier.padding(vertical = 8.dp),
                    color = MaterialTheme.colorScheme.outline,
                )

                // Subtotal
                AmountRow("小计 (${activeItems.size}项)", currentOrder.subtotal)
            }

            Spacer(modifier = Modifier.width(16.dp))

            // RIGHT: Discount + Total + Payment
            Column(
                modifier = Modifier
                    .width(320.dp)
                    .fillMaxHeight(),
            ) {
                // Discount section
                Card(
                    modifier = Modifier.fillMaxWidth(),
                    colors = CardDefaults.cardColors(containerColor = TxDarkCard),
                    shape = RoundedCornerShape(12.dp),
                ) {
                    Column(
                        modifier = Modifier.padding(16.dp),
                    ) {
                        Text(
                            text = "优惠",
                            style = MaterialTheme.typography.titleMedium,
                            fontWeight = FontWeight.Bold,
                        )
                        Spacer(modifier = Modifier.height(8.dp))

                        // Discount type chips
                        FlowRow(
                            horizontalArrangement = Arrangement.spacedBy(6.dp),
                            verticalArrangement = Arrangement.spacedBy(6.dp),
                        ) {
                            DiscountChip("整单折扣", "percent", discountType) { discountType = it }
                            DiscountChip("减免金额", "amount", discountType) { discountType = it }
                            DiscountChip("赠菜", "free_item", discountType) { discountType = it }
                            DiscountChip("会员价", "member", discountType) { discountType = it }
                        }

                        if (discountType != null) {
                            Spacer(modifier = Modifier.height(8.dp))
                            Row(verticalAlignment = Alignment.CenterVertically) {
                                OutlinedTextField(
                                    value = discountValue,
                                    onValueChange = { discountValue = it },
                                    modifier = Modifier.weight(1f),
                                    placeholder = {
                                        Text(
                                            when (discountType) {
                                                "percent" -> "折扣(如85=8.5折)"
                                                "amount" -> "减免金额(元)"
                                                else -> "输入值"
                                            }
                                        )
                                    },
                                    singleLine = true,
                                    shape = RoundedCornerShape(8.dp),
                                    colors = OutlinedTextFieldDefaults.colors(
                                        focusedBorderColor = TxOrange,
                                        cursorColor = TxOrange,
                                    ),
                                )
                                Spacer(modifier = Modifier.width(8.dp))
                                Button(
                                    onClick = {
                                        scope.launch {
                                            applyDiscount(
                                                orderDao = app.database.orderDao(),
                                                orderRepo = orderRepo,
                                                orderId = orderId,
                                                type = discountType!!,
                                                value = discountValue,
                                                subtotal = currentOrder.subtotal,
                                            )
                                            discountType = null
                                            discountValue = ""
                                        }
                                    },
                                    colors = ButtonDefaults.buttonColors(containerColor = TxOrange),
                                    shape = RoundedCornerShape(8.dp),
                                ) {
                                    Text("应用")
                                }
                            }
                        }

                        if (currentOrder.discountAmount > 0) {
                            Spacer(modifier = Modifier.height(4.dp))
                            AmountRow("已优惠", -currentOrder.discountAmount, color = PaySuccess)
                        }
                    }
                }

                Spacer(modifier = Modifier.height(16.dp))

                // Total
                Card(
                    modifier = Modifier.fillMaxWidth(),
                    colors = CardDefaults.cardColors(containerColor = TxDarkCard),
                    shape = RoundedCornerShape(12.dp),
                ) {
                    Column(modifier = Modifier.padding(16.dp)) {
                        AmountRow("小计", currentOrder.subtotal)
                        if (currentOrder.discountAmount > 0) {
                            AmountRow("优惠", -currentOrder.discountAmount, color = PaySuccess)
                        }
                        HorizontalDivider(
                            modifier = Modifier.padding(vertical = 8.dp),
                            color = MaterialTheme.colorScheme.outline,
                        )
                        Row(
                            modifier = Modifier.fillMaxWidth(),
                            horizontalArrangement = Arrangement.SpaceBetween,
                            verticalAlignment = Alignment.CenterVertically,
                        ) {
                            Text(
                                text = "应收",
                                style = MaterialTheme.typography.titleLarge,
                                fontWeight = FontWeight.Bold,
                            )
                            Text(
                                text = "¥%.2f".format(currentOrder.totalAmount / 100.0),
                                style = MaterialTheme.typography.headlineLarge,
                                color = TxOrange,
                                fontWeight = FontWeight.Bold,
                            )
                        }
                    }
                }

                Spacer(modifier = Modifier.weight(1f))

                // Payment button
                Button(
                    onClick = { showPaymentDialog = true },
                    modifier = Modifier
                        .fillMaxWidth()
                        .height(56.dp),
                    colors = ButtonDefaults.buttonColors(containerColor = TxOrange),
                    shape = RoundedCornerShape(12.dp),
                    enabled = !isSettling && currentOrder.totalAmount > 0,
                ) {
                    if (isSettling) {
                        CircularProgressIndicator(
                            modifier = Modifier.size(24.dp),
                            color = TxWhite,
                        )
                    } else {
                        Icon(Icons.Default.Payment, "支付")
                        Spacer(modifier = Modifier.width(8.dp))
                        Text(
                            text = "收款 ¥%.2f".format(currentOrder.totalAmount / 100.0),
                            style = MaterialTheme.typography.titleMedium,
                            fontWeight = FontWeight.Bold,
                        )
                    }
                }
            }
        }
    }

    // Payment dialog
    if (showPaymentDialog) {
        PaymentDialog(
            totalAmount = currentOrder.totalAmount,
            onDismiss = { showPaymentDialog = false },
            onConfirm = { selections ->
                scope.launch {
                    isSettling = true
                    showPaymentDialog = false

                    val hasCash = selections.any { it.method == "cash" }

                    val result = orderRepo.settleOrder(
                        orderId = orderId,
                        payments = selections.map {
                            PaymentInfo(
                                method = it.method,
                                amount = it.amount,
                                receivedAmount = it.receivedAmount,
                            )
                        },
                    )

                    result.onSuccess { settleResult ->
                        // Open cash drawer for cash payment
                        if (hasCash) {
                            SunmiCashBox(app).open()
                        }

                        // Print receipt
                        val printer = SunmiPrinter(app)
                        val dateFormat = SimpleDateFormat("yyyy-MM-dd HH:mm", Locale.CHINA)
                        printer.printReceipt(
                            ReceiptData(
                                storeName = "屯象餐厅",
                                orderNumber = currentOrder.orderNumber,
                                tableName = null,
                                time = dateFormat.format(Date()),
                                cashierName = currentOrder.cashierName,
                                items = activeItems.map {
                                    ReceiptItem(it.dishName, it.quantity, it.unitPrice, it.finalAmount, it.note)
                                },
                                subtotal = currentOrder.subtotal,
                                discountAmount = currentOrder.discountAmount,
                                totalAmount = currentOrder.totalAmount,
                                payments = selections.map {
                                    ReceiptPayment(it.method, it.amount)
                                },
                                changeAmount = settleResult.changeAmount,
                            )
                        )

                        isSettling = false
                        onSettled()
                    }

                    result.onFailure {
                        isSettling = false
                    }
                }
            },
        )
    }
}

@Composable
private fun SettleItemRow(item: LocalOrderItem) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .padding(vertical = 4.dp),
        horizontalArrangement = Arrangement.SpaceBetween,
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Column(modifier = Modifier.weight(1f)) {
            Text(
                text = item.dishName,
                style = MaterialTheme.typography.bodyMedium,
                color = TxWhite,
            )
            if (item.note != null) {
                Text(
                    text = "[${item.note}]",
                    style = MaterialTheme.typography.bodySmall,
                    color = TxGray,
                )
            }
        }

        Text(
            text = "x${item.quantity}",
            style = MaterialTheme.typography.bodyMedium,
            color = TxGrayLight,
            modifier = Modifier.padding(horizontal = 12.dp),
        )

        Column(horizontalAlignment = Alignment.End) {
            Text(
                text = "¥%.2f".format(item.finalAmount / 100.0),
                style = MaterialTheme.typography.bodyMedium,
                color = TxWhite,
            )
            if (item.discountAmount > 0) {
                Text(
                    text = "¥%.2f".format(item.amount / 100.0),
                    style = MaterialTheme.typography.bodySmall,
                    color = TxGray,
                    textDecoration = TextDecoration.LineThrough,
                )
            }
        }
    }
}

@Composable
private fun AmountRow(
    label: String,
    amount: Long,
    color: androidx.compose.ui.graphics.Color = TxWhite,
) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .padding(vertical = 2.dp),
        horizontalArrangement = Arrangement.SpaceBetween,
    ) {
        Text(text = label, style = MaterialTheme.typography.bodyMedium, color = TxGrayLight)
        Text(
            text = if (amount < 0) "-¥%.2f".format(-amount / 100.0) else "¥%.2f".format(amount / 100.0),
            style = MaterialTheme.typography.bodyMedium,
            color = color,
            fontWeight = FontWeight.Medium,
        )
    }
}

@Composable
private fun DiscountChip(
    label: String,
    type: String,
    selectedType: String?,
    onSelect: (String?) -> Unit,
) {
    FilterChip(
        selected = selectedType == type,
        onClick = { onSelect(if (selectedType == type) null else type) },
        label = { Text(label, style = MaterialTheme.typography.labelSmall) },
        colors = FilterChipDefaults.filterChipColors(
            selectedContainerColor = TxOrange.copy(alpha = 0.2f),
            selectedLabelColor = TxOrange,
        ),
    )
}

private suspend fun applyDiscount(
    orderDao: com.tunxiang.pos.data.local.dao.OrderDao,
    orderRepo: OrderRepository,
    orderId: String,
    type: String,
    value: String,
    subtotal: Long,
) {
    val numValue = value.toDoubleOrNull() ?: return
    val discountCents = when (type) {
        "percent" -> {
            // value = 85 means 85% (8.5 zhe), discount = subtotal * (100 - 85) / 100
            val pct = numValue.toLong()
            subtotal * (100 - pct) / 100
        }
        "amount" -> (numValue * 100).toLong()
        else -> 0L
    }

    if (discountCents > 0) {
        val total = maxOf(subtotal - discountCents, 0)
        orderDao.updateAmounts(orderId, subtotal, discountCents, total)
    }
}
