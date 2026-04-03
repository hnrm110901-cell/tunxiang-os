/// TunxiangOS iPad Shell — WKWebView + 首次配置页
///
/// 规则：不写业务逻辑，只做 WebView 加载
/// 不连任何外设。打印/扫码指令 HTTP 转发到安卓 POS。

import SwiftUI

struct ContentView: View {
    @State private var showSetup = !AppConfig.isConfigured

    var body: some View {
        if showSetup {
            SetupView(onComplete: { showSetup = false })
        } else {
            WebViewController(
                url: URL(string: AppConfig.appUrl)!,
                posHostUrl: AppConfig.posHostUrl,
                macMiniUrl: AppConfig.macMiniUrl
            )
            .ignoresSafeArea()
            .statusBar(hidden: true)
        }
    }
}

/// 首次启动配置页 — 填写服务器地址
struct SetupView: View {
    @State private var appUrl = AppConfig.appUrl
    @State private var posHostUrl = AppConfig.posHostUrl
    @State private var macMiniUrl = AppConfig.macMiniUrl
    var onComplete: () -> Void

    var body: some View {
        NavigationView {
            Form {
                Section(header: Text("门店服务器")) {
                    TextField("Web App 地址", text: $appUrl)
                        .keyboardType(.URL).autocapitalization(.none)
                    TextField("POS 主机地址（外设转发）", text: $posHostUrl)
                        .keyboardType(.URL).autocapitalization(.none)
                    TextField("Mac mini 地址（AI推理）", text: $macMiniUrl)
                        .keyboardType(.URL).autocapitalization(.none)
                }
                Section {
                    Button("开始使用") {
                        AppConfig.appUrl = appUrl
                        AppConfig.posHostUrl = posHostUrl
                        AppConfig.macMiniUrl = macMiniUrl
                        AppConfig.markConfigured()
                        onComplete()
                    }
                    .frame(maxWidth: .infinity, alignment: .center)
                }
            }
            .navigationTitle("屯象OS — iPad 配置")
        }
        .navigationViewStyle(.stack)
    }
}
