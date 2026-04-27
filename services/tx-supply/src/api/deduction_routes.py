"""领料扣料与损耗中心 API 路由

路由：
- POST /deduction/order/{order_id}     — 订单扣料
- POST /deduction/rollback/{order_id}  — 回滚扣料
- POST /stocktake                      — 创建盘点
- POST /stocktake/{id}/count           — 录入实盘
- POST /stocktake/{id}/finalize        — 完成盘点
- GET  /stocktake/history              — 历史盘点
- GET  /waste/analysis                 — 损耗分析
- GET  /waste/top-items                — 损耗排行
"""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.events.src.emitter import emit_event
from shared.events.src.event_types import InventoryEventType
from shared.ontology.src.database import get_db

from ..services.auto_deduction import deduct_for_order, rollback_deduction
from ..services.stocktake_loss_service import (
    CaseValidationError,
    auto_create_loss_case_from_stocktake,
)
from ..services.stocktake_service import (
    create_stocktake,
    finalize_stocktake,
    get_stocktake_history,
    record_count,
)
from ..services.waste_attribution import analyze_waste, get_top_waste_items

router = APIRouter(prefix="/api/v1/supply", tags=["deduction-stocktake-waste"])


async def _set_rls(db: AsyncSession, tenant_id: str) -> None:
    """设置 RLS 上下文变量 app.tenant_id（路由层防御纵深）。"""
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": str(tenant_id)},
    )


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Request / Response models
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class OrderItemInput(BaseModel):
    dish_id: str
    quantity: int = 1
    item_name: str = ""


class DeductOrderRequest(BaseModel):
    store_id: str
    order_items: list[OrderItemInput]


class RecordCountRequest(BaseModel):
    ingredient_id: str
    actual_qty: float


class WasteAnalysisParams(BaseModel):
    store_id: str
    date_from: str = Field(..., description="YYYY-MM-DD")
    date_to: str = Field(..., description="YYYY-MM-DD")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  扣料
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.post("/deduction/order/{order_id}")
async def deduct_for_order_route(
    order_id: str,
    body: DeductOrderRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """订单完成时自动BOM扣料

    根据每道菜的 BOM 配方扣减门店库存，创建 consume 类型流水。
    库存不足时记录告警但不阻塞。
    """
    await _set_rls(db, x_tenant_id)
    try:
        order_items = [item.model_dump() for item in body.order_items]
        data = await deduct_for_order(order_id, order_items, body.store_id, x_tenant_id, db)
        # ─── Phase 1 平行事件写入：BOM扣料（每个食材一条事件）───
        for deducted in data.get("deducted_items", []):
            asyncio.create_task(
                emit_event(
                    event_type=InventoryEventType.CONSUMED,
                    tenant_id=x_tenant_id,
                    stream_id=deducted.get("ingredient_id", order_id),
                    payload={
                        "ingredient_id": deducted.get("ingredient_id"),
                        "ingredient_name": deducted.get("ingredient_name", ""),
                        "quantity_g": deducted.get("quantity", 0),
                        "theoretical_g": deducted.get("theoretical_quantity", deducted.get("quantity", 0)),
                        "order_id": order_id,
                        "bom_deduction": True,
                    },
                    store_id=body.store_id,
                    source_service="tx-supply",
                    causation_id=order_id,
                )
            )
        return {"ok": True, "data": data}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/deduction/rollback/{order_id}")
async def rollback_deduction_route(
    order_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """退菜/退单时回滚扣料

    查找该订单产生的所有 consume 流水，逐条反向回补库存。
    """
    await _set_rls(db, x_tenant_id)
    try:
        data = await rollback_deduction(order_id, x_tenant_id, db)
        # ─── Phase 1 平行事件写入：扣料回滚（每条回补记录一个事件）───
        for item in data.get("restored_items", []):
            asyncio.create_task(
                emit_event(
                    event_type=InventoryEventType.ADJUSTED,
                    tenant_id=x_tenant_id,
                    stream_id=item.get("ingredient_id", order_id),
                    payload={
                        "ingredient_id": item.get("ingredient_id"),
                        "ingredient_name": item.get("ingredient_name", ""),
                        "delta_g": item.get("quantity", 0),
                        "reason": "deduction_rollback",
                        "order_id": order_id,
                    },
                    source_service="tx-supply",
                    causation_id=order_id,
                )
            )
        return {"ok": True, "data": data}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  盘点
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.post("/stocktake")
async def create_stocktake_route(
    store_id: str = Query(...),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """创建盘点单，快照当前系统库存"""
    await _set_rls(db, x_tenant_id)
    try:
        data = await create_stocktake(store_id, x_tenant_id, db)
        return {"ok": True, "data": data}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/stocktake/{stocktake_id}/count")
async def record_count_route(
    stocktake_id: str,
    body: RecordCountRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """录入单条原料的实盘数量"""
    await _set_rls(db, x_tenant_id)
    try:
        data = await record_count(stocktake_id, body.ingredient_id, body.actual_qty, x_tenant_id, db)
        return {"ok": True, "data": data}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/stocktake/{stocktake_id}/finalize")
async def finalize_stocktake_route(
    stocktake_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    x_user_id: str | None = Header(default=None, alias="X-User-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """完成盘点：对比系统库存 vs 实盘，生成差异报告。

    若净亏损金额超过 AUTO_CREATE_THRESHOLD_FEN，则异步自动建盘亏案件
    （tx-finance 通过事件订阅自动准备凭证；详见 v370）。
    """
    await _set_rls(db, x_tenant_id)
    try:
        data = await finalize_stocktake(stocktake_id, x_tenant_id, db)
        # ─── Phase 1 平行事件写入：盘点完成调整（每条差异一个事件）───
        for diff in data.get("differences", []):
            delta = diff.get("delta_g", 0)
            if delta == 0:
                continue
            asyncio.create_task(
                emit_event(
                    event_type=InventoryEventType.ADJUSTED,
                    tenant_id=x_tenant_id,
                    stream_id=diff.get("ingredient_id", stocktake_id),
                    payload={
                        "stocktake_id": stocktake_id,
                        "ingredient_id": diff.get("ingredient_id"),
                        "ingredient_name": diff.get("ingredient_name", ""),
                        "delta_g": delta,
                        "system_qty_g": diff.get("system_qty_g"),
                        "actual_qty_g": diff.get("actual_qty_g"),
                        "reason": "stocktake_finalize",
                    },
                    source_service="tx-supply",
                    causation_id=stocktake_id,
                )
            )
        # ─── v370 集成：盘点完成后自动建盘亏案件 ───
        # 异步触发，不阻塞响应；失败仅记录日志，不影响盘点本身
        async def _try_auto_create() -> None:
            try:
                await auto_create_loss_case_from_stocktake(
                    stocktake_id=stocktake_id,
                    tenant_id=x_tenant_id,
                    db=db,
                    created_by=x_user_id or x_tenant_id,
                )
            except CaseValidationError:
                # 盘点未完成或不存在等业务校验失败；不打断主流程
                pass

        asyncio.create_task(_try_auto_create())
        return {"ok": True, "data": data}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/stocktake/history")
async def get_stocktake_history_route(
    store_id: str = Query(...),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """历史盘点列表"""
    await _set_rls(db, x_tenant_id)
    try:
        data = await get_stocktake_history(store_id, x_tenant_id, db)
        return {"ok": True, "data": data}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  损耗分析
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.get("/waste/analysis")
async def get_waste_analysis(
    store_id: str = Query(...),
    date_from: str = Query(..., description="YYYY-MM-DD"),
    date_to: str = Query(..., description="YYYY-MM-DD"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """多维度损耗归因分析

    返回 by_type / by_ingredient / by_time_slot 三个维度。
    """
    await _set_rls(db, x_tenant_id)
    try:
        data = await analyze_waste(store_id, date_from, date_to, x_tenant_id, db)
        return {"ok": True, "data": data}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/waste/top-items")
async def get_top_waste_items_route(
    store_id: str = Query(...),
    limit: int = Query(10, ge=1, le=50),
    days: int = Query(30, ge=1, le=365),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """损耗金额最高的原料排行"""
    await _set_rls(db, x_tenant_id)
    try:
        data = await get_top_waste_items(store_id, x_tenant_id, db, limit=limit)
        return {"ok": True, "data": data}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
