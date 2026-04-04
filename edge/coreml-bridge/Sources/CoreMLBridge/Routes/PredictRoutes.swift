/// PredictRoutes.swift — 预测路由
///
/// POST /predict/dish-time       — 出餐时间预测
/// POST /predict/discount-risk   — 折扣异常检测评分
/// POST /predict/traffic         — 客流量预测

import Vapor

// MARK: - 请求 DTO

struct DishTimeRequest: Content {
    let dish_id: String
    let order_count: Int
    let time_of_day: Int
    let day_of_week: Int
}

struct DiscountRiskRequest: Content {
    let discount_rate: Double
    let order_amount_fen: Int
    let customer_type: String
}

struct TrafficRequest: Content {
    let store_id: String
    let date: String
    let hour: Int
}

// MARK: - 路由注册

func registerPredictRoutes(_ app: Application) {

    let manager = ModelManager.shared

    // MARK: POST /predict/dish-time

    app.post("predict", "dish-time") { req async throws -> Response in
        let body: DishTimeRequest
        do {
            body = try req.content.decode(DishTimeRequest.self)
        } catch {
            return try makeErrorResponse(
                status: .badRequest,
                code: "invalid_request",
                message: "请求体解析失败: \(error.localizedDescription)"
            )
        }

        guard body.time_of_day >= 0, body.time_of_day <= 23 else {
            return try makeErrorResponse(
                status: .badRequest,
                code: "invalid_param",
                message: "time_of_day must be 0-23"
            )
        }

        guard body.day_of_week >= 0, body.day_of_week <= 6 else {
            return try makeErrorResponse(
                status: .badRequest,
                code: "invalid_param",
                message: "day_of_week must be 0-6 (0=Sunday)"
            )
        }

        guard body.order_count >= 0 else {
            return try makeErrorResponse(
                status: .badRequest,
                code: "invalid_param",
                message: "order_count must be >= 0"
            )
        }

        let features = DishTimeFeatures(
            dishId: body.dish_id,
            orderCount: body.order_count,
            timeOfDay: body.time_of_day,
            dayOfWeek: body.day_of_week
        )

        let prediction = manager.predictDishTime(features: features)

        return try makeOkResponse(data: [
            "predicted_minutes": AnyCodable(prediction.predictedMinutes),
            "confidence": AnyCodable(prediction.confidence),
            "model": AnyCodable(prediction.model),
        ])
    }

    // MARK: POST /predict/discount-risk

    app.post("predict", "discount-risk") { req async throws -> Response in
        let body: DiscountRiskRequest
        do {
            body = try req.content.decode(DiscountRiskRequest.self)
        } catch {
            return try makeErrorResponse(
                status: .badRequest,
                code: "invalid_request",
                message: "请求体解析失败: \(error.localizedDescription)"
            )
        }

        guard body.discount_rate >= 0, body.discount_rate <= 1.0 else {
            return try makeErrorResponse(
                status: .badRequest,
                code: "invalid_param",
                message: "discount_rate must be 0.0-1.0"
            )
        }

        guard body.order_amount_fen >= 0 else {
            return try makeErrorResponse(
                status: .badRequest,
                code: "invalid_param",
                message: "order_amount_fen must be >= 0"
            )
        }

        let features = DiscountFeatures(
            discountRate: body.discount_rate,
            orderAmountFen: body.order_amount_fen,
            customerType: body.customer_type
        )

        let score = manager.predictDiscountRisk(features: features)

        return try makeOkResponse(data: [
            "risk_score": AnyCodable(score.riskScore),
            "action": AnyCodable(score.action),
            "reason": AnyCodable(score.reason),
        ])
    }

    // MARK: POST /predict/traffic

    app.post("predict", "traffic") { req async throws -> Response in
        let body: TrafficRequest
        do {
            body = try req.content.decode(TrafficRequest.self)
        } catch {
            return try makeErrorResponse(
                status: .badRequest,
                code: "invalid_request",
                message: "请求体解析失败: \(error.localizedDescription)"
            )
        }

        guard body.hour >= 0, body.hour <= 23 else {
            return try makeErrorResponse(
                status: .badRequest,
                code: "invalid_param",
                message: "hour must be 0-23"
            )
        }

        let formatter = DateFormatter()
        formatter.dateFormat = "yyyy-MM-dd"
        guard formatter.date(from: body.date) != nil else {
            return try makeErrorResponse(
                status: .badRequest,
                code: "invalid_param",
                message: "date must be yyyy-MM-dd format"
            )
        }

        let features = TrafficFeatures(
            storeId: body.store_id,
            date: body.date,
            hour: body.hour
        )

        let prediction = manager.predictTraffic(features: features)

        return try makeOkResponse(data: [
            "predicted_covers": AnyCodable(prediction.predictedCovers),
            "confidence": AnyCodable(prediction.confidence),
        ])
    }
}
