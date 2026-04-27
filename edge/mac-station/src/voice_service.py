"""Voice Service — 语音指令识别与意图解析

职责：
1. Whisper 语音转文字（本地模型，graceful fallback to mock）
2. 中文餐饮场景意图解析（正则 + 关键词匹配）
3. 语音指令一站式流水线：录音 → 转写 → 意图 → Agent 路由
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import Any

import structlog

logger = structlog.get_logger()


# ─── Data Models ───


@dataclass
class TranscriptionResult:
    text: str
    language: str
    confidence: float
    duration_ms: int
    source: str  # "whisper" or "mock"


@dataclass
class IntentResult:
    intent: str
    entities: dict[str, Any]
    confidence: float
    suggested_action: dict[str, Any]


@dataclass
class VoiceCommandResult:
    transcription: TranscriptionResult
    intent: IntentResult
    agent_result: dict[str, Any] | None = None


# ─── Intent → Agent Action 映射 ───

INTENT_AGENT_MAP: dict[str, dict[str, str]] = {
    "open_table": {"agent_id": "serve_dispatch", "action": "assign_table"},
    "add_dish": {"agent_id": "smart_menu", "action": "recommend_dishes"},
    "checkout": {"agent_id": "", "action": "direct_trade_api"},
    "rush_order": {"agent_id": "serve_dispatch", "action": "prioritize_order"},
    "cancel_dish": {"agent_id": "", "action": "direct_trade_api"},
    "call_service": {"agent_id": "smart_service", "action": "handle_request"},
    "query_status": {"agent_id": "serve_dispatch", "action": "get_kitchen_status"},
    "daily_report": {"agent_id": "finance_audit", "action": "daily_summary"},
    "stock_check": {"agent_id": "inventory_alert", "action": "check_stock"},
}


# ─── VoiceService ───


class VoiceService:
    """语音服务核心类：转写 + 意图解析 + 指令流水线"""

    def __init__(self) -> None:
        self.whisper_model: Any | None = None
        self._whisper_available: bool = False

        # 意图正则模式（按优先级排列，先匹配先命中）
        self.intent_patterns: list[tuple[str, list[re.Pattern[str]]]] = self._build_intent_patterns()

    # ─── 模型加载 ───

    def _load_whisper(self, model_name: str = "base") -> bool:
        """延迟加载 Whisper 模型。加载失败返回 False（降级到 mock）。"""
        if self.whisper_model is not None:
            return self._whisper_available
        try:
            import whisper  # type: ignore[import-untyped]

            logger.info("whisper_loading", model=model_name)
            self.whisper_model = whisper.load_model(model_name)
            self._whisper_available = True
            logger.info("whisper_loaded", model=model_name)
            return True
        except ImportError:
            logger.warning("whisper_not_installed", hint="pip install openai-whisper")
            self._whisper_available = False
            return False
        except RuntimeError as exc:
            logger.warning("whisper_load_failed", error=str(exc))
            self._whisper_available = False
            return False

    # ─── 转写 ───

    async def transcribe(self, audio_bytes: bytes, language: str = "zh") -> TranscriptionResult:
        """将音频字节流转写为文字。Whisper 不可用时返回 mock 结果。"""
        start = time.monotonic()

        if self._load_whisper():
            return await self._transcribe_whisper(audio_bytes, language, start)
        return self._transcribe_mock(language, start)

    async def _transcribe_whisper(self, audio_bytes: bytes, language: str, start: float) -> TranscriptionResult:
        """使用本地 Whisper 模型进行转写。"""
        import os
        import tempfile

        # Whisper 需要文件路径，写入临时文件
        tmp_path = ""
        try:
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                tmp.write(audio_bytes)
                tmp_path = tmp.name

            result = self.whisper_model.transcribe(tmp_path, language=language)
            elapsed_ms = int((time.monotonic() - start) * 1000)

            text: str = result.get("text", "").strip()
            # Whisper 不直接给单次置信度，用 segments 平均 no_speech_prob 反推
            segments = result.get("segments", [])
            if segments:
                avg_no_speech = sum(s.get("no_speech_prob", 0.0) for s in segments) / len(segments)
                confidence = round(1.0 - avg_no_speech, 4)
            else:
                confidence = 0.0

            logger.info("whisper_transcribed", language=language, length=len(text), ms=elapsed_ms)
            return TranscriptionResult(
                text=text,
                language=language,
                confidence=confidence,
                duration_ms=elapsed_ms,
                source="whisper",
            )
        except (OSError, RuntimeError, ValueError) as exc:
            logger.error("whisper_transcribe_error", error=str(exc))
            return self._transcribe_mock(language, start)
        finally:
            if tmp_path:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass

    def _transcribe_mock(self, language: str, start: float) -> TranscriptionResult:
        """Mock 转写结果（Whisper 不可用时）。"""
        elapsed_ms = int((time.monotonic() - start) * 1000)
        mock_text = "5号桌加一份红烧肉" if language == "zh" else "Add one braised pork to table five"
        logger.info("mock_transcribed", language=language)
        return TranscriptionResult(
            text=mock_text,
            language=language,
            confidence=0.0,
            duration_ms=elapsed_ms,
            source="mock",
        )

    # ─── 意图解析 ───

    @staticmethod
    def _build_intent_patterns() -> list[tuple[str, list[re.Pattern[str]]]]:
        """构建中文意图识别的正则模式列表。"""
        return [
            # ── open_table: 开台 / 开桌 ──
            (
                "open_table",
                [
                    re.compile(r"(?P<table_no>\d+)\s*号?\s*桌?\s*(开台|开桌)"),
                    re.compile(r"(开台|开桌)\s*(?P<table_no>\d+)\s*号?\s*桌?"),
                    re.compile(r"(开台|开桌)"),
                ],
            ),
            # ── checkout: 买单 / 结账 ──
            (
                "checkout",
                [
                    re.compile(r"(?P<table_no>\d+)\s*号?\s*桌?\s*(买单|结账|结帐|埋单)"),
                    re.compile(r"(买单|结账|结帐|埋单)\s*(?P<table_no>\d+)\s*号?\s*桌?"),
                    re.compile(r"(买单|结账|结帐|埋单)"),
                ],
            ),
            # ── rush_order: 催菜 / 催一下 ──
            (
                "rush_order",
                [
                    re.compile(r"(?P<table_no>\d+)\s*号?\s*桌?\s*(催菜|催一下|催单)"),
                    re.compile(r"(催菜|催一下|催单)\s*(?P<table_no>\d+)\s*号?\s*桌?"),
                    re.compile(r"(催菜|催一下|催单)"),
                ],
            ),
            # ── cancel_dish: 退菜 / 取消 ──
            (
                "cancel_dish",
                [
                    re.compile(
                        r"(退|取消)\s*(?P<quantity>[一二两三四五六七八九十\d]+)?\s*[份个道]?\s*(?P<dish_name>[\u4e00-\u9fff]{2,})"
                    ),
                    re.compile(r"(?P<dish_name>[\u4e00-\u9fff]{2,})\s*(退了|不要了|取消)"),
                    re.compile(r"(退菜|退掉)"),
                ],
            ),
            # ── add_dish: 加菜 / 来个 / 加一份 ──
            (
                "add_dish",
                [
                    re.compile(
                        r"(?P<table_no>\d+)\s*号?\s*桌?\s*(加|来|上)\s*(?P<quantity>[一二两三四五六七八九十\d]+)?\s*[份个道]?\s*(?P<dish_name>[\u4e00-\u9fff]{2,})"
                    ),
                    re.compile(
                        r"(加|来|上|再来)\s*(?P<quantity>[一二两三四五六七八九十\d]+)\s*[份个道]\s*(?P<dish_name>[\u4e00-\u9fff]{2,})"
                    ),
                    re.compile(
                        r"(?P<dish_name>[\u4e00-\u9fff]{2,})\s*(来|要)\s*(?P<quantity>[一二两三四五六七八九十\d]+)\s*[份个道]"
                    ),
                    re.compile(r"(加菜|加个|来个|来一个|来份|来一份|上一份)\s*(?P<dish_name>[\u4e00-\u9fff]{2,})?"),
                ],
            ),
            # ── call_service: 叫服务员 ──
            (
                "call_service",
                [
                    re.compile(r"(服务员|叫一下服务员|呼叫服务员|叫服务员)"),
                ],
            ),
            # ── query_status: 查询状态 ──
            (
                "query_status",
                [
                    re.compile(r"(?P<table_no>\d+)\s*号?\s*桌?\s*(什么情况|什么状态|怎么样了|状态|情况)"),
                    re.compile(r"(查一下|查看|查询)\s*(订单|桌台|状态|情况)"),
                    re.compile(r"(订单|桌台).*(查|看|状态)"),
                ],
            ),
            # ── daily_report: 营业额查询 ──
            (
                "daily_report",
                [
                    re.compile(
                        r"(今天|今日|昨天|昨日|本周|这周|本月|这个月)\s*(营业额|收入|流水|卖了多少|营收|销售额)"
                    ),
                    re.compile(r"(营业额|收入|流水|营收|销售额)\s*(多少|是多少|怎么样|如何|报表|报告)"),
                    re.compile(r"(日报|日结|营业报表|经营报表|营业报告)"),
                ],
            ),
            # ── stock_check: 库存查询 ──
            (
                "stock_check",
                [
                    re.compile(r"(?P<dish_name>[\u4e00-\u9fff]{2,})\s*(还有多少|还有吗|还有没有|库存|剩多少|还剩)"),
                    re.compile(r"(库存|存货)\s*(查一下|查看|查询|怎么样|多少)"),
                    re.compile(r"(查一下|查看|查询)\s*(库存|存货)"),
                    re.compile(r"(?P<dish_name>[\u4e00-\u9fff]{2,})\s*(有没有|有多少|够不够)"),
                ],
            ),
        ]

    async def parse_intent(self, text: str) -> IntentResult:
        """解析文本中的餐饮场景意图和实体。"""
        if not text or not text.strip():
            return IntentResult(
                intent="unknown",
                entities={},
                confidence=0.0,
                suggested_action={},
            )

        text = text.strip()

        for intent_name, patterns in self.intent_patterns:
            for pattern in patterns:
                match = pattern.search(text)
                if match:
                    entities = self._extract_entities(match)
                    confidence = 0.95 if entities else 0.85
                    action_map = INTENT_AGENT_MAP.get(intent_name, {})
                    suggested_action = {
                        "agent_id": action_map.get("agent_id", ""),
                        "action": action_map.get("action", ""),
                        "params": entities,
                    }
                    logger.info(
                        "intent_parsed",
                        intent=intent_name,
                        entities=entities,
                        confidence=confidence,
                    )
                    return IntentResult(
                        intent=intent_name,
                        entities=entities,
                        confidence=confidence,
                        suggested_action=suggested_action,
                    )

        logger.info("intent_unknown", text=text)
        return IntentResult(
            intent="unknown",
            entities={},
            confidence=0.0,
            suggested_action={},
        )

    @staticmethod
    def _extract_entities(match: re.Match[str]) -> dict[str, Any]:
        """从正则匹配中提取实体（桌号、菜名、数量等）。"""
        entities: dict[str, Any] = {}
        groupdict = match.groupdict()

        if groupdict.get("table_no"):
            entities["table_no"] = groupdict["table_no"]

        if groupdict.get("dish_name"):
            entities["dish_name"] = groupdict["dish_name"]

        if groupdict.get("quantity"):
            entities["quantity"] = _chinese_num_to_int(groupdict["quantity"])

        if groupdict.get("order_id"):
            entities["order_id"] = groupdict["order_id"]

        return entities

    # ─── 语音指令一站式流水线 ───

    async def execute_voice_command(self, audio_bytes: bytes, language: str = "zh") -> VoiceCommandResult:
        """完整流水线：音频 → 转写 → 意图解析 → Agent 路由。"""
        transcription = await self.transcribe(audio_bytes, language)
        intent = await self.parse_intent(transcription.text)

        # Agent 路由（当前返回 None，后续接入 Agent 框架）
        agent_result: dict[str, Any] | None = None
        if intent.intent != "unknown" and intent.suggested_action.get("agent_id"):
            agent_result = {
                "routed": True,
                "agent_id": intent.suggested_action["agent_id"],
                "action": intent.suggested_action["action"],
                "params": intent.suggested_action.get("params", {}),
                "status": "pending",
            }

        logger.info(
            "voice_command_executed",
            text=transcription.text,
            intent=intent.intent,
            routed=agent_result is not None,
        )
        return VoiceCommandResult(
            transcription=transcription,
            intent=intent,
            agent_result=agent_result,
        )


# ─── 辅助函数 ───

_CN_NUM_MAP: dict[str, int] = {
    "零": 0,
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
    "十": 10,
}


def _chinese_num_to_int(s: str) -> int:
    """将中文数字或阿拉伯数字字符串转为 int。"""
    s = s.strip()
    if s.isdigit():
        return int(s)

    # 简单中文数字处理（1-99）
    if len(s) == 1 and s in _CN_NUM_MAP:
        return _CN_NUM_MAP[s]

    # "十X" = 10+X, "X十" = X*10, "X十Y" = X*10+Y
    if "十" in s:
        parts = s.split("十")
        tens = _CN_NUM_MAP.get(parts[0], 1) if parts[0] else 1
        ones = _CN_NUM_MAP.get(parts[1], 0) if len(parts) > 1 and parts[1] else 0
        return tens * 10 + ones

    return 1  # fallback


# ─── FastAPI Router ───

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

router = APIRouter(prefix="/api/v1/voice", tags=["voice"])

# 模块级单例
_voice_service = VoiceService()


def get_voice_service() -> VoiceService:
    """获取 VoiceService 单例（方便测试替换）。"""
    return _voice_service


class ParseIntentRequest(BaseModel):
    text: str
    language: str = "zh"


class TranscriptionResponse(BaseModel):
    ok: bool = True
    data: dict[str, Any] = {}


@router.post("/transcribe")
async def transcribe_audio(
    file: UploadFile = File(...),
    language: str = Form("zh"),
) -> dict[str, Any]:
    """POST /api/v1/voice/transcribe — 语音转文字"""
    # 校验文件类型
    allowed_types = {
        "audio/wav",
        "audio/x-wav",
        "audio/wave",
        "audio/mp3",
        "audio/mpeg",
        "audio/m4a",
        "audio/x-m4a",
        "audio/mp4",
        "application/octet-stream",  # 兜底：部分客户端不设 MIME
    }
    content_type = file.content_type or "application/octet-stream"
    if content_type not in allowed_types:
        # 也允许通过文件扩展名判断
        filename = (file.filename or "").lower()
        if not any(filename.endswith(ext) for ext in (".wav", ".mp3", ".m4a")):
            raise HTTPException(
                status_code=400,
                detail={"code": "INVALID_AUDIO_FORMAT", "message": f"Unsupported audio format: {content_type}"},
            )

    if language not in ("zh", "en"):
        raise HTTPException(
            status_code=400,
            detail={"code": "INVALID_LANGUAGE", "message": f"Unsupported language: {language}. Use 'zh' or 'en'."},
        )

    audio_bytes = await file.read()
    if not audio_bytes:
        raise HTTPException(
            status_code=400,
            detail={"code": "EMPTY_AUDIO", "message": "Audio file is empty"},
        )

    svc = get_voice_service()
    result = await svc.transcribe(audio_bytes, language)

    return {
        "ok": True,
        "data": {
            "text": result.text,
            "language": result.language,
            "confidence": result.confidence,
            "duration_ms": result.duration_ms,
            "source": result.source,
        },
    }


@router.post("/parse-intent")
async def parse_intent(req: ParseIntentRequest) -> dict[str, Any]:
    """POST /api/v1/voice/parse-intent — 文本意图解析"""
    svc = get_voice_service()
    result = await svc.parse_intent(req.text)

    return {
        "ok": True,
        "data": {
            "intent": result.intent,
            "entities": result.entities,
            "confidence": result.confidence,
            "suggested_action": result.suggested_action,
        },
    }


@router.post("/command")
async def voice_command(
    file: UploadFile = File(...),
    language: str = Form("zh"),
) -> dict[str, Any]:
    """POST /api/v1/voice/command — 语音指令一站式流水线"""
    audio_bytes = await file.read()
    if not audio_bytes:
        raise HTTPException(
            status_code=400,
            detail={"code": "EMPTY_AUDIO", "message": "Audio file is empty"},
        )

    svc = get_voice_service()
    result = await svc.execute_voice_command(audio_bytes, language)

    return {
        "ok": True,
        "data": {
            "transcription": {
                "text": result.transcription.text,
                "language": result.transcription.language,
                "confidence": result.transcription.confidence,
                "duration_ms": result.transcription.duration_ms,
                "source": result.transcription.source,
            },
            "intent": {
                "intent": result.intent.intent,
                "entities": result.intent.entities,
                "confidence": result.intent.confidence,
                "suggested_action": result.intent.suggested_action,
            },
            "agent_result": result.agent_result,
        },
    }
