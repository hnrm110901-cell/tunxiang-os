"""顾客评价管理 API — 提交/查询/商家回复/统计"""
from datetime import datetime, timedelta
from typing import Optional, List
from uuid import uuid4
import random

import structlog
from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel

log = structlog.get_logger()
router = APIRouter(prefix="/api/v1/trade/reviews", tags=["reviews"])


class ReviewCreate(BaseModel):
    order_id: str
    overall_rating: int              # 1-5
    sub_ratings: dict                # {food: 4, service: 5, environment: 4, speed: 3}
    content: Optional[str] = None
    tags: List[str] = []
    image_urls: List[str] = []
    is_anonymous: bool = False


class MerchantReply(BaseModel):
    content: str


# Mock数据
MOCK_REVIEWS = [
    {
        "id": "rev001", "order_id": "ord-001", "store_name": "五一广场店",
        "customer_name": "张*", "is_anonymous": False,
        "overall_rating": 5,
        "sub_ratings": {"food": 5, "service": 5, "environment": 4, "speed": 5},
        "content": "菜品非常鲜美，尤其是椒盐虾，外酥里嫩，服务员也很热情！强烈推荐！",
        "tags": ["味道棒极了", "服务热情", "会再来"],
        "image_urls": [],
        "merchant_reply": "感谢您的好评！椒盐虾是我们的招牌菜，欢迎您下次再来😊",
        "merchant_replied_at": "2026-04-02T10:30:00Z",
        "created_at": "2026-04-02T09:00:00Z",
        "status": "published",
    },
    {
        "id": "rev002", "order_id": "ord-002", "store_name": "东塘店",
        "customer_name": "匿名用户", "is_anonymous": True,
        "overall_rating": 3,
        "sub_ratings": {"food": 4, "service": 3, "environment": 3, "speed": 2},
        "content": "食物不错，但等待时间有点长，上菜慢。",
        "tags": ["上菜慢"],
        "image_urls": [],
        "merchant_reply": None,
        "merchant_replied_at": None,
        "created_at": "2026-04-02T12:30:00Z",
        "status": "published",
    },
    {
        "id": "rev003", "order_id": "ord-003", "store_name": "五一广场店",
        "customer_name": "李*", "is_anonymous": False,
        "overall_rating": 4,
        "sub_ratings": {"food": 5, "service": 4, "environment": 4, "speed": 4},
        "content": "整体很好，食材新鲜，价格实惠，性价比很高！",
        "tags": ["性价比高", "分量充足"],
        "image_urls": [],
        "merchant_reply": None,
        "merchant_replied_at": None,
        "created_at": "2026-04-01T18:00:00Z",
        "status": "published",
    },
    {
        "id": "rev004", "order_id": "ord-004", "store_name": "河西万达店",
        "customer_name": "王*", "is_anonymous": False,
        "overall_rating": 2,
        "sub_ratings": {"food": 2, "service": 2, "environment": 3, "speed": 2},
        "content": "这次体验很差，菜品咸了，服务员态度也不好，不会再来了。",
        "tags": [],
        "image_urls": [],
        "merchant_reply": None,
        "merchant_replied_at": None,
        "created_at": "2026-04-01T19:30:00Z",
        "status": "pending_review",  # 差评需要人工审核
    },
]


@router.get("")
async def list_reviews(
    store_id: Optional[str] = Query(None),
    rating_filter: Optional[int] = Query(None, description="1-5星筛选"),
    status: Optional[str] = Query(None),
    has_image: Optional[bool] = Query(None),
    replied: Optional[bool] = Query(None),
    page: int = Query(1),
    size: int = Query(20),
    x_tenant_id: str = Header("demo-tenant", alias="X-Tenant-ID"),
):
    """评价列表（管理端）"""
    items = MOCK_REVIEWS
    if rating_filter:
        items = [r for r in items if r["overall_rating"] == rating_filter]
    if status:
        items = [r for r in items if r["status"] == status]
    if has_image is not None:
        items = [r for r in items if bool(r["image_urls"]) == has_image]
    if replied is not None:
        items = [r for r in items if (r["merchant_reply"] is not None) == replied]

    total = len(items)
    avg = sum(r["overall_rating"] for r in MOCK_REVIEWS) / len(MOCK_REVIEWS)
    positive = sum(1 for r in MOCK_REVIEWS if r["overall_rating"] >= 4)
    return {
        "ok": True,
        "data": {
            "items": items[:size],
            "total": total,
            "avg_rating": round(avg, 1),
            "positive_rate": round(positive / len(MOCK_REVIEWS) * 100, 1),
            "unreplied_count": sum(1 for r in MOCK_REVIEWS if not r["merchant_reply"]),
            "_is_mock": True,
        }
    }


@router.post("")
async def create_review(
    body: ReviewCreate,
    x_tenant_id: str = Header("demo-tenant", alias="X-Tenant-ID"),
):
    """顾客提交评价"""
    new_id = f"rev{uuid4().hex[:6]}"
    log.info("review.create", review_id=new_id, rating=body.overall_rating, order_id=body.order_id)
    return {
        "ok": True,
        "data": {
            "id": new_id,
            "order_id": body.order_id,
            "overall_rating": body.overall_rating,
            "status": "published" if body.overall_rating >= 3 else "pending_review",
            "_is_mock": True,
        }
    }


@router.post("/{review_id}/reply")
async def merchant_reply(
    review_id: str,
    body: MerchantReply,
    x_tenant_id: str = Header("demo-tenant", alias="X-Tenant-ID"),
):
    """商家回复评价"""
    log.info("review.reply", review_id=review_id)
    return {
        "ok": True,
        "data": {
            "id": review_id,
            "merchant_reply": body.content,
            "merchant_replied_at": datetime.utcnow().isoformat(),
            "_is_mock": True,
        }
    }


@router.post("/{review_id}/hide")
async def hide_review(
    review_id: str,
    x_tenant_id: str = Header("demo-tenant", alias="X-Tenant-ID"),
):
    """隐藏/屏蔽评价（违规内容）"""
    log.info("review.hide", review_id=review_id)
    return {"ok": True, "data": {"id": review_id, "status": "hidden", "_is_mock": True}}


@router.get("/stats")
async def review_stats(
    days: int = Query(30),
    x_tenant_id: str = Header("demo-tenant", alias="X-Tenant-ID"),
):
    """评价统计"""
    return {
        "ok": True,
        "data": {
            "avg_rating": 3.9,
            "total_reviews": len(MOCK_REVIEWS),
            "rating_distribution": {
                "5": 35, "4": 28, "3": 20, "2": 10, "1": 7
            },
            "sub_rating_avg": {
                "food": 4.2, "service": 3.8, "environment": 3.7, "speed": 3.5
            },
            "positive_rate": 62.5,
            "unreplied_count": 2,
            "top_tags": [
                {"tag": "味道棒极了", "count": 45},
                {"tag": "服务热情", "count": 32},
                {"tag": "性价比高", "count": 28},
                {"tag": "分量充足", "count": 21},
                {"tag": "会再来", "count": 18},
            ],
            "_is_mock": True,
        }
    }
