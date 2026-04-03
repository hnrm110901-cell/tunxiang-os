# CoreML Bridge — Swift HTTP Server (port 8100)

屯象OS边缘推理层。运行在门店 Mac mini M4 上，封装 Apple Neural Engine，
通过 HTTP 接口暴露三类 CoreML 推理能力给 Python 服务（mac-station、tx-agent）调用。

---

## 架构位置

```
Python 服务 (tx-agent / mac-station)
    │
    │  HTTP  http://localhost:8100/predict/*
    ▼
CoreML Bridge (本文件 — Swift Vapor)
    │
    │  CoreML framework
    ▼
Apple M4 Neural Engine (DishTimePredictor / DiscountRiskDetector / TrafficPredictor)
```

---

## 端点

| 方法 | 路径 | 功能 |
|------|------|------|
| GET | /health | 健康检查，返回已加载模型列表 |
| POST | /predict/dish-time | 出餐时间预测（秒） |
| POST | /predict/discount-risk | 折扣异常风险评分 |
| POST | /predict/traffic | 客流量预测（桌数/人次） |
| POST | /transcribe | 语音识别（v2 实现，当前返回 501） |

### POST /predict/dish-time

```json
// 请求
{
    "dish_id": "dish_001",
    "hour": 12,
    "day_type": "weekday",
    "queue_length": 3
}

// 响应
{
    "predicted_seconds": 480,
    "confidence": 0.85,
    "model": "dish_time_v1"
}
```

### POST /predict/discount-risk

```json
// 请求
{
    "discount_rate": 0.35,
    "order_amount": 256.0,
    "member_level": "gold"
}

// 响应
{
    "risk_score": 0.72,
    "risk_level": "high",
    "reason": "discount_rate_exceeds_member_limit"
}
```

### POST /predict/traffic

```json
// 请求
{
    "store_id": "store_001",
    "date": "2026-04-01",
    "hour": 12
}

// 响应
{
    "predicted_covers": 45,
    "confidence": 0.78
}
```

### GET /health

```json
{
    "ok": true,
    "models_loaded": ["dish_time_v1", "discount_risk_v1"],
    "memory_mb": 210,
    "version": "1.0.0"
}
```

---

## Mac mini 部署

### 前置条件

- macOS 14 (Sonoma) 或更高
- Swift 5.9+（检查：`swift --version`）
- Xcode Command Line Tools：`xcode-select --install`

### 安装 Swift（如未安装）

```bash
# 方式1：通过 Xcode（推荐，含 CoreML 框架）
# App Store 安装 Xcode，然后 xcode-select --install

# 方式2：Swift.org 官网下载 toolchain
# https://www.swift.org/download/
```

### 编译 & 运行

```bash
cd /opt/tunxiang/edge/coreml-bridge

# 首次编译（下载依赖约 2-3 分钟）
swift build -c release

# 运行
.build/release/CoreMLBridge
# 服务启动后监听 http://127.0.0.1:8100

# 验证
curl http://localhost:8100/health
```

### 模型文件放置路径

CoreML 模型文件（.mlmodelc 编译后格式）放置在与可执行文件相同目录：

```
.build/release/
├── CoreMLBridge              ← 可执行文件
├── DishTimePredictor.mlmodelc    ← 出餐时间模型（可选）
├── DiscountRiskDetector.mlmodelc ← 折扣风险模型（可选）
└── TrafficPredictor.mlmodelc     ← 客流预测模型（可选）
```

**注意**：模型文件不存在时，服务自动 fallback 到统计规则，不会崩溃。
这保证了"零模型也能上线，后续迭代添加模型"的渐进式部署策略。

### 编译模型

```bash
# 将 .mlmodel 编译为 .mlmodelc（运行时格式）
xcrun coremlcompiler compile YourModel.mlmodel .build/release/
```

---

## launchd 开机自启配置

在 Mac mini 上配置 launchd 守护进程，实现开机自启 + 崩溃自动重启。

### 1. 创建 plist 文件

```bash
sudo nano /Library/LaunchDaemons/com.tunxiang.coreml-bridge.plist
```

写入以下内容：

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.tunxiang.coreml-bridge</string>

    <key>ProgramArguments</key>
    <array>
        <string>/opt/tunxiang/edge/coreml-bridge/.build/release/CoreMLBridge</string>
    </array>

    <key>WorkingDirectory</key>
    <string>/opt/tunxiang/edge/coreml-bridge/.build/release</string>

    <key>RunAtLoad</key>
    <true/>

    <key>KeepAlive</key>
    <true/>

    <key>StandardOutPath</key>
    <string>/var/log/tunxiang/coreml-bridge.log</string>

    <key>StandardErrorPath</key>
    <string>/var/log/tunxiang/coreml-bridge-error.log</string>

    <key>EnvironmentVariables</key>
    <dict>
        <key>LOG_LEVEL</key>
        <string>info</string>
    </dict>
</dict>
</plist>
```

### 2. 加载服务

```bash
# 创建日志目录
sudo mkdir -p /var/log/tunxiang

# 设置 plist 权限
sudo chown root:wheel /Library/LaunchDaemons/com.tunxiang.coreml-bridge.plist
sudo chmod 644 /Library/LaunchDaemons/com.tunxiang.coreml-bridge.plist

# 加载并启动
sudo launchctl load /Library/LaunchDaemons/com.tunxiang.coreml-bridge.plist
sudo launchctl start com.tunxiang.coreml-bridge
```

### 3. 管理命令

```bash
# 查看状态
sudo launchctl list | grep coreml-bridge

# 停止
sudo launchctl stop com.tunxiang.coreml-bridge

# 卸载（不再开机自启）
sudo launchctl unload /Library/LaunchDaemons/com.tunxiang.coreml-bridge.plist

# 查看日志
tail -f /var/log/tunxiang/coreml-bridge.log
```

---

## 健康检查

Python 服务通过以下方式确认 bridge 状态：

```python
from services.edge_inference import EdgeInferenceClient

client = EdgeInferenceClient()
online = await client.is_available()
print("CoreML Bridge:", "在线" if online else "离线（使用统计规则 fallback）")
```

手动检查：

```bash
curl -s http://localhost:8100/health | python3 -m json.tool
```

---

## 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `COREML_BRIDGE_URL` | `http://localhost:8100` | Python 客户端连接地址 |

当 Mac mini 和 Python 服务不在同一台机器时（未来分离部署），
设置 `COREML_BRIDGE_URL=http://<mac-mini-ip>:8100`。

---

## 开发说明

### Fallback 策略

所有推理端点在 CoreML 模型文件缺失时自动使用统计规则（在 `ModelManager.swift` 中实现）。
Python 客户端 (`EdgeInferenceClient`) 在 bridge 不可用时也有同等 fallback。

双层 fallback 保证了零停机部署：
1. **Swift fallback**：模型未加载 → 统计规则，bridge 仍然可用
2. **Python fallback**：bridge 宕机/超时 → Python 端统计规则，业务不中断

### 添加新端点

1. 在 `ModelManager.swift` 添加新的 Features/Prediction 结构体和推理函数
2. 在 `PredictHandlers.swift` 添加新的请求/响应 DTO 和路由处理器
3. 在 `EdgeInferenceClient` 添加对应的 Python 调用方法
4. 在 `test_edge_inference.py` 添加对应测试
