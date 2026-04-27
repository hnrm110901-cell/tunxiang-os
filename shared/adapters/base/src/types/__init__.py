"""
屯象OS 行业公共字典

连锁餐饮行业统一数据模型，所有外部系统适配器映射到此字典。
不跟随任何一家三方系统的字段定义。
"""

from .bill import UnifiedBill
from .customer import UnifiedCustomer
from .dish import UnifiedDish, UnifiedDishMethod, UnifiedSetMeal
from .enums import (
    ChannelSource,
    CustomerLevel,
    DishCategory,
    Gender,
    MealPeriod,
    OrderStatus,
    OrderType,
    PaymentMethod,
    ReservationStatus,
    ReservationType,
    TableStatus,
    TableType,
)
from .inventory import UnifiedIngredient, UnifiedInventoryRecord
from .order import UnifiedOrder, UnifiedOrderItem
from .reservation import (
    CreateReservationRequest,
    ReservationStats,
    UnifiedReservation,
)
from .supplier import UnifiedPurchaseOrder, UnifiedSupplier
from .table import UnifiedTable

__all__ = [
    # Enums
    "ReservationStatus",
    "OrderStatus",
    "OrderType",
    "ReservationType",
    "TableType",
    "TableStatus",
    "MealPeriod",
    "PaymentMethod",
    "ChannelSource",
    "Gender",
    "CustomerLevel",
    "DishCategory",
    # Reservation
    "UnifiedReservation",
    "ReservationStats",
    "CreateReservationRequest",
    # Customer
    "UnifiedCustomer",
    # Table
    "UnifiedTable",
    # Order
    "UnifiedOrder",
    "UnifiedOrderItem",
    # Bill
    "UnifiedBill",
    # Dish
    "UnifiedDish",
    "UnifiedDishMethod",
    "UnifiedSetMeal",
    # Inventory
    "UnifiedIngredient",
    "UnifiedInventoryRecord",
    # Supplier
    "UnifiedSupplier",
    "UnifiedPurchaseOrder",
]
