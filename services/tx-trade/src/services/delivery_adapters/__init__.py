"""外卖平台适配器包 — Adapter 模式"""

from .base_adapter import BaseDeliveryAdapter, DeliveryOrder, DeliveryOrderItem
from .douyin_adapter import DouyinAdapter
from .eleme_adapter import ElemeAdapter
from .meituan_adapter import MeituanAdapter

__all__ = [
    "BaseDeliveryAdapter",
    "DeliveryOrder",
    "DeliveryOrderItem",
    "MeituanAdapter",
    "ElemeAdapter",
    "DouyinAdapter",
]
