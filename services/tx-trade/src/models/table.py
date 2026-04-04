"""
Table Model - 智能桌台卡片的数据模型

该模型继承自 TenantBase，提供多租户隔离和基础的审计字段。
支持桌台的完整生命周期管理：空桌 -> 用餐 -> 待结账 -> 待清台 -> 预订等状态。
config JSON 字段支持灵活的布局和卡片显示配置。
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional, Any

from sqlalchemy import JSON, Boolean, ForeignKey, Integer, String, event
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import TenantBase


class Table(TenantBase):
    """
    餐厅桌台模型

    属性:
        id: 唯一标识符 (UUID)
        store_id: 所属店铺ID (外键关联stores表)
        table_no: 桌号，如 "A01", "B05" (String 20)
        area: 桌台所在区域，如 "大厅", "包厢", "户外" (String 50)
        seats: 桌台座位数 (Integer, 默认4)
        status: 桌台状态 (String 20)
            - empty: 空桌
            - dining: 用餐中
            - reserved: 已预订
            - pending_checkout: 待结账
            - pending_cleanup: 待清台
        is_active: 是否活跃，用于逻辑删除而非硬删除 (Boolean, 默认True)
        config: JSON配置，包含布局和卡片显示设置 (JSON dict)

        config JSONB 结构示例:
        {
            "layout": {
                "pos_x": 45.0,      # 平面图X坐标(%)
                "pos_y": 30.0,      # 平面图Y坐标(%)
                "width": 8.0,       # 宽度(%)
                "height": 8.0,      # 高度(%)
                "rotation": 0,      # 旋转角度(度)
                "shape": "rect"     # 形状: rect/circle/hexagon
            },
            "card_overrides": {
                "pin_fields": ["amount", "duration"],  # 固定显示的字段
                "hide_fields": ["waiter"],              # 隐藏的字段
                "custom_labels": {                      # 自定义标签
                    "amount": "金额",
                    "duration": "时长"
                }
            }
        }
    """

    __tablename__ = "tables"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        doc="桌台唯一标识符"
    )

    store_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("stores.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        doc="所属店铺ID"
    )

    table_no: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        index=True,
        doc="桌号，如 A01, B05 (store_id内唯一)"
    )

    area: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="大厅",
        doc="桌台所在区域"
    )

    seats: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=4,
        doc="桌台座位数"
    )

    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="empty",
        index=True,
        doc="桌台状态: empty/dining/reserved/pending_checkout/pending_cleanup"
    )

    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        index=True,
        doc="是否活跃（逻辑删除标记）"
    )

    config: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
        doc="JSON配置：包含layout(布局)和card_overrides(卡片显示设置)"
    )

    # 继承自 TenantBase 的字段：
    # - tenant_id: 租户ID (多租户隔离)
    # - created_at: 创建时间
    # - updated_at: 更新时间
    # - is_deleted: 软删除标记

    def __repr__(self) -> str:
        return (
            f"<Table(id={self.id}, store_id={self.store_id}, "
            f"table_no='{self.table_no}', status='{self.status}')>"
        )

    def get_layout(self) -> dict[str, Any]:
        """
        获取桌台布局配置

        返回:
            dict: 包含 pos_x, pos_y, width, height, rotation, shape 的布局字典
        """
        return self.config.get("layout", {
            "pos_x": 0.0,
            "pos_y": 0.0,
            "width": 8.0,
            "height": 8.0,
            "rotation": 0,
            "shape": "rect"
        })

    def get_card_overrides(self) -> dict[str, Any]:
        """
        获取卡片显示覆盖配置

        返回:
            dict: 包含 pin_fields, hide_fields, custom_labels 的配置字典
        """
        return self.config.get("card_overrides", {
            "pin_fields": [],
            "hide_fields": [],
            "custom_labels": {}
        })

    def update_layout(
        self,
        pos_x: Optional[float] = None,
        pos_y: Optional[float] = None,
        width: Optional[float] = None,
        height: Optional[float] = None,
        rotation: Optional[int] = None,
        shape: Optional[str] = None
    ) -> None:
        """
        更新布局配置

        参数:
            pos_x: X坐标 (%)
            pos_y: Y坐标 (%)
            width: 宽度 (%)
            height: 高度 (%)
            rotation: 旋转角度 (度)
            shape: 形状
        """
        if "layout" not in self.config:
            self.config["layout"] = {}

        layout = self.config["layout"]
        if pos_x is not None:
            layout["pos_x"] = pos_x
        if pos_y is not None:
            layout["pos_y"] = pos_y
        if width is not None:
            layout["width"] = width
        if height is not None:
            layout["height"] = height
        if rotation is not None:
            layout["rotation"] = rotation
        if shape is not None:
            layout["shape"] = shape

    def update_card_overrides(
        self,
        pin_fields: Optional[list[str]] = None,
        hide_fields: Optional[list[str]] = None,
        custom_labels: Optional[dict[str, str]] = None
    ) -> None:
        """
        更新卡片显示配置

        参数:
            pin_fields: 固定显示的字段列表
            hide_fields: 隐藏的字段列表
            custom_labels: 自定义标签字典
        """
        if "card_overrides" not in self.config:
            self.config["card_overrides"] = {}

        overrides = self.config["card_overrides"]
        if pin_fields is not None:
            overrides["pin_fields"] = pin_fields
        if hide_fields is not None:
            overrides["hide_fields"] = hide_fields
        if custom_labels is not None:
            overrides["custom_labels"] = custom_labels
