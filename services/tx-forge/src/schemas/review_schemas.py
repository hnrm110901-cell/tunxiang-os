"""审核 Pydantic schemas"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class ReviewCreate(BaseModel):
    app_id: str
    reviewer_id: str
    decision: str
    review_notes: str = Field(default="")


class ReviewOut(BaseModel):
    review_id: str
    app_id: str
    reviewer_id: str
    decision: str
    review_notes: str
    reviewed_at: datetime

    model_config = {"from_attributes": True}
