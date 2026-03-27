package com.tunxiang.pos.ui.components

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.tunxiang.pos.ui.theme.*

/**
 * NumPad - Numeric keypad for amount input.
 *
 * Used in:
 * - SettleScreen for cash payment amount
 * - WeighDialog for market price input
 * - PaymentDialog for split payment amounts
 */
@Composable
fun NumPad(
    value: String,
    onValueChange: (String) -> Unit,
    modifier: Modifier = Modifier,
) {
    Column(modifier = modifier) {
        // Display
        Surface(
            modifier = Modifier
                .fillMaxWidth()
                .padding(bottom = 8.dp),
            color = TxDarkInput,
            shape = RoundedCornerShape(8.dp),
        ) {
            Text(
                text = if (value.isEmpty()) "0.00" else "¥$value",
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(16.dp),
                style = MaterialTheme.typography.headlineMedium,
                color = TxOrange,
                fontWeight = FontWeight.Bold,
                textAlign = TextAlign.End,
            )
        }

        // Keypad grid
        val keys = listOf(
            listOf("7", "8", "9"),
            listOf("4", "5", "6"),
            listOf("1", "2", "3"),
            listOf(".", "0", "C"),
        )

        for (row in keys) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(4.dp),
            ) {
                for (key in row) {
                    NumPadKey(
                        key = key,
                        onClick = {
                            when (key) {
                                "C" -> onValueChange("")
                                "." -> {
                                    if (!value.contains(".")) {
                                        onValueChange(if (value.isEmpty()) "0." else "$value.")
                                    }
                                }
                                else -> {
                                    // Limit to 2 decimal places
                                    val dotIndex = value.indexOf(".")
                                    if (dotIndex >= 0 && value.length - dotIndex > 2) {
                                        // Already 2 decimal places
                                    } else if (value.length < 10) {
                                        onValueChange(value + key)
                                    }
                                }
                            }
                        },
                        modifier = Modifier.weight(1f),
                        isAction = key == "C",
                    )
                }
            }
            Spacer(modifier = Modifier.height(4.dp))
        }
    }
}

@Composable
private fun NumPadKey(
    key: String,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    isAction: Boolean = false,
) {
    Button(
        onClick = onClick,
        modifier = modifier.height(52.dp),
        shape = RoundedCornerShape(8.dp),
        colors = ButtonDefaults.buttonColors(
            containerColor = if (isAction) TxDarkCard else TxDarkInput,
            contentColor = if (isAction) PayFailed else TxWhite,
        ),
        contentPadding = PaddingValues(0.dp),
    ) {
        Text(
            text = if (key == "C") "清除" else key,
            fontSize = if (key == "C") 14.sp else 20.sp,
            fontWeight = FontWeight.Medium,
        )
    }
}
