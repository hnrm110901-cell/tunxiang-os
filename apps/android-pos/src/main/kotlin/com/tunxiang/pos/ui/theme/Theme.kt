package com.tunxiang.pos.ui.theme

import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.sp

// ─── Tunxiang Brand Colors ───

val TxOrange = Color(0xFFFF6B35)       // Primary brand orange
val TxOrangeDark = Color(0xFFE55A2B)   // Pressed state
val TxOrangeLight = Color(0xFFFF8F65)  // Light variant

val TxDarkBg = Color(0xFF1A1A2E)       // Main background
val TxDarkSurface = Color(0xFF16213E)  // Card/panel background
val TxDarkCard = Color(0xFF0F3460)     // Elevated card
val TxDarkInput = Color(0xFF1C2541)    // Input field background

val TxWhite = Color(0xFFEEEEEE)        // Primary text
val TxGray = Color(0xFF9E9E9E)         // Secondary text
val TxGrayLight = Color(0xFFBDBDBD)    // Tertiary text

// Table status colors
val TableFree = Color(0xFF4CAF50)      // Green - available
val TableOccupied = Color(0xFFF44336)  // Red - occupied
val TableReserved = Color(0xFFFFEB3B)  // Yellow - reserved
val TableDisabled = Color(0xFF757575)  // Gray - disabled

// Payment status
val PaySuccess = Color(0xFF4CAF50)
val PayPending = Color(0xFFFFC107)
val PayFailed = Color(0xFFF44336)

// ─── Dark Color Scheme ───

private val TunxiangDarkColorScheme = darkColorScheme(
    primary = TxOrange,
    onPrimary = Color.White,
    primaryContainer = TxOrangeDark,
    onPrimaryContainer = Color.White,
    secondary = Color(0xFF03DAC6),
    onSecondary = Color.Black,
    background = TxDarkBg,
    onBackground = TxWhite,
    surface = TxDarkSurface,
    onSurface = TxWhite,
    surfaceVariant = TxDarkCard,
    onSurfaceVariant = TxGrayLight,
    error = Color(0xFFCF6679),
    onError = Color.Black,
    outline = Color(0xFF444444),
)

// ─── Typography ───

val TunxiangTypography = Typography(
    headlineLarge = TextStyle(
        fontWeight = FontWeight.Bold,
        fontSize = 28.sp,
        lineHeight = 36.sp,
        color = TxWhite,
    ),
    headlineMedium = TextStyle(
        fontWeight = FontWeight.Bold,
        fontSize = 22.sp,
        lineHeight = 28.sp,
        color = TxWhite,
    ),
    titleLarge = TextStyle(
        fontWeight = FontWeight.SemiBold,
        fontSize = 20.sp,
        lineHeight = 26.sp,
        color = TxWhite,
    ),
    titleMedium = TextStyle(
        fontWeight = FontWeight.Medium,
        fontSize = 16.sp,
        lineHeight = 22.sp,
        color = TxWhite,
    ),
    bodyLarge = TextStyle(
        fontWeight = FontWeight.Normal,
        fontSize = 16.sp,
        lineHeight = 24.sp,
        color = TxWhite,
    ),
    bodyMedium = TextStyle(
        fontWeight = FontWeight.Normal,
        fontSize = 14.sp,
        lineHeight = 20.sp,
        color = TxGrayLight,
    ),
    bodySmall = TextStyle(
        fontWeight = FontWeight.Normal,
        fontSize = 12.sp,
        lineHeight = 16.sp,
        color = TxGray,
    ),
    labelLarge = TextStyle(
        fontWeight = FontWeight.SemiBold,
        fontSize = 14.sp,
        lineHeight = 20.sp,
        color = TxWhite,
    ),
    labelMedium = TextStyle(
        fontWeight = FontWeight.Medium,
        fontSize = 12.sp,
        lineHeight = 16.sp,
        color = TxGray,
    ),
)

// ─── Theme Composable ───

@Composable
fun TunxiangPOSTheme(
    content: @Composable () -> Unit
) {
    // POS always uses dark theme for restaurant lighting conditions
    MaterialTheme(
        colorScheme = TunxiangDarkColorScheme,
        typography = TunxiangTypography,
        content = content
    )
}
