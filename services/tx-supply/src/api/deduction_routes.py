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

from fastapi import APIRouter, Header, Query
from pydantic import BaseModel, Field

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
async def deduct_for_order(
    order_id: str,
    body: DeductOrderRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict[str, Any]:
    """订单完成时自动BOM扣料

    根据每道菜的 BOM 配方扣减门店库存，创建 consume 类型流水。
    库存不足时记录告警但不阻塞。
    """
    # TODO: 注入真实 AsyncSession（当前返回桩数据）
    return {
        "ok": True,
        "data": {
            "order_id": order_id,
            "deducted_items": [],
            "missing_bom": [],
            "insufficient_stock": [],
            "message": "扣料完成（待接入真实DB）",
        },
    }


@router.post("/deduction/rollback/{order_id}")
async def rollback_deduction(
    order_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict[str, Any]:
    """退菜/退单时回滚扣料

    查找该订单产生的所有 consume 流水，逐条反向回补库存。
    """
    return {
        "ok": True,
        "data": {
            "order_id": order_id,
            "rolled_back_count": 0,
            "restored_items": [],
            "message": "回滚完成（待接入真实DB）",
        },
    }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  盘点
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.post("/stocktake")
async def create_stocktake(
    store_id: str = Query(...),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict[str, Any]:
    """创建盘点单，快照当前系统库存"""
    return {
        "ok": True,
        "data": {
            "stocktake_id": "placeholder",
            "store_id": store_id,
            "status": "open",
            "item_count": 0,
            "items": [],
            "message": "盘点单已创建（待接入真实DB）",
        },
    }


@router.post("/stocktake/{stocktake_id}/count")
async def record_count(
    stocktake_id: str,
    body: RecordCountRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict[str, Any]:
    """录入单条原料的实盘数量"""
    return {
        "ok": True,
        "data": {
            "stocktake_id": stocktake_id,
            "ingredient_id": body.ingredient_id,
            "actual_qty": body.actual_qty,
            "message": "实盘已录入（待接入真实DB）",
        },
    }


@router.post("/stocktake/{stocktake_id}/finalize")
async def finalize_stocktake(
    stocktake_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict[str, Any]:
    """完成盘点：对比系统库存 vs 实盘，生成差异报告"""
    return {
        "ok": True,
        "data": {
            "stocktake_id": stocktake_id,
            "status": "finalized",
            "total_items": 0,
            "matched": 0,
            "surplus": 0,
            "deficit": 0,
            "deficit_cost_fen": 0,
            "message": "盘点完成（待接入真实DB）",
        },
    }


@router.get("/stocktake/history")
async def get_stocktake_history(
    store_id: str = Query(...),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict[str, Any]:
    """历史盘点列表"""
    return {
        "ok": True,
        "data": {
            "stocktakes": [],
        },
    }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  损耗分析
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.get("/waste/analysis")
async def get_waste_analysis(
    store_id: str = Query(...),
    date_from: str = Query(..., description="YYYY-MM-DD"),
    date_to: str = Query(..., description="YYYY-MM-DD"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict[str, Any]:
    """多维度损耗归因分析

    返回 by_type / by_ingredient / by_time_slot 三个维度。
    """
    return {
        "ok": True,
        "data": {
            "store_id": store_id,
            "period": {"from": date_from, "to": date_to},
            "total_waste_cost_fen": 0,
            "total_waste_cost_yuan": 0.0,
            "by_type": {},
            "by_ingredient": [],
            "by_time_slot": [],
            "message": "分析完成（待接入真实DB）",
        },
    }


@router.get("/waste/top-items")
async def get_top_waste_items(
    store_id: str = Query(...),
    limit: int = Query(10, ge=1, le=50),
    days: int = Query(30, ge=1, le=365),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict[str, Any]:
    """损耗金额最高的原料排行"""
    return {
        "ok": True,
        "data": {
            "store_id": store_id,
            "period_days": days,
            "items": [],
            "message": "排行查询完成（待接入真实DB）",
        },
    }
