/// ModelManager.swift — CoreML模型管理器
///
/// 职责：懒加载CoreML模型，模型不存在时返回mock数据（fallback）
/// 生产：将 .mlmodel 文件放到与可执行文件同目录，ModelManager 自动加载
///
/// 当前状态：全部使用统计规则作为 fallback（模型文件未提供时）

import Foundation

// MARK: - 输入结构体

struct DishTimeFeatures {
    let dishId: String
    let hour: Int
    let dayType: String    // "weekday" | "weekend"
    let queueLength: Int
}

struct DiscountFeatures {
    let discountRate: Double
    let orderAmount: Double
    let memberLevel: String  // "regular" | "silver" | "gold" | "platinum"
}

struct TrafficFeatures {
    let storeId: String
    let date: String   // "2026-04-01"
    let hour: Int
}

// MARK: - 输出结构体

struct DishTimePrediction {
    let predictedSeconds: Int
    let confidence: Double
    let model: String
}

struct RiskScore {
    let riskScore: Double
    let riskLevel: String   // "low" | "medium" | "high"
    let reason: String
}

struct TrafficPrediction {
    let predictedCovers: Int
    let confidence: Double
}

// MARK: - ModelManager

/// 懒加载 CoreML 模型，不存在时 graceful fallback 到统计规则
final class ModelManager {

    static let shared = ModelManager()
    private init() {}

    /// 已加载模型列表（用于 /health 接口展示）
    private(set) var loadedModels: [String] = []

    // MARK: - 出餐时间预测

    /// 预测出餐时间（秒）
    /// - 生产: 加载 DishTimePredictor.mlmodel，Neural Engine 推理
    /// - fallback: 基于队列长度和时段的统计公式
    func predictDishTime(features: DishTimeFeatures) -> DishTimePrediction {
        // TODO: 尝试加载 CoreML 模型
        // let modelURL = Bundle.module.url(forResource: "DishTimePredictor", withExtension: "mlmodelc")
        // if let url = modelURL, let model = try? DishTimePredictor(contentsOf: url) {
        //     loadedModels.append("dish_time_v1")
        //     let output = try? model.prediction(...)
        // }

        // Fallback: 统计规则
        // 基准：5分钟 + 每道菜2分钟 + 高峰时段加成 + 队列等待
        let baseSecs = 300
        let queueWait = features.queueLength * 90       // 每单90秒队列等待
        let peakHours = [11, 12, 13, 17, 18, 19, 20]
        let peakBonus = peakHours.contains(features.hour) ? 120 : 0
        let weekendBonus = features.dayType == "weekend" ? 60 : 0

        let total = baseSecs + queueWait + peakBonus + weekendBonus
        let confidence = features.queueLength < 5 ? 0.85 : 0.72

        return DishTimePrediction(
            predictedSeconds: total,
            confidence: confidence,
            model: "dish_time_v1_fallback"
        )
    }

    // MARK: - 折扣风险评分

    /// 折扣异常风险评分
    /// - 生产: 加载 DiscountRiskDetector.mlmodel
    /// - fallback: 规则引擎（折扣率阈值 + 会员等级）
    func predictDiscountRisk(features: DiscountFeatures) -> RiskScore {
        // TODO: CoreML 异常检测模型
        // Fallback: 规则引擎

        // 会员等级允许的最大折扣
        let maxAllowedDiscount: Double
        let memberLevel = features.memberLevel.lowercased()
        switch memberLevel {
        case "platinum":
            maxAllowedDiscount = 0.40
        case "gold":
            maxAllowedDiscount = 0.30
        case "silver":
            maxAllowedDiscount = 0.20
        default:
            maxAllowedDiscount = 0.10
        }

        let excess = max(0, features.discountRate - maxAllowedDiscount)
        var riskScore = excess * 2.0   // 超出部分线性映射到风险分

        // 高额订单额外风险
        if features.orderAmount > 500 {
            riskScore += 0.15
        }

        riskScore = min(1.0, riskScore)

        let riskLevel: String
        let reason: String

        if riskScore >= 0.7 {
            riskLevel = "high"
            reason = features.discountRate > maxAllowedDiscount
                ? "discount_rate_exceeds_member_limit"
                : "discount_rate_too_high"
        } else if riskScore >= 0.4 {
            riskLevel = "medium"
            reason = "discount_rate_near_limit"
        } else {
            riskLevel = "low"
            reason = "within_normal_range"
        }

        return RiskScore(
            riskScore: riskScore,
            riskLevel: riskLevel,
            reason: reason
        )
    }

    // MARK: - 客流量预测

    /// 预测到店客流（桌位/人次）
    /// - 生产: 加载 TrafficPredictor.mlmodel（含历史序列特征）
    /// - fallback: 时段 + 星期几统计均值
    func predictTraffic(features: TrafficFeatures) -> TrafficPrediction {
        // TODO: CoreML 时序预测模型
        // Fallback: 统计均值

        // 解析日期获取星期
        let formatter = DateFormatter()
        formatter.dateFormat = "yyyy-MM-dd"
        let date = formatter.date(from: features.date) ?? Date()
        let calendar = Calendar.current
        let weekday = calendar.component(.weekday, from: date)  // 1=Sunday, 7=Saturday
        let isWeekend = weekday == 1 || weekday == 7

        // 时段权重（以12:00为100%基准）
        let hourWeights: [Int: Double] = [
            6: 0.05, 7: 0.10, 8: 0.15, 9: 0.20, 10: 0.30,
            11: 0.80, 12: 1.00, 13: 0.90, 14: 0.50, 15: 0.30,
            16: 0.25, 17: 0.70, 18: 1.00, 19: 0.95, 20: 0.80,
            21: 0.50, 22: 0.20
        ]

        let weight = hourWeights[features.hour] ?? 0.10
        let baseCover = 40.0
        let weekendMultiplier = isWeekend ? 1.35 : 1.0
        let predicted = baseCover * weight * weekendMultiplier

        let confidence = weight > 0.5 ? 0.78 : 0.62  // 高峰时段置信度更高

        return TrafficPrediction(
            predictedCovers: max(0, Int(predicted.rounded())),
            confidence: confidence
        )
    }

    // MARK: - 内存使用（近似值）

    var estimatedMemoryMB: Int {
        // 模型未加载时基准内存约 50MB
        let baseMemory = 50
        let modelMemory = loadedModels.count * 80  // 每个 CoreML 模型约 80MB
        return baseMemory + modelMemory
    }
}
