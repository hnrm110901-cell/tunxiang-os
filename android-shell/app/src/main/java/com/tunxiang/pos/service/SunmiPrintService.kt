package com.tunxiang.pos.service

import android.content.Context
import android.util.Log
import java.util.concurrent.ConcurrentLinkedQueue

/**
 * SunmiPrintService -- 商米打印 SDK 封装
 *
 * 职责：
 * 1. 封装商米 InnerPrinterManager AIDL 调用
 * 2. ESC/POS 指令生成与发送
 * 3. 外接 USB 打印机支持（降级方案）
 * 4. 打印队列管理（避免并发打印冲突）
 *
 * 商米 SDK 文档：https://developer.sunmi.com/docs/zh-CN/
 * 本类不含业务逻辑，仅做 SDK 桥接。
 */
class SunmiPrintService(private val context: Context) {

    companion object {
        private const val TAG = "SunmiPrintService"
    }

    /** 打印机是否已连接绑定 */
    private var isBound = false

    /** 打印队列：先进先出，保证打印顺序 */
    private val printQueue = ConcurrentLinkedQueue<PrintJob>()

    /** 当前是否正在打印 */
    @Volatile
    private var isPrinting = false

    // ── 生命周期 ─────────────────────────────────────────────────────────

    /**
     * 绑定商米打印服务。在 Activity.onCreate 中调用。
     */
    fun bindService() {
        Log.d(TAG, "bindService() called")
        try {
            // TODO: 接入商米 InnerPrinterManager AIDL
            // InnerPrinterManager.getInstance().bindService(context, object : InnerPrinterCallback() {
            //     override fun onConnected(service: SunmiPrinterService) {
            //         isBound = true
            //         Log.d(TAG, "Printer service connected")
            //         processPrintQueue()
            //     }
            //     override fun onDisconnected() {
            //         isBound = false
            //         Log.w(TAG, "Printer service disconnected")
            //     }
            // })
            isBound = true // 开发模式模拟
            Log.d(TAG, "bindService() -> 商米打印 SDK 待接入")
        } catch (e: SecurityException) {
            Log.e(TAG, "bindService() 权限不足: ${e.message}", e)
        } catch (e: IllegalStateException) {
            Log.e(TAG, "bindService() 服务状态异常: ${e.message}", e)
        }
    }

    /**
     * 解绑商米打印服务。在 Activity.onDestroy 中调用。
     */
    fun unbindService() {
        Log.d(TAG, "unbindService() called")
        try {
            // TODO: InnerPrinterManager.getInstance().unBindService(context, callback)
            isBound = false
            printQueue.clear()
            Log.d(TAG, "unbindService() -> 已解绑")
        } catch (e: IllegalStateException) {
            Log.e(TAG, "unbindService() 异常: ${e.message}", e)
        }
    }

    // ── 打印接口 ─────────────────────────────────────────────────────────

    /**
     * 提交打印任务。自动入队，按顺序执行。
     *
     * @param content ESC/POS 格式内容或 JSON 打印指令
     * @param type 打印类型（receipt=小票, kitchen=厨房单, label=标签）
     */
    fun print(content: String, type: PrintType = PrintType.RECEIPT) {
        Log.d(TAG, "print() enqueue, type=$type, length=${content.length}")
        printQueue.offer(PrintJob(content, type))
        processPrintQueue()
    }

    /**
     * 打开钱箱（通过打印机 ESC 指令驱动）。
     * 商米 T2 钱箱通过打印机端口的 ESC 指令控制。
     */
    fun openCashDrawer() {
        Log.d(TAG, "openCashDrawer() called")
        try {
            // TODO: 商米 T2 钱箱开启指令
            // sunmiPrinterService.sendRAWData(byteArrayOf(0x1B, 0x70, 0x00, 0x19, 0xFA), null)
            Log.d(TAG, "openCashDrawer() -> ESC 指令: 1B 70 00 19 FA，商米 SDK 待接入")
        } catch (e: SecurityException) {
            Log.e(TAG, "openCashDrawer() 权限不足: ${e.message}", e)
        } catch (e: IllegalStateException) {
            Log.e(TAG, "openCashDrawer() 打印机未就绪: ${e.message}", e)
        }
    }

    // ── 队列处理 ─────────────────────────────────────────────────────────

    /**
     * 处理打印队列：依次取出任务发送到打印机。
     * 使用 synchronized 防止并发调用。
     */
    @Synchronized
    private fun processPrintQueue() {
        if (isPrinting || printQueue.isEmpty()) return
        if (!isBound) {
            Log.w(TAG, "processPrintQueue() printer not bound, waiting...")
            return
        }

        isPrinting = true
        val job = printQueue.poll()
        if (job != null) {
            executePrint(job)
        }
        isPrinting = false

        // 递归处理剩余队列
        if (printQueue.isNotEmpty()) {
            processPrintQueue()
        }
    }

    /**
     * 执行单个打印任务。
     */
    private fun executePrint(job: PrintJob) {
        Log.d(TAG, "executePrint() type=${job.type}, length=${job.content.length}")
        try {
            when (job.type) {
                PrintType.RECEIPT -> printReceipt(job.content)
                PrintType.KITCHEN -> printKitchen(job.content)
                PrintType.LABEL -> printLabel(job.content)
            }
        } catch (e: SecurityException) {
            Log.e(TAG, "executePrint() 权限不足: ${e.message}", e)
        } catch (e: IllegalStateException) {
            Log.e(TAG, "executePrint() 打印失败: ${e.message}", e)
        }
    }

    /**
     * 打印小票。80mm 热敏纸。
     */
    private fun printReceipt(content: String) {
        // TODO: 商米 AIDL 打印小票
        // sunmiPrinterService.printerInit(null)
        // sunmiPrinterService.setAlignment(1, null)  // 居中
        // sunmiPrinterService.printText(content, null)
        // sunmiPrinterService.lineWrap(3, null)       // 走纸3行
        // sunmiPrinterService.cutPaper(null)           // 切纸
        Log.d(TAG, "printReceipt() -> 商米小票打印 SDK 待接入")
    }

    /**
     * 打印厨房单。58mm 热敏纸，大字号。
     */
    private fun printKitchen(content: String) {
        // TODO: 商米 AIDL 打印厨房单
        // sunmiPrinterService.printerInit(null)
        // sunmiPrinterService.setFontSize(32f, null)   // 大字号
        // sunmiPrinterService.printText(content, null)
        // sunmiPrinterService.lineWrap(4, null)
        // sunmiPrinterService.cutPaper(null)
        Log.d(TAG, "printKitchen() -> 商米厨房单打印 SDK 待接入")
    }

    /**
     * 打印标签。适用于称重商品贴标。
     */
    private fun printLabel(content: String) {
        // TODO: 商米标签打印
        Log.d(TAG, "printLabel() -> 商米标签打印 SDK 待接入")
    }

    // ── USB 外接打印机（降级） ───────────────────────────────────────────

    /**
     * 通过 USB 连接外接打印机（当商米内置打印机不可用时）。
     * 使用 ESC/POS 标准协议。
     */
    fun printViaUsb(content: String) {
        Log.d(TAG, "printViaUsb() called, length=${content.length}")
        // TODO: USB Host API 连接外接打印机
        // val usbManager = context.getSystemService(Context.USB_SERVICE) as UsbManager
        // 查找 ESC/POS 兼容打印机 -> 发送原始字节
        Log.d(TAG, "printViaUsb() -> USB 打印待实现")
    }

    // ── 内部类 ───────────────────────────────────────────────────────────

    /** 打印任务 */
    data class PrintJob(
        val content: String,
        val type: PrintType
    )

    /** 打印类型 */
    enum class PrintType {
        RECEIPT,    // 小票（80mm）
        KITCHEN,    // 厨房单（58mm，大字号）
        LABEL       // 标签（称重贴标）
    }
}
