"""D3c — Dish Pricing Pydantic schemas.

所有金额字段单位为**分（整数）**，不使用浮点。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# 时段枚举（边缘和云端共用）
TimeOfDayLiteral = Literal["lunch_peak", "dinner_peak", "off_peak"]
TrafficForecastLiteral = Literal["high", "medium", "low"]
InventoryStatusLiteral = Literal["near_expiry", "normal", "low_stock"]
SourceLiteral = Literal["edge", "cloud"]


class DishPricingRequest(BaseModel):
    """菜品动态定价请求"""

    model_config = ConfigDict(extra="ignore")

    dish_id: str = Field(..., description="菜品ID")
    store_id: str = Field(..., description="门店ID")
    tenant_id: str = Field(..., description="租户ID")
    base_price_fen: int = Field(..., gt=0, description="基准价（分）")
    cost_fen: int = Field(..., ge=0, description="成本价（分），需 < base_price_fen")
    time_of_day: TimeOfDayLiteral = Field(..., description="时段")
    traffic_forecast: TrafficForecastLiteral = Field(..., description="客流预测")
    inventory_status: InventoryStatusLiteral = Field(..., description="库存状态")


class PricingSignal(BaseModel):
    """单条定价信号（用于解释推理过程）"""

    model_config = ConfigDict(extra="ignore")

    name: str = Field(..., description="信号名（如 traffic / near_expiry / margin_floor_clamp）")
    delta: str = Field(..., description="对价格的乘数偏移（如 '+0.05' / '-0.10' / 'applied'）")


class DishPricingResponse(BaseModel):
    """菜品动态定价响应

    Note:
        floor_protected=True 表示毛利底线 GUARD 触发，建议价已被夹回 cost/0.85
        confidence < 0.7 时不应直接进入推荐流（影子模式观察）
    """

    model_config = ConfigDict(extra="ignore")

    recommended_price_fen: int = Field(..., gt=0)
    confidence: float = Field(..., ge=0.0, le=1.0)
    reasoning_signals: list[PricingSignal] = Field(default_factory=list)
    model_version: str = Field(..., description="如 stub-v0 / cloud-fallback-v0 / coreml-v1")
    computed_at_ms: int = Field(..., description="计算完成的 epoch ms")
    floor_protected: bool = Field(False, description="毛利底线 GUARD 是否触发")
    source: SourceLiteral = Field(..., description="推理来源：edge / cloud")
