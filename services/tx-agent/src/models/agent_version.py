"""Agent 版本 — 模板的版本化管理，支持语义化版本号和快照"""
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column

from shared.ontology.src.base import TenantBase


class AgentVersion(TenantBase):
    """Agent 版本 — 每个模板可发布多个版本，支持 SKILL.yaml/prompt 快照"""

    __tablename__ = "agent_versions"
    __table_args__ = (
        UniqueConstraint("template_id", "version_tag", name="uq_agent_version_template_tag"),
    )

    # 关联模板
    template_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agent_templates.id"),
        nullable=False,
        index=True,
        comment="所属模板ID",
    )

    # 版本信息
    version_tag: Mapped[str] = mapped_column(
        String(50), nullable=False, comment="语义化版本号（如 1.0.0, 1.1.0-beta）"
    )
    skill_yaml_snapshot: Mapped[dict | None] = mapped_column(
        JSON, nullable=True, comment="发布时的 SKILL.yaml 快照"
    )
    prompt_snapshot: Mapped[dict | None] = mapped_column(
        JSON, nullable=True, comment="发布时的 prompt 配置快照"
    )
    changelog: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="版本变更说明"
    )

    # 状态
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", comment="是否为当前激活版本"
    )

    # 发布信息
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="发布时间"
    )
    published_by: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="发布者"
    )
