"""Order 聚合的 Ontology 事件 payload 定义.

聚合根: Order (aggregate_type='order')
相关事件: order.created / order.paid

演进规则: 只加不改 (见 base.OntologyEvent 注释)
"""
from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import Field

from .base import OntologyEvent


class PaymentMethod(str, Enum):
    """支付方式枚举."""

    WECHAT = "wechat"
    ALIPAY = "alipay"
    CASH = "cash"
    UNION_PAY = "union_pay"
    MEMBER_BALANCE = "member_balance"
    MEAL_VOUCHER = "meal_voucher"


class OrderChannel(str, Enum):
    """订单渠道枚举."""

    DINE_IN = "dine_in"
    TAKEOUT = "takeout"
    DELIVERY = "delivery"
    BANQUET = "banquet"


class OrderCreatedPayload(OntologyEvent):
    """订单创建事件 payload."""

    order_id: str
    store_id: str
    total_fen: int = Field(ge=0, description="总金额, 单位: 分")
    table_id: Optional[str] = None
    created_by: str = Field(description="创建人员工 ID")


class OrderPaidPayload(OntologyEvent):
    """订单支付完成事件 payload.

    paid_fen 可小于 total_fen (部分支付场景, 如会员折扣 + 现金补差).
    """

    order_id: str
    store_id: str
    total_fen: int = Field(ge=0)
    paid_fen: int = Field(ge=0, description="实收金额, 分")
    payment_method: PaymentMethod
    channel: OrderChannel
