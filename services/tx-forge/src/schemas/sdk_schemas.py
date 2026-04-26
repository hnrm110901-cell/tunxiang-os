"""SDK / API Key Pydantic schemas"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class KeyCreate(BaseModel):
    developer_id: str
    key_name: str = Field(..., max_length=200)
    permissions: list[str] = Field(default=["read"])


class KeyOut(BaseModel):
    key_id: str
    key_name: str
    api_key_prefix: str
    permissions: list[str]
    status: str
    created_at: datetime

    model_config = {"from_attributes": True}
