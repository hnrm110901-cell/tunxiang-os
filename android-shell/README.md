# android-shell -- 屯象 POS 安卓壳层

商米 T2/V2 专用 WebView 壳层。加载 React Web App，通过 JS Bridge 桥接商米外设 SDK。

**本层不含业务逻辑**，仅做 WebView 容器 + 外设桥接。

## 目录结构

```
android-shell/
  app/src/main/
    java/com/tunxiang/pos/
      MainActivity.kt              -- 主 Activity，WebView 容器
      bridge/
        TXBridge.kt                -- JS Bridge 主接口（window.TXBridge）
        PrintBridge.kt             -- 打印桥接（小票/厨房单/标签）
        ScanBridge.kt              -- 扫码桥接（内置扫码头 + 相机降级）
        ScaleBridge.kt             -- 称重桥接（电子秤数据流）
        CashBoxBridge.kt           -- 钱箱桥接（ESC 指令驱动）
        DeviceInfoBridge.kt        -- 设备信息（型号/序列号/版本）
      service/
        SunmiPrintService.kt       -- 商米打印 SDK 封装（AIDL + 队列管理）
        SunmiScanService.kt        -- 商米扫码 SDK 封装（广播接收）
      config/
        AppConfig.kt               -- 应用配置（地址管理 + mDNS 发现 + 机型检测）
    AndroidManifest.xml
    assets/                        -- 离线 HTML（React build 产物）
  build.gradle                     -- 根项目构建
  settings.gradle
```

## 架构

```
React Web App (WebView)
    |
    | window.TXBridge.*
    v
TXBridge (JS Bridge 主入口)
    |
    +-- PrintBridge --> SunmiPrintService --> 商米打印 SDK (AIDL)
    +-- ScanBridge  --> SunmiScanService  --> 商米扫码 SDK (广播)
    +-- ScaleBridge                       --> 商米电子秤 SDK
    +-- CashBoxBridge --> SunmiPrintService --> ESC 钱箱指令
    +-- DeviceInfoBridge                  --> Android Build + AppConfig
```

## JS Bridge 接口 (window.TXBridge)

| 方法 | 说明 | 返回值 |
|------|------|--------|
| `print(content)` | 打印小票/厨房单 | void |
| `openCashBox()` | 弹出钱箱 | void |
| `scan()` | 启动扫码 | void（结果通过回调） |
| `startScale()` | 开始称重 | void（数据通过回调） |
| `getDeviceInfo()` | 设备信息 | JSON string |
| `getMacMiniUrl()` | Mac mini 地址 | URL string |
| `vibrate(ms)` | 震动 | void |
| `playSound(type)` | 提示音 | void |
| `setKeepScreenOn(keep)` | 屏幕常亮 | void |

TypeScript 类型声明：`shared/hardware/src/tx-bridge.d.ts`

## 商米 SDK 接入状态

所有商米 SDK 调用当前以 TODO 占位，需从商米开发者平台下载 AAR 后接入：

- [ ] InnerPrinterManager（打印）
- [ ] SunmiScanHead（扫码）
- [ ] ScaleManager（电子秤）
- [ ] SunmiCashDrawer（钱箱）
- [ ] SunmiDevice（设备序列号）

SDK 下载：https://developer.sunmi.com/docs/zh-CN/

## 构建

```bash
# 需要 Android SDK 34 + Kotlin 1.9.22
cd android-shell
./gradlew assembleDebug
./gradlew assembleRelease
```

## 目标机型

| 型号 | 屏幕 | 用途 |
|------|------|------|
| 商米 T2 | 15.6" 双屏（主+客显） | 收银台 POS |
| 商米 V2 | 5.99" 单屏 | 手持点餐/扫码 |
