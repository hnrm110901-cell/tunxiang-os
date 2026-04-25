"""channel_dispute_routes — Sprint E4 渠道异议工作流 HTTP 端点

POST /api/v1/channels/disputes/open
  - 打开异议（自动接受 ≤ tenant 阈值；否则 pending）
  - 鉴权：JWT + role ∈ {integration, store_manager, admin}

POST /api/v1/channels/disputes/{id}/resolve
  - 人工裁决（accepted / rejected / escalated）
  - 鉴权：JWT + role ∈ {store_manager, admin}
  - 重复裁决 → 409 ALREADY_RESOLVED

GET  /api/v1/channels/disputes
  - 分页列表（可按 state / store_id 过滤）
  - 鉴权：role ∈ {viewer, store_manager, admin, integration}

设计：响应统一 {ok, data, error}，三方租户一致性强校验。
"""

from __future__ import annotations

from typing import Optional

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Path, Query, Request
from pydantic import BaseModel
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

from ..schemas.channel_dispute import (
    DEFAULT_AUTO_ACCEPT_THRESHOLD_FEN,
    DisputeListResponse,
    OpenDisputeRequest,
    ResolveDisputeRequest,
)
from ..security.rbac import UserContext, require_role
from ..services.channel_dispute_service import (
    ChannelDisputeService,
    DisputeAlreadyResolvedError,
    DisputeNotFoundError,
)

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/channels/disputes", tags=["channel-dispute"])


class StandardResponse(BaseModel):
    ok: bool
    data: Optional[dict] = None
    error: Optional[dict] = None


def _ok(data: dict | BaseModel | None) -> StandardResponse:
    if isinstance(data, BaseModel):
        return StandardResponse(ok=True, data=data.model_dump(mode="json"))
    return StandardResponse(ok=True, data=data)


def _check_tenant_consistency(
    *, header_tenant: str, body_tenant: str, user: UserContext
) -> None:
    if header_tenant != body_tenant:
        logger.warning(
            "channel_dispute_tenant_mismatch_header",
            header_tenant=header_tenant,
            body_tenant=body_tenant,
            user_id=user.user_id,
        )
        raise HTTPException(status_code=403, detail="TENANT_MISMATCH")
    if user.tenant_id and user.tenant_id != body_tenant:
        logger.warning(
            "channel_dispute_tenant_mismatch_user",
            user_tenant=user.tenant_id,
            body_tenant=body_tenant,
            user_id=user.user_id,
        )
        raise HTTPException(status_code=403, detail="USER_TENANT_MISMATCH")


# ─── 路由 ────────────────────────────────────────────────────────────────────


@router.post("/open", response_model=StandardResponse)
async def open_dispute(
    body: OpenDisputeRequest,
    request: Request,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
    user: UserContext = Depends(
        require_role("integration", "store_manager", "admin")
    ),
) -> StandardResponse:
    """打开异议；小额自动接受，大额走人工 pending。

    auto_accept_threshold 当前由代码常量提供（决策点 #5 默认 5000 分），
    后续将从 tenant_setting 读取以实现按租户覆盖。
    """
    _check_tenant_consistency(
        header_tenant=x_tenant_id,
        body_tenant=str(body.tenant_id),
        user=user,
    )

    svc = ChannelDisputeService(db, tenant_id=str(body.tenant_id))
    try:
        record, created = await svc.open_dispute(
            body, auto_accept_threshold_fen=DEFAULT_AUTO_ACCEPT_THRESHOLD_FEN
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": "INVALID_REQUEST", "message": str(exc)},
        )
    except SQLAlchemyError:
        logger.exception(
            "channel_dispute_open_db_error",
            external_dispute_id=body.external_dispute_id,
        )
        raise HTTPException(
            status_code=500,
            detail={"code": "DB_ERROR", "message": "dispute open failed"},
        )

    return _ok({"record": record.model_dump(mode="json"), "created": created})


@router.post("/{dispute_id}/resolve", response_model=StandardResponse)
async def resolve_dispute(
    body: ResolveDisputeRequest,
    dispute_id: str = Path(..., min_length=1, max_length=64),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
    user: UserContext = Depends(require_role("store_manager", "admin")),
) -> StandardResponse:
    """人工裁决。仅 pending / manual_reviewing 可被裁决。"""
    _check_tenant_consistency(
        header_tenant=x_tenant_id,
        body_tenant=str(body.tenant_id),
        user=user,
    )

    svc = ChannelDisputeService(db, tenant_id=str(body.tenant_id))
    try:
        record = await svc.resolve_dispute(
            dispute_id=dispute_id,
            decision=body.decision,
            reason=body.reason,
            operator_id=user.user_id,
        )
    except DisputeNotFoundError:
        raise HTTPException(
            status_code=404,
            detail={"code": "NOT_FOUND", "message": "dispute not found"},
        )
    except DisputeAlreadyResolvedError as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": "ALREADY_RESOLVED", "message": str(exc)},
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": "INVALID_DECISION", "message": str(exc)},
        )
    except SQLAlchemyError:
        logger.exception("channel_dispute_resolve_db_error", id=dispute_id)
        raise HTTPException(
            status_code=500,
            detail={"code": "DB_ERROR", "message": "dispute resolve failed"},
        )

    return _ok({"record": record.model_dump(mode="json")})


@router.get("", response_model=StandardResponse)
async def list_disputes(
    request: Request,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    store_id: Optional[str] = Query(default=None, max_length=64),
    state: Optional[list[str]] = Query(default=None),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    user: UserContext = Depends(
        require_role("viewer", "store_manager", "admin", "integration")
    ),
) -> StandardResponse:
    if user.tenant_id and user.tenant_id != x_tenant_id:
        raise HTTPException(status_code=403, detail="USER_TENANT_MISMATCH")

    svc = ChannelDisputeService(db, tenant_id=x_tenant_id)
    try:
        records, total = await svc.list_pending(
            store_id=store_id, states=state, page=page, size=size
        )
    except SQLAlchemyError:
        logger.exception("channel_dispute_list_db_error", tenant_id=x_tenant_id)
        raise HTTPException(
            status_code=500,
            detail={"code": "DB_ERROR", "message": "dispute list failed"},
        )

    resp = DisputeListResponse(
        items=records, total=total, page=page, size=size
    )
    return _ok(resp)
