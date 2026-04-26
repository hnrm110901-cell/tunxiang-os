"""挑战 API — 8端点

/api/v1/member/challenges

从内存存储迁移至 v310(challenges) + v311(challenge_progress) 数据库表。
通过 challenge_engine 模块操作 DB，tenant_id RLS 隔离。
"""

import json
from typing import Any, Optional

from fastapi import APIRouter, Depends, Header, Query
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db
from services.tx_member.src.services import challenge_engine

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


# ─── 辅助函数 ────────────────────────────────────────────────────────────────


def _ok(data: Any) -> dict:
    return {"ok": True, "data": data}


def _err(code: str, message: str) -> dict:
    return {"ok": False, "error": {"code": code, "message": message}}


# ─── 端点 ─────────────────────────────────────────────────────────────────────


@router.post("")
async def create_challenge(
    req: CreateChallengeReq,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """1. 创建挑战 → INSERT INTO challenges"""
    try:
        row = await db.execute(
            text("""
                INSERT INTO challenges (tenant_id, name, description, type,
                                        rules, reward, badge_id,
                                        start_date, end_date,
                                        max_participants, icon_url, display_order)
                VALUES (:tid, :name, :desc, :type, :rules::jsonb, :reward::jsonb,
                        :badge_id, :start_date::timestamptz, :end_date::timestamptz,
                        :max_p, :icon, :ord)
                RETURNING id, tenant_id, name, description, type, rules, reward,
                          badge_id, start_date, end_date, max_participants,
                          current_participants, is_active, display_order, icon_url,
                          created_at, updated_at
            """),
            {
                "tid": x_tenant_id,
                "name": req.name,
                "desc": req.description,
                "type": req.type,
                "rules": json.dumps(req.rules),
                "reward": json.dumps(req.reward),
                "badge_id": req.badge_id,
                "start_date": req.start_date,
                "end_date": req.end_date,
                "max_p": req.max_participants,
                "icon": req.icon_url,
                "ord": req.display_order,
            },
        )
        await db.commit()
        challenge = dict(row.mappings().first())
        return _ok(challenge)
    except SQLAlchemyError:
        await db.rollback()
        raise


@router.get("")
async def list_challenges(
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    type: Optional[str] = Query(None),
    is_active: Optional[bool] = Query(None),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """2. 列出挑战 → SELECT FROM challenges"""
    offset = (page - 1) * size
    where_parts = ["tenant_id = :tid", "is_deleted = false"]
    params: dict[str, Any] = {"tid": x_tenant_id, "lim": size, "off": offset}

    if type is not None:
        where_parts.append("type = :type")
        params["type"] = type
    if is_active is not None:
        where_parts.append("is_active = :active")
        params["active"] = is_active

    where_clause = " AND ".join(where_parts)

    count_row = await db.execute(
        text(f"SELECT COUNT(*) FROM challenges WHERE {where_clause}"),
        params,
    )
    total = int(count_row.scalar() or 0)

    rows = await db.execute(
        text(f"""
            SELECT id, name, description, type, rules, reward, badge_id,
                   start_date, end_date, max_participants, current_participants,
                   is_active, display_order, icon_url, created_at, updated_at
            FROM challenges
            WHERE {where_clause}
            ORDER BY display_order, start_date
            LIMIT :lim OFFSET :off
        """),
        params,
    )
    items = [dict(r) for r in rows.mappings().all()]
    return _ok({"items": items, "total": total})


@router.get("/{challenge_id}")
async def get_challenge(
    challenge_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """3. 获取挑战详情 → SELECT ... WHERE id = ..."""
    row = await db.execute(
        text("""
            SELECT id, name, description, type, rules, reward, badge_id,
                   start_date, end_date, max_participants, current_participants,
                   is_active, display_order, icon_url, created_at, updated_at
            FROM challenges
            WHERE tenant_id = :tid AND id = :cid AND is_deleted = false
        """),
        {"tid": x_tenant_id, "cid": challenge_id},
    )
    ch = row.mappings().first()
    if not ch:
        return _err("NOT_FOUND", "challenge not found")
    return _ok(dict(ch))


@router.put("/{challenge_id}")
async def update_challenge(
    challenge_id: str,
    req: UpdateChallengeReq,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """4. 更新挑战 → UPDATE challenges SET ..."""
    updates = {k: v for k, v in req.model_dump().items() if v is not None}
    if not updates:
        return _err("NO_CHANGES", "no fields to update")

    ALLOWED_COLUMNS = {"name", "description", "type", "rules", "reward", "goal_value",
                       "start_date", "end_date", "max_participants", "is_active"}
    set_parts: list[str] = ["updated_at = NOW()"]
    params: dict[str, Any] = {"tid": x_tenant_id, "cid": challenge_id}
    for key, val in updates.items():
        if key not in ALLOWED_COLUMNS:
            continue
        if key in ("rules", "reward"):
            set_parts.append(f'"{key}" = :{key}::jsonb')
            params[key] = json.dumps(val)
        elif key in ("start_date", "end_date"):
            set_parts.append(f'"{key}" = :{key}::timestamptz')
            params[key] = val
        else:
            set_parts.append(f'"{key}" = :{key}')
            params[key] = val

    set_clause = ", ".join(set_parts)
    try:
        row = await db.execute(
            text(f"""
                UPDATE challenges
                SET {set_clause}
                WHERE tenant_id = :tid AND id = :cid AND is_deleted = false
                RETURNING id, name, description, type, rules, reward, badge_id,
                          start_date, end_date, max_participants, current_participants,
                          is_active, display_order, icon_url, created_at, updated_at
            """),
            params,
        )
        await db.commit()
        result = row.mappings().first()
        if not result:
            return _err("NOT_FOUND", "challenge not found")
        return _ok(dict(result))
    except SQLAlchemyError:
        await db.rollback()
        raise


@router.delete("/{challenge_id}")
async def delete_challenge(
    challenge_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """5. 删除挑战（软删除） → UPDATE challenges SET is_deleted = true"""
    try:
        result = await db.execute(
            text("""
                UPDATE challenges
                SET is_deleted = true, is_active = false, updated_at = NOW()
                WHERE tenant_id = :tid AND id = :cid AND is_deleted = false
            """),
            {"tid": x_tenant_id, "cid": challenge_id},
        )
        await db.commit()
        if result.rowcount == 0:
            return _err("NOT_FOUND", "challenge not found")
        return _ok({"deleted": True})
    except SQLAlchemyError:
        await db.rollback()
        raise


@router.post("/join")
async def join_challenge_api(
    req: JoinChallengeReq,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """6. 会员参加挑战 → challenge_engine.join_challenge"""
    try:
        progress = await challenge_engine.join_challenge(
            db, x_tenant_id, req.customer_id, req.challenge_id
        )
        return _ok(progress)
    except ValueError as e:
        return _err("JOIN_FAILED", str(e))


@router.post("/progress")
async def update_progress(
    req: UpdateProgressReq,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """7. 更新挑战进度 → challenge_engine.update_progress"""
    try:
        progress = await challenge_engine.update_progress(
            db,
            x_tenant_id,
            req.customer_id,
            req.challenge_id,
            increment=req.increment,
            detail=req.detail if req.detail else None,
        )
        return _ok(progress)
    except ValueError as e:
        return _err("NOT_JOINED", str(e))


@router.post("/claim")
async def claim_reward(
    req: ClaimRewardReq,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """8. 领取挑战奖励 → challenge_engine.claim_reward"""
    try:
        result = await challenge_engine.claim_reward(
            db, x_tenant_id, req.customer_id, req.challenge_id
        )
        return _ok(result)
    except ValueError as e:
        return _err("CLAIM_FAILED", str(e))
