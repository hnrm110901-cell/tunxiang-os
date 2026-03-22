/// TunxiangOS iPad POS Shell — WKWebView 壳层
///
/// 规则：
/// - 不写业务逻辑，只做 WebView 加载
/// - 不连接任何外设
/// - 打印/称重等指令通过 HTTP 发送到安卓 POS 主机执行
/// - 安卓 POS 断开时降级为"仅查看"模式

import SwiftUI
import WebKit

struct ContentView: View {
    var body: some View {
        POSWebView()
            .ignoresSafeArea()
    }
}

struct POSWebView: UIViewRepresentable {
    // Mac mini 本地 API 地址（同时也是 web-pos 的服务地址）
    let webAppURL = ProcessInfo.processInfo.environment["WEB_POS_URL"]
        ?? "http://192.168.1.100:5173"

    func makeUIView(context: Context) -> WKWebView {
        let config = WKWebViewConfiguration()
        config.allowsInlineMediaPlayback = true

        let webView = WKWebView(frame: .zero, configuration: config)
        webView.scrollView.bounces = false
        webView.isOpaque = false

        if let url = URL(string: webAppURL) {
            webView.load(URLRequest(url: url))
        }

        return webView
    }

    func updateUIView(_ uiView: WKWebView, context: Context) {}
}

#Preview {
    ContentView()
}
