"""生态健康指标 ORM"""

import datetime as dt
from typing import Optional

from sqlalchemy import Date, Integer, BigInteger, Numeric
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from shared.ontology.src.base import TenantBase


class ForgeEcosystemMetric(TenantBase):
    __tablename__ = "forge_ecosystem_metrics"

    metric_date: Mapped[dt.date] = mapped_column(Date, nullable=False)
    isv_active_rate: Mapped[Optional[float]] = mapped_column(Numeric(5, 2), default=0)
    product_quality_score: Mapped[Optional[float]] = mapped_column(Numeric(5, 2), default=0)
    install_density: Mapped[Optional[float]] = mapped_column(Numeric(5, 2), default=0)
    outcome_conversion_rate: Mapped[Optional[float]] = mapped_column(Numeric(5, 2), default=0)
    token_efficiency: Mapped[Optional[float]] = mapped_column(Numeric(10, 2), default=0)
    developer_nps: Mapped[int] = mapped_column(Integer, default=0)
    tthw_minutes: Mapped[int] = mapped_column(Integer, default=0)
    ecosystem_gmv_fen: Mapped[int] = mapped_column(BigInteger, default=0)
    composite_score: Mapped[Optional[float]] = mapped_column(Numeric(5, 2), default=0)
    details: Mapped[Optional[dict]] = mapped_column(JSONB, default=dict)
