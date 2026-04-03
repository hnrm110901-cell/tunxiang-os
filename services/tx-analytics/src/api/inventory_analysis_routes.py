"""库存成本深度分析 API 路由 — D6 模块

8 个端点: 周转率/涨跌监控/损耗排行/盘点差异/采购偏差/成本偏差/活鲜损耗/食安图谱
统一响应格式: {"ok": bool, "data": {}, "error": {}}
"""

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/api/v1/analytics/inventory", tags=["inventory-analysis"])


# ─── 请求模型 ───


class DateRangeRequest(BaseModel):
    start: str
    end: str


# ─── 依赖 ───


def _get_tenant_id(x_tenant_id: str = Header(...)) -> str:
    return x_tenant_id


# ─── 1. 库存周转率 ───


@router.post("/stores/{store_id}/turnover")
async def inventory_turnover(
    store_id: str,
    body: DateRangeRequest,
    x_tenant_id: str = Header(...),
):
    """库存周转率（天）: 平均库存成本 * 天数 / 期间消耗成本"""
    from ..services.inventory_analysis import inventory_turnover as svc

    try:
        result = await svc(
            store_id=store_id,
            date_range=body.model_dump(),
            tenant_id=x_tenant_id,
            db=None,
        )
        return {"ok": True, "data": result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ─── 2. 原料涨跌监控 ───


@router.post("/price-fluctuation")
async def price_fluctuation_monitor(
    body: DateRangeRequest,
    x_tenant_id: str = Header(...),
):
    """原料涨跌监控"""
    from ..services.inventory_analysis import price_fluctuation_monitor as svc

    try:
        result = await svc(
            tenant_id=x_tenant_id,
            date_range=body.model_dump(),
            db=None,
        )
        return {"ok": True, "data": result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ─── 3. 损耗排行 ───


@router.post("/stores/{store_id}/waste-ranking")
async def waste_ranking(
    store_id: str,
    body: DateRangeRequest,
    x_tenant_id: str = Header(...),
):
    """损耗排行（金额/数量/频率）"""
    from ..services.inventory_analysis import waste_ranking as svc

    try:
        result = await svc(
            store_id=store_id,
            date_range=body.model_dump(),
            tenant_id=x_tenant_id,
            db=None,
        )
        return {"ok": True, "data": result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ─── 4. 盘点差异分析 ───


@router.post("/stores/{store_id}/stocktake-variance")
async def stocktake_variance_analysis(
    store_id: str,
    body: DateRangeRequest,
    x_tenant_id: str = Header(...),
):
    """盘点差异分析（按原料/按门店）"""
    from ..services.inventory_analysis import stocktake_variance_analysis as svc

    try:
        result = await svc(
            store_id=store_id,
            date_range=body.model_dump(),
            tenant_id=x_tenant_id,
            db=None,
        )
        return {"ok": True, "data": result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ─── 5. 采购偏差 ───


@router.post("/stores/{store_id}/procurement-variance")
async def procurement_variance(
    store_id: str,
    body: DateRangeRequest,
    x_tenant_id: str = Header(...),
):
    """采购偏差（计划 vs 实际）"""
    from ..services.inventory_analysis import procurement_variance as svc

    try:
        result = await svc(
            store_id=store_id,
            date_range=body.model_dump(),
            tenant_id=x_tenant_id,
            db=None,
        )
        return {"ok": True, "data": result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ─── 6. 菜品成本偏差 ───


@router.post("/stores/{store_id}/dish-cost-variance")
async def dish_cost_variance_deep(
    store_id: str,
    body: DateRangeRequest,
    x_tenant_id: str = Header(...),
):
    """菜品成本偏差（理论 vs 实际，细到原料级）"""
    from ..services.inventory_analysis import dish_cost_variance_deep as svc

    try:
        result = await svc(
            store_id=store_id,
            date_range=body.model_dump(),
            tenant_id=x_tenant_id,
            db=None,
        )
        return {"ok": True, "data": result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ─── 7. 活鲜损耗专项 ───


@router.post("/stores/{store_id}/seafood-waste")
async def seafood_waste_analysis(
    store_id: str,
    body: DateRangeRequest,
    x_tenant_id: str = Header(...),
):
    """活鲜损耗专项（徐记海鲜核心）: 存活/死亡/品质降级"""
    from ..services.inventory_analysis import seafood_waste_analysis as svc

    try:
        result = await svc(
            store_id=store_id,
            date_range=body.model_dump(),
            tenant_id=x_tenant_id,
            db=None,
        )
        return {"ok": True, "data": result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ─── 8. 食安风险图谱 ───


@router.get("/stores/{store_id}/food-safety-risk")
async def food_safety_risk_graph(
    store_id: str,
    x_tenant_id: str = Header(...),
):
    """食安风险图谱（临期/过期/异常温度/高风险原料）"""
    from ..services.inventory_analysis import food_safety_risk_graph as svc

    try:
        result = await svc(
            store_id=store_id,
            tenant_id=x_tenant_id,
            db=None,
        )
        return {"ok": True, "data": result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
