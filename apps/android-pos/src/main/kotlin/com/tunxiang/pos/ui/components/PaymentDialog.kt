package com.tunxiang.pos.ui.components

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.grid.GridCells
import androidx.compose.foundation.lazy.grid.LazyVerticalGrid
import androidx.compose.foundation.lazy.grid.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties
import com.tunxiang.pos.ui.theme.*

/**
 * PaymentDialog - Payment method selection with multi-payment split support.
 *
 * Supported methods: cash / wechat / alipay / unionpay / member / credit
 * Supports splitting a single order across multiple payment methods.
 */
@Composable
fun PaymentDialog(
    totalAmount: Long,
    onDismiss: () -> Unit,
    onConfirm: (List<PaymentSelection>) -> Unit,
) {
    var payments by remember { mutableStateOf(listOf<PaymentSelection>()) }
    var selectedMethod by remember { mutableStateOf<String?>(null) }
    var inputAmount by remember { mutableStateOf("") }
    var showNumPad by remember { mutableStateOf(false) }

    val remainingAmount = totalAmount - payments.sumOf { it.amount }

    Dialog(
        onDismissRequest = onDismiss,
        properties = DialogProperties(usePlatformDefaultWidth = false),
    ) {
        Card(
            modifier = Modifier
                .fillMaxWidth(0.85f)
                .fillMaxHeight(0.8f),
            shape = RoundedCornerShape(16.dp),
            colors = CardDefaults.cardColors(containerColor = TxDarkBg),
        ) {
            Column(
                modifier = Modifier
                    .fillMaxSize()
                    .padding(20.dp),
            ) {
                // Header
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.SpaceBetween,
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Text(
                        text = "选择支付方式",
                        style = MaterialTheme.typography.titleLarge,
                        fontWeight = FontWeight.Bold,
                    )
                    IconButton(onClick = onDismiss) {
                        Icon(Icons.Default.Close, "关闭", tint = TxGray)
                    }
                }

                // Total and remaining
                Spacer(modifier = Modifier.height(12.dp))
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.SpaceBetween,
                ) {
                    Column {
                        Text("应收", style = MaterialTheme.typography.bodySmall, color = TxGray)
                        Text(
                            text = "¥%.2f".format(totalAmount / 100.0),
                            style = MaterialTheme.typography.headlineMedium,
                            color = TxOrange,
                            fontWeight = FontWeight.Bold,
                        )
                    }
                    if (payments.isNotEmpty()) {
                        Column(horizontalAlignment = Alignment.End) {
                            Text("待收", style = MaterialTheme.typography.bodySmall, color = TxGray)
                            Text(
                                text = "¥%.2f".format(remainingAmount / 100.0),
                                style = MaterialTheme.typography.headlineMedium,
                                color = if (remainingAmount > 0) PayPending else PaySuccess,
                                fontWeight = FontWeight.Bold,
                            )
                        }
                    }
                }

                Spacer(modifier = Modifier.height(16.dp))

                // Payment method grid
                val methods = listOf(
                    PaymentMethodInfo("cash", "现金", Icons.Default.Payments, Color(0xFF4CAF50)),
                    PaymentMethodInfo("wechat", "微信", Icons.Default.QrCode, Color(0xFF07C160)),
                    PaymentMethodInfo("alipay", "支付宝", Icons.Default.QrCodeScanner, Color(0xFF1677FF)),
                    PaymentMethodInfo("unionpay", "银联", Icons.Default.CreditCard, Color(0xFFE62E2E)),
                    PaymentMethodInfo("member", "会员余额", Icons.Default.CardMembership, Color(0xFFFF9800)),
                    PaymentMethodInfo("credit", "挂账", Icons.Default.Receipt, Color(0xFF9E9E9E)),
                )

                LazyVerticalGrid(
                    columns = GridCells.Fixed(3),
                    horizontalArrangement = Arrangement.spacedBy(8.dp),
                    verticalArrangement = Arrangement.spacedBy(8.dp),
                    modifier = Modifier.height(180.dp),
                ) {
                    items(methods) { method ->
                        PaymentMethodCard(
                            info = method,
                            isSelected = selectedMethod == method.code,
                            onClick = {
                                selectedMethod = method.code
                                if (method.code == "cash") {
                                    showNumPad = true
                                    inputAmount = ""
                                } else {
                                    // Non-cash: default to remaining amount
                                    inputAmount = "%.2f".format(remainingAmount / 100.0)
                                    showNumPad = false
                                }
                            },
                        )
                    }
                }

                Spacer(modifier = Modifier.height(12.dp))

                // Amount input + NumPad for cash
                if (selectedMethod != null) {
                    if (showNumPad) {
                        NumPad(
                            value = inputAmount,
                            onValueChange = { inputAmount = it },
                            modifier = Modifier.weight(1f),
                        )
                    } else {
                        Spacer(modifier = Modifier.weight(1f))
                    }

                    Spacer(modifier = Modifier.height(12.dp))

                    // Add payment button
                    Button(
                        onClick = {
                            val amountCents = ((inputAmount.toDoubleOrNull() ?: 0.0) * 100).toLong()
                            if (amountCents > 0 && selectedMethod != null) {
                                payments = payments + PaymentSelection(
                                    method = selectedMethod!!,
                                    amount = minOf(amountCents, remainingAmount),
                                    receivedAmount = if (selectedMethod == "cash") amountCents else null,
                                )
                                selectedMethod = null
                                inputAmount = ""
                                showNumPad = false
                            }
                        },
                        modifier = Modifier.fillMaxWidth(),
                        colors = ButtonDefaults.buttonColors(containerColor = TxOrange),
                        shape = RoundedCornerShape(8.dp),
                        enabled = selectedMethod != null && inputAmount.isNotEmpty(),
                    ) {
                        Text("添加支付", fontWeight = FontWeight.Bold)
                    }
                } else {
                    Spacer(modifier = Modifier.weight(1f))
                }

                // Added payments summary
                if (payments.isNotEmpty()) {
                    Spacer(modifier = Modifier.height(8.dp))
                    HorizontalDivider(color = MaterialTheme.colorScheme.outline)
                    Spacer(modifier = Modifier.height(8.dp))

                    for (p in payments) {
                        Row(
                            modifier = Modifier
                                .fillMaxWidth()
                                .padding(vertical = 2.dp),
                            horizontalArrangement = Arrangement.SpaceBetween,
                        ) {
                            Text(
                                text = paymentMethodLabel(p.method),
                                style = MaterialTheme.typography.bodyMedium,
                            )
                            Text(
                                text = "¥%.2f".format(p.amount / 100.0),
                                style = MaterialTheme.typography.bodyMedium,
                                color = PaySuccess,
                            )
                        }
                    }
                }

                Spacer(modifier = Modifier.height(12.dp))

                // Confirm button (only when fully paid)
                Button(
                    onClick = { onConfirm(payments) },
                    modifier = Modifier.fillMaxWidth(),
                    colors = ButtonDefaults.buttonColors(
                        containerColor = if (remainingAmount <= 0) PaySuccess else TxGray,
                    ),
                    shape = RoundedCornerShape(8.dp),
                    enabled = remainingAmount <= 0 && payments.isNotEmpty(),
                ) {
                    Text(
                        text = if (remainingAmount <= 0) "确认收款" else "请完成支付",
                        style = MaterialTheme.typography.labelLarge,
                        fontWeight = FontWeight.Bold,
                    )
                }
            }
        }
    }
}

@Composable
private fun PaymentMethodCard(
    info: PaymentMethodInfo,
    isSelected: Boolean,
    onClick: () -> Unit,
) {
    Card(
        modifier = Modifier
            .fillMaxWidth()
            .clickable { onClick() },
        shape = RoundedCornerShape(8.dp),
        colors = CardDefaults.cardColors(
            containerColor = if (isSelected) info.color.copy(alpha = 0.2f) else TxDarkCard,
        ),
        border = if (isSelected) {
            CardDefaults.outlinedCardBorder().copy(brush = androidx.compose.ui.graphics.SolidColor(info.color))
        } else null,
    ) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(12.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            Icon(
                imageVector = info.icon,
                contentDescription = info.label,
                tint = info.color,
                modifier = Modifier.size(28.dp),
            )
            Spacer(modifier = Modifier.height(4.dp))
            Text(
                text = info.label,
                style = MaterialTheme.typography.labelMedium,
                color = if (isSelected) info.color else TxGrayLight,
            )
        }
    }
}

private fun paymentMethodLabel(method: String): String = when (method) {
    "cash" -> "现金"
    "wechat" -> "微信支付"
    "alipay" -> "支付宝"
    "unionpay" -> "银联"
    "member" -> "会员余额"
    "credit" -> "挂账"
    else -> method
}

data class PaymentMethodInfo(
    val code: String,
    val label: String,
    val icon: ImageVector,
    val color: Color,
)

data class PaymentSelection(
    val method: String,
    val amount: Long,
    val receivedAmount: Long? = null,
    val tradeNo: String? = null,
)
