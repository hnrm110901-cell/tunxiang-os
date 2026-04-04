"""订单课程模型 — Course Firing 上菜节奏控制

支持宴席和散台两种场景的上菜节奏控制：
- 宴席：由厨师长手动推进各课程（fire_course）
- 散台/VIP：自动按菜品分类分配课程，按预设延时自动开火或手动调整
"""
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import Index, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from shared.ontology.src.base import TenantBase


class OrderCourse(TenantBase):
    """订单课程：记录一个订单中某个上菜课程的状态与开火信息"""
    __tablename__ = "order_courses"

    order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True,
        comment="关联订单ID"
    )
    course_name: Mapped[str] = mapped_column(
        String(50), nullable=False,
        comment="课程名称: drink/appetizer/main/soup/staple/dessert"
    )
    course_label: Mapped[str] = mapped_column(
        String(50), nullable=False,
        comment="课程显示名称: 饮品/前菜/主菜/汤品/主食/甜品"
    )
    sort_order: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1,
        comment="排序序号"
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="waiting",
        comment="课程状态: waiting/hold/fired/completed"
    )
    delay_minutes: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0,
        comment="相对首道课程的延迟分钟数（散台自动节奏控制）"
    )
    scheduled_fire_at: Mapped[Optional[datetime]] = mapped_column(
        comment="计划开火时间（首道课程开火时间 + delay_minutes）"
    )
    fired_at: Mapped[Optional[datetime]] = mapped_column(
        comment="实际开火时间"
    )
    fired_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        comment="开火操作员ID"
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(
        comment="全部出餐时间"
    )

    __table_args__ = (
        Index("ix_order_courses_tenant_order", "tenant_id", "order_id"),
        UniqueConstraint("order_id", "course_name", name="uix_order_courses_order_course"),
    )
