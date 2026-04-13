"""
差旅费用 ORM 模型
包含：TravelRequest（差旅申请主表）、TravelItinerary（行程明细）、TravelAllocation（费用分摊）

设计说明：
- 所有金额字段单位为分(fen)，BigInteger 存储，展示时除以100转元
- 继承 TenantBase 确保 RLS 租户隔离（tenant_id + is_deleted 由基类提供）
- 与 v239 迁移文件表结构完全对应
- TravelRequest.inspection_task_id 对接屯象OS巡店任务，实现督导差旅全程打通
- TravelItinerary 含 GPS 轨迹，支持里程核实与异常检测
- TravelAllocation 按停留时长自动分摊门店 P&L 成本
"""
from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import List, Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Integer,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from shared.ontology.src.base import TenantBase
from .expense_enums import TravelStatus


# ─────────────────────────────────────────────────────────────────────────────
# TravelRequest — 差旅申请主表
# ─────────────────────────────────────────────────────────────────────────────

class TravelRequest(TenantBase):
    """
    差旅申请主表
    核心设计：与屯象OS巡店任务（inspection_task_id）深度打通，
    GPS轨迹驱动里程计算，替代自报里程。
    estimated_cost_fen / total_cost_fen / mileage_allowance_fen 单位均为分(fen)。
    """
    __tablename__ = "travel_requests"

    brand_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True, comment="所属品牌ID"
    )
    store_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True, comment="申请人所属门店"
    )
    traveler_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True, comment="出行人员工ID"
    )
    applicant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True,
        comment="申请人（可能不同于出行人）"
    )

    # 关联巡店任务（核心打通点）
    inspection_task_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), nullable=True, index=True,
        comment="关联的巡店任务ID（可空，非巡店差旅为NULL）"
    )
    task_type: Mapped[str] = mapped_column(
        String(30), nullable=False, default="inspection",
        comment="值域：inspection（巡店）/ training（培训）/ meeting（会议）/ other（其他）"
    )

    # 行程信息
    departure_city: Mapped[Optional[str]] = mapped_column(
        String(50), nullable=True, comment="出发城市"
    )
    destination_cities: Mapped[list] = mapped_column(
        JSON, default=list, nullable=False,
        comment="目的地城市列表（多城市行程）"
    )
    planned_stores: Mapped[list] = mapped_column(
        JSON, default=list, nullable=False,
        comment="计划巡店的门店ID列表"
    )
    planned_start_date: Mapped[date] = mapped_column(
        Date, nullable=False, comment="计划出发日期"
    )
    planned_end_date: Mapped[date] = mapped_column(
        Date, nullable=False, comment="计划返回日期"
    )
    planned_days: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, comment="计划天数"
    )

    # 适用差标
    staff_level: Mapped[Optional[str]] = mapped_column(
        String(30), nullable=True,
        comment="出行人职级（提交时固化），参见 StaffLevel 枚举"
    )
    applicable_standards: Mapped[dict] = mapped_column(
        JSON, default=dict, nullable=False,
        comment="适用的差标快照（提交时固化）"
    )

    # 交通方式与预估费用
    transport_mode: Mapped[str] = mapped_column(
        String(20), nullable=False, default="train",
        comment="交通方式，参见 TransportMode 枚举"
    )
    estimated_cost_fen: Mapped[Optional[int]] = mapped_column(
        BigInteger, nullable=True, default=0,
        comment="预估总费用，单位：分(fen)，展示时除以100转元"
    )

    # 状态
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=TravelStatus.DRAFT.value,
        index=True,
        comment="申请状态，参见 TravelStatus 枚举"
    )
    approval_instance_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), nullable=True, comment="关联的审批实例"
    )

    # 实际数据（行程完成后填写）
    actual_start_date: Mapped[Optional[date]] = mapped_column(
        Date, nullable=True, comment="实际出发日期"
    )
    actual_end_date: Mapped[Optional[date]] = mapped_column(
        Date, nullable=True, comment="实际返回日期"
    )
    actual_days: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True, comment="实际天数"
    )
    total_mileage_km: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(10, 2), nullable=True, default=0,
        comment="实际里程（公里，GPS计算）"
    )
    total_cost_fen: Mapped[Optional[int]] = mapped_column(
        BigInteger, nullable=True, default=0,
        comment="实际总费用，单位：分(fen)，展示时除以100转元"
    )
    mileage_allowance_fen: Mapped[Optional[int]] = mapped_column(
        BigInteger, nullable=True, default=0,
        comment="里程补贴，单位：分(fen)，展示时除以100转元，GPS核实后计算"
    )

    # 报销单关联
    expense_application_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), nullable=True,
        comment="关联的费用报销申请ID"
    )

    notes: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True, comment="申请备注"
    )

    # 关系
    itineraries: Mapped[List["TravelItinerary"]] = relationship(
        "TravelItinerary",
        back_populates="travel_request",
        cascade="all, delete-orphan",
        lazy="select",
        order_by="TravelItinerary.sequence_order",
    )
    allocations: Mapped[List["TravelAllocation"]] = relationship(
        "TravelAllocation",
        back_populates="travel_request",
        cascade="all, delete-orphan",
        lazy="select",
    )


# ─────────────────────────────────────────────────────────────────────────────
# TravelItinerary — 行程明细
# ─────────────────────────────────────────────────────────────────────────────

class TravelItinerary(TenantBase):
    """
    行程明细（每个到访门店对应一条记录）
    GPS 轨迹用于核实里程，签到/签退时间用于计算停留时长，
    停留时长作为费用分摊基准（TravelAllocation）。
    """
    __tablename__ = "travel_itineraries"

    travel_request_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        index=True,
        comment="所属差旅申请ID"
    )
    store_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True, comment="本次到访的门店"
    )
    store_name: Mapped[Optional[str]] = mapped_column(
        String(100), nullable=True, comment="冗余存储门店名（避免关联查询）"
    )

    # 时间记录
    checkin_time: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="到达签到时间"
    )
    checkout_time: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="离开签退时间"
    )
    duration_minutes: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True, default=0, comment="停留时长（分钟）"
    )

    # GPS 数据
    checkin_location: Mapped[Optional[dict]] = mapped_column(
        JSON, nullable=True,
        comment='签到位置 {"lat": float, "lng": float, "accuracy": float}'
    )
    checkout_location: Mapped[Optional[dict]] = mapped_column(
        JSON, nullable=True, comment="签退位置"
    )
    gps_track: Mapped[list] = mapped_column(
        JSON, default=list, nullable=False,
        comment="轨迹点列表（精简存储，每5分钟1个点）"
    )
    distance_from_store_m: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True, comment="签到时距门店距离（米）"
    )

    # 里程
    leg_mileage_km: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(10, 2), nullable=True, default=0,
        comment="本段里程（到达本门店的路程，公里）"
    )
    is_mileage_anomaly: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False,
        comment="GPS里程异常标记（绕路>30%）"
    )
    anomaly_reason: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True, comment="里程异常说明"
    )

    # 状态
    itinerary_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="planned",
        comment="值域：planned / checked_in / checked_out / skipped（计划未到访）"
    )
    skip_reason: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True, comment="未到访原因"
    )

    sequence_order: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, comment="行程顺序"
    )

    # 关系
    travel_request: Mapped["TravelRequest"] = relationship(
        "TravelRequest",
        back_populates="itineraries",
        foreign_keys=[travel_request_id],
    )


# ─────────────────────────────────────────────────────────────────────────────
# TravelAllocation — 差旅费用分摊（门店成本中心分摊）
# ─────────────────────────────────────────────────────────────────────────────

class TravelAllocation(TenantBase):
    """
    差旅费用分摊明细
    按实际签到时长自动分摊差旅费用到各门店 P&L 成本中心。
    allocated_amount_fen = total_travel_cost_fen × allocation_rate，单位均为分(fen)。
    """
    __tablename__ = "travel_allocations"

    travel_request_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        index=True,
        comment="所属差旅申请ID"
    )
    store_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True, comment="分摊到的门店"
    )
    brand_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True, comment="所属品牌ID"
    )

    # 分摊规则
    allocation_basis: Mapped[str] = mapped_column(
        String(20), nullable=False, default="duration",
        comment="值域：duration（按停留时长）/ equal（平均分摊）/ manual（手工指定）"
    )
    basis_value: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(10, 4), nullable=True,
        comment="分摊基准值（如停留分钟数）"
    )
    allocation_rate: Mapped[Decimal] = mapped_column(
        Numeric(7, 6), nullable=False,
        comment="分摊比例（0.000000-1.000000）"
    )

    # 分摊金额（单位：分）
    total_travel_cost_fen: Mapped[int] = mapped_column(
        BigInteger, nullable=False,
        comment="本次差旅总费用，单位：分(fen)，展示时除以100转元"
    )
    allocated_amount_fen: Mapped[int] = mapped_column(
        BigInteger, nullable=False,
        comment="分摊到本门店的金额，单位：分(fen)，展示时除以100转元"
    )

    # 成本归因
    cost_center_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), nullable=True, comment="成本中心ID（关联门店）"
    )
    is_attributed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False,
        comment="是否已归入门店P&L"
    )
    attributed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="归入P&L的时间"
    )

    # 关系
    travel_request: Mapped["TravelRequest"] = relationship(
        "TravelRequest",
        back_populates="allocations",
        foreign_keys=[travel_request_id],
    )
