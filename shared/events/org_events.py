"""组织人事域事件类型定义

组织人事域所有跨服务事件均通过 OrgEvent 传递，事件类型由 OrgEventType 枚举定义。
Redis Stream key: org_events
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from uuid import UUID, uuid4


class OrgEventType(str, Enum):
    """组织人事域事件类型

    命名规范：org.{entity}.{action}
    全部小写，单词间用点分隔。
    """

    # ── 考勤类 ─────────────────────────────────────────────────────
    ATTENDANCE_LATE = "org.attendance.late"             # 员工迟到
    ATTENDANCE_ABSENT = "org.attendance.absent"         # 员工旷工
    ATTENDANCE_EXCEPTION = "org.attendance.exception"   # 考勤异常需人工复核

    # ── 请假类 ─────────────────────────────────────────────────────
    LEAVE_APPROVED = "org.leave.approved"               # 请假审批通过
    LEAVE_REJECTED = "org.leave.rejected"               # 请假审批拒绝

    # ── 审批类 ─────────────────────────────────────────────────────
    APPROVAL_COMPLETED = "org.approval.completed"       # 审批流完成
    APPROVAL_TIMEOUT = "org.approval.timeout"           # 审批超时

    # ── 薪资类 ─────────────────────────────────────────────────────
    PAYROLL_GENERATED = "org.payroll.generated"         # 薪资单生成

    # ── 员工类 ─────────────────────────────────────────────────────
    EMPLOYEE_ONBOARDED = "org.employee.onboarded"       # 员工入职
    EMPLOYEE_OFFBOARDED = "org.employee.offboarded"     # 员工离职


@dataclass
class OrgEvent:
    """组织人事域事件数据类

    Attributes:
        event_type:     事件类型（OrgEventType 枚举值）
        tenant_id:      租户 UUID（RLS 隔离）
        store_id:       门店 UUID
        employee_id:    主体员工 UUID
        event_data:     事件具体数据（业务字段，按事件类型不同）
        event_id:       唯一事件 ID（默认自动生成 uuid4）
        occurred_at:    事件发生时刻（UTC，默认当前时间）
        source_service: 来源服务名
    """

    event_type: OrgEventType
    tenant_id: UUID
    store_id: UUID
    employee_id: UUID
    event_data: dict
    event_id: str = field(default_factory=lambda: str(uuid4()))
    occurred_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    source_service: str = "tx-org"
