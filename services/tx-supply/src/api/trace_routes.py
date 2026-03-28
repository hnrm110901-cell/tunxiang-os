"""原料追溯 API

5 个端点：正向追溯、反向追溯、追溯时间线、追溯报告、原料关系图。
"""
from fastapi import APIRouter, Header
from pydantic import BaseModel, Field

from services.tx_supply.src.services import traceability

router = APIRouter(prefix="/api/v1/supply/trace", tags=["traceability"])


# ─── Pydantic 请求体 ───


class BackwardTraceRequest(BaseModel):
    order_id: str
    dish_id: str


# ─── 端点 ───


@router.get("/forward/{batch_no}")
async def trace_forward(
    batch_no: str,
    x_tenant_id: str = Header(alias="X-Tenant-ID"),
):
    """正向追溯（供应商 -> 入库 -> 领用 -> BOM -> 菜品 -> 订单 -> 客户）"""
    result = traceability.full_trace_forward(
        batch_no=batch_no,
        tenant_id=x_tenant_id,
    )
    return {"ok": True, "data": result}


@router.post("/backward")
async def trace_backward(
    body: BackwardTraceRequest,
    x_tenant_id: str = Header(alias="X-Tenant-ID"),
):
    """反向追溯（客户 -> 订单 -> 菜品 -> BOM -> 原料 -> 批次 -> 供应商）"""
    result = traceability.full_trace_backward(
        order_id=body.order_id,
        dish_id=body.dish_id,
        tenant_id=x_tenant_id,
    )
    return {"ok": True, "data": result}


@router.get("/timeline/{batch_no}")
async def trace_timeline(
    batch_no: str,
    x_tenant_id: str = Header(alias="X-Tenant-ID"),
):
    """追溯时间线（每个节点的时间/操作人/位置）"""
    result = traceability.get_trace_timeline(
        batch_no=batch_no,
        tenant_id=x_tenant_id,
    )
    return {"ok": True, "data": result}


@router.get("/report/{batch_no}")
async def trace_report(
    batch_no: str,
    x_tenant_id: str = Header(alias="X-Tenant-ID"),
):
    """追溯报告（用于食安事件）"""
    result = traceability.generate_trace_report(
        batch_no=batch_no,
        tenant_id=x_tenant_id,
    )
    return {"ok": True, "data": result}


@router.get("/graph/{ingredient_id}")
async def ingredient_graph(
    ingredient_id: str,
    x_tenant_id: str = Header(alias="X-Tenant-ID"),
):
    """原料关系图（替代料/BOM关联/供应商网络）"""
    result = traceability.build_ingredient_graph(
        ingredient_id=ingredient_id,
        tenant_id=x_tenant_id,
    )
    return {"ok": True, "data": result}
