/// TranscribeRoute.swift — 语音识别路由
///
/// POST /transcribe
/// 输入: multipart/form-data audio file (wav/m4a)
/// 输出: { "ok": true, "data": { "text": "来一份宫保鸡丁", "confidence": 0.92, "language": "zh" } }
///
/// 当前状态：Mock 模式，返回模拟识别结果
/// 生产计划：集成 Apple Speech framework 或 Whisper CoreML 模型

import Vapor

func registerTranscribeRoutes(_ app: Application) {

    let manager = ModelManager.shared

    // MARK: POST /transcribe

    app.on(.POST, "transcribe", body: .collect(maxSize: "10mb")) { req async throws -> Response in

        // 尝试从 multipart 表单中提取音频文件
        let audioData: Data
        let filename: String

        if let file = try? req.content.decode(FileUpload.self) {
            audioData = Data(buffer: file.audio.data)
            filename = file.audio.filename
        } else if let bodyData = req.body.data {
            audioData = Data(buffer: bodyData)
            filename = "audio.wav"
        } else {
            return try makeErrorResponse(
                status: .badRequest,
                code: "missing_audio",
                message: "请上传音频文件（multipart field 'audio' 或 raw body）"
            )
        }

        // 校验文件大小
        guard audioData.count > 0 else {
            return try makeErrorResponse(
                status: .badRequest,
                code: "empty_audio",
                message: "音频文件为空"
            )
        }

        // 校验文件扩展名
        let ext = (filename as NSString).pathExtension.lowercased()
        let allowedExtensions = ["wav", "m4a", "mp3", "aac", "flac"]
        if !ext.isEmpty, !allowedExtensions.contains(ext) {
            return try makeErrorResponse(
                status: .badRequest,
                code: "unsupported_format",
                message: "不支持的音频格式: \(ext)，支持: \(allowedExtensions.joined(separator: ", "))"
            )
        }

        req.logger.info("Transcribe request: file=\(filename), size=\(audioData.count) bytes")

        let result = manager.transcribe(audioData: audioData, filename: filename)

        return try makeOkResponse(data: [
            "text": AnyCodable(result.text),
            "confidence": AnyCodable(result.confidence),
            "language": AnyCodable(result.language),
        ])
    }
}

// MARK: - 文件上传 DTO

struct FileUpload: Content {
    let audio: File
}
