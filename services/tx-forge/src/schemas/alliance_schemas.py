"""跨品牌联盟 Pydantic schemas"""

from typing import Any, Dict, List
from uuid import UUID

from pydantic import BaseModel, Field


class AllianceListingCreate(BaseModel):
    app_id: str
    sharing_mode: str = "invited"
    shared_tenants: List[str] = Field(default=[])
    revenue_share_rate: float = 0.7


class AllianceListingOut(BaseModel):
    listing_id: UUID
    app_id: str
    owner_tenant_id: str
    sharing_mode: str
    revenue_share_rate: float
    install_count: int = 0
    total_revenue_fen: int = 0
    is_active: bool = True

    model_config = {"from_attributes": True}


class AllianceRevenueOut(BaseModel):
    total_revenue_fen: int = 0
    owner_share_fen: int = 0
    platform_share_fen: int = 0
    transactions: List[Dict[str, Any]] = Field(default=[])
