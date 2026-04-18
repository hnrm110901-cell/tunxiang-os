"""
法人主体模型 — 多主体管理（Task 1）

屯象OS 连锁场景下，同一品牌门店可能分属于不同法人：
  - 直营门店 → 品牌总部法人
  - 加盟门店 → 加盟商法人
  - 合资门店 → 合资公司法人
签约、发薪、开票必须对齐门店当前生效法人主体。
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import Boolean, Column, Date, DateTime
from sqlalchemy import Enum as SAEnum
from sqlalchemy import Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID

from .base import Base, TimestampMixin


class LegalEntityType(str, enum.Enum):
    """法人主体类型"""

    DIRECT_OPERATED = "direct_operated"  # 直营
    FRANCHISE = "franchise"  # 加盟
    JOINT_VENTURE = "joint_venture"  # 合资
    SUBSIDIARY = "subsidiary"  # 子公司


class LegalEntityStatus(str, enum.Enum):
    ACTIVE = "active"
    SUSPENDED = "suspended"  # 暂停营业
    DISSOLVED = "dissolved"  # 已注销


class LegalEntity(Base, TimestampMixin):
    """法人主体（工商实体）"""

    __tablename__ = "legal_entities"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    brand_id = Column(String(50), nullable=True, index=True)  # 所属品牌（多租户）

    code = Column(String(50), nullable=False, unique=True, index=True)  # 主体编码
    name = Column(String(200), nullable=False)  # 公司全称
    entity_type = Column(
        SAEnum(LegalEntityType, name="legal_entity_type_enum"),
        nullable=False,
        default=LegalEntityType.DIRECT_OPERATED,
    )

    # 工商信息
    unified_social_credit = Column(String(50), nullable=True, unique=True)  # 统一社会信用代码
    legal_representative = Column(String(100), nullable=True)  # 法定代表人
    registered_address = Column(String(500), nullable=True)
    registered_capital_fen = Column(Integer, nullable=True)  # 注册资本（分）
    establish_date = Column(Date, nullable=True)

    status = Column(
        SAEnum(LegalEntityStatus, name="legal_entity_status_enum"),
        nullable=False,
        default=LegalEntityStatus.ACTIVE,
        index=True,
    )

    # 税务/银行（签约结算用）
    tax_number = Column(String(50), nullable=True)
    bank_name = Column(String(100), nullable=True)
    bank_account = Column(String(50), nullable=True)

    contact_phone = Column(String(50), nullable=True)
    remark = Column(Text, nullable=True)

    def __repr__(self) -> str:
        return f"<LegalEntity(code='{self.code}', type='{self.entity_type}')>"


class StoreLegalEntity(Base, TimestampMixin):
    """门店-法人关联（支持历史变更：转加盟 / 转直营）"""

    __tablename__ = "store_legal_entities"
    __table_args__ = (
        UniqueConstraint("store_id", "legal_entity_id", "start_date", name="uq_store_legal_entity_period"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    store_id = Column(String(50), nullable=False, index=True)
    legal_entity_id = Column(UUID(as_uuid=True), nullable=False, index=True)

    start_date = Column(Date, nullable=False)  # 生效起日
    end_date = Column(Date, nullable=True)  # NULL 表示仍然有效
    is_primary = Column(Boolean, default=True)  # 主签约主体

    remark = Column(Text, nullable=True)

    def __repr__(self) -> str:
        return f"<StoreLegalEntity(store='{self.store_id}', entity='{self.legal_entity_id}')>"
