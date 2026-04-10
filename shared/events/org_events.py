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
    EMPLOYEE_PROFILE_UPDATED = "org.employee.profile_updated"         # 员工档案更新
    EMPLOYEE_DEPARTMENT_CHANGED = "org.employee.department_changed"   # 员工部门调动
    EMPLOYEE_GRADE_CHANGED = "org.employee.grade_changed"             # 员工职级变更
    EMPLOYEE_CONTRACT_EXPIRING = "org.employee.contract_expiring"     # 合同即将到期
    EMPLOYEE_TRANSFERRED = "org.employee.transferred"                 # 员工调店

    # ── 排班类 ─────────────────────────────────────────────────────
    SCHEDULE_CREATED = "org.schedule.created"             # 排班创建
    SCHEDULE_UPDATED = "org.schedule.updated"             # 排班修改
    SCHEDULE_CANCELLED = "org.schedule.cancelled"         # 排班取消
    SCHEDULE_SWAPPED = "org.schedule.swapped"             # 调班换班
    SCHEDULE_BATCH_CREATED = "org.schedule.batch_created" # 批量排班

    # ── 缺口类 ─────────────────────────────────────────────────────
    SHIFT_GAP_OPENED = "org.shift_gap.opened"             # 缺口产生
    SHIFT_GAP_CLAIMED = "org.shift_gap.claimed"           # 员工认领缺口
    SHIFT_GAP_FILLED = "org.shift_gap.filled"             # 缺口已填补

    # ── 合规类 ─────────────────────────────────────────────────────
    COMPLIANCE_ALERT_CREATED = "org.compliance.alert_created"     # 合规预警
    COMPLIANCE_ALERT_RESOLVED = "org.compliance.alert_resolved"   # 合规预警解除


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
