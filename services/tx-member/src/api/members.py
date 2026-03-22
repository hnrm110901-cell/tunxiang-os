"""会员管理 API — Golden ID + RFM + 旅程"""
from typing import Optional
from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(prefix="/api/v1/member", tags=["member"])


class CreateMemberReq(BaseModel):
    phone: str
    display_name: Optional[str] = None
    source: str = "manual"


# Golden ID 会员
@router.get("/customers")
async def list_customers(store_id: str, rfm_level: Optional[str] = None, page: int = 1, size: int = 20):
    return {"ok": True, "data": {"items": [], "total": 0}}

@router.post("/customers")
async def create_customer(req: CreateMemberReq):
    return {"ok": True, "data": {"customer_id": "new"}}

@router.get("/customers/{customer_id}")
async def get_customer(customer_id: str):
    """Golden ID 360 度画像"""
    return {"ok": True, "data": None}

@router.get("/customers/{customer_id}/orders")
async def get_customer_orders(customer_id: str, page: int = 1, size: int = 20):
    return {"ok": True, "data": {"items": [], "total": 0}}

# RFM 分析
@router.get("/rfm/segments")
async def get_rfm_segments(store_id: str):
    """RFM 分层分布：S1-S5"""
    return {"ok": True, "data": {"segments": {}}}

@router.get("/rfm/at-risk")
async def get_at_risk_customers(store_id: str, risk_threshold: float = 0.5):
    """流失风险客户列表"""
    return {"ok": True, "data": {"customers": []}}

# 营销活动
@router.get("/campaigns")
async def list_campaigns(store_id: str):
    return {"ok": True, "data": {"campaigns": []}}

@router.post("/campaigns")
async def create_campaign(data: dict):
    return {"ok": True, "data": {"campaign_id": "new"}}

@router.post("/campaigns/{campaign_id}/trigger")
async def trigger_campaign(campaign_id: str):
    return {"ok": True, "data": {"triggered": True}}

# 用户旅程
@router.get("/journeys")
async def list_journeys(store_id: str, status: Optional[str] = None):
    return {"ok": True, "data": {"journeys": []}}

@router.post("/journeys/trigger")
async def trigger_journey(customer_id: str, journey_type: str):
    return {"ok": True, "data": {"journey_id": "new"}}

# 身份合并
@router.post("/customers/merge")
async def merge_customers(primary_id: str, secondary_id: str):
    """Golden ID 合并"""
    return {"ok": True, "data": {"merged_into": primary_id}}
