"""宴会AI决策 + KPI ORM模型"""
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Optional
from sqlalchemy import Boolean, Date, Index, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column
from shared.ontology.src.base import TenantBase

class BanquetAIDecision(TenantBase):
    __tablename__ = "banquet_ai_decisions"
    store_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    banquet_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    agent_type: Mapped[str] = mapped_column(String(30), nullable=False, comment="pricing/operations/growth")
    decision_type: Mapped[str] = mapped_column(String(30), nullable=False)
    input_context_json: Mapped[dict] = mapped_column(JSON, default=dict)
    recommendation_json: Mapped[dict] = mapped_column(JSON, default=dict)
    reasoning: Mapped[Optional[str]] = mapped_column(Text)
    confidence: Mapped[Decimal] = mapped_column(Numeric(3, 2), default=Decimal("0"))
    accepted: Mapped[Optional[bool]] = mapped_column(Boolean)
    accepted_at: Mapped[Optional[datetime]] = mapped_column()
    operator_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    operator_feedback: Mapped[Optional[str]] = mapped_column(Text)
    execution_ms: Mapped[int] = mapped_column(Integer, default=0)
    __table_args__ = (Index("idx_bad_tenant", "tenant_id", "agent_type"), {"comment": "AI决策日志"})
    def to_dict(self) -> dict:
        return {"id": str(self.id), "agent_type": self.agent_type, "decision_type": self.decision_type, "recommendation_json": self.recommendation_json, "reasoning": self.reasoning, "confidence": float(self.confidence), "accepted": self.accepted, "created_at": self.created_at.isoformat() if self.created_at else None}

class BanquetDemandForecast(TenantBase):
    __tablename__ = "banquet_demand_forecasts"
    store_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    forecast_month: Mapped[str] = mapped_column(String(7), nullable=False, comment="YYYY-MM")
    event_type: Mapped[str] = mapped_column(String(30), nullable=False)
    predicted_count: Mapped[int] = mapped_column(Integer, default=0)
    predicted_revenue_fen: Mapped[int] = mapped_column(Integer, default=0)
    actual_count: Mapped[Optional[int]] = mapped_column(Integer)
    actual_revenue_fen: Mapped[Optional[int]] = mapped_column(Integer)
    accuracy_pct: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 2))
    factors_json: Mapped[dict] = mapped_column(JSON, default=dict)
    model_version: Mapped[str] = mapped_column(String(20), default="v1")
    __table_args__ = (Index("idx_bdf_store", "tenant_id", "store_id", "forecast_month"), {"comment": "需求预测"})
    def to_dict(self) -> dict:
        return {"id": str(self.id), "store_id": str(self.store_id), "forecast_month": self.forecast_month, "event_type": self.event_type, "predicted_count": self.predicted_count, "predicted_revenue_fen": self.predicted_revenue_fen, "actual_count": self.actual_count, "accuracy_pct": float(self.accuracy_pct) if self.accuracy_pct else None}

class BanquetKPISnapshot(TenantBase):
    __tablename__ = "banquet_kpi_snapshots"
    store_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    period: Mapped[str] = mapped_column(String(10), nullable=False, comment="daily/weekly/monthly")
    period_date: Mapped[date] = mapped_column(Date, nullable=False)
    leads_count: Mapped[int] = mapped_column(Integer, default=0)
    conversion_rate: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=Decimal("0"))
    bookings_count: Mapped[int] = mapped_column(Integer, default=0)
    revenue_fen: Mapped[int] = mapped_column(Integer, default=0)
    avg_per_table_fen: Mapped[int] = mapped_column(Integer, default=0)
    avg_guest_count: Mapped[int] = mapped_column(Integer, default=0)
    top_event_type: Mapped[Optional[str]] = mapped_column(String(30))
    venue_utilization_rate: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=Decimal("0"))
    customer_satisfaction: Mapped[Decimal] = mapped_column(Numeric(3, 1), default=Decimal("0"))
    repeat_rate: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=Decimal("0"))
    total_tables: Mapped[int] = mapped_column(Integer, default=0)
    total_guests: Mapped[int] = mapped_column(Integer, default=0)
    cancellation_rate: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=Decimal("0"))
    food_cost_rate: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=Decimal("0"))
    __table_args__ = (Index("idx_bks_store", "tenant_id", "store_id", "period_date"), {"comment": "宴会KPI"})
    def to_dict(self) -> dict:
        return {"id": str(self.id), "store_id": str(self.store_id), "period": self.period, "period_date": self.period_date.isoformat(), "leads_count": self.leads_count, "conversion_rate": float(self.conversion_rate), "bookings_count": self.bookings_count, "revenue_fen": self.revenue_fen, "avg_per_table_fen": self.avg_per_table_fen, "customer_satisfaction": float(self.customer_satisfaction), "repeat_rate": float(self.repeat_rate)}

class BanquetCompetitiveBenchmark(TenantBase):
    __tablename__ = "banquet_competitive_benchmarks"
    store_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    period: Mapped[str] = mapped_column(String(10), nullable=False)
    period_date: Mapped[date] = mapped_column(Date, nullable=False)
    metric_name: Mapped[str] = mapped_column(String(50), nullable=False)
    store_value: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0"))
    brand_avg: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0"))
    brand_best: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0"))
    rank: Mapped[int] = mapped_column(Integer, default=0)
    percentile: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=Decimal("0"))
    trend: Mapped[str] = mapped_column(String(10), default="flat")
    __table_args__ = (Index("idx_bcb_store", "tenant_id", "store_id", "period_date"), {"comment": "跨店对标"})
    def to_dict(self) -> dict:
        return {"id": str(self.id), "store_id": str(self.store_id), "metric_name": self.metric_name, "store_value": float(self.store_value), "brand_avg": float(self.brand_avg), "brand_best": float(self.brand_best), "rank": self.rank, "percentile": float(self.percentile), "trend": self.trend}
