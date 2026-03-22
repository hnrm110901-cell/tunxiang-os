# iPad POS Shell (可选升级包)

适用于高端连锁品牌（如徐记海鲜），用 iPad 替代安卓平板作为 POS/KDS 终端。

## 技术实现

- SwiftUI + WKWebView 加载同一套 React web-pos
- **不连接任何外设**
- 打印/称重等指令通过 WiFi HTTP 发送到安卓 POS 主机
- 安卓 POS 断开时降级为"仅查看"

## 构建

```bash
open apps/ios-shell/TunxiangPOS.xcodeproj
# 或使用 xcodebuild
xcodebuild -scheme TunxiangPOS -destination 'platform=iOS Simulator,name=iPad Air'
```

## 环境变量

- `WEB_POS_URL`: web-pos 地址（默认 `http://192.168.1.100:5173`）
