"""结果计价 Pydantic schemas"""

from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class OutcomeDefinitionCreate(BaseModel):
    app_id: str
    outcome_type: str
    outcome_name: str
    description: str = ""
    measurement_method: str = "event_count"
    price_fen_per_outcome: int = 0
    attribution_window_hours: int = 24
    verification_method: str = "auto"


class OutcomeDefinitionOut(BaseModel):
    outcome_id: UUID
    app_id: str
    outcome_type: str
    outcome_name: str
    price_fen_per_outcome: int
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class OutcomeEventCreate(BaseModel):
    outcome_id: str
    app_id: str
    store_id: Optional[str] = None
    agent_id: Optional[str] = None
    decision_log_id: Optional[str] = None
    outcome_data: Dict[str, Any] = Field(default={})


class OutcomeEventOut(BaseModel):
    id: UUID
    outcome_id: str
    app_id: str
    store_id: Optional[str]
    agent_id: Optional[str]
    verified: bool
    revenue_fen: int
    created_at: datetime

    model_config = {"from_attributes": True}


class OutcomeVerify(BaseModel):
    verified: bool


class OutcomeDashboard(BaseModel):
    total_outcomes: int
    verified_outcomes: int
    total_revenue_fen: int
    by_type: List[Dict[str, Any]]
    daily_trend: List[Dict[str, Any]]
    top_agents: List[Dict[str, Any]]
