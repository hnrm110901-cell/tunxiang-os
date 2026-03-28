"""BOM 管理 API 路由

提供 BOM 模板的 CRUD + 版本激活 + 理论成本计算。
"""
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/api/v1/supply/bom", tags=["bom"])


# ─── 请求/响应模型 ───


class BOMItemCreate(BaseModel):
    ingredient_id: str
    standard_qty: float
    unit: str
    unit_cost_fen: Optional[int] = None
    raw_qty: Optional[float] = None
    waste_factor: float = 0.0
    is_key_ingredient: bool = False
    is_optional: bool = False
    prep_notes: Optional[str] = None


class BOMTemplateCreate(BaseModel):
    dish_id: str
    store_id: str
    version: str = "v1"
    yield_rate: float = 1.0
    standard_portion: Optional[float] = None
    prep_time_minutes: Optional[int] = None
    scope: str = "store"
    notes: Optional[str] = None
    created_by: Optional[str] = None
    items: list[BOMItemCreate]


class BOMTemplateUpdate(BaseModel):
    yield_rate: Optional[float] = None
    standard_portion: Optional[float] = None
    prep_time_minutes: Optional[int] = None
    notes: Optional[str] = None
    items: list[BOMItemCreate]


class OrderCostItem(BaseModel):
    dish_id: str
    quantity: int = 1


class OrderCostRequest(BaseModel):
    items: list[OrderCostItem]


# ─── 依赖占位 ───
# 实际部署时通过 Depends 注入 AsyncSession
# 这里提供占位签名，与 main.py 中的 db 依赖配合使用


def _get_tenant_id(x_tenant_id: str = Header(...)) -> str:
    """从请求头提取 tenant_id"""
    return x_tenant_id


# ─── BOM 模板 CRUD ───


@router.post("/templates")
async def create_bom_template(
    body: BOMTemplateCreate,
    tenant_id: str = Depends(_get_tenant_id),
):
    """创建 BOM 模板"""
    # 注意：真实实现中通过 Depends 注入 db session
    # 此处返回占位响应, 由 main.py 中注册时绑定实际 db
    from services.bom_service import BOMService
    from services.cost_calculator import CostCalculator  # noqa: F401

    # 占位: 实际项目中使用 Depends 获取 db
    return {"ok": True, "data": {"message": "BOM template creation endpoint ready"}}


@router.get("/templates")
async def list_bom_templates(
    dish_id: Optional[str] = None,
    store_id: Optional[str] = None,
    is_active: Optional[bool] = None,
    page: int = 1,
    size: int = 20,
    tenant_id: str = Depends(_get_tenant_id),
):
    """列表查询 BOM 模板"""
    return {"ok": True, "data": {"items": [], "total": 0, "page": page, "size": size}}


@router.get("/templates/{template_id}")
async def get_bom_template(
    template_id: str,
    tenant_id: str = Depends(_get_tenant_id),
):
    """获取 BOM 模板详情（含明细行）"""
    return {"ok": True, "data": None}


@router.put("/templates/{template_id}")
async def update_bom_template(
    template_id: str,
    body: BOMTemplateUpdate,
    tenant_id: str = Depends(_get_tenant_id),
):
    """更新 BOM 模板（替换所有明细行）"""
    return {"ok": True, "data": None}


@router.delete("/templates/{template_id}")
async def delete_bom_template(
    template_id: str,
    tenant_id: str = Depends(_get_tenant_id),
):
    """软删除 BOM 模板"""
    return {"ok": True, "data": {"deleted": False}}


@router.post("/templates/{template_id}/activate")
async def activate_bom_version(
    template_id: str,
    tenant_id: str = Depends(_get_tenant_id),
):
    """激活指定 BOM 版本（同时停用同菜品其他版本）"""
    return {"ok": True, "data": None}


# ─── 理论成本计算 ───


@router.get("/cost/{dish_id}")
async def calculate_dish_cost(
    dish_id: str,
    tenant_id: str = Depends(_get_tenant_id),
):
    """计算菜品理论成本（基于激活 BOM x 最新采购价）"""
    return {"ok": True, "data": {
        "dish_id": dish_id,
        "theoretical_cost_fen": 0,
        "items": [],
    }}


@router.get("/cost/{dish_id}/breakdown")
async def get_cost_breakdown(
    dish_id: str,
    tenant_id: str = Depends(_get_tenant_id),
):
    """获取菜品成本分解明细（每个原料占比）"""
    return {"ok": True, "data": {
        "dish_id": dish_id,
        "theoretical_cost_fen": 0,
        "breakdown": [],
    }}


@router.post("/cost/order")
async def calculate_order_cost(
    body: OrderCostRequest,
    tenant_id: str = Depends(_get_tenant_id),
):
    """批量计算一个订单的理论成本"""
    return {"ok": True, "data": {
        "total_theoretical_cost_fen": 0,
        "per_item": [],
    }}
