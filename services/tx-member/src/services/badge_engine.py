"""徽章引擎 — 评估解锁 + 排行榜

规则类型：visit_count / spend_total / consecutive_visits / dish_variety / referral_count
每种规则对应 JSONB 中的 threshold 字段。

解锁流程：evaluate_badges → 匹配 unlock_rule → 写入 member_badges → 发放积分奖励
"""

from __future__ import annotations

import json
from typing import Any

import structlog
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger(__name__)

# ─── 支持的规则类型 ──────────────────────────────────────────────────────────

RULE_TYPES = frozenset(
    {
        "visit_count",
        "spend_total",
        "consecutive_visits",
        "dish_variety",
        "referral_count",
    }
)


# ─── 规则评估器 ─────────────────────────────────────────────────────────────


async def _get_customer_stats(
    db: AsyncSession,
    tenant_id: str,
    customer_id: str,
) -> dict[str, Any]:
    """从订单和会员表聚合顾客统计数据"""
    stats: dict[str, Any] = {}

    # 到店次数
    row = await db.execute(
        text("""
            SELECT COUNT(DISTINCT DATE(created_at)) AS visit_count
            FROM orders
            WHERE tenant_id = :tid AND customer_id = :cid
              AND is_deleted = false AND status = 'paid'
        """),
        {"tid": tenant_id, "cid": customer_id},
    )
    r = row.mappings().first()
    stats["visit_count"] = int(r["visit_count"]) if r else 0

    # 累计消费（分）
    row = await db.execute(
        text("""
            SELECT COALESCE(SUM(total_fen), 0) AS spend_total
            FROM orders
            WHERE tenant_id = :tid AND customer_id = :cid
              AND is_deleted = false AND status = 'paid'
        """),
        {"tid": tenant_id, "cid": customer_id},
    )
    r = row.mappings().first()
    stats["spend_total"] = int(r["spend_total"]) if r else 0

    # 连续到店天数（最近连续）
    row = await db.execute(
        text("""
            WITH daily AS (
                SELECT DISTINCT DATE(created_at) AS d
                FROM orders
                WHERE tenant_id = :tid AND customer_id = :cid
                  AND is_deleted = false AND status = 'paid'
                ORDER BY d DESC
            ),
            numbered AS (
                SELECT d, d - (ROW_NUMBER() OVER (ORDER BY d DESC) * INTERVAL '1 day')
                       AS grp
                FROM daily
            )
            SELECT COUNT(*) AS streak
            FROM numbered
            WHERE grp = (SELECT grp FROM numbered LIMIT 1)
        """),
        {"tid": tenant_id, "cid": customer_id},
    )
    r = row.mappings().first()
    stats["consecutive_visits"] = int(r["streak"]) if r else 0

    # 品类多样性（不同菜品数）
    row = await db.execute(
        text("""
            SELECT COUNT(DISTINCT oi.dish_id) AS dish_variety
            FROM order_items oi
            JOIN orders o ON o.id = oi.order_id AND o.tenant_id = oi.tenant_id
            WHERE o.tenant_id = :tid AND o.customer_id = :cid
              AND o.is_deleted = false AND o.status = 'paid'
        """),
        {"tid": tenant_id, "cid": customer_id},
    )
    r = row.mappings().first()
    stats["dish_variety"] = int(r["dish_variety"]) if r else 0

    # 推荐人数
    row = await db.execute(
        text("""
            SELECT COUNT(*) AS referral_count
            FROM referrals
            WHERE tenant_id = :tid AND referrer_id = :cid
              AND is_deleted = false AND status = 'completed'
        """),
        {"tid": tenant_id, "cid": customer_id},
    )
    r = row.mappings().first()
    stats["referral_count"] = int(r["referral_count"]) if r else 0

    return stats


def _check_rule(rule: dict, stats: dict[str, Any]) -> bool:
    """检查单条规则是否满足"""
    rule_type = rule.get("type", "")
    if rule_type not in RULE_TYPES:
        logger.warning("unknown_badge_rule_type", rule_type=rule_type)
        return False
    threshold = rule.get("threshold", 0)
    current = stats.get(rule_type, 0)
    return current >= threshold


# ─── 公共接口 ────────────────────────────────────────────────────────────────


async def evaluate_badges(
    db: AsyncSession,
    tenant_id: str,
    customer_id: str,
) -> list[dict]:
    """评估顾客可解锁的全部徽章，返回新解锁列表"""
    logger.info("badge_evaluate_start", tenant_id=tenant_id, customer_id=customer_id)

    stats = await _get_customer_stats(db, tenant_id, customer_id)

    # 获取该租户所有活跃徽章
    rows = await db.execute(
        text("""
            SELECT id, name, category, unlock_rule, rarity, points_reward
            FROM badges
            WHERE tenant_id = :tid AND is_active = true AND is_deleted = false
        """),
        {"tid": tenant_id},
    )
    badges = rows.mappings().all()

    # 获取已解锁徽章
    owned_rows = await db.execute(
        text("""
            SELECT badge_id FROM member_badges
            WHERE tenant_id = :tid AND customer_id = :cid AND is_deleted = false
        """),
        {"tid": tenant_id, "cid": customer_id},
    )
    owned_ids = {str(r["badge_id"]) for r in owned_rows.mappings().all()}

    newly_unlocked: list[dict] = []
    for badge in badges:
        badge_id = str(badge["id"])
        if badge_id in owned_ids:
            continue

        unlock_rule = badge["unlock_rule"] if isinstance(badge["unlock_rule"], dict) else {}
        rules = unlock_rule.get("conditions", [unlock_rule]) if unlock_rule else []
        if not isinstance(rules, list):
            rules = [rules]

        mode = unlock_rule.get("mode", "all")  # all / any
        if mode == "any":
            matched = any(_check_rule(r, stats) for r in rules if r)
        else:
            matched = all(_check_rule(r, stats) for r in rules if r)

        if matched and rules:
            unlocked = await unlock_badge(
                db,
                tenant_id,
                customer_id,
                badge_id,
                context={"stats": stats, "rule": unlock_rule},
            )
            if unlocked:
                newly_unlocked.append(
                    {
                        "badge_id": badge_id,
                        "name": badge["name"],
                        "category": badge["category"],
                        "rarity": badge["rarity"],
                        "points_reward": badge["points_reward"],
                    }
                )

    logger.info(
        "badge_evaluate_done",
        tenant_id=tenant_id,
        customer_id=customer_id,
        new_count=len(newly_unlocked),
    )
    return newly_unlocked


async def unlock_badge(
    db: AsyncSession,
    tenant_id: str,
    customer_id: str,
    badge_id: str,
    context: dict | None = None,
) -> bool:
    """解锁单个徽章，返回是否成功（幂等，重复解锁返回 False）"""
    try:
        await db.execute(
            text("""
                INSERT INTO member_badges (tenant_id, customer_id, badge_id, unlock_context)
                VALUES (:tid, :cid, :bid, :ctx::jsonb)
                ON CONFLICT (tenant_id, customer_id, badge_id) DO NOTHING
            """),
            {
                "tid": tenant_id,
                "cid": customer_id,
                "bid": badge_id,
                "ctx": json.dumps(context or {}),
            },
        )
        await db.commit()
        logger.info("badge_unlocked", tenant_id=tenant_id, customer_id=customer_id, badge_id=badge_id)
        return True
    except IntegrityError:
        await db.rollback()
        logger.debug("badge_already_unlocked", badge_id=badge_id, customer_id=customer_id)
        return False
    except SQLAlchemyError:
        await db.rollback()
        logger.exception("badge_unlock_db_error", badge_id=badge_id)
        raise


async def get_customer_badges(
    db: AsyncSession,
    tenant_id: str,
    customer_id: str,
) -> list[dict]:
    """获取顾客所有已解锁徽章"""
    rows = await db.execute(
        text("""
            SELECT mb.id, mb.badge_id, mb.unlocked_at, mb.is_showcase,
                   b.name, b.category, b.rarity, b.icon_url, b.points_reward
            FROM member_badges mb
            JOIN badges b ON b.id = mb.badge_id AND b.tenant_id = mb.tenant_id
            WHERE mb.tenant_id = :tid AND mb.customer_id = :cid
              AND mb.is_deleted = false AND b.is_deleted = false
            ORDER BY mb.unlocked_at DESC
        """),
        {"tid": tenant_id, "cid": customer_id},
    )
    return [dict(r) for r in rows.mappings().all()]


async def get_badge_leaderboard(
    db: AsyncSession,
    tenant_id: str,
    limit: int = 20,
) -> list[dict]:
    """徽章排行榜 — 按解锁数量排名"""
    rows = await db.execute(
        text("""
            SELECT mb.customer_id,
                   COUNT(*) AS badge_count,
                   SUM(b.points_reward) AS total_points
            FROM member_badges mb
            JOIN badges b ON b.id = mb.badge_id AND b.tenant_id = mb.tenant_id
            WHERE mb.tenant_id = :tid AND mb.is_deleted = false AND b.is_deleted = false
            GROUP BY mb.customer_id
            ORDER BY badge_count DESC, total_points DESC
            LIMIT :lim
        """),
        {"tid": tenant_id, "lim": limit},
    )
    result = []
    for i, r in enumerate(rows.mappings().all(), 1):
        result.append(
            {
                "rank": i,
                "customer_id": str(r["customer_id"]),
                "badge_count": int(r["badge_count"]),
                "total_points": int(r["total_points"]),
            }
        )
    return result


async def get_badge_holders(
    db: AsyncSession,
    tenant_id: str,
    badge_id: str,
    page: int = 1,
    size: int = 20,
) -> dict:
    """获取某徽章的所有持有者"""
    offset = (page - 1) * size
    count_row = await db.execute(
        text("""
            SELECT COUNT(*) AS total FROM member_badges
            WHERE tenant_id = :tid AND badge_id = :bid AND is_deleted = false
        """),
        {"tid": tenant_id, "bid": badge_id},
    )
    total = int(count_row.scalar() or 0)

    rows = await db.execute(
        text("""
            SELECT customer_id, unlocked_at, unlock_context
            FROM member_badges
            WHERE tenant_id = :tid AND badge_id = :bid AND is_deleted = false
            ORDER BY unlocked_at DESC
            LIMIT :lim OFFSET :off
        """),
        {"tid": tenant_id, "bid": badge_id, "lim": size, "off": offset},
    )
    items = [dict(r) for r in rows.mappings().all()]
    return {"items": items, "total": total}


async def list_badges(
    db: AsyncSession,
    tenant_id: str,
    category: str | None = None,
    page: int = 1,
    size: int = 20,
) -> dict:
    """列出租户的徽章定义"""
    offset = (page - 1) * size
    where_extra = " AND category = :cat" if category else ""
    params: dict[str, Any] = {"tid": tenant_id, "lim": size, "off": offset}
    if category:
        params["cat"] = category

    count_row = await db.execute(
        text(f"""
            SELECT COUNT(*) FROM badges
            WHERE tenant_id = :tid AND is_deleted = false{where_extra}
        """),
        params,
    )
    total = int(count_row.scalar() or 0)

    rows = await db.execute(
        text(f"""
            SELECT id, name, description, category, unlock_rule, rarity,
                   points_reward, icon_url, display_order, is_active
            FROM badges
            WHERE tenant_id = :tid AND is_deleted = false{where_extra}
            ORDER BY display_order, created_at
            LIMIT :lim OFFSET :off
        """),
        params,
    )
    items = [dict(r) for r in rows.mappings().all()]
    return {"items": items, "total": total}
