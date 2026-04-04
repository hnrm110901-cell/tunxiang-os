package com.tunxiang.pos.config

import android.content.Context
import android.content.SharedPreferences
import android.net.nsd.NsdManager
import android.net.nsd.NsdServiceInfo
import android.os.Build
import android.util.Log

/**
 * AppConfig -- 屯象 POS 壳层应用配置
 *
 * 职责：
 * 1. 管理 WebView 加载地址（Mac mini 本地 -> 云端降级）
 * 2. mDNS 发现局域网内 Mac mini
 * 3. 商米设备型号检测（T2/V2）
 *
 * 本类不含业务逻辑，仅做配置管理。
 */
object AppConfig {

    private const val TAG = "AppConfig"
    private const val PREFS_NAME = "tx_pos_config"
    private const val KEY_MAC_MINI_URL = "mac_mini_url"
    private const val KEY_CLOUD_URL = "cloud_url"

    // ── 默认地址 ───────────────────────────────────────────────────────────
    /** Mac mini 本地 React Web App 地址（门店边缘服务器） */
    const val DEFAULT_WEB_APP_URL = "http://mac-mini.local:3000"

    /** Mac mini 本地 API 地址 */
    const val DEFAULT_MAC_MINI_API_URL = "http://mac-mini.local:8000"

    /** 云端降级地址（Mac mini 不可达时回退） */
    const val DEFAULT_CLOUD_URL = "https://pos.tunxiang.com"

    /** 离线回退：从 assets 加载 */
    const val OFFLINE_FALLBACK_URL = "file:///android_asset/index.html"

    /** mDNS 服务类型（Mac mini 注册的服务） */
    private const val MDNS_SERVICE_TYPE = "_txpos._tcp."

    // ── 商米机型常量 ─────────────────────────────────────────────────────
    const val MODEL_SUNMI_T2 = "T2"
    const val MODEL_SUNMI_V2 = "V2"
    private val SUPPORTED_MODELS = setOf(MODEL_SUNMI_T2, MODEL_SUNMI_V2)

    private lateinit var prefs: SharedPreferences

    /**
     * 初始化配置，在 Application.onCreate 或 MainActivity.onCreate 中调用。
     */
    fun init(context: Context) {
        prefs = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
        Log.d(TAG, "AppConfig initialized, device=${getDeviceModel()}")
    }

    // ── WebView 加载地址 ─────────────────────────────────────────────────

    /**
     * 获取 WebView 应加载的 URL。
     * 优先级：SharedPreferences 配置 > 默认 Mac mini 地址
     */
    fun getWebAppUrl(): String {
        return prefs.getString(KEY_MAC_MINI_URL, DEFAULT_WEB_APP_URL)
            ?: DEFAULT_WEB_APP_URL
    }

    /**
     * 获取 Mac mini API 地址。
     */
    fun getMacMiniApiUrl(): String {
        val webUrl = getWebAppUrl()
        // 从 web URL 推导 API URL（端口 3000 -> 8000）
        return webUrl.replace(":3000", ":8000")
    }

    /**
     * 获取云端降级地址。
     */
    fun getCloudUrl(): String {
        return prefs.getString(KEY_CLOUD_URL, DEFAULT_CLOUD_URL)
            ?: DEFAULT_CLOUD_URL
    }

    /**
     * 运维手动设置 Mac mini 地址（如局域网 IP 固定分配）。
     */
    fun setMacMiniUrl(url: String) {
        prefs.edit().putString(KEY_MAC_MINI_URL, url).apply()
        Log.d(TAG, "Mac mini URL updated: $url")
    }

    // ── mDNS 发现 ────────────────────────────────────────────────────────

    /**
     * 通过 mDNS 发现局域网内的 Mac mini。
     * 发现成功后自动更新 SharedPreferences 中的地址。
     *
     * @param context Android Context
     * @param onDiscovered 发现回调，返回 Mac mini 的 URL
     */
    fun discoverMacMini(context: Context, onDiscovered: (String) -> Unit) {
        val nsdManager = context.getSystemService(Context.NSD_SERVICE) as? NsdManager
        if (nsdManager == null) {
            Log.w(TAG, "NsdManager unavailable, skipping mDNS discovery")
            return
        }

        val listener = object : NsdManager.DiscoveryListener {
            override fun onDiscoveryStarted(serviceType: String) {
                Log.d(TAG, "mDNS discovery started for $serviceType")
            }

            override fun onServiceFound(serviceInfo: NsdServiceInfo) {
                Log.d(TAG, "mDNS service found: ${serviceInfo.serviceName}")
                nsdManager.resolveService(serviceInfo, object : NsdManager.ResolveListener {
                    override fun onResolveFailed(si: NsdServiceInfo, errorCode: Int) {
                        Log.w(TAG, "mDNS resolve failed: errorCode=$errorCode")
                    }

                    override fun onServiceResolved(si: NsdServiceInfo) {
                        val host = si.host?.hostAddress ?: return
                        val port = si.port
                        val url = "http://$host:$port"
                        Log.d(TAG, "mDNS resolved Mac mini: $url")
                        setMacMiniUrl(url)
                        onDiscovered(url)
                    }
                })
            }

            override fun onServiceLost(serviceInfo: NsdServiceInfo) {
                Log.w(TAG, "mDNS service lost: ${serviceInfo.serviceName}")
            }

            override fun onDiscoveryStopped(serviceType: String) {
                Log.d(TAG, "mDNS discovery stopped")
            }

            override fun onStartDiscoveryFailed(serviceType: String, errorCode: Int) {
                Log.e(TAG, "mDNS discovery start failed: errorCode=$errorCode")
            }

            override fun onStopDiscoveryFailed(serviceType: String, errorCode: Int) {
                Log.e(TAG, "mDNS discovery stop failed: errorCode=$errorCode")
            }
        }

        nsdManager.discoverServices(MDNS_SERVICE_TYPE, NsdManager.PROTOCOL_DNS_SD, listener)
    }

    // ── 商米设备检测 ─────────────────────────────────────────────────────

    /**
     * 获取设备型号。
     */
    fun getDeviceModel(): String = Build.MODEL

    /**
     * 获取设备制造商。
     */
    fun getDeviceManufacturer(): String = Build.MANUFACTURER

    /**
     * 是否为商米设备。
     */
    fun isSunmiDevice(): Boolean {
        return Build.MANUFACTURER.equals("SUNMI", ignoreCase = true)
    }

    /**
     * 是否为支持的商米 POS 机型（T2/V2）。
     */
    fun isSupportedModel(): Boolean {
        return isSunmiDevice() && SUPPORTED_MODELS.any { model ->
            Build.MODEL.contains(model, ignoreCase = true)
        }
    }

    /**
     * 是否为商米 T2（双屏收银机）。
     */
    fun isSunmiT2(): Boolean {
        return isSunmiDevice() && Build.MODEL.contains(MODEL_SUNMI_T2, ignoreCase = true)
    }

    /**
     * 是否为商米 V2（手持 POS）。
     */
    fun isSunmiV2(): Boolean {
        return isSunmiDevice() && Build.MODEL.contains(MODEL_SUNMI_V2, ignoreCase = true)
    }
}
