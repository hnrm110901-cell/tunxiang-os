"""企微群运营数据模型

WecomGroupConfig  — 群运营配置（群名、目标分群、SOP日历、建群规则）
WecomGroupMessage — 群消息发送历史记录

注意：使用 Base（非 TenantBase），因为群运营是跨租户配置，
但仍包含 tenant_id 字段，RLS 由迁移文件配置。
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import Boolean, DateTime, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class WecomGroupConfig(Base):
    """企微群运营配置表

    每条记录代表一个企微群的完整运营配置，包含：
    - 目标分群（来自 tx-growth 的 RFM 分层 ID）
    - 建群规则（最大成员数、是否自动邀请）
    - SOP 内容日历（JSONB，支持 daily/weekly/holiday/new_dish 类型）
    """

    __tablename__ = "wecom_group_configs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        nullable=False,
        comment="主键",
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        comment="租户 UUID（RLS 隔离键）",
    )

    # ── 群基本信息 ────────────────────────────────────────────────
    group_name: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        comment='群名称，如"高端海鲜VIP群"',
    )
    group_chat_id: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
        comment="企微群 chatid（建群后回填）",
    )

    # ── 目标分群 ──────────────────────────────────────────────────
    target_segment_id: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        comment="关联 tx-growth 分群 ID，如 rfm_champions",
    )
    target_store_ids: Mapped[list[Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        server_default="'[]'",
        comment="目标门店 UUID 列表（空数组=全部门店）",
    )

    # ── 建群规则 ──────────────────────────────────────────────────
    max_members: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=200,
        server_default="200",
        comment="最大群成员数（企微上限500，建议200以内便于运营）",
    )
    auto_invite: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default="true",
        comment="是否自动邀请符合分群条件的新会员",
    )

    # ── SOP 内容日历 ──────────────────────────────────────────────
    # 格式示例：
    # [
    #   {"type": "daily",   "time": "09:00", "content": "早安..."},
    #   {"type": "weekly",  "weekday": 5, "time": "17:00", "content": "周末..."},
    #   {"type": "holiday", "holiday": "spring_festival", "content": "新春..."},
    #   {"type": "new_dish","content": "新品上市：{dish_name}"},
    # ]
    sop_calendar: Mapped[list[Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        server_default="'[]'",
        comment="SOP 内容日历（JSONB），支持 daily/weekly/holiday/new_dish 类型",
    )

    # ── 状态 ──────────────────────────────────────────────────────
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="active",
        server_default="'active'",
        comment="active | paused | disbanded",
    )

    # ── 时间戳 ────────────────────────────────────────────────────
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        comment="创建时间",
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        comment="最后更新时间",
    )

    def __repr__(self) -> str:
        return f"<WecomGroupConfig id={self.id} name={self.group_name!r} status={self.status}>"


class WecomGroupMessage(Base):
    """企微群消息发送历史记录

    每次通过系统发送的群消息记录一条，用于：
    - SOP 执行频率统计
    - 消息发送成功/失败审计
    - 运营效果分析基础数据
    """

    __tablename__ = "wecom_group_messages"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        nullable=False,
        comment="主键",
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        comment="租户 UUID（RLS 隔离键）",
    )
    group_config_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        comment="关联的 WecomGroupConfig.id",
    )
    group_chat_id: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        comment="企微群 chatid",
    )

    # ── 消息内容 ──────────────────────────────────────────────────
    message_type: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        comment="text | image | news | miniapp",
    )
    content: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="消息内容（JSON 序列化字符串）",
    )
    sop_type: Mapped[str | None] = mapped_column(
        String(30),
        nullable=True,
        comment="daily | weekly | holiday | new_dish | manual",
    )

    # ── 发送状态 ──────────────────────────────────────────────────
    sent_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        comment="发送时间",
    )
    sent_by: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        default="system",
        server_default="'system'",
        comment="发送者：system 或员工的企微 userid",
    )
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="sent",
        comment="sent | failed",
    )
    error_msg: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="发送失败时的错误信息",
    )

    def __repr__(self) -> str:
        return (
            f"<WecomGroupMessage id={self.id} "
            f"group={self.group_chat_id!r} "
            f"type={self.sop_type!r} "
            f"status={self.status}>"
        )
