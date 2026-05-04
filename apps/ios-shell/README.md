# 屯象OS iPad POS Shell (可选升级包)

适用于高端连锁品牌的 iPad POS/KDS 终端。iPad 运行同一套 React Web App（web-pos），通过 WKWebView 加载，外设指令通过 HTTP 转发到 Android POS 主机执行。

## 适用场景

- 高端餐厅（如徐记海鲜）用 iPad 替代 Android 平板提升品牌调性
- 门店经理使用 iPad 便携巡店 + 看数据驾驶舱
- 宴会厅/包间专属 iPad 终端

## 技术架构

```
┌──────────────────────────────────────────┐
│              iPad POS Shell               │
│                                           │
│  SwiftUI + WKWebView                      │
│    │                                      │
│    ├─ ContentView (首次配置页 / WebView)   │
│    ├─ WebViewController (WKWebView 封装)   │
│    ├─ TXBridge_iOS (JS Bridge 桥接层)      │
│    ├─ AppConfig (配置管理)                 │
│    └─ TunxiangPOSApp (入口)               │
│                                           │
│  桥接能力：                                │
│    ✅ 摄像头扫码（二维码/条形码）           │
│    ✅ 推送通知注册 + 前台展示              │
│    ✅ 设备信息查询                         │
│    ✅ 生物识别（Face ID / Touch ID）       │
│    ✅ 剪贴板读写                           │
│    ✅ 触觉反馈                             │
│    ❌ 打印 → HTTP 转发 Android POS         │
│    ❌ 钱箱 → HTTP 转发 Android POS         │
│    ❌ 称重 → HTTP 转发 Android POS         │
│    ❌ 扫码枪 → HTTP 转发 Android POS       │
└──────────────────────────────────────────┘
```

### 职责边界（铁律）

- **iPad 不连接任何外设**（CLAUDE.md SS12）
- **不写业务逻辑**（CLAUDE.md SS13）
- 外设指令通过 WiFi HTTP 转发到 Android POS 主机执行
- Android POS 断开时降级为"仅查看"模式

## 环境要求

| 项 | 要求 |
|---|---|
| Xcode | 16.0+ (Swift 6, iOS 18 SDK) |
| 部署目标 | iOS 17.0+ |
| 设备 | iPad Air / iPad Pro / iPad mini |
| Swift 版本 | Swift 6 |
| UI 框架 | SwiftUI + WKWebView |
| 项目格式 | Xcode 16 project |

## 项目结构

```
apps/ios-shell/
  README.md                              # 本文件
  TunxiangPOS/
    TunxiangPOSApp.swift                 # @main 入口 + PushNotificationDelegate
    ContentView.swift                    # 首次配置页 / WebView 容器
    WebViewController.swift              # WKWebView UIViewRepresentable 封装
    TXBridge_iOS.swift                   # JS Bridge: 摄像头/推送/生物识别/转发
    AppConfig.swift                      # 配置管理（plist → UserDefaults → Info.plist 降级）
    tunxiang-pos.plist.example           # 门店部署配置文件模板（勿提交真实 plist）
    Info.plist                           # 编译默认值与环境声明
  TunxiangPOSTests/
    TXBridge_iOSTests.swift              # TXBridge 单元测试
  TunxiangPOSUITests/
    TunxiangPOSUITests.swift             # UI 自动化测试
```

## 快速开始

### 1. 打开项目

```bash
cd apps/ios-shell
open TunxiangPOS.xcodeproj
# 或
xed .
```

### 2. 配置门店信息

有三种配置方式，优先级由高到低：

**方式 A：plist 文件（推荐，门店批量部署）**

```bash
cp TunxiangPOS/tunxiang-pos.plist.example TunxiangPOS/tunxiang-pos.plist
# 编辑 tunxiang-pos.plist 填入门店实际 IP 和 ID
```

**方式 B：首次启动配置页（单设备手动配置）**

首次启动 App 时自动弹出配置表单，填写：
- 门店 ID（如 `xuji-hunan-001`）
- 环境（dev / staging / prod）
- Web App 地址（React web-pos 部署地址）
- POS 主机地址（Android POS 外设转发目标）
- Mac mini 地址（边缘 AI 推理目标）

**方式 C：Xcode Scheme 环境变量（开发调试）**

在 Xcode Scheme → Run → Arguments → Environment Variables 中设置：
```
TX_APP_URL       = http://192.168.1.100:8000
```

### 3. 运行

- 选择 `TunxiangPOS` scheme
- 目标设备选择 `iPad (11-inch)` 或 `iPad Pro (12.9-inch)`
- Cmd+R 运行

### 4. 构建发布

```bash
# Archive for App Store / TestFlight
xcodebuild archive \
  -scheme TunxiangPOS \
  -archivePath ./build/TunxiangPOS.xcarchive \
  -destination 'generic/platform=iOS'

# Simulator debug build
xcodebuild build \
  -scheme TunxiangPOS \
  -destination 'platform=iOS Simulator,name=iPad Pro 12.9-inch (18.0)'
```

## 运行测试

### Xcode IDE

- 打开项目，选择 `TunxiangPOSTests` scheme → Cmd+U 运行单元测试
- 选择 `TunxiangPOSUITests` scheme → Cmd+U 运行 UI 测试

### 命令行

```bash
# 运行单元测试
xcodebuild test \
  -scheme TunxiangPOSTests \
  -destination 'platform=iOS Simulator,name=iPad Pro 12.9-inch (18.0)'

# 运行 UI 测试
xcodebuild test \
  -scheme TunxiangPOSUITests \
  -destination 'platform=iOS Simulator,name=iPad Pro 12.9-inch (18.0)'

# 运行全部测试
xcodebuild test \
  -scheme TunxiangPOS \
  -destination 'platform=iOS Simulator,name=iPad Pro 12.9-inch (18.0)'
```

## JS Bridge 接口

React Web App 通过 `window.webkit.messageHandlers.txNative.postMessage()` 调用原生能力：

```typescript
// 消息格式
{
  type: "getDeviceInfo" | "startCamera" | "registerPush" | ... ,
  payload: { ... },
  callbackId: "cb_001"  // 可选，用于接收异步回调
}
```

支持的消息类型：

| type | 说明 | 本地处理 | 转发到 POS |
|---|---|---|---|
| `getDeviceInfo` | 获取设备型号/系统版本 | Yes | No |
| `startCamera` | 摄像头扫码（权限预检） | Yes | No |
| `registerPush` | 查询推送通知注册状态 | Yes | No |
| `requestNotificationPermission` | 请求推送通知权限 | Yes | No |
| `authenticateBiometric` | Face ID / Touch ID 验证 | Yes | No |
| `copyToClipboard` | 写入剪贴板 | Yes | No |
| `hapticFeedback` | 触觉反馈 | Yes | No |
| `print` | 打印小票 | No | Yes |
| `openCashBox` | 弹出钱箱 | No | Yes |
| `scale` | 电子秤读数 | No | Yes |
| `coreMLPredict` | Core ML 推理 | No | Mac mini |

## 配置管理

### 配置优先级

```
tunxiang-pos.plist  (门店部署包内置)
  └─ UserDefaults    (首次配置页交互写入)
       └─ Info.plist  (Xcode Scheme ENV 变量)
            └─ 硬编码默认值 (仅开发环境)
```

### 配置项说明

| 键 | 说明 | 示例值 |
|---|---|---|
| `store_id` | 门店 ID（租户标识） | `xuji-hunan-001` |
| `environment` | 运行环境 | `dev` / `staging` / `prod` |
| `app_url` | React Web App 地址 | `http://192.168.1.100:8000` |
| `pos_host_url` | Android POS 主机地址 | `http://192.168.1.10:8080` |
| `mac_mini_url` | Mac mini 地址 | `http://192.168.1.100:8000` |

### 重置配置

```swift
// 开发调试时重置首次配置状态
AppConfig.resetConfiguration()
```

或直接删除 App 重新安装。

## 网络拓扑

```
  iPad (WKWebView)
    │  WiFi
    ├───── Android POS 主机 (192.168.1.10:8080)
    │        └─ 打印机 / 钱箱 / 电子秤 / 扫码枪
    │
    └───── Mac mini M4 (192.168.1.100:8000)
             ├─ React Web App (port 8000)
             ├─ Core ML Bridge (port 8100)
             └─ 本地 PostgreSQL
```

## 离线降级

当 iPad 无法连接 Android POS 主机时：
- 外设转发请求静默失败（收银员可手动重试）
- 界面自动降级为"仅查看"模式
- WKWebView 加载失败时显示离线降级页面（含门店服务器信息）

## 与 Android POS 壳层的差异

| 能力 | Android POS | iPad POS |
|---|---|---|
| WebView | WebView (Chromium) | WKWebView (Safari) |
| JS Bridge | `window.TXBridge.*` | `webkit.messageHandlers.txNative.postMessage()` |
| 打印 | 商米 SDK 直连 | HTTP 转发 Android POS |
| 钱箱 | USB 直连 | HTTP 转发 Android POS |
| 称重 | USB 直连 | HTTP 转发 Android POS |
| 扫码 | 商米 SDK 直连 | 摄像头 getUserMedia() 或转发 |
| 外设控制 | 本地 | HTTP 转发 |
| 离线能力 | Service Worker | 受限（WKWebView 无 SW） |

## 许可证

私有项目。屯象科技所有。
