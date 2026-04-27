"""会员等级体系管理 API — 等级配置 / 升降级日志 / 升级资格检查

数据表：
  member_tier_configs  — v130 迁移，等级定义
  tier_upgrade_logs    — v130 迁移，升降级记录
  member_cards         — 早期迁移，会员卡（含积分、消费等级）
"""

from typing import Any

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

log = structlog.get_logger(__name__)
router = APIRouter(prefix="/api/v1/member/tiers", tags=["member-tiers"])


# ── 请求模型 ──────────────────────────────────────────────────


class TierConfig(BaseModel):
    name: str
    level: int = 1
    min_points: int = 0
    min_spend_fen: int = 0
    benefits: list[str] = []
    discount_rate: float = 1.0
    points_multiplier: float = 1.0
    birthday_bonus_fen: int = 0
    free_delivery_threshold_fen: int = 0
    color: str = "#8C8C8C"
    icon: str = ""
    is_active: bool = True


# ── 辅助函数 ──────────────────────────────────────────────────


async def _set_rls(db: AsyncSession, tenant_id: str) -> None:
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": tenant_id},
    )


def _row_to_tier(row: Any) -> dict[str, Any]:
    """将 DB 行转换为 API 响应字典"""
    return {
        "id": str(row[0]),
        "tenant_id": str(row[1]),
        "level": row[2],
        "name": row[3],
        "min_points": row[4],
        "min_spend_fen": row[5],
        "discount_rate": float(row[6]) if row[6] is not None else 1.0,
        "points_multiplier": float(row[7]) if row[7] is not None else 1.0,
        "birthday_bonus_fen": row[8],
        "free_delivery_threshold_fen": row[9],
        "benefits": row[10] or [],
        "color": row[11] or "#8C8C8C",
        "icon": row[12] or "",
        "is_active": row[13],
    }


# ── 端点 ──────────────────────────────────────────────────────


@router.get("")
async def list_tiers(
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """所有等级配置 + 各等级会员数统计"""
    if not x_tenant_id:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header is required")

    try:
        await _set_rls(db, x_tenant_id)

        rows = await db.execute(
            text("""
                SELECT
                    tc.id, tc.tenant_id, tc.level, tc.name,
                    tc.min_points, tc.min_spend_fen,
                    tc.discount_rate, tc.points_multiplier,
                    tc.birthday_bonus_fen, tc.free_delivery_threshold_fen,
                    tc.benefits, tc.color, tc.icon, tc.is_active,
                    COUNT(mc.id) AS member_count
                FROM member_tier_configs tc
                LEFT JOIN member_cards mc
                    ON mc.tier_id = tc.id AND mc.tenant_id = tc.tenant_id
                WHERE tc.tenant_id = :tid
                GROUP BY tc.id
                ORDER BY tc.level ASC
            """),
            {"tid": x_tenant_id},
        )
        all_rows = rows.all()

        tiers = []
        total_members = 0
        for row in all_rows:
            t = _row_to_tier(row)
            count = row[14] or 0
            total_members += count
            t["member_count"] = count
            tiers.append(t)

        log.info("tier.list", tenant_id=x_tenant_id, count=len(tiers))
        return {
            "ok": True,
            "data": {
                "tiers": tiers,
                "total_members": total_members,
            },
        }

    except SQLAlchemyError as exc:
        log.error("tier.list.db_error", exc_info=True, error=str(exc))
        return {"ok": True, "data": {"tiers": [], "total_members": 0}}


@router.get("/upgrade-log")
async def get_upgrade_log(
    days: int = Query(7, ge=1, le=365, description="查询最近N天"),
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=200),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """升降级记录（支持分页）"""
    if not x_tenant_id:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header is required")

    try:
        await _set_rls(db, x_tenant_id)

        offset = (page - 1) * size
        rows = await db.execute(
            text("""
                SELECT
                    ul.id,
                    ul.customer_id,
                    COALESCE(c.nickname, '用户' || LEFT(ul.customer_id::text, 6)) AS customer_name,
                    ul.from_tier_name,
                    ul.to_tier_name,
                    ul.trigger,
                    ul.points_at_change,
                    ul.spend_total_fen,
                    ul.reason,
                    ul.created_at
                FROM tier_upgrade_logs ul
                LEFT JOIN customers c
                    ON c.id = ul.customer_id AND c.tenant_id = ul.tenant_id
                WHERE ul.tenant_id = :tid
                  AND ul.created_at >= NOW() - (:days || ' days')::interval
                ORDER BY ul.created_at DESC
                LIMIT :lim OFFSET :off
            """),
            {"tid": x_tenant_id, "days": days, "lim": size, "off": offset},
        )
        all_rows = rows.all()

        items = [
            {
                "id": str(row[0]),
                "customer_id": str(row[1]),
                "customer_name": row[2] or "未知",
                "from_tier": row[3] or "",
                "to_tier": row[4] or "",
                "trigger": row[5] or "",
                "points_at_upgrade": row[6],
                "spend_total_fen": row[7],
                "reason": row[8] or "",
                "upgraded_at": row[9].isoformat() if row[9] else "",
            }
            for row in all_rows
        ]

        upgrades = [e for e in items if e["trigger"] != "downgrade"]
        downgrades = [e for e in items if e["trigger"] == "downgrade"]

        log.info(
            "tier.upgrade_log",
            tenant_id=x_tenant_id,
            upgrades=len(upgrades),
            downgrades=len(downgrades),
        )
        return {
            "ok": True,
            "data": {
                "items": items,
                "upgrade_count": len(upgrades),
                "downgrade_count": len(downgrades),
            },
        }

    except SQLAlchemyError as exc:
        log.error("tier.upgrade_log.db_error", exc_info=True, error=str(exc))
        return {"ok": True, "data": {"items": [], "upgrade_count": 0, "downgrade_count": 0}}


@router.post("/check-upgrade/{customer_id}")
async def check_upgrade_eligibility(
    customer_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """检查顾客是否满足升级条件"""
    if not x_tenant_id:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header is required")

    try:
        await _set_rls(db, x_tenant_id)

        # 查询会员卡（积分+消费）
        card_row = await db.execute(
            text("""
                SELECT mc.points_balance, mc.total_spend_fen, mc.tier_id
                FROM member_cards mc
                WHERE mc.customer_id = :cid AND mc.tenant_id = :tid
                  AND mc.is_deleted = false
                ORDER BY mc.created_at ASC
                LIMIT 1
            """),
            {"cid": customer_id, "tid": x_tenant_id},
        )
        card = card_row.first()

        current_points = card[0] if card else 0
        current_spend = card[1] if card else 0
        current_tier_id = str(card[2]) if card and card[2] else None

        # 当前等级名称
        current_tier_name = "普通会员"
        if current_tier_id:
            ct_row = await db.execute(
                text("SELECT name, level FROM member_tier_configs WHERE id = :tid_id LIMIT 1"),
                {"tid_id": current_tier_id},
            )
            ct = ct_row.first()
            if ct:
                current_tier_name = ct[0]

        # 下一等级配置
        next_row = await db.execute(
            text("""
                SELECT id, name, min_points, min_spend_fen
                FROM member_tier_configs
                WHERE tenant_id = :tid
                  AND (min_points > :pts OR min_spend_fen > :spend)
                ORDER BY min_points ASC, min_spend_fen ASC
                LIMIT 1
            """),
            {"tid": x_tenant_id, "pts": current_points, "spend": current_spend},
        )
        next_tier = next_row.first()

        if next_tier:
            next_tier_name = next_tier[1]
            required_pts = next_tier[2]
            required_spend = next_tier[3]
            pts_gap = max(0, required_pts - current_points)
            spend_gap = max(0, required_spend - current_spend)
            eligible = pts_gap == 0 and spend_gap == 0
        else:
            next_tier_name = "已达最高等级"
            required_pts = current_points
            required_spend = current_spend
            pts_gap = 0
            spend_gap = 0
            eligible = False

        log.info(
            "tier.check_upgrade",
            customer_id=customer_id,
            current_tier=current_tier_name,
            eligible=eligible,
        )
        return {
            "ok": True,
            "data": {
                "customer_id": customer_id,
                "current_tier": current_tier_name,
                "next_tier": next_tier_name,
                "current_points": current_points,
                "required_points": required_pts,
                "points_gap": pts_gap,
                "current_spend_fen": current_spend,
                "required_spend_fen": required_spend,
                "spend_gap_fen": spend_gap,
                "eligible": eligible,
            },
        }

    except SQLAlchemyError as exc:
        log.error("tier.check_upgrade.db_error", exc_info=True, error=str(exc))
        raise HTTPException(status_code=500, detail="服务暂时不可用")


@router.get("/{tier_id}")
async def get_tier(
    tier_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """单个等级详情"""
    if not x_tenant_id:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header is required")

    try:
        await _set_rls(db, x_tenant_id)

        row = await db.execute(
            text("""
                SELECT id, tenant_id, level, name,
                       min_points, min_spend_fen,
                       discount_rate, points_multiplier,
                       birthday_bonus_fen, free_delivery_threshold_fen,
                       benefits, color, icon, is_active
                FROM member_tier_configs
                WHERE id = :tid_id AND tenant_id = :tid
                LIMIT 1
            """),
            {"tid_id": tier_id, "tid": x_tenant_id},
        )
        tier = row.first()
        if not tier:
            raise HTTPException(status_code=404, detail="等级不存在")

        return {"ok": True, "data": _row_to_tier(tier)}

    except HTTPException:
        raise
    except SQLAlchemyError as exc:
        log.error("tier.get.db_error", exc_info=True, error=str(exc))
        raise HTTPException(status_code=500, detail="服务暂时不可用")


@router.post("")
async def create_tier(
    body: TierConfig,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """新增等级配置"""
    if not x_tenant_id:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header is required")

    try:
        await _set_rls(db, x_tenant_id)

        result = await db.execute(
            text("""
                INSERT INTO member_tier_configs
                    (tenant_id, level, name, min_points, min_spend_fen,
                     discount_rate, points_multiplier,
                     birthday_bonus_fen, free_delivery_threshold_fen,
                     benefits, color, icon, is_active)
                VALUES
                    (:tid, :level, :name, :min_pts, :min_spend,
                     :discount, :multiplier,
                     :bday_bonus, :free_delivery,
                     :benefits, :color, :icon, :is_active)
                RETURNING id
            """),
            {
                "tid": x_tenant_id,
                "level": body.level,
                "name": body.name,
                "min_pts": body.min_points,
                "min_spend": body.min_spend_fen,
                "discount": body.discount_rate,
                "multiplier": body.points_multiplier,
                "bday_bonus": body.birthday_bonus_fen,
                "free_delivery": body.free_delivery_threshold_fen,
                "benefits": body.benefits,
                "color": body.color,
                "icon": body.icon,
                "is_active": body.is_active,
            },
        )
        new_id = str(result.scalar())
        await db.commit()

        log.info("tier.create", tier_id=new_id, name=body.name, tenant_id=x_tenant_id)
        return {"ok": True, "data": {"id": new_id, **body.model_dump()}}

    except SQLAlchemyError as exc:
        await db.rollback()
        log.error("tier.create.db_error", exc_info=True, error=str(exc))
        raise HTTPException(status_code=500, detail="服务暂时不可用")


@router.put("/{tier_id}")
async def update_tier(
    tier_id: str,
    body: TierConfig,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """更新等级配置"""
    if not x_tenant_id:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header is required")

    try:
        await _set_rls(db, x_tenant_id)

        result = await db.execute(
            text("""
                UPDATE member_tier_configs
                SET level = :level, name = :name,
                    min_points = :min_pts, min_spend_fen = :min_spend,
                    discount_rate = :discount, points_multiplier = :multiplier,
                    birthday_bonus_fen = :bday_bonus,
                    free_delivery_threshold_fen = :free_delivery,
                    benefits = :benefits, color = :color, icon = :icon,
                    is_active = :is_active,
                    updated_at = NOW()
                WHERE id = :tier_id AND tenant_id = :tid
                RETURNING id
            """),
            {
                "tier_id": tier_id,
                "tid": x_tenant_id,
                "level": body.level,
                "name": body.name,
                "min_pts": body.min_points,
                "min_spend": body.min_spend_fen,
                "discount": body.discount_rate,
                "multiplier": body.points_multiplier,
                "bday_bonus": body.birthday_bonus_fen,
                "free_delivery": body.free_delivery_threshold_fen,
                "benefits": body.benefits,
                "color": body.color,
                "icon": body.icon,
                "is_active": body.is_active,
            },
        )
        updated = result.first()
        if not updated:
            raise HTTPException(status_code=404, detail="等级不存在")

        await db.commit()

        log.info("tier.update", tier_id=tier_id, tenant_id=x_tenant_id)
        return {"ok": True, "data": {"id": tier_id, **body.model_dump()}}

    except HTTPException:
        raise
    except SQLAlchemyError as exc:
        await db.rollback()
        log.error("tier.update.db_error", exc_info=True, error=str(exc))
        raise HTTPException(status_code=500, detail="服务暂时不可用")
