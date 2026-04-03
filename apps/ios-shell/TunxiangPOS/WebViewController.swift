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
                NSLog("TXiOS: unknown message type: %@", type)
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
            <html><body style="display:flex;align-items:center;justify-content:center;
            height:100vh;font-family:-apple-system,sans-serif;background:#f5f5f7;">
            <div style="text-align:center;color:#1d1d1f">
              <div style="font-size:48px;margin-bottom:16px">⏳</div>
              <h2 style="font-size:24px;font-weight:600">连接门店服务器中</h2>
              <p style="color:#6e6e73">请确认 Mac mini 和 POS 主机已开机</p>
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
