"""食安合规与追溯 API

8 个端点：禁用过期原料、检查禁用食材、批次追溯、留样记录、
温控记录、合规检查表、食安事件上报、责任追踪链。
"""
from datetime import date, datetime
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from services.tx_supply.src.services import food_safety

router = APIRouter(prefix="/api/v1/supply/food-safety", tags=["food-safety"])


# ─── Pydantic 请求体 ───


class BlockExpiredRequest(BaseModel):
    ingredient_id: str
    store_id: str


class CheckBannedRequest(BaseModel):
    order_items: list[dict] = Field(description="[{ingredient_id, name, ...}]")
    store_id: str


class TraceBatchRequest(BaseModel):
    batch_no: str


class RecordSampleRequest(BaseModel):
    store_id: str
    dish_id: str
    sample_time: datetime
    photo_url: str
    operator_id: str


class RecordTemperatureRequest(BaseModel):
    store_id: str
    location: str = Field(description="cold_storage | freezer | hot_chain")
    temperature: float
    operator_id: str


class ReportEventRequest(BaseModel):
    store_id: str
    event_type: str = Field(
        description="expired_ingredient / temperature_violation / "
                    "foreign_object / food_poisoning / pest / other",
    )
    detail: str
    severity: str = Field(description="low / medium / high / critical")


class ResponsibilityChainRequest(BaseModel):
    event_id: str
    batch_no: Optional[str] = None
    ingredient_id: Optional[str] = None
    store_id: Optional[str] = None


# ─── 依赖注入占位 ───


async def _get_db():
    """数据库会话依赖 -- 由 main.py 覆盖"""
    raise NotImplementedError("DB session dependency not configured")


# ─── 端点 ───


@router.post("/block-expired")
async def block_expired_ingredient(
    body: BlockExpiredRequest,
    x_tenant_id: str = Header(alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
):
    """禁用过期原料（硬约束：不可出品）"""
    result = await food_safety.block_expired_ingredient(
        ingredient_id=body.ingredient_id,
        store_id=body.store_id,
        tenant_id=x_tenant_id,
        db=db,
    )
    return {"ok": True, "data": result}


@router.post("/check-banned")
async def check_banned_ingredients(
    body: CheckBannedRequest,
    x_tenant_id: str = Header(alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
):
    """检查订单中是否包含禁用食材"""
    result = await food_safety.check_banned_ingredients(
        order_items=body.order_items,
        store_id=body.store_id,
        tenant_id=x_tenant_id,
        db=db,
    )
    if not result["passed"]:
        raise HTTPException(
            status_code=422,
            detail={
                "message": "订单包含禁用食材，不可出品",
                "banned_items": result["banned_items"],
            },
        )
    return {"ok": True, "data": result}


@router.get("/trace/{batch_no}")
async def trace_batch(
    batch_no: str,
    x_tenant_id: str = Header(alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
):
    """批次追溯（供应商 -> 入库 -> 领用 -> 出品 -> 客户）"""
    result = await food_safety.trace_batch(
        batch_no=batch_no,
        tenant_id=x_tenant_id,
        db=db,
    )
    if not result["found"]:
        raise HTTPException(status_code=404, detail=f"批次 {batch_no} 未找到")
    return {"ok": True, "data": result}


@router.post("/sample")
async def record_sample(
    body: RecordSampleRequest,
    x_tenant_id: str = Header(alias="X-Tenant-ID"),
):
    """留样记录（至少保留 48 小时）"""
    result = food_safety.record_sample(
        store_id=body.store_id,
        dish_id=body.dish_id,
        sample_time=body.sample_time,
        photo_url=body.photo_url,
        operator_id=body.operator_id,
        tenant_id=x_tenant_id,
    )
    return {"ok": True, "data": result}


@router.post("/temperature")
async def record_temperature(
    body: RecordTemperatureRequest,
    x_tenant_id: str = Header(alias="X-Tenant-ID"),
):
    """温控记录（冷藏 0-4C / 冷冻 <-18C / 热链 >60C）"""
    result = food_safety.record_temperature(
        store_id=body.store_id,
        location=body.location,
        temperature=body.temperature,
        operator_id=body.operator_id,
        tenant_id=x_tenant_id,
    )
    return {"ok": True, "data": result}


@router.get("/checklist/{store_id}")
async def get_compliance_checklist(
    store_id: str,
    check_date: Optional[date] = None,
    x_tenant_id: str = Header(alias="X-Tenant-ID"),
):
    """合规检查表"""
    d = check_date or date.today()
    result = food_safety.get_compliance_checklist(
        store_id=store_id,
        check_date=d,
        tenant_id=x_tenant_id,
    )
    return {"ok": True, "data": result}


@router.post("/event")
async def report_food_safety_event(
    body: ReportEventRequest,
    x_tenant_id: str = Header(alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
):
    """食安事件上报（severity=critical 自动通知区域经理）"""
    result = await food_safety.report_food_safety_event(
        store_id=body.store_id,
        event_type=body.event_type,
        detail=body.detail,
        severity=body.severity,
        tenant_id=x_tenant_id,
        db=db,
    )
    return {"ok": True, "data": result}


@router.post("/responsibility-chain")
async def get_responsibility_chain(
    body: ResponsibilityChainRequest,
    x_tenant_id: str = Header(alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
):
    """责任追踪链（谁采购 -> 谁验收 -> 谁领用 -> 谁出品）"""
    result = await food_safety.get_responsibility_chain(
        event_id=body.event_id,
        tenant_id=x_tenant_id,
        db=db,
        batch_no=body.batch_no,
        ingredient_id=body.ingredient_id,
        store_id=body.store_id,
    )
    return {"ok": True, "data": result}
