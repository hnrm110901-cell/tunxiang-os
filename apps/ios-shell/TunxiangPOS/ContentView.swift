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

/// 首次启动配置页 — 填写服务器地址 + 门店信息
struct SetupView: View {
    @State private var appUrl = AppConfig.appUrl
    @State private var posHostUrl = AppConfig.posHostUrl
    @State private var macMiniUrl = AppConfig.macMiniUrl
    @State private var storeId = AppConfig.storeId
    @State private var selectedEnv = AppConfig.environment
    var onComplete: () -> Void

    var body: some View {
        NavigationView {
            Form {
                Section(header: Text("门店信息")) {
                    TextField("门店 ID（示例: xuji-hunan-001）", text: $storeId)
                        .autocapitalization(.none)
                        .disableAutocorrection(true)

                    Picker("环境", selection: $selectedEnv) {
                        ForEach(AppConfig.Environment.allCases, id: \.self) { env in
                            Text(env.displayName).tag(env)
                        }
                    }
                }

                Section(header: Text("门店服务器")) {
                    TextField("Web App 地址", text: $appUrl)
                        .keyboardType(.URL).autocapitalization(.none)
                    TextField("POS 主机地址（外设转发）", text: $posHostUrl)
                        .keyboardType(.URL).autocapitalization(.none)
                    TextField("Mac mini 地址（AI推理）", text: $macMiniUrl)
                        .keyboardType(.URL).autocapitalization(.none)
                }

                Section(header: Text("当前设备")) {
                    HStack {
                        Text("型号")
                        Spacer()
                        Text(AppConfig.deviceModel)
                            .foregroundColor(.secondary)
                            .font(.system(.body, design: .monospaced))
                    }
                    HStack {
                        Text("平台")
                        Spacer()
                        Text("iPad")
                            .foregroundColor(.secondary)
                    }
                }

                Section(footer: Text("配置保存后可随时在设置中修改")) {
                    Button("开始使用") {
                        AppConfig.appUrl = appUrl
                        AppConfig.posHostUrl = posHostUrl
                        AppConfig.macMiniUrl = macMiniUrl
                        AppConfig.storeId = storeId
                        AppConfig.environment = selectedEnv
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
