"""菜品深度智能 API

4 个端点：口碑指标、经营状态推导、生命周期、动作建议。
"""
from fastapi import APIRouter, Header
from services.tx_menu.src.services import dish_intelligence

router = APIRouter(prefix="/api/v1/menu/dish-intel", tags=["dish-intelligence"])


# ─── 端点 ───


@router.get("/reputation/{dish_id}")
async def get_dish_reputation(
    dish_id: str,
    x_tenant_id: str = Header(alias="X-Tenant-ID"),
):
    """菜品口碑指标（评分/差评率/推荐率/复点率）"""
    result = dish_intelligence.calculate_dish_reputation(
        dish_id=dish_id,
        tenant_id=x_tenant_id,
    )
    return {"ok": True, "data": result}


@router.get("/status/{dish_id}")
async def get_dish_status(
    dish_id: str,
    x_tenant_id: str = Header(alias="X-Tenant-ID"),
):
    """经营状态自动推导（star/rising/declining/underperform/seasonal_peak/new）"""
    result = dish_intelligence.auto_derive_status(
        dish_id=dish_id,
        tenant_id=x_tenant_id,
    )
    return {"ok": True, "data": result}


@router.get("/lifecycle/{dish_id}")
async def get_dish_lifecycle(
    dish_id: str,
    x_tenant_id: str = Header(alias="X-Tenant-ID"),
):
    """菜品生命周期（launch/growth/mature/decline）"""
    result = dish_intelligence.get_dish_lifecycle(
        dish_id=dish_id,
        tenant_id=x_tenant_id,
    )
    return {"ok": True, "data": result}


@router.get("/suggest/{dish_id}")
async def suggest_dish_action(
    dish_id: str,
    x_tenant_id: str = Header(alias="X-Tenant-ID"),
):
    """基于状态建议动作（推广/提价/降价/替换/下架）"""
    result = dish_intelligence.suggest_dish_action(
        dish_id=dish_id,
        tenant_id=x_tenant_id,
    )
    return {"ok": True, "data": result}
