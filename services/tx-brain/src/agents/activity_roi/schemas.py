"""Pydantic V2 Schemas — 活动 ROI 预测（D3b）

所有金额字段统一使用**分**（int），不使用浮点。

设计原则：
- ActivityROIRequest 描述一个未启动的营销活动（投入预算、目标人群、活动起止）
- ActivityROIResponse 由 Pipeline 拼装：Prophet 基线 + 增量模型 + Sonnet 叙述
- ActivityROIPredictionPoint 用于按日展示 baseline / lift / 总量
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# ─── 错误类型 ────────────────────────────────────────────────────────────────


class InsufficientHistoricalDataError(ValueError):
    """历史数据不足以训练 Prophet 基线（< 14 天）。"""


# ─── 活动类型枚举 ────────────────────────────────────────────────────────────

ActivityType = Literal[
    "full_reduction",       # 满减（满 100 减 20 等）
    "member_day",           # 会员日折扣
    "douyin_groupon",       # 抖音团购
    "xiaohongshu_coupon",   # 小红书优惠券种草
    "wechat_groupon",       # 微信小程序团购
    "second_half_off",      # 第二份半价
    "free_dish",            # 满赠菜品
    "limited_time_special", # 限时特价单品
]


# ─── 请求 ────────────────────────────────────────────────────────────────────


class ActivityROIRequest(BaseModel):
    """活动 ROI 预测请求。

    fields 全部为活动启动**前**已知的输入。历史数据由 repository 注入，
    本 schema 不携带 GMV 序列。
    """

    model_config = ConfigDict(extra="forbid")

    tenant_id: UUID
    store_id: UUID
    activity_type: ActivityType
    start_at: datetime = Field(..., description="活动开始时间（含时区）")
    end_at: datetime = Field(..., description="活动结束时间（含时区）")
    cost_budget_fen: int = Field(..., gt=0, description="活动预算（分）")
    target_audience_size: int | None = Field(
        default=None, ge=0, description="目标触达人群规模（None 表示未限定）"
    )
    historical_baseline_days: int = Field(
        default=30,
        ge=14,
        le=365,
        description="使用过去 N 天作为 Prophet 训练数据，最少 14 天",
    )

    @model_validator(mode="after")
    def _validate_window(self) -> "ActivityROIRequest":
        if self.end_at <= self.start_at:
            raise ValueError("end_at 必须晚于 start_at")
        # 限制单次预测窗口最长 90 天，超出对 Prophet 不合理
        delta = (self.end_at - self.start_at).days
        if delta > 90:
            raise ValueError("活动窗口不得超过 90 天")
        return self


# ─── 单日预测点 ──────────────────────────────────────────────────────────────


class ActivityROIPredictionPoint(BaseModel):
    """活动期间单日的 GMV 拆解。"""

    model_config = ConfigDict(extra="forbid")

    date: date
    baseline_gmv_fen: int = Field(..., ge=0, description="不做活动的预测 GMV（Prophet 输出）")
    expected_lift_gmv_fen: int = Field(..., description="活动带来的增量 GMV（可负，假动作）")
    expected_total_gmv_fen: int = Field(..., ge=0, description="baseline + lift（裁剪到 ≥ 0）")

    @field_validator("expected_total_gmv_fen")
    @classmethod
    def _non_negative_total(cls, v: int) -> int:
        if v < 0:
            raise ValueError("expected_total_gmv_fen 不能为负")
        return v


# ─── 响应 ────────────────────────────────────────────────────────────────────


class ActivityROIResponse(BaseModel):
    """活动 ROI 预测响应。

    Sonnet 生成的 narrative_zh 用于经理阅读，包含：
    - 预期 lift 与活动成本对比
    - 三大风险（假动作 / 客流稀释 / 毛利侵蚀）
    - 是否建议启动
    """

    model_config = ConfigDict(extra="forbid")

    request_id: UUID
    predicted_total_lift_gmv_fen: int = Field(..., description="累计增量 GMV（分）")
    predicted_lift_gross_margin_fen: int = Field(
        ..., description="累计增量毛利（分），可能为负"
    )
    predicted_roi_ratio: float = Field(
        ..., description="增量毛利 / 活动成本，>1 即正 ROI"
    )
    confidence_interval: tuple[float, float] = Field(
        ..., description="ROI 80% 置信区间（low, high）"
    )
    daily_predictions: list[ActivityROIPredictionPoint]
    narrative_zh: str = Field(..., min_length=1, description="Sonnet 生成的中文叙述")
    mape_estimate: float = Field(
        ..., ge=0.0, description="历史回测 MAPE 估计（如 0.18 表示 18%）"
    )
    cache_hit_ratio: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Prompt Cache 命中率估计（None 表示未启用 cache）",
    )
