"""会员行为事件类型定义

所有跨服务事件均通过 MemberEvent 传递，事件类型由 MemberEventType 枚举定义。
Redis Stream key: member_events
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from uuid import UUID, uuid4


class MemberEventType(str, Enum):
    """会员行为事件类型

    命名规范：{domain}.{entity}.{action}
    全部小写，单词间用点分隔。
    """

    # ── 交易类 ─────────────────────────────────────────────────────
    ORDER_PLACED = "member.order.placed"  # 下单（未支付）
    ORDER_PAID = "member.order.paid"  # 支付成功
    ORDER_CANCELLED = "member.order.cancelled"  # 取消订单

    # ── 会员类 ─────────────────────────────────────────────────────
    MEMBER_REGISTERED = "member.registered"  # 新会员注册
    MEMBER_LEVEL_UPGRADED = "member.level.upgraded"  # 等级升级
    MEMBER_LEVEL_DOWNGRADED = "member.level.downgraded"  # 等级降级

    # ── 储值类 ─────────────────────────────────────────────────────
    STORED_VALUE_RECHARGED = "member.sv.recharged"  # 储值充值
    STORED_VALUE_CONSUMED = "member.sv.consumed"  # 储值消费

    # ── 互动类 ─────────────────────────────────────────────────────
    COUPON_ISSUED = "member.coupon.issued"  # 优惠券发放
    COUPON_REDEEMED = "member.coupon.redeemed"  # 优惠券核销
    POINTS_EARNED = "member.points.earned"  # 积分获得
    POINTS_REDEEMED = "member.points.redeemed"  # 积分兑换

    # ── 私域类 ─────────────────────────────────────────────────────
    WECOM_BOUND = "member.wecom.bound"  # 企微绑定
    WECOM_UNBOUND = "member.wecom.unbound"  # 企微解绑

    # ── 风险类 ─────────────────────────────────────────────────────
    CHURN_RISK_DETECTED = "member.churn.risk"  # 流失风险检测


@dataclass
class MemberEvent:
    """会员行为事件数据类

    Attributes:
        event_type:     事件类型（MemberEventType 枚举值）
        tenant_id:      租户 UUID（RLS 隔离）
        customer_id:    客户 UUID（Golden ID）
        event_data:     事件具体数据（业务字段，按事件类型不同）
        event_id:       唯一事件 ID（默认自动生成 uuid4）
        occurred_at:    事件发生时刻（UTC，默认当前时间）
        source_service: 来源服务名（如 "tx-member"、"tx-trade"）
    """

    event_type: MemberEventType
    tenant_id: UUID
    customer_id: UUID
    event_data: dict
    event_id: str = field(default_factory=lambda: str(uuid4()))
    occurred_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    source_service: str = "unknown"
