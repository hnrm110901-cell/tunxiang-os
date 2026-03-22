# Android POS Shell

商米 POS WebView 壳层 + JS Bridge。

## 架构

```
MainActivity (WebView全屏)
  └── TXBridge (JS Bridge)
        ├── print()         → 商米打印 SDK
        ├── openCashBox()   → 商米钱箱
        ├── startScale()    → 商米电子秤
        ├── scan()          → 商米扫码
        ├── getDeviceInfo() → 设备信息
        └── getMacMiniUrl() → Mac mini 局域网地址
```

## 构建

```bash
cd apps/android-shell
./gradlew assembleDebug
```

## 规则

- **不写业务逻辑** — 壳层只做桥接
- **锁定商米 T2/V2** — 减少适配成本
- 每个新 JS Bridge 接口必须有对应的 TypeScript 类型定义（见 web-pos/src/bridge/TXBridge.ts）
