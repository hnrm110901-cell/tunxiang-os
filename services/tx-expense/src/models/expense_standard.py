"""
差标规则模型
ExpenseStandard：差旅费标准规则（职级×城市级别×费用类型三维匹配）。
StandardCityTier：城市级别映射表（城市名→tier1/tier2/tier3）。

差标匹配逻辑：
  申请人职级 × 目的地城市级别 × 费用类型 → 查找匹配规则 → 返回 daily_limit/single_limit
"""
from __future__ import annotations

import uuid
from datetime import date
from typing import Optional

from sqlalchemy import Boolean, Date, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from shared.ontology.src.base import TenantBase
from .expense_enums import CityTier, StaffLevel, TravelExpenseType


# ─────────────────────────────────────────────────────────────────────────────
# StandardCityTier — 城市级别映射表
# ─────────────────────────────────────────────────────────────────────────────

class StandardCityTier(TenantBase):
    """
    城市级别映射表
    将城市名称映射到 tier1/tier2/tier3，供差标规则匹配时查询。
    is_system=True 表示系统预置数据（如北上广深为 tier1），租户可追加自定义城市。
    """
    __tablename__ = "standard_city_tiers"

    city_name: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        index=True,
        comment="城市名称，如「北京」「成都」"
    )
    city_code: Mapped[Optional[str]] = mapped_column(
        String(20),
        nullable=True,
        comment="城市行政区划代码（可选，如 110000）"
    )
    province: Mapped[Optional[str]] = mapped_column(
        String(50),
        nullable=True,
        comment="所属省份/直辖市名称"
    )
    tier: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        index=True,
        comment="城市级别，参见 CityTier 枚举（tier1/tier2/tier3/other）"
    )
    is_system: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        comment="是否系统预置数据（系统预置不允许租户删除）"
    )


# ─────────────────────────────────────────────────────────────────────────────
# ExpenseStandard — 差旅费标准规则
# ─────────────────────────────────────────────────────────────────────────────

class ExpenseStandard(TenantBase):
    """
    差旅费标准规则（三维匹配：职级 × 城市级别 × 费用类型）
    daily_limit/single_limit 单位均为分(fen)，展示时除以100转元。
    同一 brand_id 下，同一 (staff_level, city_tier, expense_type) 组合在有效期内应唯一。
    """
    __tablename__ = "expense_standards"

    brand_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        index=True,
        comment="所属品牌ID（差标按品牌配置，不跨品牌共用）"
    )
    name: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        comment="规则名称，如「店长-一线城市-住宿标准」"
    )
    staff_level: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        index=True,
        comment="适用员工职级，参见 StaffLevel 枚举"
    )
    city_tier: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        index=True,
        comment="适用城市级别，参见 CityTier 枚举"
    )
    expense_type: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        index=True,
        comment="差旅费用类型，参见 TravelExpenseType 枚举"
    )
    daily_limit: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        comment="每日限额，单位：分(fen)，展示时除以100转元"
    )
    single_limit: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True,
        comment="单笔限额，单位：分(fen)，None 表示不限单笔金额"
    )
    notes: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        comment="备注说明（如适用范围、特殊条件等）"
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        comment="是否启用（停用后不参与差标匹配）"
    )
    effective_from: Mapped[date] = mapped_column(
        Date,
        nullable=False,
        comment="生效日期（含）"
    )
    effective_to: Mapped[Optional[date]] = mapped_column(
        Date,
        nullable=True,
        comment="失效日期（含），None 表示长期有效"
    )
