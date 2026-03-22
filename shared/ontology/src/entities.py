"""六大核心实体 — Ontology L1 层骨架定义

详细字段在各域微服务中扩展，此处仅定义核心标识字段。
"""
from sqlalchemy import String, Integer, Numeric
from sqlalchemy.orm import Mapped, mapped_column

from .base import TenantBase


class Customer(TenantBase):
    """顾客 — Golden ID, 全渠道画像, RFM 分层, 生命周期"""
    __tablename__ = "customers"

    golden_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(20))


class Dish(TenantBase):
    """菜品 — BOM 配方, 各渠道价格, 毛利模型, 四象限分类"""
    __tablename__ = "dishes"

    dish_name: Mapped[str] = mapped_column(String(200), nullable=False)
    price_fen: Mapped[int] = mapped_column(Integer, nullable=False, comment="售价(分)")
    category: Mapped[str | None] = mapped_column(String(100))


class Store(TenantBase):
    """门店 — 桌台拓扑, 档口配置, 人效模型, 经营指标"""
    __tablename__ = "stores"

    store_name: Mapped[str] = mapped_column(String(200), nullable=False)
    store_code: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    address: Mapped[str | None] = mapped_column(String(500))


class Order(TenantBase):
    """订单 — 全渠道统一, 折扣明细, 核销记录, 出餐状态"""
    __tablename__ = "orders"

    order_no: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    total_fen: Mapped[int] = mapped_column(Integer, nullable=False, comment="订单总额(分)")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")


class Ingredient(TenantBase):
    """食材 — 库存量, 效期, 采购价, 批次, 供应商"""
    __tablename__ = "ingredients"

    ingredient_name: Mapped[str] = mapped_column(String(200), nullable=False)
    unit: Mapped[str] = mapped_column(String(20), nullable=False)
    unit_price_fen: Mapped[int] = mapped_column(Integer, comment="单价(分)")


class Employee(TenantBase):
    """员工 — 角色, 技能, 排班, 业绩提成, 效率指标"""
    __tablename__ = "employees"

    emp_name: Mapped[str] = mapped_column(String(100), nullable=False)
    role: Mapped[str] = mapped_column(String(50), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(20))
