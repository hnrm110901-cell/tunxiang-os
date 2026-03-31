"""KDS任务模型 — 持久化到PostgreSQL，替代内存OrderedDict

每条记录代表一道菜的出品任务，生命周期：
  pending → cooking → done / cancelled

催菜SLA字段：
  promised_at   — 厨师确认催菜后承诺完成时间
  rush_count    — 同一任务累计催菜次数（用于30分钟限流）
  last_rush_at  — 最后一次催菜时间（用于限流滑动窗口）

v076 新增冗余字段（方便KDS展示，避免联表查询）：
  order_id      — 订单ID（便于按订单聚合任务进度）
  dish_id       — 菜品ID
  dish_name     — 菜品名称
  quantity      — 菜品数量
  table_number  — 桌号
  order_no      — 订单号
  notes         — 菜品备注
"""
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import String, Integer, Text, Index, Boolean
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
    order_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), index=True,
        comment="关联订单ID（冗余存储，方便按订单聚合查询所有档口任务）"
    )
    dept_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), index=True,
        comment="出品档口ID（关联 production_depts）"
    )

    # ── 菜品信息（冗余存储，KDS展示用，避免联表查询） ──
    dish_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        comment="菜品ID（冗余存储，便于按菜品统计出品数据）"
    )
    dish_name: Mapped[Optional[str]] = mapped_column(
        String(100),
        comment="菜品名称（冗余存储，KDS展示用）"
    )
    quantity: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="1",
        comment="菜品数量"
    )
    table_number: Mapped[Optional[str]] = mapped_column(
        String(20),
        comment="桌号（冗余存储，KDS展示用）"
    )
    order_no: Mapped[Optional[str]] = mapped_column(
        String(50),
        comment="订单号（冗余存储，KDS展示用）"
    )
    notes: Mapped[Optional[str]] = mapped_column(
        Text,
        comment="菜品备注（如不要辣、少盐等）"
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

    # ── 等叫（calling）状态字段 ──
    called_at: Mapped[Optional[datetime]] = mapped_column(
        comment="厨师标记等叫的时间"
    )
    served_at: Mapped[Optional[datetime]] = mapped_column(
        comment="服务员确认上桌的时间"
    )
    call_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0,
        comment="等叫累计次数"
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
        ),
        Index(
            "ix_kds_tasks_tenant_status_created",
            "tenant_id", "status", "created_at",
        ),
        Index(
            "ix_kds_tasks_promised_at",
            "promised_at",
            postgresql_where="promised_at IS NOT NULL AND status NOT IN ('done', 'cancelled')",
        ),
        # v076：KDS轮询"某档口待出品任务"的核心查询路径
        Index(
            "ix_kds_tasks_dept_status_created",
            "dept_id", "status", "created_at",
            postgresql_where="is_deleted = false",
        ),
        # v076：按订单聚合任务进度
        Index(
            "ix_kds_tasks_order_id",
            "order_id",
            postgresql_where="order_id IS NOT NULL AND is_deleted = false",
        ),
    )
