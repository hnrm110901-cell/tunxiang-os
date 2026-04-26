"""智能发现 Pydantic schemas"""

from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class IntentSearchRequest(BaseModel):
    query: str


class IntentSearchResult(BaseModel):
    intents: List[str]
    apps: List[Dict[str, Any]]
    combos: List[Dict[str, Any]]
    search_id: str


class ComboCreate(BaseModel):
    combo_name: str
    description: str
    app_ids: List[str]
    use_case: str
    target_role: str = ""
    synergy_score: int = 0
    evidence: Dict[str, Any] = Field(default={})


class ComboOut(BaseModel):
    combo_id: UUID
    combo_name: str
    description: str
    app_ids: List[str]
    use_case: str
    target_role: str
    synergy_score: int
    install_count: int

    model_config = {"from_attributes": True}


class SearchClick(BaseModel):
    clicked_app_id: str
