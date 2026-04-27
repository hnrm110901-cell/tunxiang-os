"""裂变拉新数据模型 — 邀请有礼（老带新）

表：
  referral_campaigns  — 裂变活动配置
  referral_records    — 邀请记录（每条对应一个邀请链接）

金额单位：分(fen)
"""

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from shared.ontology.src.base import TenantBase


class ReferralCampaign(TenantBase):
    """裂变活动配置表

    状态机: draft -> active -> paused -> ended
    """

    __tablename__ = "referral_campaigns"

    # 基本信息
    name: Mapped[str] = mapped_column(String(100), nullable=False, comment="活动名称，如：春节邀友活动")
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="draft",
        comment="draft|active|paused|ended",
    )

    # 邀请方奖励（老会员）
    referrer_reward_type: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="coupon",
        comment="coupon|points|stored_value",
    )
    referrer_reward_value: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        comment="优惠券ID(coupon) / 积分数(points) / 储值分(stored_value, 整数分)",
    )
    referrer_reward_condition: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="first_order",
        comment="new_register=新人注册即得 | first_order=新人首单才得",
    )

    # 被邀请方奖励（新用户，注册即得）
    invitee_reward_type: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="coupon",
        comment="coupon|points|stored_value",
    )
    invitee_reward_value: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        comment="优惠券ID(coupon) / 积分数(points) / 储值分(stored_value, 整数分)",
    )

    # 限制条件
    max_referrals_per_user: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        comment="每人最多邀请N人，0=不限",
    )
    min_order_amount_fen: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        comment="新人首单最低金额(分)，0=不限",
    )
    valid_days: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=30,
        comment="邀请链接有效天数",
    )

    # 防刷开关
    anti_fraud_same_device: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        comment="同设备限制：同一 campaign 内同设备ID只能被邀请一次",
    )
    anti_fraud_same_ip: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        comment="同IP限制（移动端不可靠，默认关闭）",
    )
    anti_fraud_same_phone_prefix: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        comment="同手机前7位限制：同一 campaign 内相同前缀只能注册一次",
    )

    # 时效
    valid_from: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        comment="活动开始时间",
    )
    valid_until: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="活动结束时间，NULL=永久有效",
    )

    __table_args__ = (
        Index("idx_referral_campaigns_tenant_status", "tenant_id", "status"),
        {"comment": "裂变活动配置表"},
    )


class ReferralRecord(TenantBase):
    """邀请记录表

    每次老会员生成邀请链接产生一条 pending 记录。
    新用户通过链接注册后填入 invitee 信息，状态流转：
      pending -> registered -> rewarded
      pending -> expired
      pending/registered -> fraud_detected
    """

    __tablename__ = "referral_records"

    # 关联
    campaign_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("referral_campaigns.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
        comment="所属裂变活动",
    )
    referrer_customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        index=True,
        comment="邀请人（老会员）客户ID",
    )
    invitee_customer_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
        index=True,
        comment="被邀请人（新用户）客户ID，注册后填入",
    )

    # 邀请码与链接
    invite_code: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        unique=True,
        comment="唯一邀请码（8位大写字母数字）",
    )
    invite_url: Mapped[str] = mapped_column(
        String(500),
        nullable=False,
        comment="完整邀请链接",
    )

    # 状态
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="pending",
        comment="pending|registered|rewarded|fraud_detected|expired",
    )

    # 时间戳
    invited_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        comment="邀请链接生成时间",
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        comment="邀请链接过期时间（invited_at + valid_days）",
    )
    registered_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="新用户注册时间",
    )
    first_order_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="新用户首单完成时间",
    )
    rewarded_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="奖励发放时间（最近一次）",
    )

    # 防刷记录
    invitee_device_id: Mapped[Optional[str]] = mapped_column(
        String(128),
        nullable=True,
        comment="被邀请人设备ID（小程序 device_id）",
    )
    invitee_ip: Mapped[Optional[str]] = mapped_column(
        String(64),
        nullable=True,
        comment="被邀请人注册时IP地址",
    )
    invitee_phone: Mapped[Optional[str]] = mapped_column(
        String(20),
        nullable=True,
        comment="被邀请人手机号（用于前7位防刷）",
    )

    # 奖励发放状态
    referrer_rewarded: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        comment="邀请人是否已获奖",
    )
    invitee_rewarded: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        comment="被邀请人是否已获奖",
    )

    __table_args__ = (
        # 邀请码唯一（已由 unique=True 保证，此处建复合查询索引）
        Index("idx_referral_records_campaign_referrer", "campaign_id", "referrer_customer_id"),
        Index("idx_referral_records_device_campaign", "invitee_device_id", "campaign_id"),
        Index("idx_referral_records_invitee", "invitee_customer_id", "campaign_id"),
        Index("idx_referral_records_tenant_status", "tenant_id", "status"),
        {"comment": "邀请记录表（每条对应一个邀请链接）"},
    )
