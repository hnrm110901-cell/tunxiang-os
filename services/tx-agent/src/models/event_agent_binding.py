"""事件→Agent 映射绑定 — 可配置化事件驱动路由

将原先硬编码在 event_bus.py 中的 DEFAULT_EVENT_HANDLERS 映射持久化到 DB，
使新增/修改映射规则无需改代码重新部署。
"""
import uuid

from sqlalchemy import Boolean, Index, Integer, String
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column

from shared.ontology.src.base import TenantBase


class EventAgentBinding(TenantBase):
    """事件→Agent 映射绑定表"""

    __tablename__ = "event_agent_bindings"
    __table_args__ = (
        Index("ix_eab_event_type", "event_type"),
        Index("ix_eab_agent_id", "agent_id"),
    )

    event_type: Mapped[str] = mapped_column(
        String(100), nullable=False, comment="事件类型（如 trade.order.paid）"
    )
    agent_id: Mapped[str] = mapped_column(
        String(100), nullable=False, comment="目标 Agent ID（如 discount_guard）"
    )
    action: Mapped[str] = mapped_column(
        String(100), nullable=False, comment="要调用的 action（如 log_violation）"
    )
    priority: Mapped[int] = mapped_column(
        Integer, default=50, server_default="50", comment="执行优先级（越高越先执行）"
    )
    enabled: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="true", comment="是否启用"
    )
    condition_json: Mapped[dict | None] = mapped_column(
        JSON, nullable=True, comment="条件表达式（可选，如 {min_amount_fen: 10000}）"
    )
    description: Mapped[str | None] = mapped_column(
        String(500), nullable=True, comment="中文描述"
    )
    source: Mapped[str] = mapped_column(
        String(20), default="config", server_default="'config'",
        comment="来源：default（系统默认）/ config（手动配置）",
    )
