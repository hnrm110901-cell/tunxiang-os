package com.tunxiang.pos.bridge

import android.content.Context
import android.os.Build
import android.util.Log
import android.webkit.JavascriptInterface
import com.tunxiang.pos.config.AppConfig
import org.json.JSONObject

/**
 * DeviceInfoBridge -- 设备信息桥接
 *
 * 提供设备基础信息给 React Web App，用于：
 * - 设备注册（门店设备管理）
 * - 功能适配（T2 双屏 vs V2 手持）
 * - 故障排查（远程诊断）
 *
 * 本类不含业务逻辑。
 */
class DeviceInfoBridge(private val context: Context) {

    companion object {
        private const val TAG = "DeviceInfoBridge"
    }

    // ── JS Bridge 方法 ──────────────────────────────────────────────────

    /**
     * 返回设备基础信息 JSON。
     *
     * @return JSON 字符串：
     * {
     *   "model": "T2",
     *   "manufacturer": "SUNMI",
     *   "serial": "SN123456",
     *   "osVersion": "8.1.0",
     *   "sdkInt": 27,
     *   "isSunmi": true,
     *   "isSupported": true,
     *   "appVersion": "0.1.0"
     * }
     */
    @JavascriptInterface
    fun getDeviceInfo(): String {
        Log.d(TAG, "getDeviceInfo() called")
        return try {
            val info = JSONObject().apply {
                put("model", Build.MODEL)
                put("manufacturer", Build.MANUFACTURER)
                put("osVersion", Build.VERSION.RELEASE)
                put("sdkInt", Build.VERSION.SDK_INT)
                put("isSunmi", AppConfig.isSunmiDevice())
                put("isSupported", AppConfig.isSupportedModel())
                put("isSunmiT2", AppConfig.isSunmiT2())
                put("isSunmiV2", AppConfig.isSunmiV2())
                // TODO: 商米设备序列号（通过 SunmiDevice.getSerial()）
                put("serial", Build.SERIAL)  // API 28+ 需 READ_PHONE_STATE 权限
                // 应用版本
                try {
                    val pkgInfo = context.packageManager.getPackageInfo(context.packageName, 0)
                    put("appVersion", pkgInfo.versionName)
                    put("appVersionCode", pkgInfo.longVersionCode)
                } catch (e: android.content.pm.PackageManager.NameNotFoundException) {
                    put("appVersion", "unknown")
                }
            }
            Log.d(TAG, "getDeviceInfo() -> $info")
            info.toString()
        } catch (e: SecurityException) {
            Log.e(TAG, "getDeviceInfo() 权限不足: ${e.message}", e)
            errorJson("permission_denied", e.message)
        } catch (e: RuntimeException) {
            Log.e(TAG, "getDeviceInfo() 异常: ${e.message}", e)
            errorJson("runtime_error", e.message)
        }
    }

    /**
     * 返回 Mac mini 局域网地址。
     */
    @JavascriptInterface
    fun getMacMiniUrl(): String {
        Log.d(TAG, "getMacMiniUrl() called")
        val url = AppConfig.getMacMiniApiUrl()
        Log.d(TAG, "getMacMiniUrl() -> $url")
        return url
    }

    // ── 辅助 ────────────────────────────────────────────────────────────

    private fun errorJson(code: String, message: String?): String {
        return JSONObject().apply {
            put("error", code)
            put("message", message ?: "unknown")
        }.toString()
    }
}
