"""Voice AI API Routes — 语音交互接口

Endpoints:
  POST /api/v1/voice/command      — Full pipeline (audio -> action -> response)
  POST /api/v1/voice/transcribe   — ASR only
  POST /api/v1/voice/understand   — NLU only
  POST /api/v1/voice/session      — Create session
  GET  /api/v1/voice/session/{id} — Get session state
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from ..services.voice_orchestrator import VoiceOrchestrator
from ..services.voice_session import VoiceSessionManager

router = APIRouter(prefix="/api/v1/voice", tags=["voice"])

# 模块级单例
_orchestrator = VoiceOrchestrator()
_session_mgr = VoiceSessionManager()


def get_orchestrator() -> VoiceOrchestrator:
    return _orchestrator


def get_session_manager() -> VoiceSessionManager:
    return _session_mgr


# ─── Request Models ──────────────────────────────────────────────


class UnderstandRequest(BaseModel):
    text: str
    context: dict[str, Any] | None = None


class CreateSessionRequest(BaseModel):
    employee_id: str
    store_id: str
    device_type: str = "pos"


# ─── Endpoints ───────────────────────────────────────────────────


@router.post("/command")
async def voice_command(
    file: UploadFile = File(...),
    language: str = Form("zh"),
    session_id: str = Form(""),
    store_id: str = Form(""),
    employee_id: str = Form(""),
) -> dict[str, Any]:
    """POST /api/v1/voice/command — 完整语音指令流水线

    audio → ASR → NLU → Dialog → Action → Response
    """
    audio_bytes = await file.read()
    if not audio_bytes:
        raise HTTPException(
            status_code=400,
            detail={"code": "EMPTY_AUDIO", "message": "Audio file is empty"},
        )

    if not store_id:
        raise HTTPException(
            status_code=400,
            detail={"code": "MISSING_STORE_ID", "message": "store_id is required"},
        )

    orch = get_orchestrator()

    # 自动创建会话
    if not session_id:
        sess = get_session_manager().create_session(
            employee_id=employee_id or "anonymous",
            store_id=store_id,
            device_type="pos",
        )
        session_id = sess["session_id"]

    result = await orch.process_voice_command(
        audio_bytes=audio_bytes,
        session_id=session_id,
        store_id=store_id,
        employee_id=employee_id or "anonymous",
        language=language,
    )

    # 记录对话轮次
    sm = get_session_manager()
    sm.add_turn(session_id, "user", result["transcription"]["text"])
    sm.add_turn(session_id, "system", result["response_text"])
    sm.update_context(session_id, {
        "last_intent": result["intent"],
        "entities": result["entities"],
    })

    return {"ok": True, "data": result}


@router.post("/transcribe")
async def transcribe_audio(
    file: UploadFile = File(...),
    language: str = Form("zh"),
) -> dict[str, Any]:
    """POST /api/v1/voice/transcribe — ASR only (语音转文字)"""
    allowed_types = {
        "audio/wav", "audio/x-wav", "audio/wave",
        "audio/mp3", "audio/mpeg",
        "audio/m4a", "audio/x-m4a", "audio/mp4",
        "application/octet-stream",
    }
    content_type = file.content_type or "application/octet-stream"
    if content_type not in allowed_types:
        filename = (file.filename or "").lower()
        if not any(filename.endswith(ext) for ext in (".wav", ".mp3", ".m4a")):
            raise HTTPException(
                status_code=400,
                detail={
                    "code": "INVALID_AUDIO_FORMAT",
                    "message": f"Unsupported: {content_type}",
                },
            )

    audio_bytes = await file.read()
    if not audio_bytes:
        raise HTTPException(
            status_code=400,
            detail={"code": "EMPTY_AUDIO", "message": "Audio file is empty"},
        )

    orch = get_orchestrator()
    result = await orch.transcribe(audio_bytes, language)
    return {"ok": True, "data": result}


@router.post("/understand")
async def understand_text(req: UnderstandRequest) -> dict[str, Any]:
    """POST /api/v1/voice/understand — NLU only (意图解析)"""
    if not req.text.strip():
        raise HTTPException(
            status_code=400,
            detail={"code": "EMPTY_TEXT", "message": "Text is empty"},
        )

    orch = get_orchestrator()
    result = await orch.understand(req.text, req.context)
    return {"ok": True, "data": result}


@router.post("/session")
async def create_session(req: CreateSessionRequest) -> dict[str, Any]:
    """POST /api/v1/voice/session — 创建语音会话"""
    sm = get_session_manager()
    session = sm.create_session(
        employee_id=req.employee_id,
        store_id=req.store_id,
        device_type=req.device_type,
    )
    return {"ok": True, "data": session}


@router.get("/session/{session_id}")
async def get_session(session_id: str) -> dict[str, Any]:
    """GET /api/v1/voice/session/{id} — 获取会话状态"""
    sm = get_session_manager()
    result = sm.get_session(session_id)
    if not result.get("ok"):
        raise HTTPException(
            status_code=404,
            detail={
                "code": "SESSION_NOT_FOUND",
                "message": result.get("error", "Session not found"),
            },
        )
    return {"ok": True, "data": result}
