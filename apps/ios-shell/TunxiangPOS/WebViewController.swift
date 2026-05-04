import SwiftUI
import WebKit

/// WKWebView 壳层 — 加载 React Web App
/// iPad 职责：纯显示 + 触控，不连任何外设
/// 外设指令通过 HTTP 转发到 Android POS 主机执行
struct WebViewController: UIViewRepresentable {
    let url: URL
    let posHostUrl: String   // Android POS 主机地址，用于转发外设指令
    let macMiniUrl: String   // Mac mini 地址，用于 AI 推理

    func makeCoordinator() -> Coordinator {
        Coordinator(posHostUrl: posHostUrl, macMiniUrl: macMiniUrl)
    }

    func makeUIView(context: Context) -> WKWebView {
        let config = WKWebViewConfiguration()
        let contentController = WKUserContentController()

        // 注入 iPad 环境标识（让 React App 知道是 iPad，无 TXBridge）
        let ipadScript = WKUserScript(
            source: """
                window.__TUNXIANG_PLATFORM__ = 'ipad';
                window.__POS_HOST_URL__ = '\(posHostUrl)';
                window.__MAC_MINI_URL__ = '\(macMiniUrl)';
                window.__STORE_ID__ = '\(AppConfig.storeId)';
                window.__ENVIRONMENT__ = '\(AppConfig.environment.rawValue)';
            """,
            injectionTime: .atDocumentStart,
            forMainFrameOnly: true
        )
        contentController.addUserScript(ipadScript)
        contentController.add(context.coordinator, name: "txNative")

        config.userContentController = contentController
        config.allowsInlineMediaPlayback = true
        config.mediaTypesRequiringUserActionForPlayback = []

        let webView = WKWebView(frame: .zero, configuration: config)
        webView.navigationDelegate = context.coordinator
        webView.uiDelegate = context.coordinator
        webView.allowsBackForwardNavigationGestures = false
        webView.scrollView.bounces = false
        webView.scrollView.pinchGestureRecognizer?.isEnabled = false

        webView.load(URLRequest(url: url))
        return webView
    }

    func updateUIView(_ uiView: WKWebView, context: Context) {}

    // ─── Coordinator ──────────────────────────────────────────────────────────

    class Coordinator: NSObject, WKNavigationDelegate, WKUIDelegate, WKScriptMessageHandler {
        let posHostUrl: String
        let macMiniUrl: String
        private let session = URLSession.shared

        init(posHostUrl: String, macMiniUrl: String) {
            self.posHostUrl = posHostUrl
            self.macMiniUrl = macMiniUrl
        }

        // React 通过 window.webkit.messageHandlers.txNative.postMessage({type, payload})
        func userContentController(
            _ userContentController: WKUserContentController,
            didReceive message: WKScriptMessage
        ) {
            guard let body = message.body as? [String: Any],
                  let type = body["type"] as? String else { return }

            let payload = body["payload"] as? [String: Any] ?? [:]

            // 使用新的 TXBridge_iOS 统一处理（Phase C4）
            TXBridge_iOS.handleMessage(
                body,
                webView: message.webView,
                posHostUrl: posHostUrl,
                macMiniUrl: macMiniUrl
            )

            // 保持向后兼容：原有映射继续工作
            switch type {
            case "print":
                forwardToPOS(path: "/api/print", payload: payload)
            case "openCashBox":
                forwardToPOS(path: "/api/cash-box/open", payload: [:])
            case "scan":
                forwardToPOS(path: "/api/scan/trigger", payload: [:])
            case "coreMLPredict":
                guard let endpoint = payload["endpoint"] as? String else { return }
                forwardToMacMini(path: "/predict/\(endpoint)", payload: payload)
            default:
                break  // TXBridge_iOS 已处理
            }
        }

        private func forwardToPOS(path: String, payload: [String: Any]) {
            guard let url = URL(string: posHostUrl + path) else { return }
            var request = URLRequest(url: url, timeoutInterval: 5)
            request.httpMethod = "POST"
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
            request.httpBody = try? JSONSerialization.data(withJSONObject: payload)
            session.dataTask(with: request) { _, _, error in
                if let error = error {
                    NSLog("TXiOS: POS forward failed: %@", error.localizedDescription)
                }
            }.resume()
        }

        private func forwardToMacMini(path: String, payload: [String: Any]) {
            guard let url = URL(string: macMiniUrl + path) else { return }
            var request = URLRequest(url: url, timeoutInterval: 10)
            request.httpMethod = "POST"
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
            request.httpBody = try? JSONSerialization.data(withJSONObject: payload)
            session.dataTask(with: request) { _, _, error in
                if let error = error {
                    NSLog("TXiOS: Mac mini forward failed: %@", error.localizedDescription)
                }
            }.resume()
        }

        func webView(_ webView: WKWebView, didFail navigation: WKNavigation!, withError error: Error) {
            NSLog("TXiOS: navigation failed: %@", error.localizedDescription)
            let html = """
            <!DOCTYPE html>
            <html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
            <style>
              * { margin:0; padding:0; box-sizing:border-box; }
              body { display:flex; align-items:center; justify-content:center;
                     height:100vh; font-family:-apple-system,BlinkMacSystemFont,sans-serif;
                     background:#0B1A20; color:#cccccc; }
              .container { text-align:center; padding:40px; max-width:480px; }
              .icon { font-size:64px; margin-bottom:24px; color:#FF6B35; }
              h2 { font-size:24px; font-weight:600; color:#ffffff; margin-bottom:12px; }
              p { font-size:15px; color:#999999; margin-bottom:8px; line-height:1.5; }
              .info { margin-top:32px; padding:16px; background:#112228; border-radius:12px;
                      font-size:13px; color:#666666; }
              .info span { display:block; margin-bottom:4px; }
              .brand { color:#FF6B35; font-weight:600; }
            </style></head><body>
            <div class="container">
              <div class="icon">&#x1F4E6;</div>
              <h2>连接门店服务器中</h2>
              <p>请确认 Mac mini 和 POS 主机已开机</p>
              <p>且与 iPad 在同一 WiFi 网络</p>
              <div class="info">
                <span>POS 主机: \(posHostUrl)</span>
                <span>Mac mini: \(macMiniUrl)</span>
                <span class="brand">屯象OS</span>
              </div>
            </div></body></html>
            """
            webView.loadHTMLString(html, baseURL: nil)
        }

        func webView(_ webView: WKWebView, didFailProvisionalNavigation nav: WKNavigation!, withError error: Error) {
            self.webView(webView, didFail: nav, withError: error)
        }

        // 防止 JS alert 阻塞 UI
        func webView(_ webView: WKWebView, runJavaScriptAlertPanelWithMessage message: String,
                     initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping () -> Void) {
            NSLog("TXiOS: JS alert: %@", message)
            completionHandler()
        }
    }
}
