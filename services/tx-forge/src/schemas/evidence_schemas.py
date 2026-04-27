"""证据卡片 Pydantic schemas"""

from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class EvidenceCardCreate(BaseModel):
    app_id: str
    card_type: str
    title: str
    summary: str = ""
    evidence_data: Dict[str, Any] = Field(default={})
    score: Optional[float] = None
    verified_by: str = ""
    verification_method: str = "auto"
    expires_at: Optional[datetime] = None


class EvidenceCardOut(BaseModel):
    card_id: UUID
    app_id: str
    card_type: str
    title: str
    summary: str
    score: Optional[float]
    verified_by: str
    is_active: bool
    created_at: datetime
    expires_at: Optional[datetime]

    model_config = {"from_attributes": True}


class EvidenceCardUpdate(BaseModel):
    title: Optional[str] = None
    summary: Optional[str] = None
    evidence_data: Optional[Dict[str, Any]] = None
    score: Optional[float] = None
    is_active: Optional[bool] = None


class TrustProfile(BaseModel):
    app_id: str
    trust_score: float
    cards_by_type: Dict[str, List[Dict[str, Any]]]
    total_cards: int
    expired_cards: int
