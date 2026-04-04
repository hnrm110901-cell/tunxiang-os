"""
Table Card Click Log Model - 桌台卡片点击日志

用于记录店长对卡片字段的点击行为，支持自学习系统的数据收集。

数据模型：
  - id: 主键
  - store_id: 店铺ID（多租户隔离）
  - table_no: 桌号
  - field_key: 被点击的字段键（如 'amount', 'duration'）
  - clicked_at: 点击时间戳
  - meal_period: 点击时的用餐时段（如 'lunch', 'dinner'）
  - score: 动态分数（基础100，每天衰减20%）
  - created_at, updated_at: 审计字段

该表的数据按时间衰减管理，定期清理过期的低分记录。
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import JSON, Float, ForeignKey, Index, String, event
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import TenantBase


class TableCardClickLog(TenantBase):
    """
    桌台卡片点击日志模型

    记录店长对卡片字段的点击行为，用于：
    1. 统计最受欢迎的字段
    2. 计算字段权重，个性化排序
    3. 分析店铺特定的工作流偏好
    4. 基于时段优化显示策略

    属性:
        id: 日志唯一标识符
        store_id: 所属店铺ID（外键关联stores表）
        table_no: 桌号（如 "A01"）
        field_key: 被点击的字段键（如 "amount", "duration", "customer_name"）
        clicked_at: 点击时间戳
        meal_period: 点击时的用餐时段（breakfast/lunch/afternoon/dinner/late_night）
        score: 点击权重分数（初始100，基于时间衰减，最低5）
        metadata: 可选的额外上下文数据（JSON）

        metadata示例:
        {
            "table_status": "dining",           # 点击时桌台状态
            "order_duration_min": 45,           # 用餐时长（分钟）
            "customer_rfm_level": "S1",         # 客户等级
            "batch_id": "batch_20240327_001"    # 批次ID（用于批量操作）
        }

    继承自 TenantBase 的字段：
        - tenant_id: 租户ID
        - created_at: 日志创建时间
        - updated_at: 日志更新时间
        - is_deleted: 软删除标记
    """

    __tablename__ = "table_card_click_logs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        doc="日志唯一标识符"
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
        doc="桌号（如 A01, B05）"
    )

    field_key: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        index=True,
        doc="被点击的字段键（如 amount, duration, customer_name）"
    )

    clicked_at: Mapped[datetime] = mapped_column(
        nullable=False,
        index=True,
        doc="点击时间戳"
    )

    meal_period: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="unknown",
        index=True,
        doc="点击时的用餐时段（breakfast/lunch/afternoon/dinner/late_night）"
    )

    score: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        default=100.0,
        doc="点击权重分数（初始100，每天衰减20%，最低5）"
    )

    metadata: Mapped[dict] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
        doc="可选的上下文数据（table_status, order_duration_min, customer_rfm_level等）"
    )

    # 复合索引：加速按店铺+时段+字殥查询
    __table_args__ = (
        Index(
            "idx_store_meal_field_time",
            "store_id",
            "meal_period",
            "field_key",
            "clicked_at",
        ),
        Index(
            "idx_store_field_time",
            "store_id",
            "field_key",
            "clicked_at",
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<TableCardClickLog(id={self.id}, store_id={self.store_id}, "
            f"table_no='{self.table_no}', field_key='{self.field_key}', "
            f"score={self.score:.1f})>"
        )

    def get_metadata(self, key: str, default: Optional[any] = None) -> Optional[any]:
        """
        获取元数据字段

        参数:
            key: 元数据键
            default: 默认值

        返回:
            元数据值，或默认值
        """
        return self.metadata.get(key, default)

    def set_metadata(self, key: str, value: any) -> None:
        """
        设置元数据字段

        参数:
            key: 元数据键
            value: 元数据值
        """
        if not self.metadata:
            self.metadata = {}
        self.metadata[key] = value

    @classmethod
    def create_from_click(
        cls,
        store_id: uuid.UUID,
        table_no: str,
        field_key: str,
        clicked_at: Optional[datetime] = None,
        meal_period: str = "unknown",
        **metadata_kwargs,
    ) -> TableCardClickLog:
        """
        工厂方法：从点击事件创建日志
        参数:
            store_id: 店铺ID
            table_no: 桌号
            field_key: 字段键
            clicked_at: 点击时间（默认为当前时间）
            meal_period: 用餐时段
            **metadata_kwargs: 额外的元数据字段
        返回:
            TableCardClickLog: 新创建的日志实例
        """
        if clicked_at is None:
            clicked_at = datetime.now()

        metadata = metadata_kwargs or {}

        return cls(
            store_id=store_id,
            table_no=table_no,
            field_key=field_key,
            clicked_at=clicked_at,
            meal_period=meal_period,
            score=100.0,
            metadata=metadata,
        )
