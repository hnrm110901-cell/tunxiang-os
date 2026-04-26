"""Token计量 Pydantic schemas"""

from typing import Optional

from pydantic import BaseModel


class TokenUsageRecord(BaseModel):
    app_id: str
    input_tokens: int
    output_tokens: int
    cost_fen: int = 0


class TokenUsageOut(BaseModel):
    app_id: str
    period_type: str
    period_key: str
    input_tokens: int
    output_tokens: int
    total_tokens: int
    cost_fen: int
    budget_fen: int
    usage_pct: float

    model_config = {"from_attributes": True}


class TokenPricing(BaseModel):
    app_id: str
    input_price_per_1k_fen: int
    output_price_per_1k_fen: int
    markup_rate: float = 0.0


class TokenAlert(BaseModel):
    app_id: str
    period_key: str
    total_tokens: int
    budget_fen: int
    usage_pct: float
    alert_threshold: float

    model_config = {"from_attributes": True}
