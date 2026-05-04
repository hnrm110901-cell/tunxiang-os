/// TunxiangOS iPad App Entry Point
import SwiftUI
import UserNotifications

@main
struct TunxiangPOSApp: App {

    init() {
        // 注册推送通知代理（前台展示 + 设备 token）
        UNUserNotificationCenter.current().delegate = PushNotificationDelegate.shared
        UIApplication.shared.registerForRemoteNotifications()
    }

    var body: some Scene {
        WindowGroup {
            ContentView()
                .preferredColorScheme(.dark)
        }
    }
}

// MARK: - Push Notification Delegate

final class PushNotificationDelegate: NSObject, UNUserNotificationCenterDelegate {
    static let shared = PushNotificationDelegate()

    /// 前台收到推送时展示 banner
    func userNotificationCenter(
        _ center: UNUserNotificationCenter,
        willPresent notification: UNNotification,
        withCompletionHandler completionHandler: @escaping (UNNotificationPresentationOptions) -> Void
    ) {
        if #available(iOS 14.0, *) {
            completionHandler([.banner, .sound, .badge])
        } else {
            completionHandler([.alert, .sound, .badge])
        }

        // 通知 Web 端
        let userInfo = notification.request.content.userInfo
        let webView = WebViewStore.shared.webView
        TXBridge_iOS.onPushNotificationReceived(userInfo, webView: webView)
    }

    /// 用户点击推送通知时打开对应页面
    func userNotificationCenter(
        _ center: UNUserNotificationCenter,
        didReceive response: UNNotificationResponse,
        withCompletionHandler completionHandler: @escaping () -> Void
    ) {
        let userInfo = response.notification.request.content.userInfo
        if let route = userInfo["route"] as? String {
            WebViewStore.shared.pendingPushRoute = route
        }
        completionHandler()
    }
}

// MARK: - WebView 引用单例

/// 轻量级单例：让 AppDelegate 能拿到当前的 WKWebView 引用
final class WebViewStore {
    static let shared = WebViewStore()
    weak var webView: WKWebView?
    var pendingPushRoute: String?

    private init() {}
}
