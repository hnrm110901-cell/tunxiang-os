"""
HR 数字人助手 API

端点：
  POST /api/v1/hr/assistant/chat                     发消息
  GET  /api/v1/hr/assistant/conversations/my          我的对话列表
  POST /api/v1/hr/assistant/conversations/{id}/close  关闭对话
  POST /api/v1/hr/assistant/conversations/{id}/feedback 反馈
  GET  /api/v1/hr/assistant/suggested-questions       推荐问题
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.database import get_db
from ..core.dependencies import get_current_active_user
from ..models.hr_assistant import HRConversation, HRMessage
from ..models.user import User
from ..services.hr_assistant_agent import HRAssistantAgent

router = APIRouter(prefix="/api/v1/hr/assistant", tags=["hr-assistant"])
logger = structlog.get_logger()

_agent = HRAssistantAgent()


# ═══════════════════════════════════════════════════════════════
# Schemas
# ═══════════════════════════════════════════════════════════════

class ChatRequest(BaseModel):
    conversation_id: Optional[str] = None
    message: str = Field(..., min_length=1, max_length=2000)
    confirm_token: Optional[Dict[str, Any]] = None  # 二次确认时回传 {tool, args}


class ChatResponse(BaseModel):
    conversation_id: str
    reply: str
    tool_invocations: List[Dict[str, Any]] = []
    suggested_actions: List[str] = []
    pending_confirm: Optional[Dict[str, Any]] = None
    ok: bool = True


class FeedbackRequest(BaseModel):
    score: int = Field(..., ge=-1, le=1)  # 1 好评 / -1 差评
    reason: Optional[str] = Field(None, max_length=500)


# ═══════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════

def _employee_id(user: User) -> str:
    """当前用户的 employee_id（兼容不同 schema）"""
    return str(getattr(user, "employee_id", None) or user.id)


async def _get_or_create_conversation(
    db: AsyncSession, conversation_id: Optional[str], employee_id: str
) -> HRConversation:
    now = datetime.utcnow()
    if conversation_id:
        try:
            row = (await db.execute(
                select(HRConversation).where(HRConversation.id == uuid.UUID(conversation_id))
            )).scalar_one_or_none()
            if row and row.employee_id == employee_id and row.status == "active":
                row.last_active_at = now
                return row
        except Exception:
            pass
    conv = HRConversation(
        id=uuid.uuid4(),
        employee_id=employee_id,
        started_at=now,
        last_active_at=now,
        status="active",
        message_count=0,
    )
    db.add(conv)
    await db.flush()
    return conv


async def _persist_message(
    db: AsyncSession, conv: HRConversation, role: str, content: str,
    tool_calls: Optional[List[Dict[str, Any]]] = None,
) -> None:
    msg = HRMessage(
        id=uuid.uuid4(),
        conversation_id=conv.id,
        role=role,
        content=content,
        tool_calls_json=tool_calls,
        occurred_at=datetime.utcnow(),
    )
    db.add(msg)
    conv.message_count = (conv.message_count or 0) + 1


# ═══════════════════════════════════════════════════════════════
# Endpoints
# ═══════════════════════════════════════════════════════════════

@router.post("/chat", response_model=ChatResponse, summary="发送消息")
async def chat(
    body: ChatRequest,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    employee_id = _employee_id(current_user)
    conv = await _get_or_create_conversation(db, body.conversation_id, employee_id)

    try:
        await _persist_message(db, conv, "user", body.message)
        result = await _agent.chat(
            current_user_id=employee_id,
            message=body.message,
            conversation_id=str(conv.id),
            confirm_token=body.confirm_token,
        )
        await _persist_message(
            db, conv, "assistant", result.get("reply", ""),
            tool_calls=result.get("tool_invocations"),
        )
        await db.commit()
    except Exception as exc:
        await db.rollback()
        logger.exception("hr_chat.failed", employee_id=employee_id)
        raise HTTPException(status_code=500, detail="对话处理失败，请稍后再试") from exc

    return ChatResponse(
        conversation_id=str(conv.id),
        reply=result.get("reply", ""),
        tool_invocations=result.get("tool_invocations", []),
        suggested_actions=result.get("suggested_actions", []),
        pending_confirm=result.get("pending_confirm"),
        ok=result.get("ok", True),
    )


@router.get("/conversations/my", summary="我的对话列表")
async def my_conversations(
    limit: int = 20,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    employee_id = _employee_id(current_user)
    rows = (
        await db.execute(
            select(HRConversation)
            .where(HRConversation.employee_id == employee_id)
            .order_by(HRConversation.last_active_at.desc())
            .limit(max(1, min(limit, 100)))
        )
    ).scalars().all()
    return [
        {
            "id": str(r.id),
            "started_at": r.started_at.isoformat(),
            "last_active_at": r.last_active_at.isoformat(),
            "status": r.status,
            "message_count": r.message_count,
            "summary": r.summary,
        }
        for r in rows
    ]


@router.post("/conversations/{conv_id}/close", summary="关闭对话")
async def close_conversation(
    conv_id: str,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    employee_id = _employee_id(current_user)
    try:
        row = (await db.execute(
            select(HRConversation).where(HRConversation.id == uuid.UUID(conv_id))
        )).scalar_one_or_none()
    except Exception:
        raise HTTPException(status_code=400, detail="非法 conversation_id")
    if row is None or row.employee_id != employee_id:
        raise HTTPException(status_code=404, detail="对话不存在")
    row.status = "closed"
    await db.commit()
    return {"ok": True}


@router.post("/conversations/{conv_id}/feedback", summary="对话反馈")
async def feedback(
    conv_id: str,
    body: FeedbackRequest,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    employee_id = _employee_id(current_user)
    try:
        row = (await db.execute(
            select(HRConversation).where(HRConversation.id == uuid.UUID(conv_id))
        )).scalar_one_or_none()
    except Exception:
        raise HTTPException(status_code=400, detail="非法 conversation_id")
    if row is None or row.employee_id != employee_id:
        raise HTTPException(status_code=404, detail="对话不存在")
    row.feedback_score = body.score
    row.feedback_reason = body.reason
    await db.commit()
    return {"ok": True}


@router.get("/suggested-questions", summary="首屏推荐问题")
async def suggested_questions(
    current_user: User = Depends(get_current_active_user),
):
    return {"questions": _agent.suggested_questions()}
