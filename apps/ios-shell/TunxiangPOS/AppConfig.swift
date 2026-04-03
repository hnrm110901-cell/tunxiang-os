import Foundation

/// 应用配置 — 从 UserDefaults 读取，支持首次启动配置页
struct AppConfig {
    private static let defaults = UserDefaults.standard

    static var appUrl: String {
        get { defaults.string(forKey: "app_url") ?? defaultAppUrl }
        set { defaults.set(newValue, forKey: "app_url") }
    }

    static var posHostUrl: String {
        get { defaults.string(forKey: "pos_host_url") ?? "http://192.168.1.10:8080" }
        set { defaults.set(newValue, forKey: "pos_host_url") }
    }

    static var macMiniUrl: String {
        get { defaults.string(forKey: "mac_mini_url") ?? "http://192.168.1.100:8000" }
        set { defaults.set(newValue, forKey: "mac_mini_url") }
    }

    static var isConfigured: Bool {
        defaults.bool(forKey: "is_configured")
    }

    static func markConfigured() {
        defaults.set(true, forKey: "is_configured")
    }

    private static var defaultAppUrl: String {
        Bundle.main.infoDictionary?["TX_APP_URL"] as? String ?? "http://192.168.1.100:8000"
    }
}
