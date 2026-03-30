"""订单操作 API — 赠菜/拆单/并单/改单申请/改单审批

统一响应格式: {"ok": bool, "data": {}, "error": {}}
所有接口需 X-Tenant-ID header，通过 get_db_with_tenant 实现 RLS 租户隔离。
"""
from typing import AsyncGenerator, Optional

import structlog
from fastapi import APIRouter, Depends, Request, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db_with_tenant
from ..services import order_extensions as ext

logger = structlog.get_logger()

router = APIRouter(prefix="/api/v1/orders", tags=["order-ops"])


# ─── 通用辅助 ───


def _get_tenant_id(request: Request) -> str:
    tid = getattr(request.state, "tenant_id", None) or request.headers.get("X-Tenant-ID", "")
    if not tid:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header required")
    return tid


async def _get_db_session(request: Request) -> AsyncGenerator[AsyncSession, None]:
    """获取带租户隔离的 DB session"""
    tenant_id = _get_tenant_id(request)
    async for session in get_db_with_tenant(tenant_id):
        yield session


def _ok(data: dict | list) -> dict:
    return {"ok": True, "data": data, "error": None}


# ─── 请求模型 ───


class GiftDishReq(BaseModel):
    dish_id: str = Field(..., description="赠送菜品ID")
    qty: int = Field(..., ge=1, description="赠菜数量")
    reason: str = Field(..., min_length=1, description="赠菜原因")
    approver_id: str = Field(..., min_length=1, description="审批人ID")


class SplitOrderReq(BaseModel):
    item_ids: list[list[str]] = Field(
        ...,
        min_length=2,
        description="拆单分组，每组为 item_id 列表，至少两组",
    )


class MergeOrdersReq(BaseModel):
    source_order_id: str = Field(..., description="被合并的副单ID")
    target_order_id: str = Field(..., description="合并到的主单ID")


class OrderChangeReq(BaseModel):
    changes: dict = Field(
        ...,
        description="改单内容: {items_to_remove: [], items_to_add: [], price_adjustments: []}",
    )
    reason: str = Field(..., min_length=1, description="改单原因")


class ApproveChangeReq(BaseModel):
    approver_id: str = Field(..., min_length=1, description="审批人ID")


# ─── 1. 赠菜 ───


@router.post("/{order_id}/gift")
async def gift_dish(
    order_id: str,
    body: GiftDishReq,
    request: Request,
    db: AsyncSession = Depends(_get_db_session),
):
    """赠菜 -- 需审批人签字，单价归零"""
    tenant_id = _get_tenant_id(request)
    log = logger.bind(order_id=order_id, tenant_id=tenant_id)
    try:
        result = await ext.gift_dish(
            order_id=order_id,
            dish_id=body.dish_id,
            quantity=body.qty,
            reason=body.reason,
            approver_id=body.approver_id,
            tenant_id=tenant_id,
            db=db,
        )
        await db.commit()
        log.info("gift_dish_api_ok", dish_id=body.dish_id, qty=body.qty)
        return _ok(result)
    except ValueError as e:
        log.warning("gift_dish_api_fail", error=str(e))
        raise HTTPException(status_code=400, detail=str(e))


# ─── 2. 拆单 ───


@router.post("/{order_id}/split")
async def split_order(
    order_id: str,
    body: SplitOrderReq,
    request: Request,
    db: AsyncSession = Depends(_get_db_session),
):
    """拆单 -- 一桌拆成多单"""
    tenant_id = _get_tenant_id(request)
    log = logger.bind(order_id=order_id, tenant_id=tenant_id)
    try:
        result = await ext.split_order(
            order_id=order_id,
            items_groups=body.item_ids,
            tenant_id=tenant_id,
            db=db,
        )
        await db.commit()
        log.info("split_order_api_ok", group_count=len(body.item_ids))
        return _ok(result)
    except ValueError as e:
        log.warning("split_order_api_fail", error=str(e))
        raise HTTPException(status_code=400, detail=str(e))


# ─── 3. 并单 ───


@router.post("/merge")
async def merge_orders(
    body: MergeOrdersReq,
    request: Request,
    db: AsyncSession = Depends(_get_db_session),
):
    """并单 -- 多单合并为一单（target 为主单）"""
    tenant_id = _get_tenant_id(request)
    log = logger.bind(
        source_order_id=body.source_order_id,
        target_order_id=body.target_order_id,
        tenant_id=tenant_id,
    )
    try:
        # merge_orders 接受 order_ids 列表，主单在前
        result = await ext.merge_orders(
            order_ids=[body.target_order_id, body.source_order_id],
            tenant_id=tenant_id,
            db=db,
        )
        await db.commit()
        log.info("merge_orders_api_ok")
        return _ok(result)
    except ValueError as e:
        log.warning("merge_orders_api_fail", error=str(e))
        raise HTTPException(status_code=400, detail=str(e))


# ─── 4. 改单申请 ───


@router.post("/{order_id}/change-request")
async def request_order_change(
    order_id: str,
    body: OrderChangeReq,
    request: Request,
    db: AsyncSession = Depends(_get_db_session),
):
    """异常改单申请 -- 需后续审批"""
    tenant_id = _get_tenant_id(request)
    log = logger.bind(order_id=order_id, tenant_id=tenant_id)
    try:
        result = await ext.request_order_change(
            order_id=order_id,
            changes=body.changes,
            reason=body.reason,
            tenant_id=tenant_id,
            db=db,
        )
        await db.commit()
        log.info("order_change_request_api_ok", change_id=result.get("change_id"))
        return _ok(result)
    except ValueError as e:
        log.warning("order_change_request_api_fail", error=str(e))
        raise HTTPException(status_code=400, detail=str(e))


# ─── 5. 改单审批 ───


@router.put("/changes/{change_id}/approve")
async def approve_order_change(
    change_id: str,
    body: ApproveChangeReq,
    request: Request,
    db: AsyncSession = Depends(_get_db_session),
):
    """改单审批 -- 审批通过后执行改单"""
    tenant_id = _get_tenant_id(request)
    log = logger.bind(change_id=change_id, tenant_id=tenant_id)
    try:
        result = await ext.approve_order_change(
            change_id=change_id,
            approver_id=body.approver_id,
            tenant_id=tenant_id,
            db=db,
        )
        await db.commit()
        log.info("approve_order_change_api_ok", approver_id=body.approver_id)
        return _ok(result)
    except ValueError as e:
        log.warning("approve_order_change_api_fail", error=str(e))
        raise HTTPException(status_code=400, detail=str(e))
