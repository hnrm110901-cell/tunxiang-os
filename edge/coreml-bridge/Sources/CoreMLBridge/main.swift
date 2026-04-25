/// main.swift — CoreML Bridge 启动入口
///
/// 启动 Vapor HTTP Server，监听 localhost:8100
/// 暴露 /predict/* 给 Python 服务（mac-station、tx-agent）调用
///
/// 端点列表：
///   POST /predict/dish-time       — 出餐时间预测
///   POST /predict/discount-risk   — 折扣异常检测评分
///   POST /predict/traffic         — 客流量预测
///   POST /predict/dish-price      — 菜品动态定价（D3c，v0 规则版）
///   POST /transcribe              — 语音指令识别 (Whisper，v2实现)
///   GET  /health                  — 健康检查

import Vapor

// MARK: - 应用配置

var env = try Environment.detect()
try LoggingSystem.bootstrap(from: &env)

let app = Application(env)
defer { app.shutdown() }

// 监听 localhost:8100（仅本机访问，Python 通过 127.0.0.1 调用）
app.http.server.configuration.hostname = "127.0.0.1"
app.http.server.configuration.port = 8100

// 设置 JSON 编解码器（snake_case）
let encoder = JSONEncoder()
encoder.outputFormatting = .prettyPrinted
let decoder = JSONDecoder()
ContentConfiguration.global.use(encoder: encoder, for: .json)
ContentConfiguration.global.use(decoder: decoder, for: .json)

// 注册路由
registerRoutes(app)

app.logger.info("CoreML Bridge starting on http://127.0.0.1:8100")
app.logger.info("Endpoints: /health, /predict/dish-time, /predict/discount-risk, /predict/traffic, /predict/dish-price, /transcribe")

// 启动服务
try app.run()
