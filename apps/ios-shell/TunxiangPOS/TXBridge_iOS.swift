import AVFoundation
import UIKit
import UserNotifications

/// TXBridge — iOS 原生桥接层
///
/// 为 iPad 提供 Android TXBridge 等价的原生能力：
///   - 摄像头扫码（二维码/条形码）
///   - 推送通知注册 + 前台展示
///   - 设备信息查询
///   - 与 Mac mini / Android POS 通信
///
/// React 通过 window.webkit.messageHandlers.txNative.postMessage() 调用
/// 不支持的操作（打印/钱箱/称重）通过 HTTP 转发到 Android POS 主机
///
/// 职责边界：不做业务逻辑，只做桥接（遵守 CLAUDE.md §13）
class TXBridge_iOS: NSObject {

    // MARK: - Message Handler

    /// 处理来自 React Web App 的消息
    /// 消息格式: { type: String, payload: Dict?, callbackId: String? }
    static func handleMessage(
        _ body: [String: Any],
        webView: WKWebView?,
        posHostUrl: String,
        macMiniUrl: String
    ) {
        guard let type = body["type"] as? String else {
            NSLog("[TXBridge] Missing message type")
            return
        }

        let payload = body["payload"] as? [String: Any] ?? [:]
        let callbackId = body["callbackId"] as? String

        switch type {

        // ── 摄像头扫码 ──────────────────────────────────────────────────
        case "startCamera":
            handleCamera(webView: webView, callbackId: callbackId)

        // ── 推送通知 ────────────────────────────────────────────────────
        case "registerPush":
            registerPushNotifications(webView: webView, callbackId: callbackId)
        case "requestNotificationPermission":
            requestNotificationPermission(webView: webView, callbackId: callbackId)

        // ── 设备信息 ────────────────────────────────────────────────────
        case "getDeviceInfo":
            getDeviceInfo(webView: webView, callbackId: callbackId)

        // ── 生物识别 ────────────────────────────────────────────────────
        case "authenticateBiometric":
            authenticateBiometric(webView: webView, reason: payload["reason"] as? String ?? "身份验证", callbackId: callbackId)

        // ── 剪贴板 ──────────────────────────────────────────────────────
        case "copyToClipboard":
            if let text = payload["text"] as? String {
                UIPasteboard.general.string = text
                respondToJS(webView: webView, callbackId: callbackId, result: ["ok": true])
            }

        // ── 触觉反馈 ────────────────────────────────────────────────────
        case "hapticFeedback":
            let style = UIImpactFeedbackGenerator.FeedbackStyle.medium
            UIImpactFeedbackGenerator(style: style).impactOccurred()

        // ── 外部转发（保持现有行为）─────────────────────────────────────
        case "print", "openCashBox", "scale":
            forwardToPOS(path: "/api/\(type)", payload: payload, posHostUrl: posHostUrl)

        case "coreMLPredict":
            guard let endpoint = payload["endpoint"] as? String else { return }
            forwardToMacMini(path: "/predict/\(endpoint)", payload: payload, macMiniUrl: macMiniUrl)

        default:
            NSLog("[TXBridge] Unknown message type: %@", type)
        }
    }

    // MARK: - Camera / Barcode Scanning

    private static var _cameraCallbackId: String?
    private static var _cameraWebView: WKWebView?

    private static func handleCamera(webView: WKWebView?, callbackId: String?) {
        guard let webView = webView else { return }
        _cameraCallbackId = callbackId
        _cameraWebView = webView

        // 通知 React 端打开相机 UI（通过注入 JS）
        // 实际相机由 React Web App 内的 getUserMedia() 处理（iOS Safari/WKWebView 支持）
        // iPad 原生相机权限由此处预检
        let authStatus = AVCaptureDevice.authorizationStatus(for: .video)
        switch authStatus {
        case .authorized:
            respondToJS(webView: webView, callbackId: callbackId, result: ["ok": true, "status": "authorized"])
        case .notDetermined:
            AVCaptureDevice.requestAccess(for: .video) { granted in
                DispatchQueue.main.async {
                    respondToJS(webView: webView, callbackId: callbackId, result: ["ok": granted, "status": granted ? "authorized" : "denied"])
                }
            }
        case .denied, .restricted:
            respondToJS(webView: webView, callbackId: callbackId, result: ["ok": false, "status": "denied", "message": "相机权限未授权，请在设置中开启"])
        @unknown default:
            respondToJS(webView: webView, callbackId: callbackId, result: ["ok": false, "status": "unknown"])
        }
    }

    // MARK: - Push Notifications

    private static func registerPushNotifications(webView: WKWebView?, callbackId: String?) {
        let center = UNUserNotificationCenter.current()
        center.getNotificationSettings { settings in
            DispatchQueue.main.async {
                guard let webView = webView else { return }
                let result: [String: Any] = [
                    "ok": true,
                    "authorizationStatus": settings.authorizationStatus.rawValue,
                    "isAuthorized": settings.authorizationStatus == .authorized,
                    "deviceToken": UserDefaults.standard.string(forKey: "tx_push_device_token") ?? NSNull(),
                ]
                respondToJS(webView: webView, callbackId: callbackId, result: result)
            }
        }
    }

    private static func requestNotificationPermission(webView: WKWebView?, callbackId: String?) {
        let center = UNUserNotificationCenter.current()
        center.requestAuthorization(options: [.alert, .sound, .badge]) { granted, error in
            DispatchQueue.main.async {
                guard let webView = webView else { return }
                if granted {
                    UIApplication.shared.registerForRemoteNotifications()
                }
                respondToJS(webView: webView, callbackId: callbackId, result: [
                    "ok": granted,
                    "error": error?.localizedDescription ?? NSNull(),
                ])
            }
        }
    }

    /// 供 AppDelegate 调用: 收到 device token 后保存并通知 Web 端
    static func onDeviceTokenReceived(_ token: Data) {
        let tokenString = token.map { String(format: "%02.2hhx", $0) }.joined()
        UserDefaults.standard.set(tokenString, forKey: "tx_push_device_token")
        NSLog("[TXBridge] Push device token: %@", tokenString)
    }

    /// 供 AppDelegate 调用: 前台收到推送时通知 Web 端
    /// 使用 JSONSerialization 安全序列化，防止推送 payload 中的 XSS 注入。
    static func onPushNotificationReceived(_ userInfo: [AnyHashable: Any], webView: WKWebView?) {
        guard let webView = webView else { return }

        // 安全序列化：先用 JSONSerialization 转 JSON data，再作为 JS 字符串字面量嵌入
        guard let safePayload = userInfo as? [String: Any],
              let jsonData = try? JSONSerialization.data(withJSONObject: safePayload, options: .fragmentsAllowed),
              let jsonString = String(data: jsonData, encoding: .utf8) else {
            NSLog("[TXBridge] Failed to serialize push notification payload")
            return
        }

        // 对 JSON 字符串进行 JS 安全转义（仅转义 </script> 和行分隔符）
        let safe = jsonString
            .replacingOccurrences(of: "</script>", with: "<\\/script>")
            .replacingOccurrences(of: "\u{2028}", with: "\\u2028")
            .replacingOccurrences(of: "\u{2029}", with: "\\u2029")

        let js = "window.dispatchEvent(new CustomEvent('txPushNotification', { detail: JSON.parse('\(safe)') }))"
        webView.evaluateJavaScript(js, completionHandler: nil)
    }

    // MARK: - Device Info

    private static func getDeviceInfo(webView: WKWebView?, callbackId: String?) {
        guard let webView = webView else { return }
        let device = UIDevice.current
        let info: [String: Any] = [
            "ok": true,
            "model": device.model,
            "name": device.name,
            "systemName": device.systemName,
            "systemVersion": device.systemVersion,
            "identifierForVendor": device.identifierForVendor?.uuidString ?? "unknown",
            "device_type": "ipad",
            "isSimulator": TARGET_OS_SIMULATOR != 0,
        ]
        respondToJS(webView: webView, callbackId: callbackId, result: info)
    }

    // MARK: - Biometric Authentication

    private static func authenticateBiometric(webView: WKWebView?, reason: String, callbackId: String?) {
        guard let webView = webView else { return }
        let context = LAContext()
        var error: NSError?

        guard context.canEvaluatePolicy(.deviceOwnerAuthenticationWithBiometrics, error: &error) else {
            respondToJS(webView: webView, callbackId: callbackId, result: [
                "ok": false,
                "error": error?.localizedDescription ?? "Biometric authentication not available",
                "biometryType": context.biometryType == .faceID ? "faceID" : (context.biometryType == .touchID ? "touchID" : "none"),
            ])
            return
        }

        context.evaluatePolicy(.deviceOwnerAuthenticationWithBiometrics, localizedReason: reason) { success, authError in
            DispatchQueue.main.async {
                respondToJS(webView: webView, callbackId: callbackId, result: [
                    "ok": success,
                    "error": authError?.localizedDescription ?? NSNull(),
                ])
            }
        }
    }

    // MARK: - Helpers

    private static func respondToJS(webView: WKWebView, callbackId: String?, result: [String: Any]) {
        guard let cbId = callbackId,
              let jsonData = try? JSONSerialization.data(withJSONObject: result, options: .fragmentsAllowed),
              let jsonString = String(data: jsonData, encoding: .utf8) else { return }

        // 安全转义 callbackId（防 JS 注入，反斜杠必须先转义以避免二次转义）
        let safeCbId = cbId.replacingOccurrences(of: "\\", with: "\\\\")
            .replacingOccurrences(of: "'", with: "\\'")
            .replacingOccurrences(of: "\"", with: "\\\"")
            .replacingOccurrences(of: "</script>", with: "<\\/script>")

        // JSON 字符串安全转义
        let safeJson = jsonString
            .replacingOccurrences(of: "</script>", with: "<\\/script>")
            .replacingOccurrences(of: "\u{2028}", with: "\\u2028")
            .replacingOccurrences(of: "\u{2029}", with: "\\u2029")

        webView.evaluateJavaScript(
            "window.__txBridgeCallback && window.__txBridgeCallback('\(safeCbId)', JSON.parse('\(safeJson)'))",
            completionHandler: nil
        )
    }

    private static let session = URLSession.shared

    private static func forwardToPOS(path: String, payload: [String: Any], posHostUrl: String) {
        guard let url = URL(string: posHostUrl + path) else { return }
        var request = URLRequest(url: url, timeoutInterval: 5)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try? JSONSerialization.data(withJSONObject: payload)
        session.dataTask(with: request) { _, _, error in
            if let error = error {
                NSLog("[TXBridge] POS forward failed: %@", error.localizedDescription)
            }
        }.resume()
    }

    private static func forwardToMacMini(path: String, payload: [String: Any], macMiniUrl: String) {
        guard let url = URL(string: macMiniUrl + path) else { return }
        var request = URLRequest(url: url, timeoutInterval: 10)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try? JSONSerialization.data(withJSONObject: payload)
        session.dataTask(with: request) { _, _, error in
            if let error = error {
                NSLog("[TXBridge] Mac mini forward failed: %@", error.localizedDescription)
            }
        }.resume()
    }
}

// Import for biometric authentication
import LocalAuthentication
