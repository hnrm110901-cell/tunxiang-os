"""库存驱动菜单联动 API 路由

对标 Lightspeed / Odoo 库存-菜单联动：
  当食材库存低于阈值时，自动下架依赖此食材的菜品。
"""
from fastapi import APIRouter, Depends, HTTPException, Header, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db
from ..services.inventory_menu_sync_service import (
    check_and_auto_soldout,
    restore_dishes_by_ingredient,
    get_soldout_watch,
    get_inventory_dashboard,
)

router = APIRouter(prefix="/api/v1/inventory", tags=["inventory-menu"])


# ─── 请求 / 响应 Schema ───

class StockUpdateRequest(BaseModel):
    current_stock: float = Field(..., ge=0, description="当前库存量")
    unit: str = Field(..., min_length=1, max_length=20, description="单位，如 kg / 份 / 个")
    updated_by: str = Field(..., description="操作人员 ID 或姓名")


class RestockRequest(BaseModel):
    add_stock: float = Field(..., gt=0, description="补货数量（正数）")
    unit: str = Field(..., min_length=1, max_length=20, description="单位")


# ─── 路由 ───

@router.post("/ingredient/{ingredient_id}/stock-update")
async def api_stock_update(
    ingredient_id: str,
    body: StockUpdateRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """
    库存更新触发菜单联动。

    由采购收货/库存盘点模块调用，
    内部执行 check_and_auto_soldout：
      - 估算依赖此食材的菜品可出份数
      - 可出份数为0时自动下架并广播
    """
    try:
        auto_soldout_list = await check_and_auto_soldout(
            ingredient_id=ingredient_id,
            current_stock=body.current_stock,
            tenant_id=x_tenant_id,
            db=db,
        )
        return {
            "ok": True,
            "data": {
                "ingredient_id": ingredient_id,
                "current_stock": body.current_stock,
                "unit": body.unit,
                "updated_by": body.updated_by,
                "auto_soldout_dishes": [
                    {
                        "dish_id": d.dish_id,
                        "dish_name": d.dish_name,
                        "estimated_servings": d.estimated_servings,
                    }
                    for d in auto_soldout_list
                ],
                "auto_soldout_count": len(auto_soldout_list),
            },
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/soldout-watch")
async def api_soldout_watch(
    store_id: str = Query(..., description="门店 ID"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """
    低库存预警菜品列表。

    返回所有低库存/已下架菜品，按紧急程度排序。
    前端 InventoryAlertBanner 每60秒轮询此接口。
    """
    try:
        items = await get_soldout_watch(
            store_id=store_id,
            tenant_id=x_tenant_id,
            db=db,
        )
        return {
            "ok": True,
            "data": {
                "items": items,
                "total": len(items),
                "store_id": store_id,
            },
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/ingredient/{ingredient_id}/restock")
async def api_restock(
    ingredient_id: str,
    body: RestockRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """
    食材补货到货，自动恢复相关菜品上架。

    仅恢复因此食材缺货而下架的菜品，
    其他原因（KDS手动下架等）的下架记录不受影响。
    """
    try:
        restored = await restore_dishes_by_ingredient(
            ingredient_id=ingredient_id,
            tenant_id=x_tenant_id,
            db=db,
        )
        return {
            "ok": True,
            "data": {
                "ingredient_id": ingredient_id,
                "add_stock": body.add_stock,
                "unit": body.unit,
                "restored_dish_ids": restored,
                "restored_count": len(restored),
            },
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/dashboard")
async def api_inventory_dashboard(
    store_id: str = Query(..., description="门店 ID"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """
    库存健康状态汇总仪表盘。

    返回：
      total_ingredients  — 食材总数
      low_stock_count    — 低库存食材数
      soldout_dishes_count — 因缺货下架的菜品数
      alerts             — 预警详情列表（按影响菜品数降序）
    """
    try:
        dashboard = await get_inventory_dashboard(
            store_id=store_id,
            tenant_id=x_tenant_id,
            db=db,
        )
        return {"ok": True, "data": dashboard}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
