package com.tunxiang.pos.bridge

import android.util.Log
import android.webkit.JavascriptInterface
import com.tunxiang.pos.service.SunmiPrintService

/**
 * PrintBridge -- 打印桥接
 *
 * 将 JS Bridge 打印调用转发到 SunmiPrintService。
 * React Web App 通过 window.TXBridge.print() 调用本接口。
 *
 * 支持：
 * - ESC/POS 指令直接发送（React 层生成指令）
 * - JSON 格式打印指令（结构化内容，由本层转换为 ESC/POS）
 * - 打印队列管理（多笔连续打印不丢单）
 * - 外接 USB 打印机降级
 *
 * 本类不含业务逻辑。
 */
class PrintBridge(private val printService: SunmiPrintService) {

    companion object {
        private const val TAG = "PrintBridge"
    }

    // ── JS Bridge 方法 ──────────────────────────────────────────────────

    /**
     * 打印小票内容。
     *
     * @param content ESC/POS 格式字符串或 JSON 打印指令
     */
    @JavascriptInterface
    fun print(content: String) {
        Log.d(TAG, "print() called, length=${content.length}")
        try {
            if (content.startsWith("{")) {
                // JSON 格式：解析后按类型分发
                printFromJson(content)
            } else {
                // 原始 ESC/POS 字符串
                printService.print(content, SunmiPrintService.PrintType.RECEIPT)
            }
        } catch (e: IllegalArgumentException) {
            Log.e(TAG, "print() 内容格式错误: ${e.message}", e)
        } catch (e: IllegalStateException) {
            Log.e(TAG, "print() 打印服务不可用: ${e.message}", e)
        }
    }

    /**
     * 打印厨房单（大字号，走纸多）。
     *
     * @param content 厨房单内容
     */
    @JavascriptInterface
    fun printKitchen(content: String) {
        Log.d(TAG, "printKitchen() called, length=${content.length}")
        try {
            printService.print(content, SunmiPrintService.PrintType.KITCHEN)
        } catch (e: IllegalStateException) {
            Log.e(TAG, "printKitchen() 打印失败: ${e.message}", e)
        }
    }

    /**
     * 打印称重标签。
     *
     * @param content 标签内容
     */
    @JavascriptInterface
    fun printLabel(content: String) {
        Log.d(TAG, "printLabel() called, length=${content.length}")
        try {
            printService.print(content, SunmiPrintService.PrintType.LABEL)
        } catch (e: IllegalStateException) {
            Log.e(TAG, "printLabel() 打印失败: ${e.message}", e)
        }
    }

    // ── JSON 格式解析 ────────────────────────────────────────────────────

    /**
     * 解析 JSON 打印指令并分发到对应打印类型。
     *
     * JSON 格式：
     * {
     *   "type": "receipt" | "kitchen" | "label",
     *   "content": "...",
     *   "copies": 1
     * }
     */
    private fun printFromJson(json: String) {
        try {
            val obj = org.json.JSONObject(json)
            val type = obj.optString("type", "receipt")
            val content = obj.optString("content", "")
            val copies = obj.optInt("copies", 1)

            if (content.isBlank()) {
                Log.w(TAG, "printFromJson() empty content, skipping")
                return
            }

            val printType = when (type) {
                "kitchen" -> SunmiPrintService.PrintType.KITCHEN
                "label" -> SunmiPrintService.PrintType.LABEL
                else -> SunmiPrintService.PrintType.RECEIPT
            }

            repeat(copies) {
                printService.print(content, printType)
            }

            Log.d(TAG, "printFromJson() type=$type, copies=$copies")
        } catch (e: org.json.JSONException) {
            Log.e(TAG, "printFromJson() JSON 解析失败: ${e.message}", e)
        }
    }
}
