/// PredictHandlers.swift — Vapor路由处理器
///
/// 注册所有 /predict/* 路由到 Vapor application
/// 输入验证 → ModelManager 推理 → 统一响应格式

import Vapor

// MARK: - 请求/响应 DTO

// POST /predict/dish-time
struct DishTimeRequest: Content {
    let dish_id: String
    let hour: Int
    let day_type: String    // "weekday" | "weekend"
    let queue_length: Int
}

struct DishTimeResponse: Content {
    let predicted_seconds: Int
    let confidence: Double
    let model: String
}

// POST /predict/discount-risk
struct DiscountRiskRequest: Content {
    let discount_rate: Double
    let order_amount: Double
    let member_level: String  // "regular" | "silver" | "gold" | "platinum"
}

struct DiscountRiskResponse: Content {
    let risk_score: Double
    let risk_level: String
    let reason: String
}

// POST /predict/traffic
struct TrafficRequest: Content {
    let store_id: String
    let date: String    // "2026-04-01"
    let hour: Int
}

struct TrafficResponse: Content {
    let predicted_covers: Int
    let confidence: Double
}

// GET /health
struct HealthResponse: Content {
    let ok: Bool
    let models_loaded: [String]
    let memory_mb: Int
    let version: String
}

// 统一错误响应
struct ErrorResponse: Content {
    let ok: Bool
    let error: String
}

// MARK: - 路由注册

func registerRoutes(_ app: Application) {

    let manager = ModelManager.shared

    // MARK: GET /health

    app.get("health") { _ async throws -> HealthResponse in
        return HealthResponse(
            ok: true,
            models_loaded: manager.loadedModels,
            memory_mb: manager.estimatedMemoryMB,
            version: "1.0.0"
        )
    }

    // MARK: POST /predict/dish-time

    app.post("predict", "dish-time") { req async throws -> Response in
        let body: DishTimeRequest
        do {
            body = try req.content.decode(DishTimeRequest.self)
        } catch {
            let errResp = ErrorResponse(ok: false, error: "invalid_request: \(error.localizedDescription)")
            return try Response(status: .badRequest, body: .init(data: JSONEncoder().encode(errResp)))
        }

        guard body.hour >= 0, body.hour <= 23 else {
            let errResp = ErrorResponse(ok: false, error: "hour must be 0-23")
            return try Response(status: .badRequest, body: .init(data: JSONEncoder().encode(errResp)))
        }

        guard body.queue_length >= 0 else {
            let errResp = ErrorResponse(ok: false, error: "queue_length must be >= 0")
            return try Response(status: .badRequest, body: .init(data: JSONEncoder().encode(errResp)))
        }

        let features = DishTimeFeatures(
            dishId: body.dish_id,
            hour: body.hour,
            dayType: body.day_type,
            queueLength: body.queue_length
        )

        let prediction = manager.predictDishTime(features: features)

        let result = DishTimeResponse(
            predicted_seconds: prediction.predictedSeconds,
            confidence: prediction.confidence,
            model: prediction.model
        )

        let data = try JSONEncoder().encode(result)
        return Response(status: .ok, body: .init(data: data))
    }

    // MARK: POST /predict/discount-risk

    app.post("predict", "discount-risk") { req async throws -> Response in
        let body: DiscountRiskRequest
        do {
            body = try req.content.decode(DiscountRiskRequest.self)
        } catch {
            let errResp = ErrorResponse(ok: false, error: "invalid_request: \(error.localizedDescription)")
            return try Response(status: .badRequest, body: .init(data: JSONEncoder().encode(errResp)))
        }

        guard body.discount_rate >= 0, body.discount_rate <= 1.0 else {
            let errResp = ErrorResponse(ok: false, error: "discount_rate must be 0.0-1.0")
            return try Response(status: .badRequest, body: .init(data: JSONEncoder().encode(errResp)))
        }

        guard body.order_amount >= 0 else {
            let errResp = ErrorResponse(ok: false, error: "order_amount must be >= 0")
            return try Response(status: .badRequest, body: .init(data: JSONEncoder().encode(errResp)))
        }

        let features = DiscountFeatures(
            discountRate: body.discount_rate,
            orderAmount: body.order_amount,
            memberLevel: body.member_level
        )

        let score = manager.predictDiscountRisk(features: features)

        let result = DiscountRiskResponse(
            risk_score: score.riskScore,
            risk_level: score.riskLevel,
            reason: score.reason
        )

        let data = try JSONEncoder().encode(result)
        return Response(status: .ok, body: .init(data: data))
    }

    // MARK: POST /predict/traffic

    app.post("predict", "traffic") { req async throws -> Response in
        let body: TrafficRequest
        do {
            body = try req.content.decode(TrafficRequest.self)
        } catch {
            let errResp = ErrorResponse(ok: false, error: "invalid_request: \(error.localizedDescription)")
            return try Response(status: .badRequest, body: .init(data: JSONEncoder().encode(errResp)))
        }

        guard body.hour >= 0, body.hour <= 23 else {
            let errResp = ErrorResponse(ok: false, error: "hour must be 0-23")
            return try Response(status: .badRequest, body: .init(data: JSONEncoder().encode(errResp)))
        }

        // 验证日期格式 yyyy-MM-dd
        let formatter = DateFormatter()
        formatter.dateFormat = "yyyy-MM-dd"
        guard formatter.date(from: body.date) != nil else {
            let errResp = ErrorResponse(ok: false, error: "date must be yyyy-MM-dd format")
            return try Response(status: .badRequest, body: .init(data: JSONEncoder().encode(errResp)))
        }

        let features = TrafficFeatures(
            storeId: body.store_id,
            date: body.date,
            hour: body.hour
        )

        let prediction = manager.predictTraffic(features: features)

        let result = TrafficResponse(
            predicted_covers: prediction.predictedCovers,
            confidence: prediction.confidence
        )

        let data = try JSONEncoder().encode(result)
        return Response(status: .ok, body: .init(data: data))
    }

    // MARK: POST /transcribe (Whisper语音识别占位)

    app.post("transcribe") { req async throws -> Response in
        // TODO: 集成 Apple Speech framework 或 Whisper CoreML 模型
        // 当前返回 501 Not Implemented，不影响其他接口
        let errResp = ErrorResponse(ok: false, error: "transcribe not yet implemented — coming in v2")
        let data = try JSONEncoder().encode(errResp)
        return Response(status: .notImplemented, body: .init(data: data))
    }
}
