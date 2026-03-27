package com.tunxiang.pos.ui.components

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import coil.compose.AsyncImage
import com.tunxiang.pos.data.local.entity.LocalDishCache
import com.tunxiang.pos.ui.theme.*

/**
 * DishCard - Dish display card with image, name, price, and add button.
 *
 * Handles three pricing types:
 * - fixed: shows price directly, tap adds to cart
 * - weighted: shows "按斤", tap opens WeighDialog
 * - market: shows "时价", tap opens price input
 */
@Composable
fun DishCard(
    dish: LocalDishCache,
    onAdd: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val isSoldOut = dish.status == "sold_out"

    Card(
        modifier = modifier
            .fillMaxWidth()
            .clickable(enabled = !isSoldOut) { onAdd() },
        shape = RoundedCornerShape(8.dp),
        colors = CardDefaults.cardColors(
            containerColor = if (isSoldOut) TxDarkInput.copy(alpha = 0.5f) else TxDarkCard,
        ),
        elevation = CardDefaults.cardElevation(defaultElevation = 2.dp),
    ) {
        Column(
            modifier = Modifier.fillMaxWidth(),
        ) {
            // Dish image
            Box(
                modifier = Modifier
                    .fillMaxWidth()
                    .aspectRatio(4f / 3f)
                    .clip(RoundedCornerShape(topStart = 8.dp, topEnd = 8.dp))
            ) {
                if (dish.imageUrl != null) {
                    AsyncImage(
                        model = dish.imageUrl,
                        contentDescription = dish.name,
                        modifier = Modifier.fillMaxSize(),
                        contentScale = ContentScale.Crop,
                    )
                } else {
                    // Placeholder
                    Surface(
                        modifier = Modifier.fillMaxSize(),
                        color = TxDarkInput,
                    ) {
                        Box(contentAlignment = Alignment.Center) {
                            Text(
                                text = dish.name.take(2),
                                style = MaterialTheme.typography.headlineMedium,
                                color = TxGray,
                            )
                        }
                    }
                }

                // Sold out overlay
                if (isSoldOut) {
                    Surface(
                        modifier = Modifier.fillMaxSize(),
                        color = Color.Black.copy(alpha = 0.6f),
                    ) {
                        Box(contentAlignment = Alignment.Center) {
                            Text(
                                text = "售罄",
                                style = MaterialTheme.typography.titleMedium,
                                color = TxGray,
                                fontWeight = FontWeight.Bold,
                            )
                        }
                    }
                }

                // Tags (top-right corner)
                val tags = dish.tags?.split(",")?.filter { it.isNotBlank() }
                if (!tags.isNullOrEmpty()) {
                    Surface(
                        modifier = Modifier
                            .align(Alignment.TopEnd)
                            .padding(4.dp),
                        color = TxOrange,
                        shape = RoundedCornerShape(4.dp),
                    ) {
                        Text(
                            text = tags.first(),
                            modifier = Modifier.padding(horizontal = 6.dp, vertical = 2.dp),
                            style = MaterialTheme.typography.labelMedium,
                            color = Color.White,
                        )
                    }
                }
            }

            // Name + price
            Column(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(horizontal = 8.dp, vertical = 6.dp),
            ) {
                Text(
                    text = dish.name,
                    style = MaterialTheme.typography.bodyMedium,
                    color = TxWhite,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                    fontWeight = FontWeight.Medium,
                )

                Spacer(modifier = Modifier.height(4.dp))

                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.SpaceBetween,
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    // Price display
                    when (dish.pricingType) {
                        "fixed" -> {
                            Text(
                                text = "¥%.0f".format(dish.price / 100.0),
                                style = MaterialTheme.typography.labelLarge,
                                color = TxOrange,
                                fontWeight = FontWeight.Bold,
                            )
                        }
                        "weighted" -> {
                            Text(
                                text = "¥%.0f/斤".format(dish.price / 100.0),
                                style = MaterialTheme.typography.labelLarge,
                                color = TxOrange,
                                fontWeight = FontWeight.Bold,
                            )
                        }
                        "market" -> {
                            Text(
                                text = "时价",
                                style = MaterialTheme.typography.labelLarge,
                                color = TxOrangeLight,
                                fontWeight = FontWeight.Bold,
                            )
                        }
                    }

                    // Add button
                    if (!isSoldOut) {
                        IconButton(
                            onClick = onAdd,
                            modifier = Modifier.size(28.dp),
                        ) {
                            Icon(
                                imageVector = Icons.Default.Add,
                                contentDescription = "添加",
                                tint = TxOrange,
                                modifier = Modifier.size(20.dp),
                            )
                        }
                    }
                }

                // Member price
                if (dish.memberPrice != null && dish.memberPrice < dish.price) {
                    Text(
                        text = "会员 ¥%.0f".format(dish.memberPrice / 100.0),
                        style = MaterialTheme.typography.bodySmall,
                        color = TxGray,
                    )
                }
            }
        }
    }
}
