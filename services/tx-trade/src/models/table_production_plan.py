"""table_production_plan.py — 同桌同出协调计划模型

TableProductionPlan 记录一张桌子的多档口出品协调状态，
目标是让所有档口在同一时刻完成，实现同桌同出。
"""
import uuid

from sqlalchemy import DateTime, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from shared.ontology.src.base import TenantBase


class TableProductionPlan(TenantBase):
    """同桌同出协调计划

    每张桌的一次出餐对应一条记录。
    dept_readiness 和 dept_delays 使用 JSONB 存储档口级状态。
    """
    __tablename__ = "table_production_plans"

    order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True, comment="订单ID"
    )
    table_no: Mapped[str] = mapped_column(
        String(20), nullable=False, comment="桌号如A01"
    )
    store_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True, comment="门店ID"
    )
    target_completion: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        comment="协调基准时间（最慢档口预计完成时间）"
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="coordinating", index=True,
        comment="计划状态：coordinating/all_ready/served"
    )
    dept_readiness: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict,
        comment='JSON: {dept_id: ready_bool} 各档口就绪状态'
    )
    dept_delays: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict,
        comment='JSON: {dept_id: delay_seconds} 各档口延迟开始时间(秒)'
    )
