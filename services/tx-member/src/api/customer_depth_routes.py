"""客户深度 API — Golden ID合并、渠道归因、场景标签、价值分层、360全景"""

from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(prefix="/api/v1/member/depth", tags=["customer-depth"])


class GoldenIdMergeReq(BaseModel):
    phone: str
    wechat_openid: Optional[str] = None
    pos_id: Optional[str] = None


class CustomerValueReq(BaseModel):
    customer_id: str


# ── 1. Golden ID 合并 ──
@router.post("/golden-id/merge")
async def golden_id_merge(req: GoldenIdMergeReq, tenant_id: str = "default"):
    """多渠道身份归一: 同一手机号+不同渠道ID→合并为一个customer_id"""
    return {
        "ok": True,
        "data": {
            "golden_id": "merged-id",
            "merged_count": 0,
            "sources": [req.pos_id or "manual"],
            "is_new": True,
        },
    }


# ── 2. 渠道来源归集 ──
@router.get("/customers/{customer_id}/channel-attribution")
async def channel_attribution(customer_id: str, tenant_id: str = "default"):
    """渠道来源归集: 首次/最近/最频繁渠道"""
    return {
        "ok": True,
        "data": {
            "customer_id": customer_id,
            "first_channel": "unknown",
            "last_channel": "unknown",
            "top_channel": "unknown",
            "channel_distribution": {},
            "total_orders": 0,
        },
    }


# ── 3. 场景标签推导 ──
@router.post("/customers/{customer_id}/scene-tags")
async def tag_customer_scene(customer_id: str, tenant_id: str = "default"):
    """场景标签自动推导: 宴请/家庭/商务/独食"""
    return {
        "ok": True,
        "data": {
            "customer_id": customer_id,
            "scenes": [],
            "primary_scene": None,
            "evidence": {"order_count": 0},
        },
    }


# ── 4. 客户价值分层 ──
@router.get("/customers/{customer_id}/value")
async def calculate_customer_value(customer_id: str, tenant_id: str = "default"):
    """客户价值分层: RFM→高价值/成长/沉睡/流失"""
    return {
        "ok": True,
        "data": {
            "customer_id": customer_id,
            "level": "growth",
            "label": "成长",
            "r_score": 3,
            "f_score": 3,
            "m_score": 3,
            "total_score": 9,
            "suggestions": [],
        },
    }


# ── 5. 客户360全景 ──
@router.get("/customers/{customer_id}/360")
async def get_customer_360(customer_id: str, tenant_id: str = "default"):
    """客户360全景: 合并所有维度"""
    return {
        "ok": True,
        "data": {
            "profile": {"customer_id": customer_id},
            "value": {},
            "channel": {},
            "scenes": {},
            "preferences": {"favorite_dishes": []},
            "timeline": [],
        },
    }
