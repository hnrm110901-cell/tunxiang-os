/// ResponseHelpers.swift — 统一响应格式
///
/// 所有接口统一返回 { "ok": bool, "data": {}, "error": {} }
/// 遵循 CLAUDE.md 第十节 API 设计规范

import Vapor

// MARK: - AnyCodable（轻量级类型擦除）

/// 用于构建动态 JSON 响应的类型擦除包装
struct AnyCodable: Codable, Sendable {
    private let value: Any

    init(_ value: Any) {
        self.value = value
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.singleValueContainer()
        if let v = try? container.decode(Bool.self) { value = v }
        else if let v = try? container.decode(Int.self) { value = v }
        else if let v = try? container.decode(Double.self) { value = v }
        else if let v = try? container.decode(String.self) { value = v }
        else if let v = try? container.decode([AnyCodable].self) { value = v }
        else if let v = try? container.decode([String: AnyCodable].self) { value = v }
        else { value = NSNull() }
    }

    func encode(to encoder: Encoder) throws {
        var container = encoder.singleValueContainer()
        switch value {
        case let v as Bool: try container.encode(v)
        case let v as Int: try container.encode(v)
        case let v as Double: try container.encode(v)
        case let v as String: try container.encode(v)
        case let v as [Any]:
            try container.encode(v.map { AnyCodable($0) })
        case let v as [String]:
            try container.encode(v)
        case let v as [String: AnyCodable]:
            try container.encode(v)
        case let v as [String: Any]:
            try container.encode(v.mapValues { AnyCodable($0) })
        default:
            try container.encodeNil()
        }
    }
}

// MARK: - 统一响应构建器

/// 构建成功响应 { "ok": true, "data": { ... } }
func makeOkResponse(data: [String: AnyCodable]) throws -> Response {
    let body: [String: AnyCodable] = [
        "ok": AnyCodable(true),
        "data": AnyCodable(data),
    ]
    let jsonData = try JSONEncoder().encode(body)
    var headers = HTTPHeaders()
    headers.add(name: .contentType, value: "application/json")
    return Response(status: .ok, headers: headers, body: .init(data: jsonData))
}

/// 构建错误响应 { "ok": false, "error": { "code": "...", "message": "..." } }
func makeErrorResponse(status: HTTPResponseStatus, code: String, message: String) throws -> Response {
    let body: [String: AnyCodable] = [
        "ok": AnyCodable(false),
        "error": AnyCodable([
            "code": AnyCodable(code),
            "message": AnyCodable(message),
        ]),
    ]
    let jsonData = try JSONEncoder().encode(body)
    var headers = HTTPHeaders()
    headers.add(name: .contentType, value: "application/json")
    return Response(status: status, headers: headers, body: .init(data: jsonData))
}
