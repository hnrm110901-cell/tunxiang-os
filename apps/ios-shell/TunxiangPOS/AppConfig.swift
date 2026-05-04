import Foundation

/// 屯象OS iPad POS Shell 配置
///
/// 配置来源优先级（高到低）：
///   1. tunxiang-pos.plist（门店部署包内置）
///   2. UserDefaults（首次配置页交互写入）
///   3. Info.plist 环境变量（TX_* 键值，Xcode Scheme 注入）
///   4. 硬编码默认值（开发用）
///
/// 配置项：
///   - Web App URL（React web-pos 部署地址）
///   - POS 主机 URL（外设指令转发目标）
///   - Mac mini URL（边缘 AI 推理目标）
///   - 门店 ID（租户标识）
///   - 环境（dev / staging / prod）
///   - 首次配置标记
struct AppConfig {

    // MARK: - Keys

    private struct Key {
        static let appUrl = "app_url"
        static let posHostUrl = "pos_host_url"
        static let macMiniUrl = "mac_mini_url"
        static let storeId = "store_id"
        static let environment = "environment"
        static let isConfigured = "is_configured"
    }

    // MARK: - Storage

    private static let defaults = UserDefaults.standard

    /// 从 tunxiang-pos.plist 读取（Bundle 内嵌，门店部署包提供）
    private static var plistConfig: [String: Any]? {
        guard let path = Bundle.main.path(forResource: "tunxiang-pos", ofType: "plist"),
              let dict = NSDictionary(contentsOfFile: path) as? [String: Any] else {
            return nil
        }
        return dict
    }

    /// 从 tunxiang-pos.plist 读取单个值
    private static func plistValue(for key: String) -> String? {
        return plistConfig?[key] as? String
    }

    // MARK: - Web App URL

    /// React web-pos 部署地址（Mac mini 本地或云端）
    static var appUrl: String {
        get {
            // 1. UserDefaults（首次配置页设置）
            if let stored = defaults.string(forKey: Key.appUrl), !stored.isEmpty {
                return stored
            }
            // 2. tunxiang-pos.plist
            if let plistVal = plistValue(for: Key.appUrl), !plistVal.isEmpty {
                return plistVal
            }
            // 3. Info.plist / 环境变量（Xcode Scheme）
            if let envVal = Bundle.main.infoDictionary?["TX_APP_URL"] as? String, !envVal.isEmpty {
                return envVal
            }
            // 4. 默认值（开发环境）
            return "http://192.168.1.100:8000"
        }
        set { defaults.set(newValue, forKey: Key.appUrl) }
    }

    // MARK: - POS Host URL

    /// Android POS 主机地址（外设指令 HTTP 转发目标）
    /// 打印/钱箱/称重/扫码指令通过此地址转发到 Android POS 主机执行
    static var posHostUrl: String {
        get {
            if let stored = defaults.string(forKey: Key.posHostUrl), !stored.isEmpty {
                return stored
            }
            if let plistVal = plistValue(for: Key.posHostUrl), !plistVal.isEmpty {
                return plistVal
            }
            return "http://192.168.1.10:8080"
        }
        set { defaults.set(newValue, forKey: Key.posHostUrl) }
    }

    // MARK: - Mac mini URL

    /// Mac mini 边缘智能后台地址
    /// Core ML 推理 / 本地 API / 数据同步均通过此地址访问
    static var macMiniUrl: String {
        get {
            if let stored = defaults.string(forKey: Key.macMiniUrl), !stored.isEmpty {
                return stored
            }
            if let plistVal = plistValue(for: Key.macMiniUrl), !plistVal.isEmpty {
                return plistVal
            }
            return "http://192.168.1.100:8000"
        }
        set { defaults.set(newValue, forKey: Key.macMiniUrl) }
    }

    // MARK: - Store ID

    /// 门店 ID（租户标识，用于 RLS 隔离 + 数据路由）
    /// 示例：xuji-hunan-001（徐记海鲜湖南总店）
    static var storeId: String {
        get {
            if let stored = defaults.string(forKey: Key.storeId), !stored.isEmpty {
                return stored
            }
            if let plistVal = plistValue(for: Key.storeId), !plistVal.isEmpty {
                return plistVal
            }
            return ""
        }
        set { defaults.set(newValue, forKey: Key.storeId) }
    }

    // MARK: - Environment

    enum Environment: String, CaseIterable {
        case dev = "dev"
        case staging = "staging"
        case prod = "prod"

        var displayName: String {
            switch self {
            case .dev: return "开发环境"
            case .staging: return "预发布"
            case .prod: return "生产环境"
            }
        }

        /// 环境对应 Info.plist 中的编译变量键名
        var bundleKeyPrefix: String {
            switch self {
            case .dev: return "TX_DEV_"
            case .staging: return "TX_STAGING_"
            case .prod: return "TX_PROD_"
            }
        }
    }

    /// 当前运行环境
    static var environment: Environment {
        get {
            if let raw = defaults.string(forKey: Key.environment),
               let env = Environment(rawValue: raw) {
                return env
            }
            if let plistRaw = plistValue(for: Key.environment),
               let env = Environment(rawValue: plistRaw) {
                return env
            }
            // 默认：Dev 环境
            return .dev
        }
        set { defaults.set(newValue.rawValue, forKey: Key.environment) }
    }

    /// 是否为生产环境
    static var isProduction: Bool {
        environment == .prod
    }

    // MARK: - Configuration State

    /// 是否已完成首次配置
    static var isConfigured: Bool {
        get { defaults.bool(forKey: Key.isConfigured) }
    }

    /// 标记已完成配置（关闭 SetupView）
    static func markConfigured() {
        defaults.set(true, forKey: Key.isConfigured)
    }

    /// 重置配置（用于门店设备重新部署）
    static func resetConfiguration() {
        defaults.removeObject(forKey: Key.appUrl)
        defaults.removeObject(forKey: Key.posHostUrl)
        defaults.removeObject(forKey: Key.macMiniUrl)
        defaults.removeObject(forKey: Key.storeId)
        defaults.removeObject(forKey: Key.environment)
        defaults.removeObject(forKey: Key.isConfigured)
    }

    // MARK: - Computed

    /// 当前设备型号标识
    static var deviceModel: String {
        var systemInfo = utsname()
        uname(&systemInfo)
        let machineMirror = Mirror(reflecting: systemInfo.machine)
        let identifier = machineMirror.children.reduce("") { identifier, element in
            guard let value = element.value as? Int8, value != 0 else { return identifier }
            return identifier + String(UnicodeScalar(UInt8(value)))
        }
        return identifier
    }

    /// 是否为 iPad（始终为 true，因为此代码仅在 iPad shell 中编译）
    static var isIPad: Bool {
        UIDevice.current.userInterfaceIdiom == .pad
    }

    /// 配置摘要（用于日志和调试）
    static var summary: String {
        """
        [TunxiangPOS Config]
          Web App URL : \(appUrl)
          POS Host    : \(posHostUrl)
          Mac mini    : \(macMiniUrl)
          Store ID    : \(storeId.isEmpty ? "(not set)" : storeId)
          Environment : \(environment.rawValue) (\(environment.displayName))
          Configured  : \(isConfigured ? "Yes" : "No")
          Device      : \(deviceModel)
        """
    }
}
