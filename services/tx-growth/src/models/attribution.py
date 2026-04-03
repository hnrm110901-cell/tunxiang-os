"""归因数据模型 — 营销触达记录与ROI汇总

表：
  marketing_touches      — 每次营销触达记一条，追踪是否转化
  attribution_summaries  — 按活动维度聚合的归因汇总（每日快照）

金额单位：分(fen)
"""
import uuid
from datetime import date, datetime
from typing import Optional

from sqlalchemy import Boolean, Date, DateTime, Float, Index, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from shared.ontology.src.base import TenantBase


class MarketingTouch(TenantBase):
    """营销触达记录表

    每次向客户推送消息/优惠时写入一条。
    订单到来时回写 is_converted / order_id / order_amount_fen / converted_at。

    归因窗口（ATTRIBUTION_WINDOW_HOURS）内最近一次未转化的 touch 被选为归因来源。
    """

    __tablename__ = "marketing_touches"

    # ------------------------------------------------------------------
    # 客户关联
    # ------------------------------------------------------------------

    customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        comment="客户 UUID",
    )

    # ------------------------------------------------------------------
    # 来源信息
    # ------------------------------------------------------------------

    touch_type: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        comment="campaign | journey | referral | manual",
    )
    source_id: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        comment="来源ID：campaign_id / journey_id / referral_campaign_id",
    )
    source_name: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
        default="",
        comment="来源名称（冗余字段，避免关联查询）",
    )
    channel: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        comment="触达渠道：wecom | sms | miniapp | pos_receipt",
    )

    # ------------------------------------------------------------------
    # 内容信息
    # ------------------------------------------------------------------

    message_title: Mapped[Optional[str]] = mapped_column(
        String(200),
        nullable=True,
        comment="消息标题",
    )
    offer_id: Mapped[Optional[str]] = mapped_column(
        String(64),
        nullable=True,
        comment="附带的优惠券/活动ID",
    )

    # ------------------------------------------------------------------
    # 转化追踪
    # ------------------------------------------------------------------

    is_converted: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        comment="是否在归因窗口内产生订单",
    )
    order_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
        comment="归因的订单 UUID",
    )
    order_amount_fen: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True,
        comment="归因订单金额（分）",
    )
    converted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="转化（下单）时间",
    )

    # ------------------------------------------------------------------
    # 触达时间
    # ------------------------------------------------------------------

    touched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        comment="触达发生时间",
    )

    # ------------------------------------------------------------------
    # 索引
    # ------------------------------------------------------------------

    __table_args__ = (
        # 归因查询核心索引：按客户 + 触达时间倒序查最近触点
        Index(
            "idx_marketing_touches_customer_touched_at",
            "tenant_id",
            "customer_id",
            "touched_at",
        ),
        # 按来源汇总查询索引
        Index(
            "idx_marketing_touches_source",
            "tenant_id",
            "source_id",
            "touched_at",
        ),
        # 转化状态过滤索引
        Index(
            "idx_marketing_touches_converted",
            "tenant_id",
            "is_converted",
            "touched_at",
        ),
        {"comment": "营销触达记录表 — 每次推送/触达记一条，支持归因回写"},
    )


class AttributionSummary(TenantBase):
    """归因汇总表 — 按活动维度 + 日期聚合的 ROI 指标快照

    由后台任务每日更新，或在 _update_summary() 中实时累加。
    """

    __tablename__ = "attribution_summaries"

    # ------------------------------------------------------------------
    # 来源维度
    # ------------------------------------------------------------------

    source_type: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        comment="campaign | journey | referral",
    )
    source_id: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        comment="来源ID",
    )
    source_name: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
        default="",
        comment="来源名称（冗余）",
    )

    # ------------------------------------------------------------------
    # 日期维度
    # ------------------------------------------------------------------

    stat_date: Mapped[date] = mapped_column(
        Date,
        nullable=False,
        comment="统计日期（UTC）",
    )

    # ------------------------------------------------------------------
    # 触达指标
    # ------------------------------------------------------------------

    total_touches: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        comment="触达记录总数（含重复触达同一客户）",
    )
    unique_customers: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        comment="触达去重客户数",
    )

    # ------------------------------------------------------------------
    # 转化指标
    # ------------------------------------------------------------------

    converted_customers: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        comment="归因窗口内下单的客户数",
    )
    conversion_rate: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        default=0.0,
        comment="转化率 = converted_customers / unique_customers",
    )

    # ------------------------------------------------------------------
    # 收益与成本指标
    # ------------------------------------------------------------------

    attributed_revenue_fen: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        comment="归因收入（分）",
    )
    cost_fen: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        comment="发出的优惠总价值（分）",
    )
    roi: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        default=0.0,
        comment="ROI = (revenue - cost) / cost；cost=0 时为 0.0",
    )

    # ------------------------------------------------------------------
    # 归因模型
    # ------------------------------------------------------------------

    model: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="last_touch",
        comment="归因模型：last_touch | first_touch | linear",
    )

    # ------------------------------------------------------------------
    # 索引
    # ------------------------------------------------------------------

    __table_args__ = (
        # 按来源 + 日期查询（主要查询路径）
        Index(
            "idx_attribution_summaries_source_date",
            "tenant_id",
            "source_id",
            "stat_date",
        ),
        # 仪表盘按日期范围汇总
        Index(
            "idx_attribution_summaries_date",
            "tenant_id",
            "stat_date",
        ),
        # source_type 过滤（区分活动/旅程/裂变）
        Index(
            "idx_attribution_summaries_source_type",
            "tenant_id",
            "source_type",
            "stat_date",
        ),
        {"comment": "归因汇总表 — 按活动维度每日 ROI 指标快照"},
    )
