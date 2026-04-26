"""AI 运维 Pydantic schemas"""

from datetime import datetime, date
from typing import Optional

from pydantic import BaseModel, Field


class AgentStatus(BaseModel):
    agent_id: str
    agent_name: str
    priority: str
    status: str
    total_decisions_7d: int
    avg_confidence: float
    avg_execution_ms: float


class TraceOut(BaseModel):
    session_id: str
    agent_template_name: str
    status: str
    total_tokens: int
    total_cost_fen: int
    started_at: datetime
    finished_at: Optional[datetime]


class DecisionOut(BaseModel):
    agent_id: str
    decision_type: str
    reasoning: str
    confidence: float
    execution_ms: float
    constraints_check: dict
    decided_at: datetime


class ModelStats(BaseModel):
    model: str
    calls: int
    avg_latency_ms: float
    total_tokens: int
    total_cost_usd: float
    success_rate: float


class LlmCostEntry(BaseModel):
    date: date
    model: str
    task_type: str
    calls: int
    cost_usd: float
    tokens: int
