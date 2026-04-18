"""
应用市场 / AI 增值工厂 模型

包含 5 张表：
  - applications          应用/数智员工/行业方案 主表（金额字段存分）
  - app_pricing_tiers     每个应用的定价档（basic/pro/enterprise）
  - app_installations     租户安装记录（含 trial_ends_at）
  - app_reviews           租户评价
  - app_billing_records   月度计费流水

所有价格使用 BigInteger 存分；金额展示字段以 `_yuan` 形式由 @property 暴露。
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import BigInteger, Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship

from .base import Base, TimestampMixin


# ═══════════════════════════════════════════════════════════════
# applications — 应用主表
# ═══════════════════════════════════════════════════════════════
class Application(Base, TimestampMixin):
    """应用市场上架的商品（自有应用 / 第三方应用 / AI 数智员工 / 行业方案）"""

    __tablename__ = "applications"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    code = Column(String(64), nullable=False, unique=True, index=True)  # 应用唯一编码
    name = Column(String(120), nullable=False)
    # self_built | third_party | ai_agent | industry_solution
    category = Column(String(32), nullable=False, index=True)
    description = Column(Text, nullable=True)
    icon_url = Column(String(500), nullable=True)
    # tunxiang | partner_xxx
    provider = Column(String(64), nullable=False, default="tunxiang")
    # free | monthly | usage_based | one_time
    price_model = Column(String(32), nullable=False, default="monthly")
    price_fen = Column(BigInteger, nullable=False, default=0)  # 标价（分）
    currency = Column(String(8), nullable=False, default="CNY")
    version = Column(String(32), nullable=False, default="1.0.0")
    # draft | published | deprecated
    status = Column(String(16), nullable=False, default="draft", index=True)
    trial_days = Column(Integer, nullable=False, default=0)
    feature_flags_json = Column(JSONB, nullable=True)        # 功能开关/能力声明
    supported_roles_json = Column(JSONB, nullable=True)      # 支持角色清单

    tiers = relationship(
        "AppPricingTier", back_populates="application",
        cascade="all, delete-orphan",
    )

    @property
    def price_yuan(self) -> float:
        return round((self.price_fen or 0) / 100, 2)


# ═══════════════════════════════════════════════════════════════
# app_pricing_tiers — 定价档
# ═══════════════════════════════════════════════════════════════
class AppPricingTier(Base, TimestampMixin):
    """应用的定价档位（basic/pro/enterprise）"""

    __tablename__ = "app_pricing_tiers"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    app_id = Column(
        UUID(as_uuid=True),
        ForeignKey("applications.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    tier_name = Column(String(32), nullable=False)  # basic | pro | enterprise
    monthly_fee_fen = Column(BigInteger, nullable=False, default=0)
    usage_limits_json = Column(JSONB, nullable=True)   # {api_calls:10000, storage_gb:50}
    features_json = Column(JSONB, nullable=True)      # 该档包含功能清单

    application = relationship("Application", back_populates="tiers")

    @property
    def monthly_fee_yuan(self) -> float:
        return round((self.monthly_fee_fen or 0) / 100, 2)


# ═══════════════════════════════════════════════════════════════
# app_installations — 租户安装记录
# ═══════════════════════════════════════════════════════════════
class AppInstallation(Base, TimestampMixin):
    """租户安装应用记录"""

    __tablename__ = "app_installations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(String(64), nullable=False, index=True)
    app_id = Column(
        UUID(as_uuid=True),
        ForeignKey("applications.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    tier_name = Column(String(32), nullable=True)      # 当前档位
    installed_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    # active | paused | uninstalled
    status = Column(String(16), nullable=False, default="active", index=True)
    trial_ends_at = Column(DateTime, nullable=True)
    config_json = Column(JSONB, nullable=True)
    installed_by = Column(String(64), nullable=True)


# ═══════════════════════════════════════════════════════════════
# app_reviews — 评价
# ═══════════════════════════════════════════════════════════════
class AppReview(Base, TimestampMixin):
    """租户对应用的评价（1-5 星 + 文本）"""

    __tablename__ = "app_reviews"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    app_id = Column(
        UUID(as_uuid=True),
        ForeignKey("applications.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    tenant_id = Column(String(64), nullable=False, index=True)
    rating = Column(Integer, nullable=False)  # 1-5
    review_text = Column(Text, nullable=True)
    reviewed_by = Column(String(64), nullable=True)
    helpful_count = Column(Integer, nullable=False, default=0)
    status = Column(String(16), nullable=False, default="visible")  # visible | hidden


# ═══════════════════════════════════════════════════════════════
# app_billing_records — 月度计费流水
# ═══════════════════════════════════════════════════════════════
class AppBillingRecord(Base, TimestampMixin):
    """按安装 × 账期（YYYY-MM）产生的计费记录"""

    __tablename__ = "app_billing_records"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    installation_id = Column(
        UUID(as_uuid=True),
        ForeignKey("app_installations.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    billing_period = Column(String(7), nullable=False, index=True)  # YYYY-MM
    amount_fen = Column(BigInteger, nullable=False, default=0)
    usage_data_json = Column(JSONB, nullable=True)
    paid_at = Column(DateTime, nullable=True)
    invoice_id = Column(String(64), nullable=True)

    @property
    def amount_yuan(self) -> float:
        return round((self.amount_fen or 0) / 100, 2)
