"""移库与拆组 API 路由 -- 3 个端点

统一响应格式: {"ok": bool, "data": {}, "error": {}}
"""
from __future__ import annotations

from typing import Any, Dict, List

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/v1/supply", tags=["warehouse-ops"])


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  请求模型
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TransferItemRequest(BaseModel):
    ingredient_id: str
    name: str = ""
    quantity: float = Field(gt=0)
    unit: str = ""
    batch_no: str = ""


class CreateTransferOrderRequest(BaseModel):
    from_warehouse: str
    to_warehouse: str
    items: List[TransferItemRequest]


class ComponentRequest(BaseModel):
    ingredient_id: str
    name: str = ""
    quantity: float = Field(gt=0)
    unit: str = ""


class CreateSplitAssemblyRequest(BaseModel):
    item_id: str
    op_type: str = Field(..., pattern="^(split|assembly)$")
    components: List[ComponentRequest]


class CreateBomSplitRequest(BaseModel):
    dish_id: str
    quantity: float = Field(gt=0)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  1. 移库单
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.post("/warehouse/transfers")
async def create_transfer_order(
    body: CreateTransferOrderRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """创建移库单"""
    from ..services.warehouse_ops import create_transfer_order as svc

    try:
        result = await svc(
            body.from_warehouse,
            body.to_warehouse,
            [i.model_dump() for i in body.items],
            x_tenant_id,
            db=None,
        )
        return {"ok": True, "data": result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  2. 拆分/组装
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.post("/warehouse/split-assembly")
async def create_split_assembly(
    body: CreateSplitAssemblyRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """创建拆分或组装单"""
    from ..services.warehouse_ops import create_split_assembly as svc

    try:
        result = await svc(
            body.item_id,
            body.op_type,
            [c.model_dump() for c in body.components],
            x_tenant_id,
            db=None,
        )
        return {"ok": True, "data": result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  3. BOM 拆分
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.post("/warehouse/bom-split")
async def create_bom_split(
    body: CreateBomSplitRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """BOM 拆分: 成品按配方拆分为原料"""
    from ..services.warehouse_ops import create_bom_split as svc

    try:
        result = await svc(
            body.dish_id,
            body.quantity,
            x_tenant_id,
            db=None,
        )
        return {"ok": True, "data": result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
