"""Application ORM — 内部研发平台 5 类资源统一目录表。"""

from __future__ import annotations

from typing import Any

from sqlalchemy import CheckConstraint, Index, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TenantMixin

# 5 类资源类型枚举（与迁移文件 v230 的 CHECK 约束保持一致）
RESOURCE_TYPE_BACKEND_SERVICE = "backend_service"
RESOURCE_TYPE_FRONTEND_APP = "frontend_app"
RESOURCE_TYPE_EDGE_IMAGE = "edge_image"
RESOURCE_TYPE_ADAPTER = "adapter"
RESOURCE_TYPE_DATA_ASSET = "data_asset"

VALID_RESOURCE_TYPES: tuple[str, ...] = (
    RESOURCE_TYPE_BACKEND_SERVICE,
    RESOURCE_TYPE_FRONTEND_APP,
    RESOURCE_TYPE_EDGE_IMAGE,
    RESOURCE_TYPE_ADAPTER,
    RESOURCE_TYPE_DATA_ASSET,
)


class Application(Base, TenantMixin):
    """DevForge 应用目录条目（CMDB 根实体）。

    每个 ``code`` 在租户内唯一，例如：``tx-trade``、``web-pos``、``mac-station``。
    """

    __tablename__ = "devforge_applications"

    code: Mapped[str] = mapped_column(String(100), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(40), nullable=False)
    owner: Mapped[str | None] = mapped_column(String(200), nullable=True)
    repo_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    tech_stack: Mapped[str | None] = mapped_column(String(50), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "code", name="uq_devforge_applications_tenant_code"),
        CheckConstraint(
            "resource_type IN ('backend_service','frontend_app','edge_image',"
            "'adapter','data_asset')",
            name="ck_devforge_applications_resource_type",
        ),
        Index(
            "ix_devforge_applications_tenant_resource_type",
            "tenant_id",
            "resource_type",
        ),
    )
