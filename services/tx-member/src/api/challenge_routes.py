"""挑战 API — 8端点

/api/v1/member/challenges
"""

from typing import Optional

from fastapi import APIRouter, Header, Query
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/v1/member/challenges", tags=["challenge-engine"])


# ─── Request / Response Models ───────────────────────────────────────────────


class CreateChallengeReq(BaseModel):
    name: str = Field(..., max_length=100)
    description: str = ""
    type: str = Field(
        ...,
        description="visit_streak/spend_target/dish_explorer/social_share/referral_drive/seasonal_event/time_limited/combo_quest",
    )
    rules: dict = Field(default_factory=dict)
    reward: dict = Field(default_factory=dict)
    badge_id: Optional[str] = None
    start_date: str = Field(..., description="ISO datetime")
    end_date: str = Field(..., description="ISO datetime")
    max_participants: int = 0
    icon_url: str = ""
    display_order: int = 0


class UpdateChallengeReq(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    rules: Optional[dict] = None
    reward: Optional[dict] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    max_participants: Optional[int] = None
    is_active: Optional[bool] = None
    icon_url: Optional[str] = None
    display_order: Optional[int] = None


class JoinChallengeReq(BaseModel):
    customer_id: str
    challenge_id: str


class UpdateProgressReq(BaseModel):
    customer_id: str
    challenge_id: str
    increment: int = 1
    detail: dict = Field(default_factory=dict)


class ClaimRewardReq(BaseModel):
    customer_id: str
    challenge_id: str


# ─── 内存存储 ────────────────────────────────────────────────────────────────

_challenge_store: dict[str, dict] = {}
_progress_store: dict[str, dict] = {}  # key: f"{customer_id}:{challenge_id}"


# ─── 端点 ─────────────────────────────────────────────────────────────────────


@router.post("")
async def create_challenge(
    req: CreateChallengeReq,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """1. 创建挑战"""
    import uuid

    challenge_id = str(uuid.uuid4())
    challenge = {
        "id": challenge_id,
        "tenant_id": x_tenant_id,
        "current_participants": 0,
        "is_active": True,
        **req.model_dump(),
    }
    _challenge_store[challenge_id] = challenge
    return {"ok": True, "data": challenge}


@router.get("")
async def list_challenges(
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    type: Optional[str] = Query(None),
    is_active: Optional[bool] = Query(None),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
):
    """2. 列出挑战"""
    items = [
        c
        for c in _challenge_store.values()
        if c["tenant_id"] == x_tenant_id
        and (type is None or c.get("type") == type)
        and (is_active is None or c.get("is_active") == is_active)
    ]
    start = (page - 1) * size
    return {"ok": True, "data": {"items": items[start : start + size], "total": len(items)}}


@router.get("/{challenge_id}")
async def get_challenge(
    challenge_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """3. 获取挑战详情"""
    ch = _challenge_store.get(challenge_id)
    if not ch or ch["tenant_id"] != x_tenant_id:
        return {"ok": False, "error": {"code": "NOT_FOUND", "message": "challenge not found"}}
    return {"ok": True, "data": ch}


@router.put("/{challenge_id}")
async def update_challenge(
    challenge_id: str,
    req: UpdateChallengeReq,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """4. 更新挑战"""
    ch = _challenge_store.get(challenge_id)
    if not ch or ch["tenant_id"] != x_tenant_id:
        return {"ok": False, "error": {"code": "NOT_FOUND", "message": "challenge not found"}}
    updates = {k: v for k, v in req.model_dump().items() if v is not None}
    ch.update(updates)
    return {"ok": True, "data": ch}


@router.delete("/{challenge_id}")
async def delete_challenge(
    challenge_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """5. 删除挑战（软删除）"""
    ch = _challenge_store.get(challenge_id)
    if not ch or ch["tenant_id"] != x_tenant_id:
        return {"ok": False, "error": {"code": "NOT_FOUND", "message": "challenge not found"}}
    ch["is_deleted"] = True
    ch["is_active"] = False
    return {"ok": True, "data": {"deleted": True}}


@router.post("/join")
async def join_challenge(
    req: JoinChallengeReq,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """6. 会员参加挑战"""
    ch = _challenge_store.get(req.challenge_id)
    if not ch or ch["tenant_id"] != x_tenant_id:
        return {"ok": False, "error": {"code": "NOT_FOUND", "message": "challenge not found"}}

    key = f"{req.customer_id}:{req.challenge_id}"
    if key in _progress_store:
        return {"ok": True, "data": _progress_store[key]}

    target = ch.get("rules", {}).get("target", 1)
    progress = {
        "customer_id": req.customer_id,
        "challenge_id": req.challenge_id,
        "current_value": 0,
        "target_value": target,
        "status": "active",
    }
    _progress_store[key] = progress
    ch["current_participants"] = ch.get("current_participants", 0) + 1
    return {"ok": True, "data": progress}


@router.post("/progress")
async def update_progress(
    req: UpdateProgressReq,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """7. 更新挑战进度"""
    key = f"{req.customer_id}:{req.challenge_id}"
    progress = _progress_store.get(key)
    if not progress:
        return {"ok": False, "error": {"code": "NOT_JOINED", "message": "not joined this challenge"}}

    if progress["status"] in ("completed", "claimed"):
        return {"ok": True, "data": progress}

    progress["current_value"] = min(
        progress["current_value"] + req.increment,
        progress["target_value"],
    )
    if progress["current_value"] >= progress["target_value"]:
        progress["status"] = "completed"
    return {"ok": True, "data": progress}


@router.post("/claim")
async def claim_reward(
    req: ClaimRewardReq,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """8. 领取挑战奖励"""
    key = f"{req.customer_id}:{req.challenge_id}"
    progress = _progress_store.get(key)
    if not progress:
        return {"ok": False, "error": {"code": "NOT_JOINED", "message": "not joined"}}

    if progress["status"] != "completed":
        return {"ok": False, "error": {"code": "NOT_COMPLETED", "message": f"status is {progress['status']}"}}

    ch = _challenge_store.get(req.challenge_id, {})
    reward = ch.get("reward", {})
    progress["status"] = "claimed"
    return {"ok": True, "data": {"claimed": True, "reward": reward}}
