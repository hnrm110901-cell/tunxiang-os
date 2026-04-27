"""徽章 API — 8端点

/api/v1/member/badges

从内存存储迁移至 v308(badges) + v309(member_badges) 数据库表。
通过 badge_engine 模块操作 DB，tenant_id RLS 隔离。
"""

import json
from typing import Any, Optional

from fastapi import APIRouter, Depends, Header, Query
from pydantic import BaseModel, Field
from services.tx_member.src.services import badge_engine
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

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


# ─── 辅助函数 ────────────────────────────────────────────────────────────────


def _ok(data: Any) -> dict:
    return {"ok": True, "data": data}


def _err(code: str, message: str) -> dict:
    return {"ok": False, "error": {"code": code, "message": message}}


# ─── 端点 ─────────────────────────────────────────────────────────────────────


@router.post("")
async def create_badge(
    req: CreateBadgeReq,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """1. 创建徽章定义 → INSERT INTO badges"""
    try:
        row = await db.execute(
            text("""
                INSERT INTO badges (tenant_id, name, description, category,
                                    unlock_rule, rarity, points_reward,
                                    icon_url, display_order)
                VALUES (:tid, :name, :desc, :cat, :rule::jsonb,
                        :rarity, :pts, :icon, :ord)
                RETURNING id, tenant_id, name, description, category,
                          unlock_rule, rarity, points_reward, icon_url,
                          display_order, is_active, created_at, updated_at
            """),
            {
                "tid": x_tenant_id,
                "name": req.name,
                "desc": req.description,
                "cat": req.category,
                "rule": json.dumps(req.unlock_rule),
                "rarity": req.rarity,
                "pts": req.points_reward,
                "icon": req.icon_url,
                "ord": req.display_order,
            },
        )
        await db.commit()
        badge = dict(row.mappings().first())
        return _ok(badge)
    except SQLAlchemyError:
        await db.rollback()
        raise


@router.get("")
async def list_badges_api(
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    category: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """2. 列出徽章 → SELECT FROM badges"""
    result = await badge_engine.list_badges(db, x_tenant_id, category=category, page=page, size=size)
    return _ok(result)


@router.get("/leaderboard/top")
async def badge_leaderboard(
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """7. 徽章排行榜 → badge_engine.get_badge_leaderboard"""
    items = await badge_engine.get_badge_leaderboard(db, x_tenant_id, limit=limit)
    return _ok({"items": items, "total": len(items)})


@router.get("/{badge_id}")
async def get_badge(
    badge_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """3. 获取徽章详情 → SELECT ... WHERE id = ..."""
    row = await db.execute(
        text("""
            SELECT id, name, description, category, unlock_rule, rarity,
                   points_reward, icon_url, display_order, is_active,
                   created_at, updated_at
            FROM badges
            WHERE tenant_id = :tid AND id = :bid AND is_deleted = false
        """),
        {"tid": x_tenant_id, "bid": badge_id},
    )
    badge = row.mappings().first()
    if not badge:
        return _err("NOT_FOUND", "badge not found")
    return _ok(dict(badge))


@router.put("/{badge_id}")
async def update_badge(
    badge_id: str,
    req: UpdateBadgeReq,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """4. 更新徽章 → UPDATE badges SET ..."""
    updates = {k: v for k, v in req.model_dump().items() if v is not None}
    if not updates:
        return _err("NO_CHANGES", "no fields to update")

    # 动态构建 SET 子句（allowlist防止SQL注入）
    ALLOWED_COLUMNS = {
        "name",
        "description",
        "category",
        "unlock_rule",
        "rarity",
        "points_reward",
        "icon_url",
        "display_order",
        "is_active",
    }
    set_parts: list[str] = ["updated_at = NOW()"]
    params: dict[str, Any] = {"tid": x_tenant_id, "bid": badge_id}
    for key, val in updates.items():
        if key not in ALLOWED_COLUMNS:
            continue
        if key == "unlock_rule":
            set_parts.append(f'"{key}" = :{key}::jsonb')
            params[key] = json.dumps(val)
        else:
            set_parts.append(f'"{key}" = :{key}')
            params[key] = val

    set_clause = ", ".join(set_parts)
    try:
        row = await db.execute(
            text(f"""
                UPDATE badges
                SET {set_clause}
                WHERE tenant_id = :tid AND id = :bid AND is_deleted = false
                RETURNING id, name, description, category, unlock_rule, rarity,
                          points_reward, icon_url, display_order, is_active,
                          created_at, updated_at
            """),
            params,
        )
        await db.commit()
        result = row.mappings().first()
        if not result:
            return _err("NOT_FOUND", "badge not found")
        return _ok(dict(result))
    except SQLAlchemyError:
        await db.rollback()
        raise


@router.delete("/{badge_id}")
async def delete_badge(
    badge_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """5. 删除徽章（软删除） → UPDATE badges SET is_deleted = true"""
    try:
        result = await db.execute(
            text("""
                UPDATE badges
                SET is_deleted = true, is_active = false, updated_at = NOW()
                WHERE tenant_id = :tid AND id = :bid AND is_deleted = false
            """),
            {"tid": x_tenant_id, "bid": badge_id},
        )
        await db.commit()
        if result.rowcount == 0:
            return _err("NOT_FOUND", "badge not found")
        return _ok({"deleted": True})
    except SQLAlchemyError:
        await db.rollback()
        raise


@router.post("/evaluate")
async def evaluate_badges_api(
    req: EvaluateBadgesReq,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """6. 评估顾客可解锁的徽章 → badge_engine.evaluate_badges"""
    newly_unlocked = await badge_engine.evaluate_badges(db, x_tenant_id, req.customer_id)
    return _ok({"customer_id": req.customer_id, "newly_unlocked": newly_unlocked})


@router.get("/{badge_id}/holders")
async def badge_holders(
    badge_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """8. 获取徽章持有者列表 → badge_engine.get_badge_holders"""
    result = await badge_engine.get_badge_holders(db, x_tenant_id, badge_id, page=page, size=size)
    return _ok(result)
