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

from typing import Any, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from shared.ontology.src.database import get_db

from ..services.auto_deduction import deduct_for_order, rollback_deduction
from ..services.stocktake_service import (
    create_stocktake,
    record_count,
    finalize_stocktake,
    get_stocktake_history,
)
from ..services.waste_attribution import analyze_waste, get_top_waste_items

router = APIRouter(prefix="/api/v1/supply", tags=["deduction-stocktake-waste"])


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
    try:
        order_items = [item.model_dump() for item in body.order_items]
        data = await deduct_for_order(order_id, order_items, body.store_id, x_tenant_id, db)
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
    try:
        data = await rollback_deduction(order_id, x_tenant_id, db)
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
    try:
        data = await record_count(stocktake_id, body.ingredient_id, body.actual_qty, x_tenant_id, db)
        return {"ok": True, "data": data}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/stocktake/{stocktake_id}/finalize")
async def finalize_stocktake_route(
    stocktake_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """完成盘点：对比系统库存 vs 实盘，生成差异报告"""
    try:
        data = await finalize_stocktake(stocktake_id, x_tenant_id, db)
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
    try:
        data = await get_top_waste_items(store_id, x_tenant_id, db, limit=limit)
        return {"ok": True, "data": data}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
