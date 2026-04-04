/// ModelManager.swift — CoreML 模型管理器
///
/// 职责：懒加载 CoreML 模型，模型不存在时返回 mock 数据（fallback）
/// 生产：将 .mlmodel 文件放到与可执行文件同目录，ModelManager 自动加载
///
/// 当前状态：全部使用统计规则作为 fallback（模型文件未提供时）

import Foundation
#if canImport(CoreML)
import CoreML
#endif

// MARK: - 输入结构体

struct DishTimeFeatures {
    let dishId: String
    let orderCount: Int
    let timeOfDay: Int
    let dayOfWeek: Int
}

struct DiscountFeatures {
    let discountRate: Double
    let orderAmountFen: Int
    let customerType: String   // "normal" | "vip" | "svip"
}

struct TrafficFeatures {
    let storeId: String
    let date: String   // "2026-04-03"
    let hour: Int
}

// MARK: - 输出结构体

struct DishTimePrediction {
    let predictedMinutes: Double
    let confidence: Double
    let model: String
}

struct RiskScore {
    let riskScore: Double
    let action: String       // "pass" | "warn" | "block"
    let reason: String
}

struct TrafficPrediction {
    let predictedCovers: Int
    let confidence: Double
}

struct TranscribeResult {
    let text: String
    let confidence: Double
    let language: String
}

// MARK: - 模型版本信息

struct ModelVersion {
    let name: String
    let version: String
    let status: ModelStatus
}

enum ModelStatus: String {
    case loaded = "loaded"
    case fallback = "fallback"
    case failed = "failed"
}

// MARK: - ModelManager

/// 懒加载 CoreML 模型，不存在时 graceful fallback 到统计规则
final class ModelManager: @unchecked Sendable {

    static let shared = ModelManager()

    /// 服务启动时间（用于 uptime 计算）
    let startTime = Date()

    /// 模型注册表
    private var models: [String: ModelVersion] = [:]

    /// 已加载模型名称列表（用于 /health 展示）
    var loadedModels: [String] {
        models.values.map { "\($0.name)-\($0.version)" }
    }

    /// Neural Engine 是否可用
    var neuralEngineAvailable: Bool {
        #if arch(arm64)
        return true
        #else
        return false
        #endif
    }

    /// 服务运行秒数
    var uptimeSeconds: Int {
        Int(Date().timeIntervalSince(startTime))
    }

    private init() {}

    // MARK: - 启动预热

    /// 预热所有模型：尝试加载 CoreML，失败则注册 fallback
    func warmup() {
        registerModel(name: "dish-time", version: "v1")
        registerModel(name: "discount-risk", version: "v1")
        registerModel(name: "traffic", version: "v1")
    }

    private func registerModel(name: String, version: String) {
        // TODO: 尝试加载真实 CoreML 模型
        // let modelURL = Bundle.main.url(forResource: name, withExtension: "mlmodelc")
        // if let url = modelURL {
        //     do {
        //         let config = MLModelConfiguration()
        //         config.computeUnits = .all  // 使用 Neural Engine
        //         let model = try MLModel(contentsOf: url, configuration: config)
        //         models[name] = ModelVersion(name: name, version: version, status: .loaded)
        //         return
        //     } catch { /* fall through to fallback */ }
        // }

        // 降级：注册 fallback 规则引擎
        models[name] = ModelVersion(name: name, version: version, status: .fallback)
    }

    // MARK: - 出餐时间预测

    /// 预测出餐时间（分钟）
    /// - 生产: 加载 DishTimePredictor.mlmodel，Neural Engine 推理
    /// - fallback: 基于订单量和时段的统计公式
    func predictDishTime(features: DishTimeFeatures) -> DishTimePrediction {
        // Fallback: 统计规则
        let baseMinutes = 8.0
        let orderFactor = Double(features.orderCount) * 1.5
        let peakHours = [11, 12, 13, 17, 18, 19, 20]
        let peakBonus = peakHours.contains(features.timeOfDay) ? 3.0 : 0.0
        let weekendBonus = (features.dayOfWeek == 0 || features.dayOfWeek == 6) ? 2.0 : 0.0

        let total = baseMinutes + orderFactor + peakBonus + weekendBonus
        let confidence = features.orderCount < 5 ? 0.85 : 0.72

        return DishTimePrediction(
            predictedMinutes: (total * 10).rounded() / 10,  // 保留1位小数
            confidence: confidence,
            model: models["dish-time"]?.status == .loaded ? "coreml" : "fallback"
        )
    }

    // MARK: - 折扣风险评分

    /// 折扣异常风险评分
    /// - 生产: 加载 DiscountRiskDetector.mlmodel
    /// - fallback: 规则引擎（折扣率阈值 + 客户类型）
    func predictDiscountRisk(features: DiscountFeatures) -> RiskScore {
        // 客户类型允许的最大折扣
        let maxAllowedDiscount: Double
        switch features.customerType.lowercased() {
        case "svip":
            maxAllowedDiscount = 0.50
        case "vip":
            maxAllowedDiscount = 0.30
        default:
            maxAllowedDiscount = 0.15
        }

        let excess = max(0, features.discountRate - maxAllowedDiscount)
        var riskScore = excess * 2.5

        // 高额订单额外风险（5万分=500元以上）
        if features.orderAmountFen > 50000 {
            riskScore += 0.15
        }

        riskScore = min(1.0, riskScore)

        let action: String
        let reason: String

        if riskScore >= 0.7 {
            action = "block"
            reason = features.discountRate > maxAllowedDiscount
                ? "折扣率超出客户等级上限"
                : "高折扣率"
        } else if riskScore >= 0.4 {
            action = "warn"
            reason = "折扣率接近上限"
        } else {
            action = "pass"
            reason = "正常范围"
        }

        return RiskScore(
            riskScore: (riskScore * 100).rounded() / 100,  // 保留2位小数
            action: action,
            reason: reason
        )
    }

    // MARK: - 客流量预测

    /// 预测到店客流（桌位/人次）
    /// - 生产: 加载 TrafficPredictor.mlmodel（含历史序列特征）
    /// - fallback: 时段 + 星期几统计均值
    func predictTraffic(features: TrafficFeatures) -> TrafficPrediction {
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
            21: 0.50, 22: 0.20,
        ]

        let weight = hourWeights[features.hour] ?? 0.10
        let baseCover = 45.0
        let weekendMultiplier = isWeekend ? 1.35 : 1.0
        let predicted = baseCover * weight * weekendMultiplier

        let confidence = weight > 0.5 ? 0.78 : 0.62

        return TrafficPrediction(
            predictedCovers: max(0, Int(predicted.rounded())),
            confidence: confidence
        )
    }

    // MARK: - 语音识别（Mock）

    /// 语音转文字（当前返回 mock 数据）
    /// - 生产: 使用 Apple Speech framework 或 Whisper CoreML 模型
    /// - fallback: 返回固定 mock 结果
    func transcribe(audioData: Data, filename: String) -> TranscribeResult {
        // TODO: 集成 Apple Speech framework
        // let recognizer = SFSpeechRecognizer(locale: Locale(identifier: "zh-CN"))
        // TODO: 或集成 Whisper CoreML 模型
        // let whisperModel = try MLModel(contentsOf: whisperURL)

        return TranscribeResult(
            text: "来一份宫保鸡丁",
            confidence: 0.92,
            language: "zh"
        )
    }

    // MARK: - 内存估算

    var estimatedMemoryMB: Int {
        let baseMemory = 50
        let loadedCount = models.values.filter { $0.status == .loaded }.count
        let modelMemory = loadedCount * 80
        return baseMemory + modelMemory
    }
}
