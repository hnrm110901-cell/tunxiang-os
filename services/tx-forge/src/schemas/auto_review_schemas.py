"""AI自动审核 Pydantic schemas"""

from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class AutoReviewRequest(BaseModel):
    app_id: str
    app_version_id: Optional[str] = None


class AutoReviewOut(BaseModel):
    review_id: UUID
    app_id: str
    auto_score: float
    auto_pass_count: int
    auto_fail_count: int
    total_checks: int
    auto_checks: List[Dict[str, Any]] = Field(default=[])
    ai_suggestions: List[str] = Field(default=[])
    human_required: bool = False
    duration_ms: int = 0

    model_config = {"from_attributes": True}


class ReviewTemplateOut(BaseModel):
    template_id: UUID
    app_category: str
    template_name: str
    pass_threshold: float
    is_active: bool = True

    model_config = {"from_attributes": True}
