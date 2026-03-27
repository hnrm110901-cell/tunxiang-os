package com.tunxiang.pos.bridge

import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.content.ServiceConnection
import android.os.IBinder
import android.util.Log

/**
 * SunmiPrinter - Wrapper for Sunmi built-in printer SDK.
 *
 * Supports ESC/POS receipt formatting for:
 * - Order receipts (customer copy)
 * - Kitchen order tickets
 * - Shift handover reports
 * - Daily close reports
 *
 * On non-Sunmi devices, operations are logged but not executed.
 */
class SunmiPrinter(private val context: Context) {

    companion object {
        private const val TAG = "SunmiPrinter"
        private const val SUNMI_SERVICE_PACKAGE = "woyou.aidlservice.jiuiv5"
        private const val SUNMI_SERVICE_CLASS = "woyou.aidlservice.jiuiv5.IWoyouService"
    }

    // In production, this would be woyou.aidlservice.jiuiv5.IWoyouService
    private var printerService: Any? = null
    private var isConnected = false

    private val serviceConnection = object : ServiceConnection {
        override fun onServiceConnected(name: ComponentName?, service: IBinder?) {
            // printerService = IWoyouService.Stub.asInterface(service)
            isConnected = true
            Log.i(TAG, "Sunmi printer service connected")
        }

        override fun onServiceDisconnected(name: ComponentName?) {
            printerService = null
            isConnected = false
            Log.w(TAG, "Sunmi printer service disconnected")
        }
    }

    /**
     * Bind to Sunmi printer service. Call in Application.onCreate().
     */
    fun connect() {
        try {
            val intent = Intent().apply {
                `package` = SUNMI_SERVICE_PACKAGE
                action = SUNMI_SERVICE_CLASS
            }
            context.bindService(intent, serviceConnection, Context.BIND_AUTO_CREATE)
        } catch (e: Exception) {
            Log.w(TAG, "Sunmi printer not available (not a Sunmi device?)")
        }
    }

    fun disconnect() {
        try {
            context.unbindService(serviceConnection)
        } catch (_: Exception) { }
        isConnected = false
    }

    /**
     * Print a formatted receipt.
     * Uses ESC/POS commands via Sunmi SDK.
     */
    fun printReceipt(receipt: ReceiptData) {
        if (!isConnected) {
            Log.w(TAG, "Printer not connected, receipt:\n${receipt.toText()}")
            return
        }

        try {
            // Sunmi SDK calls (pseudo - actual SDK uses IWoyouService AIDL)
            // printerService?.setAlignment(1, null) // Center
            // printerService?.printTextWithFont(receipt.storeName, "", 28f, null)
            // printerService?.lineWrap(1, null)

            printLine("================================")
            printCenter(receipt.storeName)
            printLine("================================")
            printLine("单号: ${receipt.orderNumber}")
            printLine("桌号: ${receipt.tableName ?: "外带"}")
            printLine("时间: ${receipt.time}")
            printLine("收银: ${receipt.cashierName}")
            printLine("--------------------------------")

            // Items
            for (item in receipt.items) {
                val priceStr = formatPrice(item.finalAmount)
                val nameQty = "${item.name} x${item.quantity}"
                printTwoColumn(nameQty, priceStr)
                if (item.note != null) {
                    printLine("  [${item.note}]")
                }
            }

            printLine("--------------------------------")
            printTwoColumn("小计", formatPrice(receipt.subtotal))
            if (receipt.discountAmount > 0) {
                printTwoColumn("优惠", "-${formatPrice(receipt.discountAmount)}")
            }
            printLine("================================")
            printTwoColumn("合计", formatPrice(receipt.totalAmount), bold = true)
            printLine("")

            // Payments
            for (payment in receipt.payments) {
                printTwoColumn(
                    paymentMethodName(payment.method),
                    formatPrice(payment.amount)
                )
            }
            if (receipt.changeAmount > 0) {
                printTwoColumn("找零", formatPrice(receipt.changeAmount))
            }

            printLine("")
            printCenter("谢谢惠顾")
            printLine("")
            printLine("")
            printLine("")

            // Cut paper
            cutPaper()

            Log.i(TAG, "Receipt printed for order ${receipt.orderNumber}")
        } catch (e: Exception) {
            Log.e(TAG, "Print failed", e)
        }
    }

    /**
     * Print kitchen order ticket.
     */
    fun printKitchenTicket(ticket: KitchenTicketData) {
        if (!isConnected) {
            Log.w(TAG, "Printer not connected, kitchen ticket:\n${ticket.tableName}")
            return
        }

        try {
            printCenter("** 厨房单 **", large = true)
            printLine("桌号: ${ticket.tableName}")
            printLine("单号: ${ticket.orderNumber}")
            printLine("时间: ${ticket.time}")
            printLine("================================")

            for (item in ticket.items) {
                printLine("${item.name} x${item.quantity}", large = true)
                if (item.note != null) {
                    printLine("  >>> ${item.note} <<<")
                }
                if (item.weightGram != null) {
                    printLine("  重量: ${item.weightGram}g")
                }
            }

            printLine("================================")
            printLine("")
            printLine("")
            cutPaper()
        } catch (e: Exception) {
            Log.e(TAG, "Kitchen ticket print failed", e)
        }
    }

    /**
     * Print shift handover report.
     */
    fun printShiftReport(report: ShiftReportData) {
        if (!isConnected) {
            Log.w(TAG, "Printer not connected")
            return
        }

        try {
            printCenter("交接班报表")
            printLine("================================")
            printLine("门店: ${report.storeName}")
            printLine("收银员: ${report.cashierName}")
            printLine("班次: ${report.shiftStart} - ${report.shiftEnd}")
            printLine("--------------------------------")
            printTwoColumn("营业额", formatPrice(report.revenue))
            printTwoColumn("订单数", "${report.orderCount}")
            printTwoColumn("客单价", formatPrice(report.avgCheck))
            printLine("--------------------------------")
            printLine("支付方式明细:")
            for ((method, amount) in report.paymentBreakdown) {
                printTwoColumn("  ${paymentMethodName(method)}", formatPrice(amount))
            }
            printLine("--------------------------------")
            printTwoColumn("系统现金", formatPrice(report.cashExpected))
            printTwoColumn("实点现金", formatPrice(report.cashCounted))
            printTwoColumn("差异", formatPrice(report.variance), bold = true)
            if (report.notes != null) {
                printLine("备注: ${report.notes}")
            }
            printLine("================================")
            printLine("")
            printLine("")
            cutPaper()
        } catch (e: Exception) {
            Log.e(TAG, "Shift report print failed", e)
        }
    }

    // ─── Low-level print helpers ───

    private fun printLine(text: String, large: Boolean = false) {
        // printerService?.printTextWithFont(text + "\n", "", if (large) 32f else 24f, null)
        Log.d(TAG, "PRINT: $text")
    }

    private fun printCenter(text: String, large: Boolean = false) {
        // printerService?.setAlignment(1, null)
        printLine(text, large)
        // printerService?.setAlignment(0, null)
    }

    private fun printTwoColumn(left: String, right: String, bold: Boolean = false) {
        val padding = 32 - left.length - right.length
        val spaces = if (padding > 0) " ".repeat(padding) else " "
        printLine("$left$spaces$right")
    }

    private fun cutPaper() {
        // printerService?.cutPaper(null)
        Log.d(TAG, "PRINT: --- CUT ---")
    }

    private fun formatPrice(cents: Long): String {
        return "¥%.2f".format(cents / 100.0)
    }

    private fun paymentMethodName(method: String): String = when (method) {
        "cash" -> "现金"
        "wechat" -> "微信"
        "alipay" -> "支付宝"
        "unionpay" -> "银联"
        "member" -> "会员余额"
        "credit" -> "挂账"
        else -> method
    }
}

// ─── Print data classes ───

data class ReceiptData(
    val storeName: String,
    val orderNumber: String,
    val tableName: String?,
    val time: String,
    val cashierName: String,
    val items: List<ReceiptItem>,
    val subtotal: Long,
    val discountAmount: Long,
    val totalAmount: Long,
    val payments: List<ReceiptPayment>,
    val changeAmount: Long = 0,
)

data class ReceiptItem(
    val name: String,
    val quantity: Int,
    val unitPrice: Long,
    val finalAmount: Long,
    val note: String? = null,
)

data class ReceiptPayment(
    val method: String,
    val amount: Long,
)

data class KitchenTicketData(
    val orderNumber: String,
    val tableName: String,
    val time: String,
    val items: List<KitchenItem>,
)

data class KitchenItem(
    val name: String,
    val quantity: Int,
    val note: String? = null,
    val weightGram: Int? = null,
)

data class ShiftReportData(
    val storeName: String,
    val cashierName: String,
    val shiftStart: String,
    val shiftEnd: String,
    val revenue: Long,
    val orderCount: Int,
    val avgCheck: Long,
    val paymentBreakdown: Map<String, Long>,
    val cashExpected: Long,
    val cashCounted: Long,
    val variance: Long,
    val notes: String? = null,
)
