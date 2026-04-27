"""tx-devforge 模型基类 — DeclarativeBase + 公共字段 mixin。

所有 devforge 表必须继承 ``TenantMixin``：保证 RLS 隔离 + 软删 + 审计时间戳。
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """tx-devforge 内部 ORM 根基类。

    刻意不复用 ``shared.ontology.src.base.TenantBase``：DevForge 是内部研发平台，
    实体语义与餐饮业务 Ontology 解耦，避免污染核心 metadata 注册表。
    """


class TenantMixin:
    """所有 devforge 表必须包含的公共字段。"""

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
    is_deleted: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )
