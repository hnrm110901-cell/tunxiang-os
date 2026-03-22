/// TunxiangOS Core ML Bridge
/// Swift HTTP Server on port 8100
///
/// Endpoints:
///   POST /predict/dish-time       — 出餐时间预测
///   POST /predict/discount-risk   — 折扣异常检测评分
///   POST /predict/traffic         — 客流量预测
///   POST /transcribe              — 语音指令识别 (Whisper)
///   GET  /health                  — 健康检查

import Foundation
import Hummingbird

struct PredictRequest: Decodable {
    let features: [String: Double]?
    let dish_count: Int?
    let hour: Int?
    let day_of_week: Int?
}

struct PredictResponse: Encodable {
    let ok: Bool
    let data: [String: Double]?
    let error: String?
}

struct HealthResponse: Encodable {
    let ok: Bool
    let service: String
    let version: String
    let models_loaded: [String]
}

// Available ML models (placeholder — replace with actual Core ML models)
let availableModels = ["dish-time", "discount-risk", "traffic"]

func buildApp() -> some ApplicationProtocol {
    let router = Router()

    // GET /health
    router.get("health") { _, _ in
        return HealthResponse(
            ok: true,
            service: "coreml-bridge",
            version: "3.0.0",
            models_loaded: availableModels
        )
    }

    // POST /predict/dish-time — 出餐时间预测
    router.post("predict/dish-time") { request, context in
        let body = try await request.decode(as: PredictRequest.self, context: context)
        let dishCount = body.dish_count ?? 1

        // Placeholder: 实际用 Core ML 模型推理
        // let model = try DishTimePredictor(configuration: .init())
        // let prediction = try model.prediction(dish_count: dishCount, ...)
        let predictedMinutes = 8.0 + Double(dishCount) * 2.5

        return PredictResponse(
            ok: true,
            data: ["predicted_minutes": predictedMinutes, "confidence": 0.85],
            error: nil
        )
    }

    // POST /predict/discount-risk — 折扣异常检测
    router.post("predict/discount-risk") { request, context in
        let body = try await request.decode(as: PredictRequest.self, context: context)
        let features = body.features ?? [:]
        let discountRate = features["discount_rate"] ?? 0

        // Placeholder: 实际用 Core ML 异常检测模型
        let riskScore = discountRate > 0.5 ? 0.9 : discountRate * 0.5

        return PredictResponse(
            ok: true,
            data: ["risk_score": riskScore, "threshold": 0.7],
            error: nil
        )
    }

    // POST /predict/traffic — 客流量预测
    router.post("predict/traffic") { request, context in
        let body = try await request.decode(as: PredictRequest.self, context: context)
        let hour = body.hour ?? 12
        let dayOfWeek = body.day_of_week ?? 3

        // Placeholder: 实际用 Core ML 客流预测模型
        let peakHours = [11, 12, 13, 17, 18, 19]
        let baseLine = 50.0
        let multiplier = peakHours.contains(hour) ? 2.5 : 1.0
        let weekendBoost = (dayOfWeek >= 5) ? 1.3 : 1.0
        let predicted = baseLine * multiplier * weekendBoost

        return PredictResponse(
            ok: true,
            data: ["predicted_customers": predicted, "confidence": 0.75],
            error: nil
        )
    }

    let app = Application(router: router, configuration: .init(address: .hostname("0.0.0.0", port: 8100)))
    return app
}

let app = buildApp()
try await app.run()
