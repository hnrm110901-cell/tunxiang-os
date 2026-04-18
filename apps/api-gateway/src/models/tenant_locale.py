"""
租户级语言/时区/货币配置
"""

import uuid

from sqlalchemy import Column, String
from sqlalchemy.dialects.postgresql import UUID

from .base import Base, TimestampMixin


class TenantLocaleConfig(Base, TimestampMixin):
    """租户级别的默认 locale/时区/货币/日期格式"""

    __tablename__ = "tenant_locale_configs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(String(64), nullable=False, unique=True, index=True)
    default_locale = Column(String(10), default="zh-CN", nullable=False)  # zh-CN / zh-TW / en-US / ...
    default_timezone = Column(String(50), default="Asia/Shanghai", nullable=False)  # Asia/Shanghai / Asia/Hong_Kong / Asia/Singapore
    currency = Column(String(10), default="CNY", nullable=False)  # CNY / HKD / SGD / USD
    date_format = Column(String(30), default="YYYY-MM-DD", nullable=False)  # YYYY-MM-DD / DD/MM/YYYY
    country_code = Column(String(5), default="CN", nullable=False)  # CN / HK / SG / VN
