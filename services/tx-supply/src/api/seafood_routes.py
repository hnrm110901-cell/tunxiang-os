"""活鲜库存 API -- 状态跟踪/损耗/鱼缸库存/按重定价/仪表盘

所有接口需要 X-Tenant-ID header。重量单位：克(g)。金额单位：分(fen)。
"""
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from services.tx_supply.src.services import live_seafood_v2

router = APIRouter(prefix="/api/v1/supply/seafood", tags=["seafood"])


# ─── 请求模型 ───


class TrackStatusRequest(BaseModel):
    ingredient_id: str
    store_id: str
    status: str = Field(description="alive|weak|dead")
    weight_g: float = Field(gt=0, description="称重(克)")


class LiveLossRequest(BaseModel):
    store_id: str
    start_date: date
    end_date: date


class PriceByWeightRequest(BaseModel):
    ingredient_id: str
    weight_g: float = Field(gt=0, description="称重(克)")


class TransferRequest(BaseModel):
    from_store_id: str
    from_warehouse_type: str = Field(description="central|store|dept")
    to_store_id: str
    to_warehouse_type: str = Field(description="central|store|dept")
    items: list[dict] = Field(description="[{ingredient_id, quantity_g}]")


# ─── 依赖注入占位 ───


async def _get_db():
    """数据库会话依赖 -- 由 main.py 覆盖"""
    raise NotImplementedError("DB session dependency not configured")


# ─── 端点 ───


@router.post("/track-status")
async def api_track_live_status(
    body: TrackStatusRequest,
    x_tenant_id: str = Header(alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
):
    """记录活鲜状态变更（alive/weak/dead，不可逆）"""
    try:
        result = await live_seafood_v2.track_live_status(
            ingredient_id=body.ingredient_id,
            store_id=body.store_id,
            status=body.status,
            weight_g=body.weight_g,
            tenant_id=x_tenant_id,
            db=db,
        )
        return {"ok": True, "data": result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/loss")
async def api_calculate_live_loss(
    body: LiveLossRequest,
    x_tenant_id: str = Header(alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
):
    """计算活鲜损耗（死亡/品质降级/称重差）"""
    try:
        result = await live_seafood_v2.calculate_live_loss(
            store_id=body.store_id,
            date_range=(body.start_date, body.end_date),
            tenant_id=x_tenant_id,
            db=db,
        )
        return {"ok": True, "data": result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/tanks/{store_id}")
async def api_get_tank_inventory(
    store_id: str,
    x_tenant_id: str = Header(alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
):
    """获取门店鱼缸/水箱分区库存"""
    result = await live_seafood_v2.get_tank_inventory(
        store_id=store_id,
        tenant_id=x_tenant_id,
        db=db,
    )
    return {"ok": True, "data": result}


@router.post("/price")
async def api_price_by_weight(
    body: PriceByWeightRequest,
    x_tenant_id: str = Header(alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
):
    """按重量实时定价（活鲜时价）"""
    try:
        result = await live_seafood_v2.price_by_weight(
            ingredient_id=body.ingredient_id,
            weight_g=body.weight_g,
            tenant_id=x_tenant_id,
            db=db,
        )
        return {"ok": True, "data": result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/dashboard/{store_id}")
async def api_get_seafood_dashboard(
    store_id: str,
    x_tenant_id: str = Header(alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
):
    """活鲜仪表盘（库存/损耗/价值/预警）"""
    result = await live_seafood_v2.get_seafood_dashboard(
        store_id=store_id,
        tenant_id=x_tenant_id,
        db=db,
    )
    return {"ok": True, "data": result}
