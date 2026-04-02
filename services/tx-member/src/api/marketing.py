"""营销方案 API — 计算、创建、列出方案"""
from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel, Field
from services.marketing_engine import (
    SCHEME_TYPES,
    apply_schemes_in_order,
)

router = APIRouter(prefix="/api/v1/member/marketing-schemes", tags=["marketing"])


# ---------------------------------------------------------------------------
# Request / Response Models
# ---------------------------------------------------------------------------

class OrderItem(BaseModel):
    dish_id: str
    name: str = ""
    price_fen: int = Field(..., ge=0, description="单价（分）")
    quantity: int = Field(1, ge=1)


class SchemeInput(BaseModel):
    scheme_type: str = Field(..., description=f"方案类型: {SCHEME_TYPES}")
    priority: int = Field(10, description="优先级，数字越小越高")
    rules: dict = Field(default_factory=dict)
    exclusion_rules: list[list[str]] = Field(
        default_factory=list,
        description='互斥规则，如 [["special_price","order_discount"]]',
    )


class CalculateReq(BaseModel):
    items: list[OrderItem]
    order_total_fen: int = Field(0, ge=0, description="订单总额（分），0 则自动求和")
    schemes: list[SchemeInput]
    member_level: Optional[str] = None


class CreateSchemeReq(BaseModel):
    scheme_type: str
    name: str
    priority: int = 10
    rules: dict = Field(default_factory=dict)
    exclusion_rules: list[list[str]] = Field(default_factory=list)
    store_id: str = ""
    enabled: bool = True


# ---------------------------------------------------------------------------
# 内存存储（无 DB 依赖，后续替换为 Repository）
# ---------------------------------------------------------------------------

_SCHEME_STORE: list[dict] = []


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/calculate")
async def calculate_order_discount(req: CalculateReq):
    """计算订单应用方案后的优惠"""
    items_raw = [it.model_dump() for it in req.items]

    order_total = req.order_total_fen
    if order_total == 0:
        order_total = sum(it.price_fen * it.quantity for it in req.items)

    schemes_raw = [s.model_dump() for s in req.schemes]

    result = apply_schemes_in_order(
        items=items_raw,
        order_total_fen=order_total,
        schemes=schemes_raw,
        member_level=req.member_level,
    )
    return {"ok": True, "data": result}


@router.get("")
async def list_schemes(store_id: Optional[str] = None, enabled: Optional[bool] = None):
    """列出方案"""
    result = _SCHEME_STORE
    if store_id is not None:
        result = [s for s in result if s.get("store_id") == store_id]
    if enabled is not None:
        result = [s for s in result if s.get("enabled") == enabled]
    return {"ok": True, "data": {"items": result, "total": len(result)}}


@router.post("")
async def create_scheme(req: CreateSchemeReq):
    """创建方案"""
    if req.scheme_type not in SCHEME_TYPES:
        return {
            "ok": False,
            "error": {"code": "INVALID_SCHEME_TYPE", "message": f"不支持的方案类型: {req.scheme_type}"},
        }

    scheme = {
        "scheme_id": f"sch_{len(_SCHEME_STORE) + 1}",
        **req.model_dump(),
    }
    _SCHEME_STORE.append(scheme)
    return {"ok": True, "data": scheme}
