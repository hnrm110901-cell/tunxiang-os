"""库存与供应链 API

入库/出库/盘点/效期/安全库存/沽清预测 路由。
"""
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db as _get_db

from ..services import expiry_monitor, inventory_io, stock_forecast
from ..services.transfer_service import (
    get_brand_ingredient_overview,
    get_brand_low_stock_alert,
)

router = APIRouter(prefix="/api/v1/supply", tags=["supply"])


# ─── Pydantic 请求体 ───


class ReceiveStockRequest(BaseModel):
    ingredient_id: str
    quantity: float = Field(gt=0)
    unit_cost_fen: int = Field(ge=0)
    batch_no: str
    expiry_date: Optional[date] = None
    store_id: str
    performed_by: Optional[str] = None


class IssueStockRequest(BaseModel):
    ingredient_id: str
    quantity: float = Field(gt=0)
    reason: str = Field(description="usage|waste|transfer")
    store_id: str
    performed_by: Optional[str] = None
    reference_id: Optional[str] = None


class AdjustStockRequest(BaseModel):
    ingredient_id: str
    quantity: float = Field(description="正=盘盈, 负=盘亏")
    reason: str
    store_id: str
    performed_by: Optional[str] = None


# ─── 库存基础查询 ───


@router.get("/inventory")
async def list_inventory(
    store_id: str,
    status: Optional[str] = None,
    page: int = 1,
    size: int = 20,
    x_tenant_id: str = Header(alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
):
    """库存列表"""
    result = await inventory_io.get_store_inventory(
        store_id=store_id, tenant_id=x_tenant_id, db=db, page=page, size=size,
    )
    return {"ok": True, "data": result}


@router.get("/inventory/{item_id}")
async def get_inventory_item(
    item_id: str,
    store_id: str = "",
    x_tenant_id: str = Header(alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
):
    """单个原料库存"""
    if not store_id:
        raise HTTPException(status_code=400, detail="store_id 必传")
    try:
        result = await inventory_io.get_stock_balance(
            ingredient_id=item_id, store_id=store_id,
            tenant_id=x_tenant_id, db=db,
        )
        return {"ok": True, "data": result}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/inventory/{item_id}/adjust")
async def adjust_inventory(
    item_id: str,
    body: AdjustStockRequest,
    x_tenant_id: str = Header(alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
):
    """盘点调整"""
    try:
        result = await inventory_io.adjust_stock(
            ingredient_id=item_id, quantity=body.quantity, reason=body.reason,
            store_id=body.store_id, tenant_id=x_tenant_id, db=db,
            performed_by=body.performed_by,
        )
        return {"ok": True, "data": result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/inventory/alerts")
async def get_inventory_alerts(
    store_id: str,
    x_tenant_id: str = Header(alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
):
    """库存预警列表（低库存 + 临期）"""
    safety = await stock_forecast.check_safety_stock(
        store_id=store_id, tenant_id=x_tenant_id, db=db,
    )
    expiry = await expiry_monitor.generate_expiry_report(
        store_id=store_id, tenant_id=x_tenant_id, db=db,
    )
    low_stock = [i for i in safety if i["status"] != "ok"]
    return {
        "ok": True,
        "data": {
            "alerts": {
                "low_stock": low_stock,
                "expiry": expiry,
            }
        },
    }


# ─── 入库出库 ───


@router.post("/inventory/receive")
async def receive_stock(
    body: ReceiveStockRequest,
    x_tenant_id: str = Header(alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
):
    """采购入库"""
    try:
        result = await inventory_io.receive_stock(
            ingredient_id=body.ingredient_id,
            quantity=body.quantity,
            unit_cost_fen=body.unit_cost_fen,
            batch_no=body.batch_no,
            expiry_date=body.expiry_date,
            store_id=body.store_id,
            tenant_id=x_tenant_id,
            db=db,
            performed_by=body.performed_by,
        )
        return {"ok": True, "data": result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/inventory/issue")
async def issue_stock(
    body: IssueStockRequest,
    x_tenant_id: str = Header(alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
):
    """出库（FIFO 先进先出）"""
    try:
        result = await inventory_io.issue_stock(
            ingredient_id=body.ingredient_id,
            quantity=body.quantity,
            reason=body.reason,
            store_id=body.store_id,
            tenant_id=x_tenant_id,
            db=db,
            performed_by=body.performed_by,
            reference_id=body.reference_id,
        )
        return {"ok": True, "data": result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ─── 库存余额与清单 ───


@router.get("/inventory/balance/{ingredient_id}")
async def get_balance(
    ingredient_id: str,
    store_id: str = "",
    x_tenant_id: str = Header(alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
):
    """单个原料库存余额 + 批次明细"""
    if not store_id:
        raise HTTPException(status_code=400, detail="store_id 必传")
    try:
        result = await inventory_io.get_stock_balance(
            ingredient_id=ingredient_id, store_id=store_id,
            tenant_id=x_tenant_id, db=db,
        )
        return {"ok": True, "data": result}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/inventory/store/{store_id}")
async def get_store_inventory(
    store_id: str,
    page: int = 1,
    size: int = 50,
    x_tenant_id: str = Header(alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
):
    """门店全部库存清单"""
    result = await inventory_io.get_store_inventory(
        store_id=store_id, tenant_id=x_tenant_id, db=db,
        page=page, size=size,
    )
    return {"ok": True, "data": result}


# ─── 效期监控 ───


@router.get("/inventory/expiry/{store_id}")
async def get_expiry_report(
    store_id: str,
    x_tenant_id: str = Header(alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
):
    """效期报告（过期 + 3天内 + 7天内）"""
    result = await expiry_monitor.generate_expiry_report(
        store_id=store_id, tenant_id=x_tenant_id, db=db,
    )
    return {"ok": True, "data": result}


# ─── 安全库存与预测 ───


@router.get("/inventory/safety/{store_id}")
async def get_safety_stock(
    store_id: str,
    safety_days: int = 3,
    x_tenant_id: str = Header(alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
):
    """安全库存检查"""
    result = await stock_forecast.check_safety_stock(
        store_id=store_id, tenant_id=x_tenant_id, db=db,
        safety_days=safety_days,
    )
    return {"ok": True, "data": {"items": result}}


@router.get("/inventory/forecast/{store_id}/{ingredient_id}")
async def get_stockout_forecast(
    store_id: str,
    ingredient_id: str,
    x_tenant_id: str = Header(alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
):
    """沽清预测"""
    try:
        result = await stock_forecast.predict_stockout(
            store_id=store_id, ingredient_id=ingredient_id,
            tenant_id=x_tenant_id, db=db,
        )
        return {"ok": True, "data": result}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/inventory/reorder/{store_id}")
async def get_reorder_suggestions(
    store_id: str,
    safety_days: int = 3,
    x_tenant_id: str = Header(alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
):
    """采购建议"""
    result = await stock_forecast.suggest_reorder(
        store_id=store_id, tenant_id=x_tenant_id, db=db,
        safety_days=safety_days,
    )
    return {"ok": True, "data": {"suggestions": result}}


# ─── 采购 ───


@router.get("/procurement/plans")
async def list_procurement_plans(store_id: str):
    return {"ok": True, "data": {"plans": []}}


@router.post("/procurement/plans")
async def create_procurement_plan(store_id: str, items: list[dict]):
    return {"ok": True, "data": {"plan_id": "new"}}


@router.post("/procurement/plans/{plan_id}/approve")
async def approve_procurement(plan_id: str, operator_id: str):
    return {"ok": True, "data": {"approved": True}}


# ─── 供应商 ───


@router.get("/suppliers")
async def list_suppliers(page: int = 1, size: int = 20):
    return {"ok": True, "data": {"items": [], "total": 0}}


@router.get("/suppliers/{supplier_id}/rating")
async def get_supplier_rating(supplier_id: str):
    return {"ok": True, "data": {"rating": None}}


@router.get("/suppliers/price-comparison")
async def compare_supplier_prices(ingredient_id: str):
    return {"ok": True, "data": {"comparisons": []}}


# ─── 损耗 ───


@router.get("/waste/top5")
async def get_waste_top5(store_id: str, period: str = "month"):
    """损耗 Top5（按金额排序+归因）"""
    return {"ok": True, "data": {"top5": []}}


@router.get("/waste/rate")
async def get_waste_rate(store_id: str):
    return {"ok": True, "data": {"waste_rate": 0, "trend": []}}


# ─── 需求预测 ───


@router.get("/demand/forecast")
async def forecast_demand(store_id: str, days: int = 7):
    return {"ok": True, "data": {"forecast": []}}


# ─── 多门店库存汇总（品牌维度） ───


@router.get("/inventory/brand-overview")
async def get_brand_overview(
    ingredient_id: str,
    x_tenant_id: str = Header(alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
):
    """品牌维度：查看所有门店某食材的库存量。

    返回: [{store_id, ingredient_name, quantity, unit, min_quantity, status}]
    方便决策从哪个门店调拨。
    """
    try:
        result = await get_brand_ingredient_overview(
            tenant_id=x_tenant_id,
            ingredient_id=ingredient_id,
            db=db,
        )
        return {"ok": True, "data": {"stores": result, "total_stores": len(result)}}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/inventory/low-stock-alert")
async def get_low_stock_alert(
    x_tenant_id: str = Header(alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
):
    """全品牌低库存预警：所有门店中库存低于安全库存的食材+所在门店。"""
    result = await get_brand_low_stock_alert(
        tenant_id=x_tenant_id,
        db=db,
    )
    return {
        "ok": True,
        "data": {
            "alerts": result,
            "total": len(result),
        },
    }
