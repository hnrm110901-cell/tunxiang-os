package com.tunxiang.pos.ui.components

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.window.Dialog
import com.tunxiang.pos.data.local.entity.LocalDishCache
import com.tunxiang.pos.ui.theme.*

/**
 * WeighDialog - Scale weigh popup for weighted/market price dishes.
 *
 * For weighted dishes:
 * - Reads weight from SunmiScale StateFlow
 * - Calculates price: price_per_jin * weight / 500
 * - Confirm adds to cart
 *
 * For market price dishes:
 * - Shows NumPad for manual price input
 * - Confirm adds to cart with custom price
 */
@Composable
fun WeighDialog(
    dish: LocalDishCache,
    currentWeight: Int,         // From SunmiScale StateFlow, in grams
    isStable: Boolean,          // From SunmiScale StateFlow
    onTare: () -> Unit,
    onConfirm: (weightGram: Int?, unitPrice: Long, amount: Long) -> Unit,
    onDismiss: () -> Unit,
) {
    val isWeighted = dish.pricingType == "weighted"
    val isMarketPrice = dish.pricingType == "market"

    var manualPrice by remember { mutableStateOf("") }

    val pricePerJin = dish.price // cents per 500g
    val calculatedAmount = if (isWeighted && currentWeight > 0) {
        (pricePerJin * currentWeight) / 500
    } else {
        0L
    }

    Dialog(onDismissRequest = onDismiss) {
        Card(
            modifier = Modifier
                .fillMaxWidth(0.7f),
            shape = RoundedCornerShape(16.dp),
            colors = CardDefaults.cardColors(containerColor = TxDarkBg),
        ) {
            Column(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(20.dp),
                horizontalAlignment = Alignment.CenterHorizontally,
            ) {
                // Header
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.SpaceBetween,
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Text(
                        text = dish.name,
                        style = MaterialTheme.typography.titleLarge,
                        fontWeight = FontWeight.Bold,
                    )
                    IconButton(onClick = onDismiss) {
                        Icon(Icons.Default.Close, "关闭", tint = TxGray)
                    }
                }

                Spacer(modifier = Modifier.height(16.dp))

                if (isWeighted) {
                    // Price per jin display
                    Text(
                        text = "单价: ¥%.2f/斤".format(pricePerJin / 100.0),
                        style = MaterialTheme.typography.bodyLarge,
                        color = TxGrayLight,
                    )

                    Spacer(modifier = Modifier.height(20.dp))

                    // Weight display (large)
                    Text(
                        text = "${currentWeight}g",
                        style = MaterialTheme.typography.headlineLarge,
                        color = if (isStable) PaySuccess else PayPending,
                        fontWeight = FontWeight.Bold,
                        textAlign = TextAlign.Center,
                    )

                    Text(
                        text = if (isStable) "稳定" else "读数中...",
                        style = MaterialTheme.typography.bodySmall,
                        color = if (isStable) PaySuccess else PayPending,
                    )

                    Spacer(modifier = Modifier.height(12.dp))

                    // Calculated amount
                    Text(
                        text = "金额: ¥%.2f".format(calculatedAmount / 100.0),
                        style = MaterialTheme.typography.headlineMedium,
                        color = TxOrange,
                        fontWeight = FontWeight.Bold,
                    )

                    Spacer(modifier = Modifier.height(16.dp))

                    // Tare button
                    OutlinedButton(
                        onClick = onTare,
                        modifier = Modifier.fillMaxWidth(),
                    ) {
                        Icon(Icons.Default.Refresh, "去皮")
                        Spacer(modifier = Modifier.width(8.dp))
                        Text("去皮归零")
                    }

                    Spacer(modifier = Modifier.height(12.dp))

                    // Confirm button
                    Button(
                        onClick = {
                            onConfirm(currentWeight, pricePerJin, calculatedAmount)
                        },
                        modifier = Modifier.fillMaxWidth(),
                        colors = ButtonDefaults.buttonColors(containerColor = TxOrange),
                        shape = RoundedCornerShape(8.dp),
                        enabled = currentWeight > 0 && isStable,
                    ) {
                        Text(
                            text = "确认称重",
                            fontWeight = FontWeight.Bold,
                        )
                    }
                }

                if (isMarketPrice) {
                    // Manual price input
                    Text(
                        text = "请输入时价",
                        style = MaterialTheme.typography.bodyLarge,
                        color = TxGrayLight,
                    )

                    Spacer(modifier = Modifier.height(16.dp))

                    NumPad(
                        value = manualPrice,
                        onValueChange = { manualPrice = it },
                    )

                    Spacer(modifier = Modifier.height(16.dp))

                    Button(
                        onClick = {
                            val priceCents = ((manualPrice.toDoubleOrNull() ?: 0.0) * 100).toLong()
                            if (priceCents > 0) {
                                onConfirm(null, priceCents, priceCents)
                            }
                        },
                        modifier = Modifier.fillMaxWidth(),
                        colors = ButtonDefaults.buttonColors(containerColor = TxOrange),
                        shape = RoundedCornerShape(8.dp),
                        enabled = manualPrice.isNotEmpty() && (manualPrice.toDoubleOrNull() ?: 0.0) > 0,
                    ) {
                        Text(
                            text = "确认价格",
                            fontWeight = FontWeight.Bold,
                        )
                    }
                }
            }
        }
    }
}
