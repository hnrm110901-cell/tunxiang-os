"""用户行为反馈信号 ORM（Phase S4: 记忆进化闭环）

表: memory_feedback_signals
信号类型: click / dismiss / dwell / feedback / override
来源: im_card / dashboard / coaching / sop_task

注意：此表无 is_deleted / updated_at（原始信号不可删除、不可修改）。
TenantBase 自带这些字段，ORM层保留但业务层不使用。
"""
import uuid
from typing import Optional

from sqlalchemy import Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from shared.ontology.src.base import TenantBase


class MemoryFeedbackSignal(TenantBase):
    """用户行为反馈信号 -- 驱动记忆进化的原始数据

    信号采集 -> 聚合分析 -> 偏好推断 -> 记忆更新 -> 个性化排序 -> 继续采集
    """

    __tablename__ = "memory_feedback_signals"

    store_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, comment="门店ID",
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, comment="用户ID",
    )
    signal_type: Mapped[str] = mapped_column(
        Text, nullable=False,
        comment="信号类型：click / dismiss / dwell / feedback / override",
    )
    source: Mapped[str] = mapped_column(
        Text, nullable=False,
        comment="信号来源：im_card / dashboard / coaching / sop_task",
    )
    source_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), nullable=True,
        comment="关联的卡片/任务/建议ID",
    )
    signal_data: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}",
        comment='信号详情，如 {"action": "expanded_cost_detail", "duration_sec": 45}',
    )
