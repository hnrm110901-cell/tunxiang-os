/// HealthRoute.swift — 健康检查路由
///
/// GET /health
/// 输出: { "ok": true, "data": { "service": "coreml-bridge", "version": "1.0.0",
///         "models_loaded": [...], "neural_engine": true, "uptime_seconds": 3600 } }

import Vapor

func registerHealthRoutes(_ app: Application) {

    let manager = ModelManager.shared

    // MARK: GET /health

    app.get("health") { _ async throws -> Response in
        return try makeOkResponse(data: [
            "service": AnyCodable("coreml-bridge"),
            "version": AnyCodable("1.0.0"),
            "models_loaded": AnyCodable(manager.loadedModels),
            "neural_engine": AnyCodable(manager.neuralEngineAvailable),
            "uptime_seconds": AnyCodable(manager.uptimeSeconds),
            "memory_mb": AnyCodable(manager.estimatedMemoryMB),
        ])
    }
}
