"""外卖平台适配器包 — Adapter 模式"""
from .base_adapter import BaseDeliveryAdapter, DeliveryOrder, DeliveryOrderItem
from .meituan_adapter import MeituanAdapter
from .eleme_adapter import ElemeAdapter
from .douyin_adapter import DouyinAdapter

__all__ = [
    "BaseDeliveryAdapter",
    "DeliveryOrder",
    "DeliveryOrderItem",
    "MeituanAdapter",
    "ElemeAdapter",
    "DouyinAdapter",
]
