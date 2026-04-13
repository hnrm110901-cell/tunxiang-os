"""
费控通知模型
ExpenseNotification：审批推送记录，记录每条消息的发送状态和结果。
支持企业微信/钉钉/飞书多渠道，按 Brand 配置自动路由。
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from shared.ontology.src.base import TenantBase
from .expense_enums import NotificationChannel, NotificationEventType, PushStatus

if TYPE_CHECKING:
    from .expense_application import ExpenseApplication


# ─────────────────────────────────────────────────────────────────────────────
# ExpenseNotification — 审批推送记录
# ─────────────────────────────────────────────────────────────────────────────

class ExpenseNotification(TenantBase):
    """
    审批推送记录
    记录每条通知消息的渠道、内容、发送状态及结果。
    一个审批事件可能产生多条记录（如同时推送企业微信和短信）。
    """
    __tablename__ = "expense_notifications"

    application_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("expense_applications.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="所属费用申请ID"
    )
    recipient_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        index=True,
        comment="消息接收人员工ID"
    )
    recipient_role: Mapped[Optional[str]] = mapped_column(
        String(50),
        nullable=True,
        comment="接收人角色标识，如 approver / applicant"
    )
    channel: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        comment="推送渠道，参见 NotificationChannel 枚举"
    )
    event_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        index=True,
        comment="通知事件类型，参见 NotificationEventType 枚举"
    )
    message_title: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
        comment="消息标题"
    )
    message_body: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="消息正文（Markdown 或纯文本，依渠道格式而定）"
    )
    push_status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default=PushStatus.PENDING.value,
        comment="推送状态，参见 PushStatus 枚举"
    )
    sent_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="实际推送成功时间"
    )
    failed_reason: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        comment="推送失败原因（HTTP 错误码或异常信息）"
    )
    retry_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        comment="重试次数，超过上限后置为 failed"
    )
    external_msg_id: Mapped[Optional[str]] = mapped_column(
        String(200),
        nullable=True,
        comment="第三方平台返回的消息 ID（企业微信/钉钉/飞书），用于追踪"
    )

    # 关系（使用 TYPE_CHECKING 避免循环导入）
    application: Mapped["ExpenseApplication"] = relationship(
        "ExpenseApplication",
        foreign_keys=[application_id],
        lazy="select",
    )
