"""档口路由规则模型 — 多品牌/多渠道/时段路由配置"""
import uuid
from datetime import time

from sqlalchemy import Boolean, ForeignKey, Integer, String, Time
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from shared.ontology.src.base import TenantBase


class DispatchRule(TenantBase):
    """档口分单路由规则。

    匹配条件全部可选（NULL = 通配）。规则按 priority DESC 排序，
    第一条所有非NULL条件均满足的规则生效。

    场景示例：
    - 外卖单走B窗口：match_channel='takeaway', target_dept_id=<B窗口>
    - 品牌A专属档口：match_brand_id=<品牌A>, target_dept_id=<A专属档口>
    - 午高峰烤鸭路由：match_dish_id=<烤鸭>, match_time_start=11:00, match_time_end=14:00
    """
    __tablename__ = "dispatch_rules"

    name: Mapped[str] = mapped_column(
        String(100), nullable=False, comment="规则名称（管理用途）"
    )
    priority: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0,
        comment="优先级，越大越先匹配"
    )

    # ── 匹配条件（全部可选，NULL=不限制/通配） ──
    match_dish_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, index=True,
        comment="按菜品ID精确匹配（NULL=不限）"
    )
    match_dish_category: Mapped[str | None] = mapped_column(
        String(50), nullable=True,
        comment="按菜品分类匹配，如 '烤制品'、'凉菜'（NULL=不限）"
    )
    match_brand_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, index=True,
        comment="按品牌ID匹配（NULL=不限，适合多品牌共用厨房）"
    )
    match_channel: Mapped[str | None] = mapped_column(
        String(30), nullable=True,
        comment="按渠道匹配：dine_in/takeaway/delivery/reservation（NULL=不限）"
    )
    match_time_start: Mapped[time | None] = mapped_column(
        Time, nullable=True,
        comment="时段开始时间（含），如 11:00（NULL=不限）"
    )
    match_time_end: Mapped[time | None] = mapped_column(
        Time, nullable=True,
        comment="时段结束时间（含），如 14:00（NULL=不限）"
    )
    match_day_type: Mapped[str | None] = mapped_column(
        String(20), nullable=True,
        comment="工作日类型：weekday/weekend/holiday（NULL=不限）"
    )

    # ── 路由目标 ──
    target_dept_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("production_depts.id"),
        nullable=False,
        comment="路由目标档口ID"
    )
    target_printer_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True,
        comment="可选覆盖打印机ID（NULL=使用档口默认打印机）"
    )

    # ── 作用域 ──
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True,
        comment="规则是否启用"
    )
    store_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True,
        comment="规则所属门店"
    )
    # tenant_id 继承自 TenantBase
