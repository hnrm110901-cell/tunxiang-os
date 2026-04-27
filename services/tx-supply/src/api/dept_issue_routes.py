"""部门领用 API 路由 -- 7 个端点

统一响应格式: {"ok": bool, "data": {}, "error": {}}
"""

from __future__ import annotations

from typing import List

from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/v1/supply", tags=["dept-issue"])


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  请求模型
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class IssueItemRequest(BaseModel):
    ingredient_id: str
    name: str = ""
    quantity: float = Field(gt=0)
    unit: str = ""
    unit_cost_fen: int = 0


class CreateIssueRequest(BaseModel):
    store_id: str
    dept_id: str
    items: List[IssueItemRequest]
    operator_id: str


class ReturnItemRequest(BaseModel):
    ingredient_id: str
    name: str = ""
    quantity: float = Field(gt=0)
    unit: str = ""
    reason: str = ""


class CreateReturnRequest(BaseModel):
    items: List[ReturnItemRequest]


class DeptTransferItemRequest(BaseModel):
    ingredient_id: str
    name: str = ""
    quantity: float = Field(gt=0)
    unit: str = ""


class CreateDeptTransferRequest(BaseModel):
    from_dept: str
    to_dept: str
    items: List[DeptTransferItemRequest]


class YieldRateRequest(BaseModel):
    dish_id: str
    store_id: str
    actual_output: float = Field(ge=0)
    theoretical_output: float = Field(gt=0)


class SalesToInventoryRequest(BaseModel):
    store_id: str
    date: str


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  1. 创建领用单
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.post("/dept-issue/orders")
async def create_issue_order(
    body: CreateIssueRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """创建部门领用单"""
    from ..services.dept_issue import create_issue_order as svc

    try:
        result = await svc(
            body.store_id,
            body.dept_id,
            [i.model_dump() for i in body.items],
            body.operator_id,
            x_tenant_id,
            db=None,
        )
        return {"ok": True, "data": result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  2. 领用退回
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.post("/dept-issue/orders/{issue_id}/return")
async def create_return_order(
    issue_id: str,
    body: CreateReturnRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """创建领用退回单"""
    from ..services.dept_issue import create_return_order as svc

    try:
        result = await svc(
            issue_id,
            [i.model_dump() for i in body.items],
            x_tenant_id,
            db=None,
        )
        return {"ok": True, "data": result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  3. 部门间调拨
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.post("/dept-issue/transfers")
async def create_dept_transfer(
    body: CreateDeptTransferRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """创建部门间调拨单"""
    from ..services.dept_issue import create_dept_transfer as svc

    try:
        result = await svc(
            body.from_dept,
            body.to_dept,
            [i.model_dump() for i in body.items],
            x_tenant_id,
            db=None,
        )
        return {"ok": True, "data": result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  4. 出料率抽检
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.post("/dept-issue/yield-check")
async def check_yield_rate(
    body: YieldRateRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """出料率抽检"""
    from ..services.dept_issue import check_yield_rate as svc

    try:
        result = await svc(
            body.dish_id,
            body.store_id,
            x_tenant_id,
            db=None,
            actual_output=body.actual_output,
            theoretical_output=body.theoretical_output,
        )
        return {"ok": True, "data": result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  5. 销售转出库
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.post("/dept-issue/sales-outbound")
async def sales_to_inventory(
    body: SalesToInventoryRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """将销售数据转为出库记录"""
    from ..services.dept_issue import sales_to_inventory as svc

    result = await svc(
        body.store_id,
        body.date,
        x_tenant_id,
        db=None,
    )
    return {"ok": True, "data": result}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  6. 领用商品流水
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.get("/dept-issue/flow/{store_id}/{dept_id}")
async def get_issue_flow(
    store_id: str,
    dept_id: str,
    start_date: str = Query("", description="开始日期 YYYY-MM-DD"),
    end_date: str = Query("", description="结束日期 YYYY-MM-DD"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """查询领用商品流水"""
    from ..services.dept_issue import get_issue_flow as svc

    result = await svc(
        store_id,
        dept_id,
        (start_date, end_date),
        x_tenant_id,
        db=None,
    )
    return {"ok": True, "data": result}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  7. 月度汇总
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.get("/dept-issue/summary/{store_id}/{month}")
async def get_monthly_summary(
    store_id: str,
    month: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """月度领用汇总"""
    from ..services.dept_issue import get_monthly_summary as svc

    result = await svc(store_id, month, x_tenant_id, db=None)
    return {"ok": True, "data": result}
