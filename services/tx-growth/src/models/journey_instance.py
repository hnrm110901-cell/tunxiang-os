"""旅程实例数据模型

表 journey_instances 持久化存储每个会员的旅程执行状态。
替代原 journey_executor.py 中的内存 dict _journey_instances。

状态机：
  running → completed   （所有节点执行完毕）
  running → failed      （超过最大重试次数）
  running → paused      （旅程被管理员暂停）
  paused  → running     （旅程恢复发布后，下次 tick 重新推进）

金额单位：分(fen)
"""
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from shared.ontology.src.base import TenantBase


class JourneyInstance(TenantBase):
    """旅程实例表 — 追踪每个会员在某旅程中的执行进度

    唯一约束：同一会员在同一旅程中只允许存在一个 status='running' 实例
    （部分唯一索引在迁移中用 PostgreSQL WHERE 条件实现）。
    """

    __tablename__ = "journey_instances"

    # ------------------------------------------------------------------
    # 关联字段
    # ------------------------------------------------------------------

    journey_id: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        index=True,
        comment="旅程ID（来自 journey_orchestrator 内存 key，8位UUID前缀）",
    )
    customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        index=True,
        comment="目标会员 UUID",
    )

    # ------------------------------------------------------------------
    # 执行状态
    # ------------------------------------------------------------------

    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="running",
        comment="running | completed | failed | paused",
    )
    current_node_id: Mapped[Optional[str]] = mapped_column(
        String(64),
        nullable=True,
        comment="当前待执行节点 ID；NULL 表示旅程已无下一节点（即将完成）",
    )
    next_execute_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        comment="下次允许执行的最早时间（wait 节点会推迟此时间）",
    )

    # ------------------------------------------------------------------
    # 执行统计
    # ------------------------------------------------------------------

    retry_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        comment="当前节点重试次数，超过 _MAX_RETRY 后转为 failed",
    )
    last_error: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        comment="最近一次错误描述（HTTP 状态码或异常消息）",
    )
    completed_nodes: Mapped[list] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        comment="已成功执行的节点 ID 列表（JSONB array of str）",
    )

    # ------------------------------------------------------------------
    # 实例生命周期时间戳（created_at / updated_at 继承自 TenantBase）
    # ------------------------------------------------------------------

    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        comment="旅程实例创建/启动时间",
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="旅程完成或失败时间",
    )

    # ------------------------------------------------------------------
    # 索引 & 唯一约束
    # ------------------------------------------------------------------

    __table_args__ = (
        # 执行器轮询：查询 running + 到期的实例
        Index(
            "idx_journey_instances_poll",
            "status",
            "next_execute_at",
            "tenant_id",
        ),
        # 防重复触发：按 journey_id + customer_id + tenant_id 快速查重
        Index(
            "idx_journey_instances_dedup",
            "journey_id",
            "customer_id",
            "tenant_id",
        ),
        # 注意：同一会员在同一旅程只能有一个 running 实例的部分唯一索引
        # (uq_journey_instance_running WHERE status='running') 通过
        # Alembic 迁移 v026 用 op.execute 创建，ORM 层不定义以避免
        # SQLAlchemy 生成不带 WHERE 条件的全量唯一约束。
        {"comment": "旅程实例表 — 每行代表一个会员在一条旅程中的执行进度"},
    )
