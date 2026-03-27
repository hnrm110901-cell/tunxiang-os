package com.tunxiang.pos.ui.components

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.tunxiang.pos.data.local.entity.LocalTableState
import com.tunxiang.pos.ui.theme.*

/**
 * TableCard - Table status card for the table map grid.
 *
 * Color scheme:
 * - Green: free (available for seating)
 * - Red: occupied (has active order)
 * - Yellow: reserved
 * - Gray: disabled
 */
@Composable
fun TableCard(
    table: LocalTableState,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val statusColor = when (table.status) {
        "free" -> TableFree
        "occupied" -> TableOccupied
        "reserved" -> TableReserved
        "disabled" -> TableDisabled
        else -> TableDisabled
    }

    val statusText = when (table.status) {
        "free" -> "空闲"
        "occupied" -> "就餐中"
        "reserved" -> "已预订"
        "disabled" -> "停用"
        else -> table.status
    }

    Card(
        modifier = modifier
            .fillMaxWidth()
            .aspectRatio(1f)
            .clickable(enabled = table.status != "disabled") { onClick() },
        shape = RoundedCornerShape(12.dp),
        colors = CardDefaults.cardColors(
            containerColor = TxDarkCard,
        ),
        elevation = CardDefaults.cardElevation(defaultElevation = 4.dp),
    ) {
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(8.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.SpaceBetween,
        ) {
            // Status indicator bar
            Box(
                modifier = Modifier
                    .fillMaxWidth()
                    .height(4.dp)
                    .clip(RoundedCornerShape(2.dp))
                    .background(statusColor)
            )

            Spacer(modifier = Modifier.height(4.dp))

            // Table number
            Text(
                text = table.tableNumber,
                style = MaterialTheme.typography.titleLarge,
                fontWeight = FontWeight.Bold,
                color = TxWhite,
                textAlign = TextAlign.Center,
            )

            // Table name
            Text(
                text = table.tableName,
                style = MaterialTheme.typography.bodySmall,
                color = TxGray,
                textAlign = TextAlign.Center,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )

            Spacer(modifier = Modifier.height(4.dp))

            // Status + extra info
            if (table.status == "occupied") {
                // Show duration and amount
                val durationMin = table.openedAt?.let {
                    ((System.currentTimeMillis() - it) / 60000).toInt()
                } ?: 0
                val durationText = if (durationMin >= 60) {
                    "${durationMin / 60}h${durationMin % 60}m"
                } else {
                    "${durationMin}min"
                }

                Text(
                    text = durationText,
                    style = MaterialTheme.typography.bodySmall,
                    color = TxOrangeLight,
                    textAlign = TextAlign.Center,
                )

                if (table.orderAmount != null && table.orderAmount > 0) {
                    Text(
                        text = "¥%.0f".format(table.orderAmount / 100.0),
                        style = MaterialTheme.typography.labelLarge,
                        color = TxWhite,
                        textAlign = TextAlign.Center,
                    )
                }

                Text(
                    text = "${table.guestCount ?: 0}人",
                    style = MaterialTheme.typography.bodySmall,
                    color = TxGrayLight,
                )
            } else {
                // Show capacity for free tables
                Text(
                    text = statusText,
                    style = MaterialTheme.typography.bodySmall,
                    color = statusColor,
                    fontWeight = FontWeight.Medium,
                )

                Text(
                    text = "${table.capacity}座",
                    style = MaterialTheme.typography.bodySmall,
                    color = TxGray,
                )
            }
        }
    }
}
