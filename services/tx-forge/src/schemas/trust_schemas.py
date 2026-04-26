"""信任治理 Pydantic schemas"""

from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field


class TrustAuditCreate(BaseModel):
    app_id: str
    requested_tier: str
    evidence: dict = Field(default={})


class TrustUpgradeRequest(BaseModel):
    target_tier: str
    evidence: dict = Field(default={})


class TrustStatusOut(BaseModel):
    app_id: str
    current_tier: str
    tier_name: str
    policy: "RuntimePolicyOut"
    recent_audits: list["TrustAuditOut"]
    violation_count_30d: int

    model_config = {"from_attributes": True}


class TrustAuditOut(BaseModel):
    audit_id: UUID
    app_id: str
    previous_tier: Optional[str]
    new_tier: str
    audit_type: str
    auditor_id: str
    reason: str
    audited_at: datetime

    model_config = {"from_attributes": True}


class RuntimePolicyOut(BaseModel):
    app_id: str
    trust_tier: str
    allowed_entities: list = Field(default=[])
    allowed_actions: list = Field(default=[])
    denied_actions: list = Field(default=[])
    token_budget_daily: int
    rate_limit_rpm: int
    kill_switch: bool
    sandbox_mode: bool

    model_config = {"from_attributes": True}


class RuntimePolicyUpdate(BaseModel):
    allowed_entities: Optional[list] = None
    allowed_actions: Optional[list] = None
    denied_actions: Optional[list] = None
    token_budget_daily: Optional[int] = None
    rate_limit_rpm: Optional[int] = None
    sandbox_mode: Optional[bool] = None


class KillSwitchRequest(BaseModel):
    reason: str


class ViolationOut(BaseModel):
    id: UUID
    app_id: str
    agent_id: Optional[str]
    violation_type: str
    severity: str
    context: dict = Field(default={})
    resolved: bool
    created_at: datetime

    model_config = {"from_attributes": True}


# Rebuild forward refs
TrustStatusOut.model_rebuild()
