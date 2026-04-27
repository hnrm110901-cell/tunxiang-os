"""生态健康 Pydantic schemas"""

from datetime import date
from typing import Dict

from pydantic import BaseModel, Field


class EcosystemMetricsOut(BaseModel):
    metric_date: date
    isv_active_rate: float = 0.0
    product_quality_score: float = 0.0
    install_density: float = 0.0
    outcome_conversion_rate: float = 0.0
    token_efficiency: float = 0.0
    developer_nps: float = 0.0
    tthw_minutes: float = 0.0
    ecosystem_gmv_fen: int = 0
    composite_score: float = 0.0

    model_config = {"from_attributes": True}


class FlywheelStatus(BaseModel):
    current: EcosystemMetricsOut
    previous: EcosystemMetricsOut
    trends: Dict[str, float] = Field(default={})
