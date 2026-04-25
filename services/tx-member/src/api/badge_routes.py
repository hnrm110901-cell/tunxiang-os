"""徽章 API — 8端点

/api/v1/member/badges
"""

from typing import Optional

from fastapi import APIRouter, Header, Query
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/v1/member/badges", tags=["badge-engine"])


# ─── Request / Response Models ───────────────────────────────────────────────


class CreateBadgeReq(BaseModel):
    name: str = Field(..., max_length=100)
    description: str = ""
    category: str = Field(..., description="loyalty/social/exploration/seasonal/milestone/secret")
    unlock_rule: dict = Field(default_factory=dict)
    rarity: str = "common"
    points_reward: int = 0
    icon_url: str = ""
    display_order: int = 0


class UpdateBadgeReq(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    category: Optional[str] = None
    unlock_rule: Optional[dict] = None
    rarity: Optional[str] = None
    points_reward: Optional[int] = None
    icon_url: Optional[str] = None
    display_order: Optional[int] = None
    is_active: Optional[bool] = None


class UnlockBadgeReq(BaseModel):
    customer_id: str
    badge_id: str
    context: dict = Field(default_factory=dict)


class EvaluateBadgesReq(BaseModel):
    customer_id: str


# ─── 内存存储（对齐项目现有模式，生产走DB） ──────────────────────────────────

_badge_store: dict[str, dict] = {}


# ─── 端点 ─────────────────────────────────────────────────────────────────────


@router.post("")
async def create_badge(
    req: CreateBadgeReq,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """1. 创建徽章定义"""
    import uuid

    badge_id = str(uuid.uuid4())
    badge = {
        "id": badge_id,
        "tenant_id": x_tenant_id,
        **req.model_dump(),
    }
    _badge_store[badge_id] = badge
    return {"ok": True, "data": badge}


@router.get("")
async def list_badges_api(
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    category: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
):
    """2. 列出徽章"""
    items = [
        b
        for b in _badge_store.values()
        if b["tenant_id"] == x_tenant_id and (not category or b.get("category") == category)
    ]
    start = (page - 1) * size
    return {"ok": True, "data": {"items": items[start : start + size], "total": len(items)}}


@router.get("/{badge_id}")
async def get_badge(
    badge_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """3. 获取徽章详情"""
    badge = _badge_store.get(badge_id)
    if not badge or badge["tenant_id"] != x_tenant_id:
        return {"ok": False, "error": {"code": "NOT_FOUND", "message": "badge not found"}}
    return {"ok": True, "data": badge}


@router.put("/{badge_id}")
async def update_badge(
    badge_id: str,
    req: UpdateBadgeReq,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """4. 更新徽章"""
    badge = _badge_store.get(badge_id)
    if not badge or badge["tenant_id"] != x_tenant_id:
        return {"ok": False, "error": {"code": "NOT_FOUND", "message": "badge not found"}}
    updates = {k: v for k, v in req.model_dump().items() if v is not None}
    badge.update(updates)
    return {"ok": True, "data": badge}


@router.delete("/{badge_id}")
async def delete_badge(
    badge_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """5. 删除徽章（软删除）"""
    badge = _badge_store.get(badge_id)
    if not badge or badge["tenant_id"] != x_tenant_id:
        return {"ok": False, "error": {"code": "NOT_FOUND", "message": "badge not found"}}
    badge["is_deleted"] = True
    return {"ok": True, "data": {"deleted": True}}


@router.post("/evaluate")
async def evaluate_badges_api(
    req: EvaluateBadgesReq,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """6. 评估顾客可解锁的徽章（冒烟模式：返回模拟数据）"""
    # 生产环境调用 badge_engine.evaluate_badges(db, tenant_id, customer_id)
    return {"ok": True, "data": {"customer_id": req.customer_id, "newly_unlocked": []}}


@router.get("/leaderboard/top")
async def badge_leaderboard(
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    limit: int = Query(20, ge=1, le=100),
):
    """7. 徽章排行榜"""
    # 生产环境调用 badge_engine.get_badge_leaderboard(db, tenant_id, limit)
    return {"ok": True, "data": {"items": [], "total": 0}}


@router.get("/{badge_id}/holders")
async def badge_holders(
    badge_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
):
    """8. 获取徽章持有者列表"""
    # 生产环境调用 badge_engine.get_badge_holders(db, tenant_id, badge_id, page, size)
    return {"ok": True, "data": {"items": [], "total": 0}}
