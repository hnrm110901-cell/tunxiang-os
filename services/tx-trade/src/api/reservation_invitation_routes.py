"""预订邀请函 / 核餐外呼 HTTP 路由（Sprint R2 Track A）

端点：
    POST /api/v1/reservation-invitations
        创建邀请记录（status=pending）
    GET  /api/v1/reservation-invitations?reservation_id=...
        按预订 ID 查询历史邀请记录
    GET  /api/v1/reservation-invitations/{invitation_id}
        查询单条邀请记录
    POST /api/v1/reservation-invitations/{invitation_id}/sent
        标记已发出（发 INVITATION_SENT / CONFIRM_CALL_SENT 事件）
    POST /api/v1/reservation-invitations/{invitation_id}/confirm
        客户确认（发 reservation.confirmed 事件）
    POST /api/v1/reservation-invitations/{invitation_id}/fail
        发送失败（不发业务事件，仅留痕）

统一响应：{"ok": bool, "data": {...}, "error": {...}}
统一鉴权：X-Tenant-ID（缺失返回 400）
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from shared.ontology.src.extensions.reservation_invitations import (
    InvitationChannel,
)

from ..repositories.reservation_invitation_repo import (
    InMemoryInvitationRepository,
    InvitationRepositoryBase,
)
from ..services.reservation_invitation_service import (
    InvalidInvitationTransitionError,
    InvitationNotFoundError,
    ReservationInvitationService,
)

logger = structlog.get_logger(__name__)
router = APIRouter(
    prefix="/api/v1/reservation-invitations", tags=["reservation-invitation"]
)


# ──────────────────────────────────────────────────────────────────────────
# 工具
# ──────────────────────────────────────────────────────────────────────────


def _ok(data: Any) -> dict[str, Any]:
    return {"ok": True, "data": data, "error": None}


def _err(msg: str, code: str = "BAD_REQUEST") -> dict[str, Any]:
    return {"ok": False, "data": None, "error": {"code": code, "message": msg}}


def _require_tenant(request: Request) -> uuid.UUID:
    raw = getattr(request.state, "tenant_id", None) or request.headers.get(
        "X-Tenant-ID", ""
    )
    if not raw:
        raise HTTPException(status_code=400, detail="Missing X-Tenant-ID")
    try:
        return uuid.UUID(str(raw))
    except ValueError as exc:
        raise HTTPException(
            status_code=400, detail=f"Invalid X-Tenant-ID: {exc}"
        ) from exc


def _optional_store_id(request: Request) -> Optional[uuid.UUID]:
    raw = request.headers.get("X-Store-ID", "")
    if not raw:
        return None
    try:
        return uuid.UUID(raw)
    except ValueError:
        return None


# 进程内默认 repo（生产环境由 lifespan 注入 Pg 版本）
_default_repo: InvitationRepositoryBase = InMemoryInvitationRepository()


def get_repo() -> InvitationRepositoryBase:
    """Repository provider。路由测试可通过 app.dependency_overrides 替换。"""
    return _default_repo


def get_service(
    repo: InvitationRepositoryBase = Depends(get_repo),
) -> ReservationInvitationService:
    return ReservationInvitationService(repo=repo)


# ──────────────────────────────────────────────────────────────────────────
# 请求模型
# ──────────────────────────────────────────────────────────────────────────


class CreateInvitationReq(BaseModel):
    reservation_id: uuid.UUID = Field(..., description="关联预订ID")
    channel: InvitationChannel = Field(..., description="发送通道")
    customer_id: Optional[uuid.UUID] = Field(default=None, description="客户ID")
    coupon_code: Optional[str] = Field(
        default=None, max_length=64, description="附带券码"
    )
    coupon_value_fen: int = Field(default=0, ge=0, description="券面值（分）")
    payload: dict[str, Any] = Field(default_factory=dict, description="通道附加上下文")
    source_event_id: Optional[uuid.UUID] = Field(
        default=None, description="触发事件ID（可选）"
    )


class MarkSentReq(BaseModel):
    sent_at: Optional[datetime] = Field(default=None, description="发送时间（可选）")


class MarkConfirmedReq(BaseModel):
    confirmed_at: Optional[datetime] = Field(
        default=None, description="确认时间（可选）"
    )


class MarkFailedReq(BaseModel):
    failure_reason: str = Field(..., min_length=1, max_length=200)


# ──────────────────────────────────────────────────────────────────────────
# 端点
# ──────────────────────────────────────────────────────────────────────────


@router.post("")
async def create_invitation(
    payload: CreateInvitationReq,
    request: Request,
    service: ReservationInvitationService = Depends(get_service),
) -> dict[str, Any]:
    tenant_id = _require_tenant(request)
    store_id = _optional_store_id(request)
    try:
        record = await service.create_invitation(
            tenant_id=tenant_id,
            reservation_id=payload.reservation_id,
            channel=payload.channel,
            customer_id=payload.customer_id,
            store_id=store_id,
            coupon_code=payload.coupon_code,
            coupon_value_fen=payload.coupon_value_fen,
            payload=payload.payload,
            source_event_id=payload.source_event_id,
        )
    except ValueError as exc:
        return _err(str(exc), code="VALIDATION_ERROR")
    return _ok(record.model_dump(mode="json"))


@router.get("")
async def list_invitations(
    request: Request,
    reservation_id: uuid.UUID = Query(..., description="预订ID"),
    service: ReservationInvitationService = Depends(get_service),
) -> dict[str, Any]:
    tenant_id = _require_tenant(request)
    items = await service.list_by_reservation(
        tenant_id=tenant_id, reservation_id=reservation_id
    )
    return _ok(
        {
            "items": [i.model_dump(mode="json") for i in items],
            "total": len(items),
        }
    )


@router.get("/{invitation_id}")
async def get_invitation(
    invitation_id: uuid.UUID,
    request: Request,
    service: ReservationInvitationService = Depends(get_service),
) -> dict[str, Any]:
    tenant_id = _require_tenant(request)
    try:
        record = await service.get(invitation_id=invitation_id, tenant_id=tenant_id)
    except InvitationNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _ok(record.model_dump(mode="json"))


@router.post("/{invitation_id}/sent")
async def mark_sent(
    invitation_id: uuid.UUID,
    payload: MarkSentReq,
    request: Request,
    service: ReservationInvitationService = Depends(get_service),
) -> dict[str, Any]:
    tenant_id = _require_tenant(request)
    try:
        record = await service.mark_sent(
            invitation_id=invitation_id,
            tenant_id=tenant_id,
            sent_at=payload.sent_at,
        )
    except InvitationNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except InvalidInvitationTransitionError as exc:
        return _err(str(exc), code=exc.code)
    return _ok(record.model_dump(mode="json"))


@router.post("/{invitation_id}/confirm")
async def confirm(
    invitation_id: uuid.UUID,
    payload: MarkConfirmedReq,
    request: Request,
    service: ReservationInvitationService = Depends(get_service),
) -> dict[str, Any]:
    tenant_id = _require_tenant(request)
    try:
        record = await service.mark_confirmed(
            invitation_id=invitation_id,
            tenant_id=tenant_id,
            confirmed_at=payload.confirmed_at,
        )
    except InvitationNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except InvalidInvitationTransitionError as exc:
        return _err(str(exc), code=exc.code)
    return _ok(record.model_dump(mode="json"))


@router.post("/{invitation_id}/fail")
async def mark_failed(
    invitation_id: uuid.UUID,
    payload: MarkFailedReq,
    request: Request,
    service: ReservationInvitationService = Depends(get_service),
) -> dict[str, Any]:
    tenant_id = _require_tenant(request)
    try:
        record = await service.mark_failed(
            invitation_id=invitation_id,
            tenant_id=tenant_id,
            failure_reason=payload.failure_reason,
        )
    except InvitationNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except InvalidInvitationTransitionError as exc:
        return _err(str(exc), code=exc.code)
    except ValueError as exc:
        return _err(str(exc), code="VALIDATION_ERROR")
    return _ok(record.model_dump(mode="json"))


__all__ = ["router"]
