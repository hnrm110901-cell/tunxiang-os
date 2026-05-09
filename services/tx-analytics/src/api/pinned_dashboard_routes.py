"""驾驶舱 Pin 洞察 BFF — S4-04 Issue #291 PR2.C HTTP 路由。

POST   /api/v1/dashboard/pins         — 新增 Pin
GET    /api/v1/dashboard/pins         — 列出 tenant 的 active Pin（最新在前）
DELETE /api/v1/dashboard/pins/{pin_id} — 软删 Pin（幂等）

调用链：
  request → Depends(_get_db_with_tenant) 注入 AsyncSession + app.tenant_id
         → service 层 add_pin / list_pins / remove_pin
         → v403 dashboard_pinned 表（RLS USING + WITH CHECK 强制）

错误映射（CLAUDE.md §10 API 设计）：
  - ValueError → 400（payload 校验错，让上游修，不应触发告警）
  - 其他       → FastAPI 默认 500（捕获日志后由 GlobalExceptionHandler 兜底）
"""

from __future__ import annotations

from typing import Any, Optional

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db_with_tenant

from ..services.pinned_dashboard import add_pin, list_pins, remove_pin

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/api/v1/dashboard", tags=["dashboard-pinned"])


async def _get_db_with_tenant(
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> AsyncSession:
    """注入 AsyncSession + 设置 app.tenant_id（RLS 强制）。"""
    async for session in get_db_with_tenant(x_tenant_id):
        yield session


# ─────────────── Pydantic V2 schemas ───────────────


class CreatePinRequest(BaseModel):
    """新增 Pin 请求体 — A2UI surface_snapshot 必填，源信息可选。"""

    pinner_user_id: str = Field(..., min_length=1, description="操作人 UUID（决策留痕）")
    surface_snapshot: dict[str, Any] = Field(..., description="A2UI v0.8 declaration")
    source_query_id: Optional[str] = Field(default=None, max_length=64)
    source_natural_query: Optional[str] = Field(default=None)


class PinItemResponse(BaseModel):
    """Pin 响应（与 service 层 PinnedItem.to_dict 形态一致）。"""

    pin_id: str
    tenant_id: str
    pinner_user_id: str
    pinned_at: str  # ISO 8601
    surface_snapshot: dict[str, Any]
    source_query_id: Optional[str]
    source_natural_query: Optional[str]


class StandardResponse(BaseModel):
    """统一响应 envelope（CLAUDE.md §10 API 设计：{ok, data, error}）。"""

    ok: bool
    data: Any = None
    error: Optional[dict[str, Any]] = None


# ─────────────── routes ───────────────


@router.post(
    "/pins",
    status_code=status.HTTP_201_CREATED,
    response_model=StandardResponse,
)
async def create_pin(
    payload: CreatePinRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db_with_tenant),
) -> StandardResponse:
    """店长把 AI 洞察 Pin 到驾驶舱。

    Body 含 surface_snapshot（A2UI declaration）+ pinner_user_id；tenant 走 header。
    成功返回 201 + 完整 PinnedItem（含 DB 生成的 pin_id / pinned_at）。
    超 PIN_LIMIT_PER_TENANT(20) 时由 service 层自动 FIFO 软删最旧。
    """
    try:
        item = await add_pin(
            db,
            tenant_id=x_tenant_id,
            pinner_user_id=payload.pinner_user_id,
            surface_snapshot=payload.surface_snapshot,
            source_query_id=payload.source_query_id,
            source_natural_query=payload.source_natural_query,
        )
    except ValueError as exc:
        logger.warning("create_pin.validation_error", tenant=x_tenant_id, err=str(exc))
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "INVALID_PAYLOAD", "message": str(exc)},
        ) from exc

    logger.info("create_pin.ok", tenant=x_tenant_id, pin_id=item.pin_id)
    return StandardResponse(ok=True, data=item.to_dict())


@router.get("/pins", response_model=StandardResponse)
async def list_pinned(
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db_with_tenant),
) -> StandardResponse:
    """列出当前 tenant 的 active Pin（最新在前，软删行不返）。

    最多返回 PIN_LIMIT_PER_TENANT(20) 条 — service 层 SQL LIMIT 守门。
    RLS USING 自动 tenant 过滤；跨 tenant 不可见。
    """
    try:
        items = await list_pins(db, x_tenant_id)
    except ValueError as exc:
        logger.warning("list_pinned.validation_error", tenant=x_tenant_id, err=str(exc))
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "INVALID_PAYLOAD", "message": str(exc)},
        ) from exc

    return StandardResponse(
        ok=True,
        data={"items": [item.to_dict() for item in items], "total": len(items)},
    )


@router.delete("/pins/{pin_id}", response_model=StandardResponse)
async def delete_pin(
    pin_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db_with_tenant),
) -> StandardResponse:
    """软删指定 Pin（幂等）。

    跨 tenant 删除：RLS 阻挡可见性 → rowcount=0 → ok:true + data.deleted=False。
    重复软删已 deleted 行：同上幂等返回。
    """
    try:
        deleted = await remove_pin(db, tenant_id=x_tenant_id, pin_id=pin_id)
    except ValueError as exc:
        logger.warning("delete_pin.validation_error", tenant=x_tenant_id, err=str(exc))
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "INVALID_PAYLOAD", "message": str(exc)},
        ) from exc

    if deleted:
        logger.info("delete_pin.ok", tenant=x_tenant_id, pin_id=pin_id)
    else:
        logger.info("delete_pin.noop", tenant=x_tenant_id, pin_id=pin_id)
    return StandardResponse(ok=True, data={"deleted": deleted})
