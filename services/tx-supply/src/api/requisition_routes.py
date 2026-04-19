"""申购全流程 API 路由 -- 8 个端点

统一响应格式: {"ok": bool, "data": {}, "error": {}}
"""

from __future__ import annotations

from typing import List

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/v1/supply", tags=["requisition"])


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  请求模型
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class RequisitionItemRequest(BaseModel):
    ingredient_id: str
    name: str = ""
    quantity: float = Field(gt=0)
    unit: str = ""
    estimated_price_fen: int = 0


class CreateRequisitionRequest(BaseModel):
    store_id: str
    items: List[RequisitionItemRequest]
    requester_id: str


class ApproveRequisitionRequest(BaseModel):
    approver_id: str
    decision: str = Field(..., pattern="^(approve|reject)$")
    approver_role: str = Field(
        "store_manager",
        pattern="^(store_manager|region_manager|hq_manager)$",
    )
    comment: str = ""


class ConvertToPurchaseRequest(BaseModel):
    supplier_id: str = ""
    supplier_name: str = ""
    delivery_date: str = ""


class ReturnItemRequest(BaseModel):
    ingredient_id: str
    name: str = ""
    quantity: float = Field(gt=0)
    unit: str = ""
    batch_no: str = ""


class CreateReturnRequest(BaseModel):
    store_id: str
    items: List[ReturnItemRequest]
    reason: str


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  1. 创建申购单
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.post("/requisitions")
async def create_requisition(
    body: CreateRequisitionRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """创建申购单"""
    from ..services.requisition import create_requisition as svc

    try:
        result = await svc(
            body.store_id,
            [i.model_dump() for i in body.items],
            body.requester_id,
            x_tenant_id,
            db=None,
        )
        return {"ok": True, "data": result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  2. 自动补货
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.post("/requisitions/replenishment/{store_id}")
async def create_replenishment(
    store_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """基于安全库存自动生成补货申购单"""
    from ..services.requisition import create_replenishment as svc

    result = await svc(store_id, x_tenant_id, db=None)
    return {"ok": True, "data": result}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  3. 提交审批
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.post("/requisitions/{req_id}/submit")
async def submit_for_approval(
    req_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """提交申购单进入审批流程"""
    from ..services.requisition import submit_for_approval as svc

    try:
        result = await svc(req_id, x_tenant_id, db=None)
        return {"ok": True, "data": result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  4. 审批
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.post("/requisitions/{req_id}/approve")
async def approve_requisition(
    req_id: str,
    body: ApproveRequisitionRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """审批申购单 (通过/驳回)"""
    from ..services.requisition import approve_requisition as svc

    try:
        result = await svc(
            req_id,
            body.approver_id,
            body.decision,
            x_tenant_id,
            db=None,
            approver_role=body.approver_role,
            comment=body.comment,
        )
        return {"ok": True, "data": result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  5. 转采购订单
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.post("/requisitions/{req_id}/convert")
async def convert_to_purchase(
    req_id: str,
    body: ConvertToPurchaseRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """将已审批的申购单转换为采购订单"""
    from ..services.requisition import convert_to_purchase as svc

    try:
        result = await svc(
            req_id,
            x_tenant_id,
            db=None,
            supplier_id=body.supplier_id,
            supplier_name=body.supplier_name,
            delivery_date=body.delivery_date,
        )
        return {"ok": True, "data": result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  6. 申退单
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.post("/requisitions/returns")
async def create_return_request(
    body: CreateReturnRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """创建申退单"""
    from ..services.requisition import create_return_request as svc

    try:
        result = await svc(
            body.store_id,
            [i.model_dump() for i in body.items],
            body.reason,
            x_tenant_id,
            db=None,
        )
        return {"ok": True, "data": result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  7. 审批日志
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.get("/requisitions/{req_id}/approval-log")
async def get_approval_log(
    req_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """获取申购单审批日志"""
    from ..services.requisition import get_approval_log as svc

    result = await svc(req_id, x_tenant_id, db=None)
    return {"ok": True, "data": result}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  8. 申购商品流水
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.get("/requisitions/flow/{store_id}")
async def get_requisition_flow(
    store_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """查询门店申购商品流水"""
    from ..services.requisition import get_requisition_flow as svc

    result = await svc(store_id, x_tenant_id, db=None)
    return {"ok": True, "data": result}
