"""
易订预订系统适配器 - YiDing Reservation System Adapter

基于易订开放API（https://open.zhidianfan.com/yidingopen/）
"""

from .adapter import YiDingAdapter
from .cache import YiDingCache
from .client import YiDingAPIError, YiDingClient
from .mapper import YiDingMapper
from .types import (
    CreateReservationDTO,
    ReservationStats,
    ReservationStatus,
    TableStatus,
    TableType,
    UnifiedBill,
    UnifiedCustomer,
    UnifiedDish,
    UnifiedReservation,
    UnifiedTable,
    YiDingConfig,
)

__version__ = "1.0.0"

__all__ = [
    "YiDingAdapter",
    "YiDingClient",
    "YiDingAPIError",
    "YiDingMapper",
    "YiDingCache",
    "YiDingConfig",
    "UnifiedReservation",
    "UnifiedCustomer",
    "UnifiedTable",
    "UnifiedBill",
    "UnifiedDish",
    "ReservationStats",
    "ReservationStatus",
    "TableType",
    "TableStatus",
    "CreateReservationDTO",
]
