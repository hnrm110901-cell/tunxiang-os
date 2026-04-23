"""AgentProcedure — Agent 程序性记忆（触发-动作规则）"""
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, Integer, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from shared.ontology.src.base import TenantBase


class AgentProcedure(TenantBase):
    """Agent 程序性记忆 — 经验证有效的触发-动作规则"""

    __tablename__ = "agent_procedures"

    store_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, comment="门店范围（NULL=品牌级）",
    )
    procedure_name: Mapped[str] = mapped_column(
        Text, nullable=False, comment="程序名称",
    )
    trigger_pattern: Mapped[str] = mapped_column(
        Text, nullable=False, comment="触发模式标识（用于快速匹配）",
    )
    trigger_config: Mapped[dict] = mapped_column(
        JSONB, nullable=False, comment="触发条件详细配置",
    )
    action_template: Mapped[dict] = mapped_column(
        JSONB, nullable=False, comment="动作模板（含参数占位符）",
    )
    success_rate: Mapped[float] = mapped_column(
        Float, default=0.0, server_default="0.0", comment="历史成功率 0-1",
    )
    execution_count: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", comment="累计执行次数",
    )
    last_executed: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="最后执行时间",
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="true", comment="是否启用",
    )
