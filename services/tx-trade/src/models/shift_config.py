"""班次配置模型 — 早班/午班/晚班时段定义

每个门店可配置多个班次，KDS生产报表按班次时段切割kds_tasks数据。
"""
import uuid
from datetime import time

from sqlalchemy import String, Boolean, Time
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from shared.ontology.src.base import TenantBase


class ShiftConfig(TenantBase):
    """班次配置

    门店可定义任意数量的班次，例如：
    - 早班  07:00–11:00
    - 午班  11:00–14:00
    - 晚班  17:00–22:00

    班次时段可跨午夜（start_time > end_time 表示跨夜班）。
    """

    __tablename__ = "shift_configs"

    store_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True, comment="门店ID"
    )
    shift_name: Mapped[str] = mapped_column(
        String(50), nullable=False, comment="班次名称：早班/午班/晚班"
    )
    start_time: Mapped[time] = mapped_column(
        Time, nullable=False, comment="班次开始时间（本地时）"
    )
    end_time: Mapped[time] = mapped_column(
        Time, nullable=False, comment="班次结束时间（本地时）"
    )
    color: Mapped[str] = mapped_column(
        String(10), nullable=False, default="#FF6B35", comment="前端显示色，如 #FF6B35"
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, comment="是否启用"
    )
