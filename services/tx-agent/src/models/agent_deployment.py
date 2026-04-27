"""Agent 部署 — 灰度发布与多级作用域管理（品牌/区域/门店）"""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, func
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column

from shared.ontology.src.base import TenantBase


class AgentDeployment(TenantBase):
    """Agent 部署 — 将特定版本部署到品牌/区域/门店，支持灰度发布"""

    __tablename__ = "agent_deployments"
    __table_args__ = (Index("ix_agent_deployment_scope", "scope_type", "scope_id"),)

    # 关联模板和版本
    template_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agent_templates.id"),
        nullable=False,
        index=True,
        comment="Agent模板ID",
    )
    version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agent_versions.id"),
        nullable=False,
        comment="部署的版本ID",
    )

    # 作用域
    scope_type: Mapped[str] = mapped_column(String(20), nullable=False, comment="作用域类型: brand/region/store")
    scope_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, comment="品牌/区域/门店 ID")

    # 部署控制
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true", comment="是否启用")
    rollout_percent: Mapped[int] = mapped_column(
        Integer, default=100, server_default="100", comment="灰度发布比例 0-100"
    )
    allowed_actions: Mapped[list | None] = mapped_column(
        JSON, nullable=True, comment="该部署范围内允许的 action 白名单"
    )
    config_overrides: Mapped[dict | None] = mapped_column(
        JSON, nullable=True, comment="部署级配置覆盖（覆盖 template 的 config_json）"
    )

    # 部署信息
    deployed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), comment="部署时间"
    )
    deployed_by: Mapped[str | None] = mapped_column(String(100), nullable=True, comment="部署者")
