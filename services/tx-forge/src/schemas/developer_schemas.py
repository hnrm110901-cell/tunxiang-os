"""开发者 Pydantic schemas"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class DeveloperCreate(BaseModel):
    name: str = Field(..., max_length=200)
    email: str = Field(..., max_length=200)
    company: str = Field(..., max_length=200)
    dev_type: str = Field(..., max_length=20)
    description: str = Field(default="")


class DeveloperUpdate(BaseModel):
    name: Optional[str] = Field(default=None, max_length=200)
    email: Optional[str] = Field(default=None, max_length=200)
    company: Optional[str] = Field(default=None, max_length=200)
    description: Optional[str] = Field(default=None)


class DeveloperOut(BaseModel):
    developer_id: str
    name: str
    email: str
    company: str
    dev_type: str
    status: str
    created_at: datetime
    app_count: Optional[int] = Field(default=None)
    total_installs: Optional[int] = Field(default=None)

    model_config = {"from_attributes": True}
