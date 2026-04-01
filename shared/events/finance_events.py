"""财务域事件类型定义

财务域所有跨服务事件均通过 FinanceEvent 传递，事件类型由 FinanceEventType 枚举定义。
Redis Stream key: finance_events
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional
from uuid import UUID, uuid4


class FinanceEventType(str, Enum):
    """财务域事件类型

    命名规范：finance.{entity}.{action}
    全部小写，单词间用点分隔。
    """

    # ── 日报类 ─────────────────────────────────────────────────────
    DAILY_PL_GENERATED = "finance.daily_pl.generated"       # 日P&L生成

    # ── 成本类 ─────────────────────────────────────────────────────
    COST_RATE_EXCEEDED = "finance.cost_rate.exceeded"        # 成本率超标
    GROSS_MARGIN_WARNING = "finance.gross_margin.warning"    # 毛利率预警

    # ── 月结类 ─────────────────────────────────────────────────────
    MONTHLY_CLOSE_COMPLETED = "finance.monthly_close.completed"  # 月结完成

    # ── 预算类 ─────────────────────────────────────────────────────
    BUDGET_OVERRUN = "finance.budget.overrun"                # 预算超支

    # ── 发票类 ─────────────────────────────────────────────────────
    INVOICE_PENDING = "finance.invoice.pending"              # 发票待处理


@dataclass
class FinanceEvent:
    """财务域事件数据类

    Attributes:
        event_type:     事件类型（FinanceEventType 枚举值）
        tenant_id:      租户 UUID（RLS 隔离）
        store_id:       门店 UUID（None 表示品牌级财务事件）
        entity_id:      主体实体 UUID（invoice_id / dish_id 等）
        event_data:     事件具体数据（业务字段，按事件类型不同）
        event_id:       唯一事件 ID（默认自动生成 uuid4）
        occurred_at:    事件发生时刻（UTC，默认当前时间）
        source_service: 来源服务名
    """

    event_type: FinanceEventType
    tenant_id: UUID
    store_id: Optional[UUID]
    entity_id: UUID
    event_data: dict
    event_id: str = field(default_factory=lambda: str(uuid4()))
    occurred_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    source_service: str = "tx-finance"
