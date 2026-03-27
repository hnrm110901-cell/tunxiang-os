package com.tunxiang.pos.ui.components

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material.icons.filled.Edit
import androidx.compose.material.icons.filled.Remove
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.tunxiang.pos.data.local.entity.LocalOrderItem
import com.tunxiang.pos.ui.theme.*

/**
 * CartPanel - Right-side cart panel on the order screen.
 *
 * Shows:
 * - List of items with quantity +/-, notes, delete
 * - Subtotal and item count
 * - Send to kitchen button
 */
@Composable
fun CartPanel(
    items: List<LocalOrderItem>,
    onQuantityChange: (LocalOrderItem, Int) -> Unit,
    onDelete: (LocalOrderItem) -> Unit,
    onEditNote: (LocalOrderItem) -> Unit,
    onSendToKitchen: () -> Unit,
    onSettle: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val activeItems = items.filter { it.status != "cancelled" }
    val totalAmount = activeItems.sumOf { it.finalAmount }
    val totalCount = activeItems.sumOf { it.quantity }
    val pendingItems = activeItems.filter { it.status == "pending" }

    Column(
        modifier = modifier
            .fillMaxHeight()
            .background(TxDarkSurface)
            .padding(12.dp),
    ) {
        // Header
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text(
                text = "购物车",
                style = MaterialTheme.typography.titleMedium,
                fontWeight = FontWeight.Bold,
            )
            // Item count badge
            if (totalCount > 0) {
                Badge(
                    containerColor = TxOrange,
                    contentColor = TxWhite,
                ) {
                    Text("$totalCount")
                }
            }
        }

        Spacer(modifier = Modifier.height(8.dp))
        HorizontalDivider(color = MaterialTheme.colorScheme.outline)
        Spacer(modifier = Modifier.height(8.dp))

        // Cart items list
        if (activeItems.isEmpty()) {
            Box(
                modifier = Modifier
                    .fillMaxWidth()
                    .weight(1f),
                contentAlignment = Alignment.Center,
            ) {
                Text(
                    text = "购物车为空\n点击菜品添加",
                    style = MaterialTheme.typography.bodyMedium,
                    color = TxGray,
                )
            }
        } else {
            LazyColumn(
                modifier = Modifier
                    .fillMaxWidth()
                    .weight(1f),
                verticalArrangement = Arrangement.spacedBy(4.dp),
            ) {
                items(activeItems, key = { it.id }) { item ->
                    CartItemRow(
                        item = item,
                        onQuantityChange = { delta -> onQuantityChange(item, item.quantity + delta) },
                        onDelete = { onDelete(item) },
                        onEditNote = { onEditNote(item) },
                    )
                }
            }
        }

        Spacer(modifier = Modifier.height(8.dp))
        HorizontalDivider(color = MaterialTheme.colorScheme.outline)
        Spacer(modifier = Modifier.height(8.dp))

        // Total
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text(
                text = "合计",
                style = MaterialTheme.typography.titleMedium,
                fontWeight = FontWeight.Bold,
            )
            Text(
                text = "¥%.2f".format(totalAmount / 100.0),
                style = MaterialTheme.typography.titleLarge,
                color = TxOrange,
                fontWeight = FontWeight.Bold,
            )
        }

        Spacer(modifier = Modifier.height(12.dp))

        // Action buttons
        if (pendingItems.isNotEmpty()) {
            Button(
                onClick = onSendToKitchen,
                modifier = Modifier.fillMaxWidth(),
                colors = ButtonDefaults.buttonColors(containerColor = TxOrange),
                shape = RoundedCornerShape(8.dp),
            ) {
                Text(
                    text = "下单 (${pendingItems.size}道新菜)",
                    style = MaterialTheme.typography.labelLarge,
                    fontWeight = FontWeight.Bold,
                )
            }

            Spacer(modifier = Modifier.height(8.dp))
        }

        OutlinedButton(
            onClick = onSettle,
            modifier = Modifier.fillMaxWidth(),
            enabled = activeItems.isNotEmpty(),
            shape = RoundedCornerShape(8.dp),
            colors = ButtonDefaults.outlinedButtonColors(
                contentColor = TxOrange,
            ),
        ) {
            Text(
                text = "结账",
                style = MaterialTheme.typography.labelLarge,
            )
        }
    }
}

@Composable
private fun CartItemRow(
    item: LocalOrderItem,
    onQuantityChange: (Int) -> Unit,
    onDelete: () -> Unit,
    onEditNote: () -> Unit,
) {
    val isSent = item.status != "pending"

    Card(
        colors = CardDefaults.cardColors(
            containerColor = if (isSent) TxDarkInput else TxDarkCard,
        ),
        shape = RoundedCornerShape(6.dp),
    ) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(8.dp),
        ) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically,
            ) {
                // Dish name
                Column(modifier = Modifier.weight(1f)) {
                    Text(
                        text = item.dishName,
                        style = MaterialTheme.typography.bodyMedium,
                        color = TxWhite,
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis,
                        fontWeight = FontWeight.Medium,
                    )
                    if (item.weightGram != null) {
                        Text(
                            text = "${item.weightGram}g",
                            style = MaterialTheme.typography.bodySmall,
                            color = TxGray,
                        )
                    }
                }

                // Price
                Text(
                    text = "¥%.2f".format(item.finalAmount / 100.0),
                    style = MaterialTheme.typography.labelLarge,
                    color = TxOrange,
                )
            }

            // Note
            if (item.note != null) {
                Text(
                    text = "[${item.note}]",
                    style = MaterialTheme.typography.bodySmall,
                    color = TxGrayLight,
                    modifier = Modifier.padding(top = 2.dp),
                )
            }

            Spacer(modifier = Modifier.height(4.dp))

            // Quantity controls (only for pending items)
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically,
            ) {
                if (!isSent) {
                    // Delete button
                    IconButton(
                        onClick = onDelete,
                        modifier = Modifier.size(24.dp),
                    ) {
                        Icon(
                            imageVector = Icons.Default.Delete,
                            contentDescription = "删除",
                            tint = PayFailed,
                            modifier = Modifier.size(16.dp),
                        )
                    }

                    // Note edit
                    IconButton(
                        onClick = onEditNote,
                        modifier = Modifier.size(24.dp),
                    ) {
                        Icon(
                            imageVector = Icons.Default.Edit,
                            contentDescription = "备注",
                            tint = TxGray,
                            modifier = Modifier.size(16.dp),
                        )
                    }
                } else {
                    Text(
                        text = "已下单",
                        style = MaterialTheme.typography.bodySmall,
                        color = PaySuccess,
                    )
                }

                Spacer(modifier = Modifier.weight(1f))

                // Quantity +/-
                if (item.pricingType == "fixed") {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        IconButton(
                            onClick = { onQuantityChange(-1) },
                            modifier = Modifier
                                .size(24.dp)
                                .background(TxDarkInput, CircleShape),
                            enabled = !isSent,
                        ) {
                            Icon(
                                Icons.Default.Remove,
                                contentDescription = "减少",
                                tint = TxWhite,
                                modifier = Modifier.size(14.dp),
                            )
                        }

                        Text(
                            text = "${item.quantity}",
                            style = MaterialTheme.typography.labelLarge,
                            color = TxWhite,
                            modifier = Modifier.padding(horizontal = 12.dp),
                        )

                        IconButton(
                            onClick = { onQuantityChange(1) },
                            modifier = Modifier
                                .size(24.dp)
                                .background(TxOrange, CircleShape),
                            enabled = !isSent,
                        ) {
                            Icon(
                                Icons.Default.Add,
                                contentDescription = "增加",
                                tint = TxWhite,
                                modifier = Modifier.size(14.dp),
                            )
                        }
                    }
                } else {
                    Text(
                        text = "x${item.quantity}",
                        style = MaterialTheme.typography.labelLarge,
                        color = TxGray,
                    )
                }
            }
        }
    }
}
