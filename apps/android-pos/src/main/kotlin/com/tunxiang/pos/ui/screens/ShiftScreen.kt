package com.tunxiang.pos.ui.screens

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.tunxiang.pos.TunxiangPOSApp
import com.tunxiang.pos.bridge.ShiftReportData
import com.tunxiang.pos.bridge.SunmiCashBox
import com.tunxiang.pos.bridge.SunmiPrinter
import com.tunxiang.pos.data.repository.OrderRepository
import com.tunxiang.pos.ui.components.NumPad
import com.tunxiang.pos.ui.theme.*
import kotlinx.coroutines.launch
import java.text.SimpleDateFormat
import java.util.*

/**
 * ShiftScreen (交接班页) - Shift handover summary and cash count.
 *
 * Features:
 * - Shift summary: revenue, orders, avg check
 * - Payment breakdown pie chart
 * - Cash count input with denomination breakdown
 * - Variance display (system vs counted)
 * - Handover notes text field
 * - Confirm + print shift report
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ShiftScreen(
    onBack: () -> Unit,
) {
    val app = TunxiangPOSApp.instance
    val storeId = app.apiClient.getStoreId()
    val scope = rememberCoroutineScope()

    val orderRepo = remember {
        OrderRepository(
            app.database.orderDao(), app.database.tableDao(),
            app.database.syncQueueDao(), app.apiClient.txCoreApi, app.syncManager
        )
    }

    // Shift time range (current shift = last 8 hours)
    val now = System.currentTimeMillis()
    val shiftStart = now - 8 * 60 * 60 * 1000

    // Load shift data
    var revenue by remember { mutableLongStateOf(0L) }
    var orderCount by remember { mutableIntStateOf(0) }
    var covers by remember { mutableIntStateOf(0) }
    var discounts by remember { mutableLongStateOf(0L) }
    var cashAmount by remember { mutableLongStateOf(0L) }
    var wechatAmount by remember { mutableLongStateOf(0L) }
    var alipayAmount by remember { mutableLongStateOf(0L) }
    var unionpayAmount by remember { mutableLongStateOf(0L) }
    var memberAmount by remember { mutableLongStateOf(0L) }

    // Cash count state
    var cashCounted by remember { mutableStateOf("") }
    var notes by remember { mutableStateOf("") }
    var isSubmitting by remember { mutableStateOf(false) }

    // Denomination breakdown
    var d100 by remember { mutableIntStateOf(0) }
    var d50 by remember { mutableIntStateOf(0) }
    var d20 by remember { mutableIntStateOf(0) }
    var d10 by remember { mutableIntStateOf(0) }
    var d5 by remember { mutableIntStateOf(0) }
    var d1 by remember { mutableIntStateOf(0) }
    var dCoin by remember { mutableIntStateOf(0) }

    val denominationTotal = (d100 * 100 + d50 * 50 + d20 * 20 + d10 * 10 + d5 * 5 + d1 * 1 + dCoin) * 100L // in cents

    LaunchedEffect(storeId) {
        revenue = orderRepo.sumRevenue(storeId, shiftStart, now)
        orderCount = orderRepo.countSettledOrders(storeId, shiftStart, now)
        covers = orderRepo.sumCovers(storeId, shiftStart, now)
        discounts = orderRepo.sumDiscounts(storeId, shiftStart, now)
        cashAmount = orderRepo.sumByPaymentMethod(storeId, shiftStart, now, "cash")
        wechatAmount = orderRepo.sumByPaymentMethod(storeId, shiftStart, now, "wechat")
        alipayAmount = orderRepo.sumByPaymentMethod(storeId, shiftStart, now, "alipay")
        unionpayAmount = orderRepo.sumByPaymentMethod(storeId, shiftStart, now, "unionpay")
        memberAmount = orderRepo.sumByPaymentMethod(storeId, shiftStart, now, "member")
    }

    val avgCheck = if (orderCount > 0) revenue / orderCount else 0L
    val cashCountedCents = denominationTotal
    val variance = cashCountedCents - cashAmount

    val dateFormat = SimpleDateFormat("HH:mm", Locale.CHINA)
    val shiftStartStr = dateFormat.format(Date(shiftStart))
    val shiftEndStr = dateFormat.format(Date(now))

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("交接班", fontWeight = FontWeight.Bold) },
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
            // LEFT: Shift summary
            Column(
                modifier = Modifier
                    .weight(1f)
                    .fillMaxHeight()
                    .verticalScroll(rememberScrollState()),
            ) {
                Text("班次: $shiftStartStr - $shiftEndStr", style = MaterialTheme.typography.titleMedium)
                Text("收银员: ${app.apiClient.getCashierName()}", style = MaterialTheme.typography.bodyMedium, color = TxGray)

                Spacer(modifier = Modifier.height(16.dp))

                // Key metrics cards
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    MetricCard("营业额", "¥%.2f".format(revenue / 100.0), TxOrange, Modifier.weight(1f))
                    MetricCard("订单数", "$orderCount", PaySuccess, Modifier.weight(1f))
                    MetricCard("客单价", "¥%.0f".format(avgCheck / 100.0), TxOrangeLight, Modifier.weight(1f))
                }

                Spacer(modifier = Modifier.height(8.dp))

                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    MetricCard("就餐人数", "$covers", TxGrayLight, Modifier.weight(1f))
                    MetricCard("优惠总额", "¥%.2f".format(discounts / 100.0), PayPending, Modifier.weight(1f))
                }

                Spacer(modifier = Modifier.height(16.dp))

                // Payment breakdown pie chart
                Text("支付方式分布", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold)
                Spacer(modifier = Modifier.height(8.dp))

                val paymentData = listOf(
                    PieSlice("现金", cashAmount, Color(0xFF4CAF50)),
                    PieSlice("微信", wechatAmount, Color(0xFF07C160)),
                    PieSlice("支付宝", alipayAmount, Color(0xFF1677FF)),
                    PieSlice("银联", unionpayAmount, Color(0xFFE62E2E)),
                    PieSlice("会员", memberAmount, Color(0xFFFF9800)),
                ).filter { it.amount > 0 }

                if (paymentData.isNotEmpty()) {
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        PaymentPieChart(
                            data = paymentData,
                            modifier = Modifier.size(120.dp),
                        )
                        Spacer(modifier = Modifier.width(16.dp))
                        Column {
                            paymentData.forEach { slice ->
                                Row(
                                    modifier = Modifier.padding(vertical = 2.dp),
                                    verticalAlignment = Alignment.CenterVertically,
                                ) {
                                    Canvas(modifier = Modifier.size(12.dp)) {
                                        drawCircle(color = slice.color)
                                    }
                                    Spacer(modifier = Modifier.width(8.dp))
                                    Text(
                                        "${slice.label}: ¥%.2f".format(slice.amount / 100.0),
                                        style = MaterialTheme.typography.bodySmall,
                                        color = TxGrayLight,
                                    )
                                }
                            }
                        }
                    }
                }
            }

            Spacer(modifier = Modifier.width(16.dp))

            // RIGHT: Cash count + submit
            Column(
                modifier = Modifier
                    .width(320.dp)
                    .fillMaxHeight()
                    .verticalScroll(rememberScrollState()),
            ) {
                Text("现金盘点", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold)
                Spacer(modifier = Modifier.height(8.dp))

                // Denomination inputs
                Card(
                    modifier = Modifier.fillMaxWidth(),
                    colors = CardDefaults.cardColors(containerColor = TxDarkCard),
                    shape = RoundedCornerShape(12.dp),
                ) {
                    Column(modifier = Modifier.padding(12.dp)) {
                        DenominationRow("100元", d100) { d100 = it }
                        DenominationRow("50元", d50) { d50 = it }
                        DenominationRow("20元", d20) { d20 = it }
                        DenominationRow("10元", d10) { d10 = it }
                        DenominationRow("5元", d5) { d5 = it }
                        DenominationRow("1元", d1) { d1 = it }
                        DenominationRow("硬币", dCoin) { dCoin = it }

                        HorizontalDivider(modifier = Modifier.padding(vertical = 8.dp), color = MaterialTheme.colorScheme.outline)

                        Row(
                            modifier = Modifier.fillMaxWidth(),
                            horizontalArrangement = Arrangement.SpaceBetween,
                        ) {
                            Text("实点合计", fontWeight = FontWeight.Bold)
                            Text(
                                "¥%.2f".format(denominationTotal / 100.0),
                                color = TxOrange,
                                fontWeight = FontWeight.Bold,
                            )
                        }
                    }
                }

                Spacer(modifier = Modifier.height(12.dp))

                // Variance display
                Card(
                    modifier = Modifier.fillMaxWidth(),
                    colors = CardDefaults.cardColors(
                        containerColor = if (variance == 0L) PaySuccess.copy(alpha = 0.1f)
                        else PayFailed.copy(alpha = 0.1f)
                    ),
                    shape = RoundedCornerShape(12.dp),
                ) {
                    Column(modifier = Modifier.padding(12.dp)) {
                        Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                            Text("系统现金", style = MaterialTheme.typography.bodyMedium, color = TxGrayLight)
                            Text("¥%.2f".format(cashAmount / 100.0), color = TxWhite)
                        }
                        Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                            Text("实点现金", style = MaterialTheme.typography.bodyMedium, color = TxGrayLight)
                            Text("¥%.2f".format(cashCountedCents / 100.0), color = TxWhite)
                        }
                        HorizontalDivider(modifier = Modifier.padding(vertical = 4.dp), color = MaterialTheme.colorScheme.outline)
                        Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                            Text("差异", fontWeight = FontWeight.Bold)
                            Text(
                                text = (if (variance >= 0) "+" else "") + "¥%.2f".format(variance / 100.0),
                                color = if (variance == 0L) PaySuccess else PayFailed,
                                fontWeight = FontWeight.Bold,
                            )
                        }
                    }
                }

                Spacer(modifier = Modifier.height(12.dp))

                // Handover notes
                OutlinedTextField(
                    value = notes,
                    onValueChange = { notes = it },
                    modifier = Modifier.fillMaxWidth(),
                    placeholder = { Text("交接备注...") },
                    minLines = 3,
                    shape = RoundedCornerShape(8.dp),
                    colors = OutlinedTextFieldDefaults.colors(
                        focusedBorderColor = TxOrange,
                        cursorColor = TxOrange,
                    ),
                )

                Spacer(modifier = Modifier.height(16.dp))

                // Submit button
                Button(
                    onClick = {
                        scope.launch {
                            isSubmitting = true

                            // Print shift report
                            val printer = SunmiPrinter(app)
                            printer.printShiftReport(
                                ShiftReportData(
                                    storeName = "屯象餐厅",
                                    cashierName = app.apiClient.getCashierName(),
                                    shiftStart = shiftStartStr,
                                    shiftEnd = shiftEndStr,
                                    revenue = revenue,
                                    orderCount = orderCount,
                                    avgCheck = avgCheck,
                                    paymentBreakdown = mapOf(
                                        "cash" to cashAmount,
                                        "wechat" to wechatAmount,
                                        "alipay" to alipayAmount,
                                        "unionpay" to unionpayAmount,
                                        "member" to memberAmount,
                                    ).filter { it.value > 0 },
                                    cashExpected = cashAmount,
                                    cashCounted = cashCountedCents,
                                    variance = variance,
                                    notes = notes.ifBlank { null },
                                )
                            )

                            // Open cash drawer for cash handover
                            SunmiCashBox(app).open()

                            isSubmitting = false
                            onBack()
                        }
                    },
                    modifier = Modifier
                        .fillMaxWidth()
                        .height(48.dp),
                    colors = ButtonDefaults.buttonColors(containerColor = TxOrange),
                    shape = RoundedCornerShape(8.dp),
                    enabled = !isSubmitting,
                ) {
                    if (isSubmitting) {
                        CircularProgressIndicator(modifier = Modifier.size(20.dp), color = TxWhite)
                    } else {
                        Icon(Icons.Default.Print, "打印")
                        Spacer(modifier = Modifier.width(8.dp))
                        Text("确认交接 & 打印", fontWeight = FontWeight.Bold)
                    }
                }
            }
        }
    }
}

@Composable
private fun MetricCard(label: String, value: String, color: Color, modifier: Modifier = Modifier) {
    Card(
        modifier = modifier,
        colors = CardDefaults.cardColors(containerColor = TxDarkCard),
        shape = RoundedCornerShape(8.dp),
    ) {
        Column(modifier = Modifier.padding(12.dp)) {
            Text(label, style = MaterialTheme.typography.bodySmall, color = TxGray)
            Spacer(modifier = Modifier.height(4.dp))
            Text(value, style = MaterialTheme.typography.titleMedium, color = color, fontWeight = FontWeight.Bold)
        }
    }
}

@Composable
private fun DenominationRow(label: String, count: Int, onChange: (Int) -> Unit) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .padding(vertical = 4.dp),
        horizontalArrangement = Arrangement.SpaceBetween,
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(label, style = MaterialTheme.typography.bodyMedium, color = TxGrayLight, modifier = Modifier.width(60.dp))

        Row(verticalAlignment = Alignment.CenterVertically) {
            IconButton(
                onClick = { if (count > 0) onChange(count - 1) },
                modifier = Modifier.size(28.dp),
            ) {
                Icon(Icons.Default.Remove, "减", tint = TxGray, modifier = Modifier.size(16.dp))
            }
            Text(
                text = "$count",
                style = MaterialTheme.typography.bodyLarge,
                color = TxWhite,
                modifier = Modifier.width(32.dp),
                fontWeight = FontWeight.Medium,
            )
            IconButton(
                onClick = { onChange(count + 1) },
                modifier = Modifier.size(28.dp),
            ) {
                Icon(Icons.Default.Add, "加", tint = TxOrange, modifier = Modifier.size(16.dp))
            }
        }
    }
}

data class PieSlice(val label: String, val amount: Long, val color: Color)

@Composable
private fun PaymentPieChart(data: List<PieSlice>, modifier: Modifier = Modifier) {
    val total = data.sumOf { it.amount }.toFloat()
    if (total <= 0) return

    Canvas(modifier = modifier) {
        var startAngle = -90f
        data.forEach { slice ->
            val sweepAngle = (slice.amount / total) * 360f
            drawArc(
                color = slice.color,
                startAngle = startAngle,
                sweepAngle = sweepAngle,
                useCenter = true,
                topLeft = Offset.Zero,
                size = Size(size.width, size.height),
            )
            startAngle += sweepAngle
        }
        // Center hole for donut style
        drawCircle(
            color = TxDarkSurface,
            radius = size.minDimension / 4f,
        )
    }
}
