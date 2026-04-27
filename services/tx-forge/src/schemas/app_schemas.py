"""应用 Pydantic schemas"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class AppSubmit(BaseModel):
    developer_id: str
    app_name: str = Field(..., max_length=200)
    category: str = Field(..., max_length=50)
    description: str
    version: str = Field(..., max_length=30)
    icon_url: str = Field(default="")
    screenshots: list[str] = Field(default=[])
    pricing_model: str = Field(default="free")
    price_fen: int = Field(default=0)
    permissions: list[str] = Field(default=[])
    api_endpoints: list[str] = Field(default=[])
    webhook_urls: list[str] = Field(default=[])


class AppUpdate(BaseModel):
    app_name: Optional[str] = Field(default=None, max_length=200)
    description: Optional[str] = Field(default=None)
    icon_url: Optional[str] = Field(default=None)
    screenshots: Optional[list[str]] = Field(default=None)
    pricing_model: Optional[str] = Field(default=None)
    price_fen: Optional[int] = Field(default=None)
    permissions: Optional[list[str]] = Field(default=None)
    api_endpoints: Optional[list[str]] = Field(default=None)
    webhook_urls: Optional[list[str]] = Field(default=None)


class AppOut(BaseModel):
    app_id: str
    developer_id: str
    app_name: str
    category: str
    description: str
    icon_url: str
    screenshots: list[str]
    pricing_model: str
    price_fen: int
    price_display: str
    permissions: list[str]
    api_endpoints: list[str]
    webhook_urls: list[str]
    status: str
    current_version: str
    rating: Optional[float]
    rating_count: int
    install_count: int
    revenue_total_fen: int
    published_at: Optional[datetime]
    created_at: datetime

    model_config = {"from_attributes": True}
