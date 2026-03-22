"""TunxiangOS Ontology — 六大核心实体基类定义"""
from .base import TenantBase
from .entities import Customer, Dish, Store, Order, Ingredient, Employee

__all__ = [
    "TenantBase",
    "Customer",
    "Dish",
    "Store",
    "Order",
    "Ingredient",
    "Employee",
]
