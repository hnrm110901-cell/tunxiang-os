"""品牌策略中枢 Pydantic schemas

涵盖 brand_profiles / brand_seasonal_calendar / brand_content_constraints
三张表的 Create / Update / Response 模型。
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator

# F#5 audit P1：jsonb 嵌套字段（list[dict] / dict）的长度上限。Pydantic 拒绝
# 在 write 路径就阻断超长 payload；read 路径仍由 sanitize_for_prompt 兜底（已
# 落盘旧数据）。具体值与 brand_strategy_db_service._build_system_prompt 的
# sanitize_for_prompt max_chars 参数对齐。
_TARGET_SEGMENT_DESC_MAX = 500  # F#5 audit P1：target_segments[].description
_TEMPLATE_HINTS_FLAT_MAX = 2000  # F#5 audit P1：template_hints 整体 flat 总长
_CAMPAIGN_THEME_MAX = 200  # F#5 audit row 67：campaign_theme
_MARKETING_FOCUS_MAX = 200  # F#5 audit row 67：marketing_focus


def _flat_str_len(value: Any) -> int:
    """递归累加 dict / list / str 中所有 str 字符总长度（含 key 和 value）

    用于 jsonb 嵌套字段（如 template_hints）的"展平后总长度"上限校验。
    """
    if value is None:
        return 0
    if isinstance(value, str):
        return len(value)
    if isinstance(value, dict):
        return sum(
            (_flat_str_len(k) if isinstance(k, str) else 0) + _flat_str_len(v)
            for k, v in value.items()
        )
    if isinstance(value, list):
        return sum(_flat_str_len(item) for item in value)
    return 0

# ---------------------------------------------------------------------------
# 嵌套结构体（JSONB 字段的类型声明，用于文档/验证）
# ---------------------------------------------------------------------------


class TargetSegmentItem(BaseModel):
    segment_name: str = Field(..., description="客群名称，如「高价值常客」")
    description: str = Field(default="", description="客群描述")
    proportion: float = Field(default=0.0, ge=0.0, le=1.0, description="占比 0~1")


class KeyScenarioItem(BaseModel):
    scenario: str = Field(..., description="场景名称，如「家庭聚餐」")
    importance: str = Field(default="medium", description="重要程度：high/medium/low")


class BrandVoice(BaseModel):
    tone: str = Field(default="", description="语气风格，如「温暖亲切」")
    style: str = Field(default="", description="写作风格，如「短句为主，口语化」")
    forbidden_words: list[str] = Field(default_factory=list, description="禁用词列表")
    preferred_words: list[str] = Field(default_factory=list, description="推荐用词列表")


class ColorPalette(BaseModel):
    primary: str = Field(default="", description="主色调，如「#E53E3E」")
    secondary: str = Field(default="", description="辅色")
    accent: str = Field(default="", description="强调色")
    background: str = Field(default="", description="背景色")


# ---------------------------------------------------------------------------
# BrandProfile — 品牌档案
# ---------------------------------------------------------------------------


class BrandProfileCreate(BaseModel):
    brand_name: str = Field(..., max_length=100, description="品牌名称")
    # F#5：max_length 与 sanitize_for_prompt 单字段 cap 对齐 — write 路径拒绝超长，
    # read 路径 sanitize 兜底（已落盘的旧数据可能超长）
    brand_slogan: Optional[str] = Field(default=None, max_length=200, description="品牌口号")
    brand_story: Optional[str] = Field(default=None, max_length=2000, description="品牌故事")
    cuisine_type: Optional[str] = Field(default=None, max_length=50, description="菜系")
    price_tier: str = Field(default="mid", description="价格带：budget/mid/upscale/luxury")
    core_value_proposition: Optional[str] = Field(default=None, max_length=200, description="核心价值主张")
    target_segments: list[dict[str, Any]] = Field(
        default_factory=list, description="目标客群列表，每项包含 segment_name/description/proportion"
    )
    key_scenarios: list[dict[str, Any]] = Field(
        default_factory=list, description="主打场景列表，每项包含 scenario/importance"
    )
    brand_voice: dict[str, Any] = Field(
        default_factory=dict, description="品牌语气配置：{tone, style, forbidden_words[], preferred_words[]}"
    )
    color_palette: dict[str, Any] = Field(
        default_factory=dict, description="品牌色配置：{primary, secondary, accent, background}"
    )
    is_active: bool = Field(default=True, description="是否为当前激活档案")

    @field_validator("price_tier")
    @classmethod
    def validate_price_tier(cls, v: str) -> str:
        allowed = {"budget", "mid", "upscale", "luxury"}
        if v not in allowed:
            raise ValueError(f"price_tier 必须是 {allowed} 之一，收到: {v!r}")
        return v

    @field_validator("target_segments")
    @classmethod
    def validate_target_segments_description(
        cls, v: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """F#5 audit P1：每条 segment 的 description 字段 ≤500 字符"""
        for item in v:
            desc = item.get("description")
            if isinstance(desc, str) and len(desc) > _TARGET_SEGMENT_DESC_MAX:
                raise ValueError(
                    f"target_segments[].description 长度 {len(desc)} 超出上限 {_TARGET_SEGMENT_DESC_MAX}"
                )
        return v


class BrandProfileUpdate(BaseModel):
    brand_name: Optional[str] = Field(default=None, max_length=100)
    # F#5：与 BrandProfileCreate 对齐
    brand_slogan: Optional[str] = Field(default=None, max_length=200)
    brand_story: Optional[str] = Field(default=None, max_length=2000)
    cuisine_type: Optional[str] = Field(default=None, max_length=50)
    price_tier: Optional[str] = None
    core_value_proposition: Optional[str] = Field(default=None, max_length=200)
    target_segments: Optional[list[dict[str, Any]]] = None
    key_scenarios: Optional[list[dict[str, Any]]] = None
    brand_voice: Optional[dict[str, Any]] = None
    color_palette: Optional[dict[str, Any]] = None
    is_active: Optional[bool] = None

    @field_validator("price_tier")
    @classmethod
    def validate_price_tier(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        allowed = {"budget", "mid", "upscale", "luxury"}
        if v not in allowed:
            raise ValueError(f"price_tier 必须是 {allowed} 之一，收到: {v!r}")
        return v

    @field_validator("target_segments")
    @classmethod
    def validate_target_segments_description(
        cls, v: Optional[list[dict[str, Any]]]
    ) -> Optional[list[dict[str, Any]]]:
        """F#5 audit P1：每条 segment 的 description 字段 ≤500 字符"""
        if v is None:
            return v
        for item in v:
            desc = item.get("description")
            if isinstance(desc, str) and len(desc) > _TARGET_SEGMENT_DESC_MAX:
                raise ValueError(
                    f"target_segments[].description 长度 {len(desc)} 超出上限 {_TARGET_SEGMENT_DESC_MAX}"
                )
        return v


class BrandProfileResponse(BaseModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    brand_name: str
    brand_slogan: Optional[str]
    brand_story: Optional[str]
    cuisine_type: Optional[str]
    price_tier: str
    core_value_proposition: Optional[str]
    target_segments: list[dict[str, Any]]
    key_scenarios: list[dict[str, Any]]
    brand_voice: dict[str, Any]
    color_palette: dict[str, Any]
    is_active: bool
    version: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# BrandSeasonalCalendar — 营销日历
# ---------------------------------------------------------------------------


class BrandSeasonalCalendarCreate(BaseModel):
    brand_profile_id: uuid.UUID = Field(..., description="关联的品牌档案 ID")
    period_type: str = Field(..., description="节点类型：节气/节日/自定义")
    period_name: str = Field(..., max_length=100, description="节点名称，如「春节」")
    start_date: date = Field(..., description="开始日期")
    end_date: date = Field(..., description="结束日期")
    # F#5 audit row 67 length cap
    campaign_theme: Optional[str] = Field(
        default=None, max_length=_CAMPAIGN_THEME_MAX, description="营销主题"
    )
    recommended_dishes: list[dict[str, Any]] = Field(
        default_factory=list, description="推荐菜品：[{dish_name, reason, discount_pct}]"
    )
    # F#5 audit row 67 length cap
    marketing_focus: Optional[str] = Field(
        default=None, max_length=_MARKETING_FOCUS_MAX, description="主推内容方向"
    )
    target_segments: list[dict[str, Any]] = Field(
        default_factory=list, description="本次活动目标人群：[{segment_name, priority}]"
    )

    @field_validator("period_type")
    @classmethod
    def validate_period_type(cls, v: str) -> str:
        allowed = {"节气", "节日", "自定义"}
        if v not in allowed:
            raise ValueError(f"period_type 必须是 {allowed} 之一，收到: {v!r}")
        return v

    @field_validator("end_date")
    @classmethod
    def validate_date_order(cls, v: date, info: Any) -> date:
        start = info.data.get("start_date")
        if start and v < start:
            raise ValueError("end_date 不能早于 start_date")
        return v


class BrandSeasonalCalendarUpdate(BaseModel):
    period_type: Optional[str] = None
    period_name: Optional[str] = Field(default=None, max_length=100)
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    # F#5 audit row 67 length cap
    campaign_theme: Optional[str] = Field(default=None, max_length=_CAMPAIGN_THEME_MAX)
    recommended_dishes: Optional[list[dict[str, Any]]] = None
    # F#5 audit row 67 length cap
    marketing_focus: Optional[str] = Field(default=None, max_length=_MARKETING_FOCUS_MAX)
    target_segments: Optional[list[dict[str, Any]]] = None


class BrandSeasonalCalendarResponse(BaseModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    brand_profile_id: uuid.UUID
    period_type: str
    period_name: str
    start_date: date
    end_date: date
    campaign_theme: Optional[str]
    recommended_dishes: list[dict[str, Any]]
    marketing_focus: Optional[str]
    target_segments: list[dict[str, Any]]
    created_at: datetime

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# BrandContentConstraints — 内容约束规则
# ---------------------------------------------------------------------------


class BrandContentConstraintsCreate(BaseModel):
    brand_profile_id: uuid.UUID = Field(..., description="关联的品牌档案 ID")
    constraint_type: str = Field(..., description="约束类型：tone/format/channel")
    channel: str = Field(..., description="渠道：wechat/miniapp/sms/poster/wecom/douyin/xiaohongshu/all")
    max_length: Optional[int] = Field(default=None, gt=0, description="最大字符数")
    required_elements: list[Any] = Field(default_factory=list, description="必须包含的元素列表")
    forbidden_elements: list[Any] = Field(default_factory=list, description="禁止出现的内容列表")
    template_hints: dict[str, Any] = Field(
        default_factory=dict, description="内容模板提示：{opening_line, closing_line, cta_style, tone_examples[]}"
    )

    @field_validator("constraint_type")
    @classmethod
    def validate_constraint_type(cls, v: str) -> str:
        allowed = {"tone", "format", "channel"}
        if v not in allowed:
            raise ValueError(f"constraint_type 必须是 {allowed} 之一，收到: {v!r}")
        return v

    @field_validator("channel")
    @classmethod
    def validate_channel(cls, v: str) -> str:
        allowed = {"wechat", "miniapp", "sms", "poster", "wecom", "douyin", "xiaohongshu", "all"}
        if v not in allowed:
            raise ValueError(f"channel 必须是 {allowed} 之一，收到: {v!r}")
        return v

    @field_validator("template_hints")
    @classmethod
    def validate_template_hints_flat_length(cls, v: dict[str, Any]) -> dict[str, Any]:
        """F#5 audit P1：template_hints flatten 后总长度 ≤2000 字符"""
        if _flat_str_len(v) > _TEMPLATE_HINTS_FLAT_MAX:
            raise ValueError(
                f"template_hints flat 总长度超出上限 {_TEMPLATE_HINTS_FLAT_MAX}"
            )
        return v


class BrandContentConstraintsUpdate(BaseModel):
    constraint_type: Optional[str] = None
    channel: Optional[str] = None
    max_length: Optional[int] = Field(default=None, gt=0)
    required_elements: Optional[list[Any]] = None
    forbidden_elements: Optional[list[Any]] = None
    template_hints: Optional[dict[str, Any]] = None

    @field_validator("template_hints")
    @classmethod
    def validate_template_hints_flat_length(
        cls, v: Optional[dict[str, Any]]
    ) -> Optional[dict[str, Any]]:
        """F#5 audit P1：template_hints flatten 后总长度 ≤2000 字符"""
        if v is None:
            return v
        if _flat_str_len(v) > _TEMPLATE_HINTS_FLAT_MAX:
            raise ValueError(
                f"template_hints flat 总长度超出上限 {_TEMPLATE_HINTS_FLAT_MAX}"
            )
        return v


class BrandContentConstraintsResponse(BaseModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    brand_profile_id: uuid.UUID
    constraint_type: str
    channel: str
    max_length: Optional[int]
    required_elements: list[Any]
    forbidden_elements: list[Any]
    template_hints: dict[str, Any]
    created_at: datetime

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# ContentBrief — build_content_brief 的返回结构
# ---------------------------------------------------------------------------


class ContentBrief(BaseModel):
    """完整的内容生成简报，供 content_generation agent 直接消费"""

    tenant_id: uuid.UUID
    channel: str
    target_segment: str
    purpose: str

    # 品牌基础信息
    brand_name: str
    brand_slogan: Optional[str]
    cuisine_type: Optional[str]
    price_tier: str
    core_value_proposition: Optional[str]

    # 品牌语气约束
    tone: str
    style: str
    forbidden_words: list[str]
    preferred_words: list[str]

    # 渠道格式约束
    max_length: Optional[int]
    required_elements: list[Any]
    forbidden_elements: list[Any]
    template_hints: dict[str, Any]

    # 当前营销时令上下文（如有）
    current_season_context: Optional[dict[str, Any]]

    # 目标客群描述
    segment_description: Optional[str]

    # 系统提示词（可直接注入 LLM system message）
    system_prompt: str

    generated_at: datetime
