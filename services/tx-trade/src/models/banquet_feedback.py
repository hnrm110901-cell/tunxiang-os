"""宴会售后 ORM模型"""

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column

from shared.ontology.src.base import TenantBase


class BanquetFeedback(TenantBase):
    __tablename__ = "banquet_feedbacks"
    banquet_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    customer_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    customer_name: Mapped[Optional[str]] = mapped_column(String(100))
    customer_phone: Mapped[Optional[str]] = mapped_column(String(20))
    overall_score: Mapped[int] = mapped_column(Integer, nullable=False, comment="1-5")
    food_score: Mapped[int] = mapped_column(Integer, default=0)
    service_score: Mapped[int] = mapped_column(Integer, default=0)
    venue_score: Mapped[int] = mapped_column(Integer, default=0)
    value_score: Mapped[int] = mapped_column(Integer, default=0)
    comments: Mapped[Optional[str]] = mapped_column(Text)
    highlights: Mapped[dict] = mapped_column(JSON, default=list)
    improvement_suggestions: Mapped[Optional[str]] = mapped_column(Text)
    would_recommend: Mapped[bool] = mapped_column(Boolean, default=True)
    photos_json: Mapped[dict] = mapped_column(JSON, default=list)
    replied_at: Mapped[Optional[datetime]] = mapped_column()
    reply_content: Mapped[Optional[str]] = mapped_column(Text)
    replied_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    __table_args__ = (Index("idx_bf_banquet", "tenant_id", "banquet_id"), {"comment": "宴会评价"})

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "banquet_id": str(self.banquet_id),
            "customer_name": self.customer_name,
            "overall_score": self.overall_score,
            "food_score": self.food_score,
            "service_score": self.service_score,
            "venue_score": self.venue_score,
            "comments": self.comments,
            "would_recommend": self.would_recommend,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class BanquetReferral(TenantBase):
    __tablename__ = "banquet_referrals"
    referrer_banquet_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    referrer_name: Mapped[Optional[str]] = mapped_column(String(100))
    referrer_phone: Mapped[Optional[str]] = mapped_column(String(20))
    referred_lead_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    referred_name: Mapped[Optional[str]] = mapped_column(String(100))
    referred_phone: Mapped[Optional[str]] = mapped_column(String(20))
    referrer_reward_type: Mapped[str] = mapped_column(String(30), default="coupon")
    referrer_reward_value_fen: Mapped[int] = mapped_column(Integer, default=0)
    referrer_reward_issued: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    converted_at: Mapped[Optional[datetime]] = mapped_column()
    rewarded_at: Mapped[Optional[datetime]] = mapped_column()
    __table_args__ = (Index("idx_br_referrer", "tenant_id", "referrer_banquet_id"), {"comment": "转介绍"})

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "referrer_banquet_id": str(self.referrer_banquet_id),
            "referrer_name": self.referrer_name,
            "referred_name": self.referred_name,
            "referrer_reward_type": self.referrer_reward_type,
            "referrer_reward_value_fen": self.referrer_reward_value_fen,
            "status": self.status,
        }
