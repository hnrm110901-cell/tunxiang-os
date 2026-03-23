"""出品部门模型 — 热菜间/凉菜间/面点/海鲜/吧台 等出品部门管理"""
import uuid

from sqlalchemy import String, Integer, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from shared.ontology.src.base import TenantBase


class ProductionDept(TenantBase):
    """出品部门"""
    __tablename__ = "production_depts"

    dept_name: Mapped[str] = mapped_column(
        String(50), nullable=False, comment="部门名称：热菜间/凉菜间/面点/海鲜/吧台"
    )
    dept_code: Mapped[str] = mapped_column(
        String(20), nullable=False, comment="部门编码", index=True
    )
    brand_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True, comment="品牌ID"
    )
    fixed_fee_type: Mapped[str | None] = mapped_column(
        String(30), comment="固定费用类型：茶位费/服务费/包间费/餐位费/无"
    )
    sort_order: Mapped[int] = mapped_column(Integer, default=0, comment="排序序号")


class DishDeptMapping(TenantBase):
    """菜品-出品部门映射（关联打印机和KDS终端）"""
    __tablename__ = "dish_dept_mappings"

    dish_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True, comment="菜品ID"
    )
    production_dept_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("production_depts.id"), nullable=False, index=True
    )
    printer_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), comment="关联打印机ID"
    )
    kds_terminal_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), comment="关联KDS终端ID"
    )
