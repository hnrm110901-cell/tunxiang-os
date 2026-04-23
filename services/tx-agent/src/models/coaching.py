"""AI运营教练 — Phase S3 ORM模型

表：sop_coaching_logs / store_baselines
"""
import uuid
from datetime import date, datetime
from typing import Optional

from sqlalchemy import Boolean, Date, DateTime, Float, Integer, Text, func
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from shared.ontology.src.base import TenantBase


# ─────────────────────────────────────────────
# sop_coaching_logs — AI教练决策日志
# ─────────────────────────────────────────────
class SOPCoachingLog(TenantBase):
    """AI教练决策日志 — 记录每次教练推送的上下文、建议和反馈

    coaching_type:
      - morning_brief: 晨会简报（09:30推送）
      - peak_alert: 高峰预警（正常不说，异常论述）
      - post_rush_review: 复盘分析（午后/晚后）
      - closing_summary: 闭店日报（21:00-23:00推送）
    """

    __tablename__ = "sop_coaching_logs"

    store_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, comment="门店ID",
    )
    user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), nullable=True, comment="接收教练推送的用户ID",
    )
    coaching_type: Mapped[str] = mapped_column(
        Text, nullable=False,
        comment="教练类型：morning_brief / peak_alert / post_rush_review / closing_summary",
    )
    slot_code: Mapped[str] = mapped_column(
        Text, nullable=False,
        comment="关联时段代码（如lunch_peak/dinner_peak/closing）",
    )
    coaching_date: Mapped[date] = mapped_column(
        Date, nullable=False, comment="教练日期",
    )
    context_snapshot: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default="{}",
        comment="当时的业务上下文快照",
    )
    memories_used: Mapped[Optional[list]] = mapped_column(
        ARRAY(UUID(as_uuid=True)), nullable=True,
        comment="本次教练使用的记忆ID列表",
    )
    recommendations: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default="{}",
        comment="教练生成的建议内容",
    )
    user_feedback: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True,
        comment="用户反馈：helpful / not_helpful / ignored",
    )
    feedback_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="反馈时间",
    )


# ─────────────────────────────────────────────
# store_baselines — 门店基线（异常检测基准）
# ─────────────────────────────────────────────
class StoreBaseline(TenantBase):
    """门店基线 — 各指标的历史均值和标准差

    metric_code 枚举：
      lunch_covers / dinner_covers / food_cost_rate / labor_cost_rate /
      avg_ticket_fen / table_turnover / serve_time_min / waste_rate /
      takeout_count / customer_complaints

    异常检测阈值：
      > 2σ = warning（黄色预警）
      > 3σ = critical（红色预警）
    """

    __tablename__ = "store_baselines"

    store_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, comment="门店ID",
    )
    metric_code: Mapped[str] = mapped_column(
        Text, nullable=False,
        comment="指标代码：lunch_covers / dinner_covers / food_cost_rate 等",
    )
    day_of_week: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True,
        comment="星期几(0=周一..6=周日)，NULL表示不区分",
    )
    slot_code: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True, comment="时段代码，NULL表示全天",
    )
    baseline_value: Mapped[float] = mapped_column(
        Float, nullable=False, comment="基线值（历史均值）",
    )
    std_deviation: Mapped[float] = mapped_column(
        Float, nullable=False, comment="标准差",
    )
    sample_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0",
        comment="样本数量",
    )
    min_value: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True, comment="历史最小值",
    )
    max_value: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True, comment="历史最大值",
    )
    last_updated: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
        comment="最后更新时间",
    )
