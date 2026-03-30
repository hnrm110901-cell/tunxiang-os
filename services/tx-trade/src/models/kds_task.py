"""KDS任务模型 — 持久化到PostgreSQL，替代内存OrderedDict

每条记录代表一道菜的出品任务，生命周期：
  pending → cooking → done / cancelled

催菜SLA字段：
  promised_at   — 厨师确认催菜后承诺完成时间
  rush_count    — 同一任务累计催菜次数（用于30分钟限流）
  last_rush_at  — 最后一次催菜时间（用于限流滑动窗口）
"""
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import String, Integer, Text, Index
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from shared.ontology.src.base import TenantBase


class KDSTask(TenantBase):
    """KDS出品任务

    内存 OrderedDict 降级为 L1 热缓存，此表为 L2 持久化层。
    重启恢复：从 status IN ('pending','cooking') 的记录重建内存索引。
    """
    __tablename__ = "kds_tasks"

    # ── 业务关联 ──
    order_item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True,
        comment="关联订单明细ID"
    )
    dept_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), index=True,
        comment="出品档口ID（关联 production_depts）"
    )

    # ── 任务状态 ──
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending", index=True,
        comment="任务状态: pending/cooking/done/cancelled"
    )
    priority: Mapped[str] = mapped_column(
        String(20), nullable=False, default="normal",
        comment="优先级: normal/rush/vip"
    )

    # ── 时间线 ──
    started_at: Mapped[Optional[datetime]] = mapped_column(
        comment="厨师开始制作时间"
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(
        comment="出品完成时间"
    )
    promised_at: Mapped[Optional[datetime]] = mapped_column(
        comment="催菜时厨师承诺完成时间（催菜SLA核心字段）"
    )

    # ── 催菜SLA ──
    rush_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0,
        comment="催菜累计次数（30分钟滑动窗口限流依据）"
    )
    last_rush_at: Mapped[Optional[datetime]] = mapped_column(
        comment="最近一次催菜时间（限流滑动窗口起点）"
    )

    # ── 重做记录 ──
    remake_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0,
        comment="重做次数"
    )
    remake_reason: Mapped[Optional[str]] = mapped_column(
        Text, comment="最近一次重做原因"
    )

    # ── 操作员 ──
    operator_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        comment="操作员ID（最后操作的厨师）"
    )

    # ── 复合索引：高频查询优化 ──
    __table_args__ = (
        Index(
            "ix_kds_tasks_tenant_dept_status",
            "tenant_id", "dept_id", "status",
            comment="档口任务队列查询"
        ),
        Index(
            "ix_kds_tasks_tenant_status_created",
            "tenant_id", "status", "created_at",
            comment="重启恢复查询：按状态+时间过滤活跃任务"
        ),
        Index(
            "ix_kds_tasks_promised_at",
            "promised_at",
            postgresql_where="promised_at IS NOT NULL AND status NOT IN ('done', 'cancelled')",
            comment="催菜SLA超时检查（局部索引）"
        ),
    )
