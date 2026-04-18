"""
多国合规规则模型 — 内地 / 香港 / 新加坡 / 越南...
"""

import uuid

from sqlalchemy import JSON, Column, Date, String
from sqlalchemy.dialects.postgresql import UUID

from .base import Base, TimestampMixin


class CountryPayrollRule(Base, TimestampMixin):
    """各国薪酬/社保/税规则 — 以 config_json 承载差异参数"""

    __tablename__ = "country_payroll_rules"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    country_code = Column(String(5), nullable=False, index=True)  # CN / HK / SG / VN
    rule_type = Column(String(40), nullable=False, index=True)  # social_insurance / tax / minimum_wage / overtime
    config_json = Column(JSON, nullable=False, default=dict)
    effective_from = Column(Date, nullable=False)
    effective_to = Column(Date, nullable=True)
