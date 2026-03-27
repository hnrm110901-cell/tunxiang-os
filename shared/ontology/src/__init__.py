"""TunxiangOS Ontology — L1 层六大核心实体 + 枚举 + RLS 基类 + 金额公约 + 渠道配置"""
from .base import TenantBase
from .enums import (
    OrderStatus, StoreStatus, InventoryStatus, TransactionType,
    EmploymentStatus, EmploymentType, StorageType, RFMLevel,
)
from .entities import (
    Customer,
    Store,
    DishCategory, Dish, DishIngredient,
    Order, OrderItem,
    IngredientMaster, Ingredient, IngredientTransaction,
    Employee,
)
from .amount_convention import yuan_to_fen, fen_to_yuan, format_amount, validate_fen
from .sales_channel import SalesChannel, DEFAULT_CHANNELS, get_channel_by_id, get_channels_by_type

__all__ = [
    "TenantBase",
    # Enums
    "OrderStatus", "StoreStatus", "InventoryStatus", "TransactionType",
    "EmploymentStatus", "EmploymentType", "StorageType", "RFMLevel",
    # Entities
    "Customer",
    "Store",
    "DishCategory", "Dish", "DishIngredient",
    "Order", "OrderItem",
    "IngredientMaster", "Ingredient", "IngredientTransaction",
    "Employee",
    # Amount convention
    "yuan_to_fen", "fen_to_yuan", "format_amount", "validate_fen",
    # Sales channels
    "SalesChannel", "DEFAULT_CHANNELS", "get_channel_by_id", "get_channels_by_type",
]
