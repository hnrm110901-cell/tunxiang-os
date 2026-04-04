package com.tunxiang.pos.bridge

import android.util.Log
import android.webkit.JavascriptInterface
import com.tunxiang.pos.service.SunmiPrintService

/**
 * CashBoxBridge -- 钱箱桥接
 *
 * 将 JS Bridge 钱箱调用转发到 SunmiPrintService（商米钱箱通过打印机端口驱动）。
 *
 * 商米 T2：钱箱连接打印机 RJ11 接口，通过 ESC/POS 指令弹开
 * 商米 V2：通过 Cash Drawer API 控制（V2 手持机一般不配钱箱）
 *
 * 本类不含业务逻辑。
 */
class CashBoxBridge(private val printService: SunmiPrintService) {

    companion object {
        private const val TAG = "CashBoxBridge"
    }

    // ── JS Bridge 方法 ──────────────────────────────────────────────────

    /**
     * 弹出钱箱。
     */
    @JavascriptInterface
    fun openCashBox() {
        Log.d(TAG, "openCashBox() called")
        try {
            printService.openCashDrawer()
        } catch (e: SecurityException) {
            Log.e(TAG, "openCashBox() 权限不足: ${e.message}", e)
        } catch (e: IllegalStateException) {
            Log.e(TAG, "openCashBox() 打印机未就绪（钱箱依赖打印机端口）: ${e.message}", e)
        }
    }
}
