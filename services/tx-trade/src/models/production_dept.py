"""出品部门模型 — 热菜间/凉菜间/面点/海鲜/吧台 等出品部门管理

v076 新增字段：
  ProductionDept: kds_device_id, display_color, printer_type, is_active
  DishDeptMapping: is_primary
"""
import uuid
from typing import Optional

from sqlalchemy import Boolean, ForeignKey, Index, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from shared.ontology.src.base import TenantBase


class ProductionDept(TenantBase):
    """出品部门（档口）— 餐厅厨房内按品类划分的出品工作站

    一个档口配置：
      - printer_address：厨打网络地址（host:port），订单提交后自动发厨打单
      - kds_device_id：对应的KDS平板设备ID，KDS屏按此ID轮询待出品任务
      - display_color：KDS屏显示颜色，用于快速识别不同档口任务
    """
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
    store_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), index=True, comment="门店ID（NULL表示品牌级通用）"
    )
    printer_address: Mapped[Optional[str]] = mapped_column(
        String(100), comment="档口打印机地址 host:port（如 192.168.1.101:9100）"
    )
    printer_type: Mapped[Optional[str]] = mapped_column(
        String(20), server_default="network",
        comment="打印机类型：network（网络打印机）/ usb / bluetooth"
    )
    kds_device_id: Mapped[Optional[str]] = mapped_column(
        String(100),
        comment="关联KDS设备标识（如设备序列号或自定义名称，NULL=无KDS屏）",
        index=True,
    )
    display_color: Mapped[Optional[str]] = mapped_column(
        String(20), server_default="blue",
        comment="KDS屏颜色标识：red/orange/green/blue/purple"
    )
    fixed_fee_type: Mapped[Optional[str]] = mapped_column(
        String(30), comment="固定费用类型：茶位费/服务费/包间费/餐位费/无"
    )
    default_timeout_minutes: Mapped[int] = mapped_column(
        Integer, default=15, comment="默认出品时限(分钟)"
    )
    sort_order: Mapped[int] = mapped_column(Integer, default=0, comment="排序序号")
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="true",
        comment="档口是否启用（停用后不接收新的分单任务）"
    )


class DishDeptMapping(TenantBase):
    """菜品-出品部门映射（关联打印机和KDS终端）

    v076 新增 is_primary 字段：标记菜品的主档口。
    一道菜通常只配置一个主档口，is_primary=True 的映射优先用于路由。
    """
    __tablename__ = "dish_dept_mappings"

    dish_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True, comment="菜品ID"
    )
    production_dept_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("production_depts.id"), nullable=False, index=True
    )
    printer_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), comment="关联打印机ID（覆盖档口默认打印机）"
    )
    kds_terminal_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), comment="关联KDS终端ID"
    )
    sort_order: Mapped[int] = mapped_column(
        Integer, default=0, comment="菜品在该档口内的排序"
    )
    is_primary: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="true",
        comment="是否为菜品主档口（优先用于路由分单）"
    )

    __table_args__ = (
        # 确保每个菜品在同一租户下只有一个主档口
        Index(
            "ix_dish_dept_mappings_tenant_dish",
            "tenant_id", "dish_id",
        ),
    )
