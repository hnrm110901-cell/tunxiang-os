"""运营日清域事件类型定义

运营域所有跨服务事件均通过 OpsEvent 传递，事件类型由 OpsEventType 枚举定义。
覆盖日清日结 E1-E8 全节点及巡店事件。
Redis Stream key: ops_events
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from uuid import UUID, uuid4


class OpsEventType(str, Enum):
    """运营日清域事件类型

    命名规范：ops.{entity}.{action}
    全部小写，单词间用点分隔。
    """

    # ── 日清日结 E1-E8 节点 ────────────────────────────────────────
    DAILY_E1_OPENING_CHECKLIST = "ops.daily.e1_opening_checklist"  # 开店清单完成
    DAILY_E2_PREP_CONFIRMED = "ops.daily.e2_prep_confirmed"  # 备货确认
    DAILY_E3_SERVICE_STARTED = "ops.daily.e3_service_started"  # 正式营业
    DAILY_E4_PEAK_STARTED = "ops.daily.e4_peak_started"  # 高峰开始
    DAILY_E5_PEAK_ENDED = "ops.daily.e5_peak_ended"  # 高峰结束
    DAILY_E6_CLOSING_PREP = "ops.daily.e6_closing_prep"  # 备关店
    DAILY_E7_SETTLEMENT_DONE = "ops.daily.e7_settlement_done"  # 日结完成
    DAILY_E8_CLOSING_COMPLETE = "ops.daily.e8_closing_complete"  # 关店完成

    # ── 巡店类 ─────────────────────────────────────────────────────
    INSPECTION_TASK_CREATED = "ops.inspection.task_created"  # 巡店任务创建
    INSPECTION_COMPLETED = "ops.inspection.completed"  # 巡店完成


@dataclass
class OpsEvent:
    """运营日清域事件数据类

    Attributes:
        event_type:     事件类型（OpsEventType 枚举值）
        tenant_id:      租户 UUID（RLS 隔离）
        store_id:       门店 UUID
        event_data:     事件具体数据（业务字段，按事件类型不同）
        event_id:       唯一事件 ID（默认自动生成 uuid4）
        occurred_at:    事件发生时刻（UTC，默认当前时间）
        source_service: 来源服务名
    """

    event_type: OpsEventType
    tenant_id: UUID
    store_id: UUID
    event_data: dict
    event_id: str = field(default_factory=lambda: str(uuid4()))
    occurred_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    source_service: str = "tx-ops"
