"""挑战引擎 — 参加 + 进度更新 + 领取奖励 + 查询

挑战类型：visit_streak / spend_target / dish_explorer / social_share /
         referral_drive / seasonal_event / time_limited / combo_quest

流程：join_challenge → update_progress → (auto complete) → claim_reward
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

import structlog
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger(__name__)


# ─── 参加挑战 ────────────────────────────────────────────────────────────────


async def join_challenge(
    db: AsyncSession,
    tenant_id: str,
    customer_id: str,
    challenge_id: str,
) -> dict:
    """会员参加挑战（幂等：已参加返回已有记录）"""
    logger.info("challenge_join", tenant_id=tenant_id, customer_id=customer_id, challenge_id=challenge_id)

    # 校验挑战存在且进行中
    ch_row = await db.execute(
        text("""
            SELECT id, name, rules, reward, max_participants, current_participants,
                   start_date, end_date, is_active
            FROM challenges
            WHERE tenant_id = :tid AND id = :cid AND is_deleted = false
        """),
        {"tid": tenant_id, "cid": challenge_id},
    )
    challenge = ch_row.mappings().first()
    if not challenge:
        raise ValueError(f"challenge {challenge_id} not found")

    now = datetime.now(timezone.utc)
    if not challenge["is_active"]:
        raise ValueError("challenge is not active")
    if now < challenge["start_date"]:
        raise ValueError("challenge has not started yet")
    if now > challenge["end_date"]:
        raise ValueError("challenge has ended")

    max_p = challenge["max_participants"]
    if max_p > 0 and challenge["current_participants"] >= max_p:
        raise ValueError("challenge is full")

    # 计算目标值
    rules = challenge["rules"] if isinstance(challenge["rules"], dict) else {}
    target_value = rules.get("target", 1)

    try:
        await db.execute(
            text("""
                INSERT INTO challenge_progress
                    (tenant_id, customer_id, challenge_id, target_value, reward_snapshot)
                VALUES (:tid, :cust, :ch, :target, :reward::jsonb)
                ON CONFLICT (tenant_id, customer_id, challenge_id) DO NOTHING
            """),
            {
                "tid": tenant_id,
                "cust": customer_id,
                "ch": challenge_id,
                "target": target_value,
                "reward": json.dumps(challenge["reward"] if isinstance(challenge["reward"], dict) else {}),
            },
        )
        # 增加参与者计数
        await db.execute(
            text("""
                UPDATE challenges
                SET current_participants = current_participants + 1,
                    updated_at = NOW()
                WHERE tenant_id = :tid AND id = :cid
                  AND NOT EXISTS (
                      SELECT 1 FROM challenge_progress
                      WHERE tenant_id = :tid AND customer_id = :cust
                        AND challenge_id = :cid AND is_deleted = false
                        AND created_at < NOW() - INTERVAL '1 second'
                  )
            """),
            {"tid": tenant_id, "cid": challenge_id, "cust": customer_id},
        )
        await db.commit()
    except IntegrityError:
        await db.rollback()
        logger.debug("challenge_already_joined", challenge_id=challenge_id)
    except SQLAlchemyError:
        await db.rollback()
        logger.exception("challenge_join_db_error")
        raise

    # 返回当前进度
    return await get_progress(db, tenant_id, customer_id, challenge_id)


# ─── 更新进度 ────────────────────────────────────────────────────────────────


async def update_progress(
    db: AsyncSession,
    tenant_id: str,
    customer_id: str,
    challenge_id: str,
    increment: int = 1,
    detail: dict | None = None,
) -> dict:
    """更新挑战进度，自动判断是否完成"""
    logger.info(
        "challenge_progress_update",
        tenant_id=tenant_id,
        customer_id=customer_id,
        challenge_id=challenge_id,
        increment=increment,
    )

    # 先获取当前进度
    row = await db.execute(
        text("""
            SELECT id, current_value, target_value, status, progress_detail
            FROM challenge_progress
            WHERE tenant_id = :tid AND customer_id = :cust
              AND challenge_id = :ch AND is_deleted = false
        """),
        {"tid": tenant_id, "cust": customer_id, "ch": challenge_id},
    )
    progress = row.mappings().first()
    if not progress:
        raise ValueError("not joined this challenge")

    if progress["status"] in ("completed", "claimed", "expired"):
        return dict(progress)

    new_value = min(progress["current_value"] + increment, progress["target_value"])
    new_detail = progress["progress_detail"] if isinstance(progress["progress_detail"], dict) else {}
    if detail:
        history = new_detail.get("history", [])
        history.append(
            {
                "at": datetime.now(timezone.utc).isoformat(),
                "increment": increment,
                **detail,
            }
        )
        new_detail["history"] = history[-50:]  # 保留最近50条

    new_status = "completed" if new_value >= progress["target_value"] else "active"
    completed_at_clause = ", completed_at = NOW()" if new_status == "completed" else ""

    await db.execute(
        text(f"""
            UPDATE challenge_progress
            SET current_value = :val,
                status = :st,
                progress_detail = :pd::jsonb,
                updated_at = NOW(){completed_at_clause}
            WHERE id = :pid AND tenant_id = :tid
        """),
        {
            "val": new_value,
            "st": new_status,
            "pd": json.dumps(new_detail),
            "pid": str(progress["id"]),
            "tid": tenant_id,
        },
    )
    await db.commit()

    logger.info(
        "challenge_progress_updated",
        new_value=new_value,
        target=progress["target_value"],
        status=new_status,
    )
    return await get_progress(db, tenant_id, customer_id, challenge_id)


# ─── 领取奖励 ────────────────────────────────────────────────────────────────


async def claim_reward(
    db: AsyncSession,
    tenant_id: str,
    customer_id: str,
    challenge_id: str,
) -> dict:
    """领取已完成挑战的奖励"""
    row = await db.execute(
        text("""
            SELECT id, status, reward_snapshot
            FROM challenge_progress
            WHERE tenant_id = :tid AND customer_id = :cust
              AND challenge_id = :ch AND is_deleted = false
        """),
        {"tid": tenant_id, "cust": customer_id, "ch": challenge_id},
    )
    progress = row.mappings().first()
    if not progress:
        raise ValueError("not joined this challenge")
    if progress["status"] != "completed":
        raise ValueError(f"cannot claim: status is {progress['status']}")

    reward = progress["reward_snapshot"] if isinstance(progress["reward_snapshot"], dict) else {}

    await db.execute(
        text("""
            UPDATE challenge_progress
            SET status = 'claimed', claimed_at = NOW(), updated_at = NOW()
            WHERE id = :pid AND tenant_id = :tid
        """),
        {"pid": str(progress["id"]), "tid": tenant_id},
    )
    await db.commit()

    logger.info(
        "challenge_reward_claimed",
        tenant_id=tenant_id,
        customer_id=customer_id,
        challenge_id=challenge_id,
        reward=reward,
    )
    return {"claimed": True, "reward": reward}


# ─── 查询接口 ────────────────────────────────────────────────────────────────


async def get_active_challenges(
    db: AsyncSession,
    tenant_id: str,
    page: int = 1,
    size: int = 20,
) -> dict:
    """获取当前进行中的挑战列表"""
    offset = (page - 1) * size
    count_row = await db.execute(
        text("""
            SELECT COUNT(*) FROM challenges
            WHERE tenant_id = :tid AND is_active = true AND is_deleted = false
              AND start_date <= NOW() AND end_date >= NOW()
        """),
        {"tid": tenant_id},
    )
    total = int(count_row.scalar() or 0)

    rows = await db.execute(
        text("""
            SELECT id, name, description, type, rules, reward, badge_id,
                   start_date, end_date, max_participants, current_participants,
                   icon_url, display_order
            FROM challenges
            WHERE tenant_id = :tid AND is_active = true AND is_deleted = false
              AND start_date <= NOW() AND end_date >= NOW()
            ORDER BY display_order, start_date
            LIMIT :lim OFFSET :off
        """),
        {"tid": tenant_id, "lim": size, "off": offset},
    )
    items = [dict(r) for r in rows.mappings().all()]
    return {"items": items, "total": total}


async def get_progress(
    db: AsyncSession,
    tenant_id: str,
    customer_id: str,
    challenge_id: str,
) -> dict:
    """获取会员在某挑战的进度"""
    row = await db.execute(
        text("""
            SELECT cp.id, cp.challenge_id, cp.current_value, cp.target_value,
                   cp.status, cp.progress_detail, cp.joined_at,
                   cp.completed_at, cp.claimed_at, cp.reward_snapshot,
                   c.name AS challenge_name, c.type AS challenge_type
            FROM challenge_progress cp
            JOIN challenges c ON c.id = cp.challenge_id AND c.tenant_id = cp.tenant_id
            WHERE cp.tenant_id = :tid AND cp.customer_id = :cust
              AND cp.challenge_id = :ch AND cp.is_deleted = false
        """),
        {"tid": tenant_id, "cust": customer_id, "ch": challenge_id},
    )
    r = row.mappings().first()
    if not r:
        return {}
    return dict(r)


async def get_customer_challenges(
    db: AsyncSession,
    tenant_id: str,
    customer_id: str,
    status: str | None = None,
) -> list[dict]:
    """获取会员参加的所有挑战和进度"""
    where_extra = " AND cp.status = :st" if status else ""
    params: dict[str, Any] = {"tid": tenant_id, "cust": customer_id}
    if status:
        params["st"] = status

    rows = await db.execute(
        text(f"""
            SELECT cp.id, cp.challenge_id, cp.current_value, cp.target_value,
                   cp.status, cp.joined_at, cp.completed_at, cp.claimed_at,
                   c.name, c.type, c.end_date, c.icon_url, c.reward
            FROM challenge_progress cp
            JOIN challenges c ON c.id = cp.challenge_id AND c.tenant_id = cp.tenant_id
            WHERE cp.tenant_id = :tid AND cp.customer_id = :cust
              AND cp.is_deleted = false{where_extra}
            ORDER BY cp.joined_at DESC
        """),
        params,
    )
    return [dict(r) for r in rows.mappings().all()]


async def get_challenge_participants(
    db: AsyncSession,
    tenant_id: str,
    challenge_id: str,
    page: int = 1,
    size: int = 20,
) -> dict:
    """获取挑战参与者列表"""
    offset = (page - 1) * size
    count_row = await db.execute(
        text("""
            SELECT COUNT(*) FROM challenge_progress
            WHERE tenant_id = :tid AND challenge_id = :ch AND is_deleted = false
        """),
        {"tid": tenant_id, "ch": challenge_id},
    )
    total = int(count_row.scalar() or 0)

    rows = await db.execute(
        text("""
            SELECT customer_id, current_value, target_value, status,
                   joined_at, completed_at, claimed_at
            FROM challenge_progress
            WHERE tenant_id = :tid AND challenge_id = :ch AND is_deleted = false
            ORDER BY current_value DESC, joined_at
            LIMIT :lim OFFSET :off
        """),
        {"tid": tenant_id, "ch": challenge_id, "lim": size, "off": offset},
    )
    items = [dict(r) for r in rows.mappings().all()]
    return {"items": items, "total": total}
