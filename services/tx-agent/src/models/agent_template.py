"""Agent 模板 — Agent Registry 的核心实体，定义 Agent 的元信息和配置"""
import uuid

from sqlalchemy import String, Text, Integer, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column

from shared.ontology.src.base import TenantBase


class AgentTemplate(TenantBase):
    """Agent 模板 — 每个 Agent 类型的元信息（名称/分类/优先级/运行位置/配置等）"""

    __tablename__ = "agent_templates"
    __table_args__ = (
        UniqueConstraint("tenant_id", "name", name="uq_agent_template_tenant_name"),
    )

    # 基础信息
    name: Mapped[str] = mapped_column(
        String(100), nullable=False, index=True, comment="Agent模板名（如 discount_guard）"
    )
    display_name: Mapped[str | None] = mapped_column(
        String(200), comment="中文显示名（如 折扣守护）"
    )
    description: Mapped[str | None] = mapped_column(
        Text, comment="模板描述"
    )
    category: Mapped[str | None] = mapped_column(
        String(50), comment="分类: trade/supply/member/growth/ops/finance/intel/org"
    )

    # 运行配置
    priority: Mapped[str] = mapped_column(
        String(10), default="P2", server_default="P2", comment="优先级 P0/P1/P2"
    )
    run_location: Mapped[str] = mapped_column(
        String(20), default="cloud", server_default="cloud",
        comment="运行位置 edge/cloud/edge+cloud",
    )
    agent_level: Mapped[int] = mapped_column(
        Integer, default=1, server_default="1",
        comment="自治等级 1=suggest 2=auto+rollback 3=autonomous",
    )

    # Agent 自定义配置
    config_json: Mapped[dict | None] = mapped_column(
        JSON, nullable=True, comment="Agent自定义配置"
    )
    model_preference: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="模型偏好（如 claude-haiku）"
    )
    tool_whitelist: Mapped[list | None] = mapped_column(
        JSON, nullable=True, comment="允许调用的工具列表"
    )

    # 状态与审计
    status: Mapped[str] = mapped_column(
        String(20), default="draft", server_default="draft",
        comment="draft/active/deprecated/archived",
    )
    created_by: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="创建者"
    )
