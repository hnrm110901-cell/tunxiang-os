package com.tunxiang.pos.ui.navigation

import androidx.compose.runtime.Composable
import androidx.navigation.NavHostController
import androidx.navigation.NavType
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.rememberNavController
import androidx.navigation.navArgument
import com.tunxiang.pos.ui.screens.*

/**
 * Navigation routes for the 5 core POS screens + WebView fallback.
 */
object Routes {
    const val TABLE_MAP = "table_map"
    const val ORDER = "order/{orderId}/{tableId}"
    const val SETTLE = "settle/{orderId}"
    const val SHIFT = "shift"
    const val DAILY_CLOSE = "daily_close"
    const val WEBVIEW = "webview/{url}"

    fun order(orderId: String, tableId: String) = "order/$orderId/$tableId"
    fun settle(orderId: String) = "settle/$orderId"
    fun webview(url: String) = "webview/${java.net.URLEncoder.encode(url, "UTF-8")}"
}

@Composable
fun NavGraph(
    navController: NavHostController = rememberNavController()
) {
    NavHost(
        navController = navController,
        startDestination = Routes.TABLE_MAP
    ) {
        // 1. Table Map (opening screen)
        composable(Routes.TABLE_MAP) {
            TableMapScreen(
                onTableOpened = { orderId, tableId ->
                    navController.navigate(Routes.order(orderId, tableId))
                },
                onNavigateToShift = {
                    navController.navigate(Routes.SHIFT)
                },
                onNavigateToDailyClose = {
                    navController.navigate(Routes.DAILY_CLOSE)
                }
            )
        }

        // 2. Order Screen
        composable(
            route = Routes.ORDER,
            arguments = listOf(
                navArgument("orderId") { type = NavType.StringType },
                navArgument("tableId") { type = NavType.StringType }
            )
        ) { backStackEntry ->
            val orderId = backStackEntry.arguments?.getString("orderId") ?: ""
            val tableId = backStackEntry.arguments?.getString("tableId") ?: ""
            OrderScreen(
                orderId = orderId,
                tableId = tableId,
                onSettle = { navController.navigate(Routes.settle(orderId)) },
                onBack = { navController.popBackStack() }
            )
        }

        // 3. Settle Screen
        composable(
            route = Routes.SETTLE,
            arguments = listOf(
                navArgument("orderId") { type = NavType.StringType }
            )
        ) { backStackEntry ->
            val orderId = backStackEntry.arguments?.getString("orderId") ?: ""
            SettleScreen(
                orderId = orderId,
                onSettled = {
                    navController.popBackStack(Routes.TABLE_MAP, inclusive = false)
                },
                onBack = { navController.popBackStack() }
            )
        }

        // 4. Shift Handover
        composable(Routes.SHIFT) {
            ShiftScreen(
                onBack = { navController.popBackStack() }
            )
        }

        // 5. Daily Close
        composable(Routes.DAILY_CLOSE) {
            DailyCloseScreen(
                onBack = { navController.popBackStack() }
            )
        }

        // 6. WebView Fallback (non-core screens load React)
        composable(
            route = Routes.WEBVIEW,
            arguments = listOf(
                navArgument("url") { type = NavType.StringType }
            )
        ) { backStackEntry ->
            val url = backStackEntry.arguments?.getString("url") ?: ""
            val decodedUrl = java.net.URLDecoder.decode(url, "UTF-8")
            WebViewScreen(
                url = decodedUrl,
                onBack = { navController.popBackStack() }
            )
        }
    }
}
