"""用户-门店访问范围（D5 跨店权限边界）

用于在店长/区域经理等非全局角色与其可访问门店之间建立多对多关系，
并为每条授权单独定义 access_level（read/write/admin）与 finance_access（财务数据可见）。

典型用法：
  - 老板（boss）无需配置，直接全局可读写；
  - 区域经理（regional_manager）通过本表授权其辖区门店；
  - 店长（store_manager）默认仅可访问其 User.store_id 对应门店；
    若需临时调店支援，可在本表额外授权。
"""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Index, String
from sqlalchemy.dialects.postgresql import UUID

from .base import Base, TimestampMixin


class UserStoreScope(Base, TimestampMixin):
    """用户可访问门店范围"""

    __tablename__ = "user_store_scopes"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    store_id = Column(String(50), nullable=False, index=True)

    # 访问级别：read / write / admin
    access_level = Column(String(20), nullable=False, default="read")
    # 是否允许访问财务敏感资源（凭证/AR-AP/薪酬/储值卡）
    finance_access = Column(Boolean, nullable=False, default=False)

    granted_by = Column(UUID(as_uuid=True), nullable=True)
    granted_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    # 可选过期时间（例如代管 30 天）
    expires_at = Column(DateTime, nullable=True)

    __table_args__ = (
        Index("uq_user_store_scope", "user_id", "store_id", unique=True),
        Index("idx_uss_store", "store_id"),
    )

    def __repr__(self):
        return f"<UserStoreScope(user={self.user_id}, store={self.store_id}, level={self.access_level})>"
