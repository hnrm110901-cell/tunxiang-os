"""日清日结数据模型 — E1-E8 八节点操作流程

E1 开店准备 → E2 营业巡航 → E3 异常处理 → E4 交接班
E5 闭店检查 → E6 日结对账 → E7 复盘归因 → E8 整改跟踪

每个节点有：状态(pending/in_progress/completed/skipped) + 检查项 + 责任人 + 时间戳
"""
import uuid
from datetime import date

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from shared.ontology.src.base import TenantBase


class DailyOpsFlow(TenantBase):
    """日清日结主流程（每店每天一条）"""
    __tablename__ = "daily_ops_flows"

    store_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("stores.id"), nullable=False, index=True)
    ops_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(20), default="not_started", comment="not_started/in_progress/completed")

    # 8 节点状态
    e1_open_store: Mapped[str] = mapped_column(String(20), default="pending")
    e2_cruise: Mapped[str] = mapped_column(String(20), default="pending")
    e3_exception: Mapped[str] = mapped_column(String(20), default="pending")
    e4_handover: Mapped[str] = mapped_column(String(20), default="pending")
    e5_close_check: Mapped[str] = mapped_column(String(20), default="pending")
    e6_settlement: Mapped[str] = mapped_column(String(20), default="pending")
    e7_review: Mapped[str] = mapped_column(String(20), default="pending")
    e8_rectification: Mapped[str] = mapped_column(String(20), default="pending")

    completed_nodes: Mapped[int] = mapped_column(Integer, default=0)
    total_nodes: Mapped[int] = mapped_column(Integer, default=8)
    operator_id: Mapped[str | None] = mapped_column(String(50))

    nodes = relationship("DailyOpsNode", back_populates="flow", cascade="all, delete-orphan")


class DailyOpsNode(TenantBase):
    """日清日结节点明细"""
    __tablename__ = "daily_ops_nodes"

    flow_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("daily_ops_flows.id"), nullable=False, index=True)
    node_code: Mapped[str] = mapped_column(String(10), nullable=False, comment="E1-E8")
    node_name: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="pending", comment="pending/in_progress/completed/skipped/abnormal")

    # 检查项
    check_items: Mapped[dict | None] = mapped_column(JSON, default=list, comment="[{item, required, checked, result}]")
    check_result: Mapped[str | None] = mapped_column(String(20), comment="pass/fail/partial")
    photo_urls: Mapped[list | None] = mapped_column(JSON, default=list)

    # 责任人与时间
    operator_id: Mapped[str | None] = mapped_column(String(50))
    operator_name: Mapped[str | None] = mapped_column(String(50))
    started_at: Mapped[str | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[str | None] = mapped_column(DateTime(timezone=True))
    duration_minutes: Mapped[int | None] = mapped_column(Integer)

    notes: Mapped[str | None] = mapped_column(Text)
    abnormal_flag: Mapped[bool] = mapped_column(Boolean, default=False)
    abnormal_detail: Mapped[str | None] = mapped_column(Text)

    flow = relationship("DailyOpsFlow", back_populates="nodes")
