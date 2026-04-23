"""月结与成本 API 路由 -- 6 个端点

统一响应格式: {"ok": bool, "data": {}, "error": {}}
"""

from __future__ import annotations

from typing import List

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/v1/supply", tags=["period-close"])


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  请求模型
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class ClosePeriodRequest(BaseModel):
    store_id: str
    month: str = Field(..., pattern=r"^\d{4}-\d{2}$")


class ReversePeriodRequest(BaseModel):
    store_id: str
    month: str = Field(..., pattern=r"^\d{4}-\d{2}$")


class CostAdjustmentItemRequest(BaseModel):
    ingredient_id: str
    name: str = ""
    old_cost_fen: int = 0
    new_cost_fen: int = 0
    reason: str = ""


class CreateCostAdjustmentRequest(BaseModel):
    store_id: str
    items: List[CostAdjustmentItemRequest]
    month: str = ""


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  1. 月结
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.post("/period/close")
async def close_period(
    body: ClosePeriodRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """月结: 锁定当月库存"""
    from ..services.period_close import close_period as svc

    try:
        result = await svc(
            body.store_id,
            body.month,
            x_tenant_id,
            db=None,
        )
        return {"ok": True, "data": result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  2. 反月结
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.post("/period/reverse")
async def reverse_close(
    body: ReversePeriodRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """反月结: 解锁已月结的期间"""
    from ..services.period_close import reverse_close as svc

    try:
        result = await svc(
            body.store_id,
            body.month,
            x_tenant_id,
            db=None,
        )
        return {"ok": True, "data": result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  3. 成本调整单
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.post("/period/cost-adjustment")
async def create_cost_adjustment(
    body: CreateCostAdjustmentRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """创建成本调整单"""
    from ..services.period_close import create_cost_adjustment as svc

    try:
        result = await svc(
            body.store_id,
            [i.model_dump() for i in body.items],
            x_tenant_id,
            db=None,
            month=body.month,
        )
        return {"ok": True, "data": result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  4. 未完成单据检查
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.get("/period/pending/{store_id}")
async def check_pending_documents(
    store_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """检查未完成单据"""
    from ..services.period_close import check_pending_documents as svc

    result = await svc(store_id, x_tenant_id, db=None)
    return {"ok": True, "data": result}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  5. 收发结存表
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.get("/period/balance/{store_id}/{month}")
async def get_receipt_balance(
    store_id: str,
    month: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """收发结存表"""
    from ..services.period_close import get_receipt_balance as svc

    result = await svc(store_id, month, x_tenant_id, db=None)
    return {"ok": True, "data": result}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  6. 应付账款统计
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.get("/period/payables/{store_id}")
async def get_payable_summary(
    store_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """应付账款统计"""
    from ..services.period_close import get_payable_summary as svc

    result = await svc(store_id, x_tenant_id, db=None)
    return {"ok": True, "data": result}
