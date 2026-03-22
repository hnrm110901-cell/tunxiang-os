"""库存与供应链 API"""
from typing import Optional
from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(prefix="/api/v1/supply", tags=["supply"])


# 库存
@router.get("/inventory")
async def list_inventory(store_id: str, status: Optional[str] = None, page: int = 1, size: int = 20):
    return {"ok": True, "data": {"items": [], "total": 0}}

@router.get("/inventory/{item_id}")
async def get_inventory_item(item_id: str):
    return {"ok": True, "data": None}

@router.post("/inventory/{item_id}/adjust")
async def adjust_inventory(item_id: str, quantity: float, reason: str):
    return {"ok": True, "data": {"adjusted": True}}

@router.get("/inventory/alerts")
async def get_inventory_alerts(store_id: str):
    """库存预警列表（低库存/临期）"""
    return {"ok": True, "data": {"alerts": []}}

# 采购
@router.get("/procurement/plans")
async def list_procurement_plans(store_id: str):
    return {"ok": True, "data": {"plans": []}}

@router.post("/procurement/plans")
async def create_procurement_plan(store_id: str, items: list[dict]):
    return {"ok": True, "data": {"plan_id": "new"}}

@router.post("/procurement/plans/{plan_id}/approve")
async def approve_procurement(plan_id: str, operator_id: str):
    return {"ok": True, "data": {"approved": True}}

# 供应商
@router.get("/suppliers")
async def list_suppliers(page: int = 1, size: int = 20):
    return {"ok": True, "data": {"items": [], "total": 0}}

@router.get("/suppliers/{supplier_id}/rating")
async def get_supplier_rating(supplier_id: str):
    return {"ok": True, "data": {"rating": None}}

@router.get("/suppliers/price-comparison")
async def compare_supplier_prices(ingredient_id: str):
    return {"ok": True, "data": {"comparisons": []}}

# 损耗
@router.get("/waste/top5")
async def get_waste_top5(store_id: str, period: str = "month"):
    """损耗 Top5（按金额排序+归因）"""
    return {"ok": True, "data": {"top5": []}}

@router.get("/waste/rate")
async def get_waste_rate(store_id: str):
    return {"ok": True, "data": {"waste_rate": 0, "trend": []}}

# 需求预测
@router.get("/demand/forecast")
async def forecast_demand(store_id: str, days: int = 7):
    return {"ok": True, "data": {"forecast": []}}
