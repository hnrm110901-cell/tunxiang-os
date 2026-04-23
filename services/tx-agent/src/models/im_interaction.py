"""Phase S2: IM全闭环 — ORM模型

表：sop_im_interactions / sop_quick_actions
"""
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from shared.ontology.src.base import TenantBase


# ─────────────────────────────────────────────
# sop_im_interactions — IM交互记录
# ─────────────────────────────────────────────
class SOPIMInteraction(TenantBase):
    """IM交互记录 — 所有SOP↔IM双向消息的审计日志

    每条记录代表一次IM消息推送或回调：
    - outbound: 系统推送到IM（任务卡/教练卡/预警卡/纠正卡）
    - inbound:  IM回调到系统（快捷回复/照片上传/语音指令）
    """

    __tablename__ = "sop_im_interactions"

    store_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, comment="门店ID",
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, comment="操作人ID",
    )
    instance_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), nullable=True,
        comment="关联的SOP任务实例ID",
    )
    action_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), nullable=True,
        comment="关联的纠正动作ID",
    )
    channel: Mapped[str] = mapped_column(
        Text, nullable=False,
        comment="IM通道：wecom / dingtalk / feishu",
    )
    direction: Mapped[str] = mapped_column(
        Text, nullable=False,
        comment="消息方向：outbound / inbound",
    )
    message_type: Mapped[str] = mapped_column(
        Text, nullable=False,
        comment="消息类型：task_card / quick_reply / photo_upload / "
                "voice_cmd / coaching_card / alert_card",
    )
    content: Mapped[dict] = mapped_column(
        JSONB, nullable=False,
        comment="消息内容 JSON",
    )
    reply_to: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), nullable=True,
        comment="回复哪条消息的ID",
    )


# ─────────────────────────────────────────────
# sop_quick_actions — IM快捷操作定义
# ─────────────────────────────────────────────
class SOPQuickAction(TenantBase):
    """IM快捷操作定义 — 卡片上的一键操作按钮配置

    action_type:
    - confirm:    一键确认（完成任务）
    - photo:      拍照上传（需要照片凭证）
    - flag:       标记异常（创建纠正动作）
    - escalate:   呼叫支援（升级通知）
    - data_entry: 快速备注（需要文字输入）
    """

    __tablename__ = "sop_quick_actions"

    action_code: Mapped[str] = mapped_column(
        Text, nullable=False,
        comment="操作代码（唯一标识）：confirm_task / photo_check / flag_issue / "
                "call_support / quick_note",
    )
    action_name: Mapped[str] = mapped_column(
        Text, nullable=False,
        comment="操作显示名：一键确认 / 拍照确认 / 标记异常 / 呼叫支援 / 快速备注",
    )
    action_type: Mapped[str] = mapped_column(
        Text, nullable=False,
        comment="操作类型：confirm / photo / flag / escalate / data_entry",
    )
    target_service: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True,
        comment="关联微服务名（如tx-agent、tx-ops等）",
    )
    target_endpoint: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True,
        comment="API路径",
    )
    payload_template: Mapped[Optional[dict]] = mapped_column(
        JSONB, nullable=True,
        comment="请求模板 JSON，可包含 {instance_id} 等占位符",
    )
    requires_photo: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false",
        comment="是否需要拍照",
    )
    requires_note: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false",
        comment="是否需要备注",
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="true",
        comment="是否启用",
    )
