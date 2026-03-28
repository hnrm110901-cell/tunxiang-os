"""定价中心 API — 8个端点

覆盖：标准售价查询、时价设置、称重计价、套餐定价、
多渠道差异价、促销价、毛利校验、调价审批。
"""
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Header, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ..services.pricing_engine import PricingEngine

router = APIRouter(prefix="/api/v1/pricing", tags=["pricing"])


# ─── 依赖注入占位 ───

async def get_db() -> AsyncSession:  # type: ignore[override]
    """数据库会话依赖 — 由 main.py 中 app.dependency_overrides 注入"""
    raise NotImplementedError("DB session dependency not configured")


# ─── 请求/响应模型 ───

class SetMarketPriceReq(BaseModel):
    dish_id: str
    price_fen: int = Field(gt=0, description="时价（分）")
    effective_from: datetime = Field(description="生效时间")


class CalculateWeighingReq(BaseModel):
    dish_id: str
    weight_g: int = Field(gt=0, description="称重重量（克）")


class ComboItemReq(BaseModel):
    dish_id: str
    quantity: int = Field(ge=1, default=1)


class CreateComboReq(BaseModel):
    dishes: list[ComboItemReq]
    discount_rate: float = Field(gt=0, le=1.0, description="折扣率，如 0.85 = 85折")


class SetChannelPriceReq(BaseModel):
    dish_id: str
    channel_prices: dict[str, int] = Field(
        description="渠道价格映射，如 {'dine_in': 5800, 'takeaway': 5500}"
    )


class SetPromotionReq(BaseModel):
    dish_id: str
    promo_price_fen: int = Field(gt=0, description="促销价（分）")
    start: datetime
    end: datetime


class ValidateMarginReq(BaseModel):
    dish_id: str
    proposed_price_fen: int = Field(gt=0, description="提议售价（分）")
    store_id: Optional[str] = None


class ApprovePriceChangeReq(BaseModel):
    change_id: str
    approver_id: str


# ─── 1. 查询标准售价 ───

@router.get("/standard-price/{dish_id}")
async def get_standard_price(
    dish_id: str,
    channel: str = "dine_in",
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """查询菜品标准售价（优先级：时价 > 渠道价 > 促销价 > 基础售价）"""
    engine = PricingEngine(db, x_tenant_id)
    result = await engine.get_standard_price(dish_id, channel)
    return {"ok": True, "data": result}


# ─── 2. 设置时价（海鲜/活鲜） ───

@router.post("/market-price")
async def set_market_price(
    req: SetMarketPriceReq,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """设置时价菜价格（每日按市场价浮动）"""
    engine = PricingEngine(db, x_tenant_id)
    result = await engine.set_market_price(
        dish_id=req.dish_id,
        price_fen=req.price_fen,
        effective_from=req.effective_from,
    )
    return {"ok": True, "data": result}


# ─── 3. 称重计价 ───

@router.post("/weighing-price")
async def calculate_weighing_price(
    req: CalculateWeighingReq,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """称重计价：单价(分/500g) x 重量(g)"""
    engine = PricingEngine(db, x_tenant_id)
    result = await engine.calculate_weighing_price(
        dish_id=req.dish_id,
        weight_g=req.weight_g,
    )
    return {"ok": True, "data": result}


# ─── 4. 套餐组合定价 ───

@router.post("/combo-price")
async def create_combo_price(
    req: CreateComboReq,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """套餐组合定价（原价合计 x 折扣率）"""
    dishes_with_qty = [{"dish_id": d.dish_id, "quantity": d.quantity} for d in req.dishes]
    engine = PricingEngine(db, x_tenant_id)
    result = await engine.create_combo_price(
        dishes_with_qty=dishes_with_qty,
        discount_rate=req.discount_rate,
    )
    return {"ok": True, "data": result}


# ─── 5. 多渠道差异价 ───

@router.post("/channel-price")
async def set_channel_price(
    req: SetChannelPriceReq,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """设置多渠道差异价（堂食/外卖/外带等）"""
    engine = PricingEngine(db, x_tenant_id)
    result = await engine.set_channel_price(
        dish_id=req.dish_id,
        channel_prices=req.channel_prices,
    )
    return {"ok": True, "data": result}


# ─── 6. 促销价 ───

@router.post("/promotion-price")
async def set_promotion_price(
    req: SetPromotionReq,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """设置促销价（限时）"""
    engine = PricingEngine(db, x_tenant_id)
    result = await engine.set_promotion_price(
        dish_id=req.dish_id,
        promo_price_fen=req.promo_price_fen,
        start=req.start,
        end=req.end,
    )
    return {"ok": True, "data": result}


# ─── 7. 毛利底线校验 ───

@router.post("/validate-margin")
async def validate_margin(
    req: ValidateMarginReq,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """毛利底线校验 — 联动 BOM 理论成本"""
    engine = PricingEngine(db, x_tenant_id)
    result = await engine.validate_margin(
        dish_id=req.dish_id,
        proposed_price_fen=req.proposed_price_fen,
        store_id=req.store_id,
    )
    return {"ok": True, "data": result}


# ─── 8. 调价审批 ───

@router.post("/approve-change")
async def approve_price_change(
    req: ApprovePriceChangeReq,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """审批调价申请（自动校验毛利底线）"""
    engine = PricingEngine(db, x_tenant_id)
    result = await engine.approve_price_change(
        change_id=req.change_id,
        approver_id=req.approver_id,
    )
    return {"ok": True, "data": result}
