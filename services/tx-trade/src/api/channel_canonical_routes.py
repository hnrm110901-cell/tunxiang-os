"""channel_canonical_routes — Sprint E1 渠道 canonical HTTP 端点

POST /api/v1/channels/canonical/orders
  - 落库一条 canonical 订单（幂等）
  - 鉴权：JWT + role ∈ {cashier, store_manager, admin, integration}
  - 三方租户一致性：X-Tenant-ID == JWT.tenant_id == body.tenant_id

GET  /api/v1/channels/canonical/orders
  - 分页列出（按 received_at 倒序）
  - 可选 store_id 过滤

GET  /api/v1/channels/canonical/orders/{id}
  - 单条读取

设计约束（红线：本路由为新增模块，不修改任何已存在路由/服务）：
  - 不调用 cashier_engine / order_service（避免触碰 Tier 1 路径）
  - 鉴权复用 src.security.rbac.require_role（现有依赖，零改动）
  - 响应统一 {ok, data, error}
"""

from __future__ import annotations

from typing import Optional

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Path, Query, Request
from pydantic import BaseModel
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

from ..schemas.channel_canonical import (
    CanonicalOrderListResponse,
    CanonicalOrderRequest,
)
from ..security.rbac import UserContext, require_role
from ..services.channel_canonical_service import ChannelCanonicalService

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/channels/canonical", tags=["channel-canonical"])


# ─── 响应包装 ────────────────────────────────────────────────────────────────


class StandardResponse(BaseModel):
    ok: bool
    data: Optional[dict] = None
    error: Optional[dict] = None


def _ok(data: dict | BaseModel | None) -> StandardResponse:
    if isinstance(data, BaseModel):
        return StandardResponse(ok=True, data=data.model_dump(mode="json"))
    return StandardResponse(ok=True, data=data)


def _check_tenant_consistency(
    *,
    header_tenant: str,
    body_tenant: str,
    user: UserContext,
) -> None:
    """三方租户一致：X-Tenant-ID / body.tenant_id / user.tenant_id。"""
    if header_tenant != body_tenant:
        logger.warning(
            "channel_canonical_tenant_mismatch_header",
            header_tenant=header_tenant,
            body_tenant=body_tenant,
            user_id=user.user_id,
        )
        raise HTTPException(status_code=403, detail="TENANT_MISMATCH")
    if user.tenant_id and user.tenant_id != body_tenant:
        logger.warning(
            "channel_canonical_tenant_mismatch_user",
            user_tenant=user.tenant_id,
            body_tenant=body_tenant,
            user_id=user.user_id,
        )
        raise HTTPException(status_code=403, detail="USER_TENANT_MISMATCH")


# ─── 路由 ────────────────────────────────────────────────────────────────────


@router.post("/orders", response_model=StandardResponse)
async def ingest_canonical_order(
    body: CanonicalOrderRequest,
    request: Request,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
    user: UserContext = Depends(
        require_role("cashier", "store_manager", "admin", "integration")
    ),
) -> StandardResponse:
    """落库 canonical 订单。

    幂等：(tenant, channel_code, external_order_id) 已存在 → 返回既有记录，
    不重复发事件。新落库时旁路 CHANNEL.ORDER_SYNCED。
    """
    _check_tenant_consistency(
        header_tenant=x_tenant_id,
        body_tenant=str(body.tenant_id),
        user=user,
    )

    svc = ChannelCanonicalService(db, tenant_id=str(body.tenant_id))
    try:
        record, created = await svc.ingest(body)
    except ValueError as exc:
        # 业务一致性失败（金额不匹配等）
        raise HTTPException(
            status_code=400,
            detail={"code": "INVALID_AMOUNTS", "message": str(exc)},
        )
    except SQLAlchemyError:
        logger.exception(
            "channel_canonical_db_error",
            channel_code=body.channel_code,
            external_order_id=body.external_order_id,
        )
        raise HTTPException(
            status_code=500,
            detail={"code": "DB_ERROR", "message": "canonical ingest failed"},
        )

    return _ok({"record": record.model_dump(mode="json"), "created": created})


@router.get("/orders", response_model=StandardResponse)
async def list_canonical_orders(
    request: Request,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    store_id: Optional[str] = Query(default=None, max_length=64),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    user: UserContext = Depends(
        require_role("cashier", "store_manager", "admin", "integration", "viewer")
    ),
) -> StandardResponse:
    """分页列出本租户 canonical 订单。"""
    if user.tenant_id and user.tenant_id != x_tenant_id:
        raise HTTPException(status_code=403, detail="USER_TENANT_MISMATCH")

    svc = ChannelCanonicalService(db, tenant_id=x_tenant_id)
    try:
        records, total = await svc.list_recent(
            store_id=store_id, page=page, size=size
        )
    except SQLAlchemyError:
        logger.exception("channel_canonical_list_db_error", tenant_id=x_tenant_id)
        raise HTTPException(
            status_code=500,
            detail={"code": "DB_ERROR", "message": "canonical list failed"},
        )

    resp = CanonicalOrderListResponse(
        items=records, total=total, page=page, size=size
    )
    return _ok(resp)


@router.get("/orders/{record_id}", response_model=StandardResponse)
async def get_canonical_order(
    record_id: str = Path(..., min_length=1, max_length=64),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
    user: UserContext = Depends(
        require_role("cashier", "store_manager", "admin", "integration", "viewer")
    ),
) -> StandardResponse:
    if user.tenant_id and user.tenant_id != x_tenant_id:
        raise HTTPException(status_code=403, detail="USER_TENANT_MISMATCH")

    svc = ChannelCanonicalService(db, tenant_id=x_tenant_id)
    try:
        record = await svc.get(record_id)
    except SQLAlchemyError:
        logger.exception(
            "channel_canonical_get_db_error",
            tenant_id=x_tenant_id,
            record_id=record_id,
        )
        raise HTTPException(
            status_code=500,
            detail={"code": "DB_ERROR", "message": "canonical get failed"},
        )

    if record is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "NOT_FOUND", "message": "canonical order not found"},
        )

    return _ok({"record": record.model_dump(mode="json")})
