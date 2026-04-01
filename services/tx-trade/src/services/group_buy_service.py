"""拼团服务 — 活动管理 / 开团 / 参团 / 成团 / 超时处理

所有金额单位：分(fen)。
并发安全：参团使用 SELECT ... FOR UPDATE 行锁防止超员。
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger(__name__)


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


async def _set_tenant(db: AsyncSession, tenant_id: str) -> None:
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": tenant_id},
    )


# ═══════════════════════════════════════════════════════════════
# 1. 拼团活动 CRUD
# ═══════════════════════════════════════════════════════════════

async def create_activity(
    name: str,
    product_id: str,
    product_name: str,
    original_price_fen: int,
    group_price_fen: int,
    group_size: int,
    time_limit_minutes: int,
    max_teams: int,
    start_time: Optional[str],
    end_time: Optional[str],
    tenant_id: str,
    db: AsyncSession,
) -> dict[str, Any]:
    """创建拼团活动"""
    await _set_tenant(db, tenant_id)

    if group_price_fen >= original_price_fen:
        raise ValueError("group_price_fen must be less than original_price_fen")
    if group_size < 2:
        raise ValueError("group_size must be >= 2")

    activity_id = uuid.uuid4()
    now = _now_utc()

    await db.execute(
        text("""
            INSERT INTO group_buy_activities
                (id, tenant_id, name, product_id, product_name,
                 original_price_fen, group_price_fen, group_size,
                 max_teams, time_limit_minutes, status,
                 start_time, end_time, created_at, updated_at)
            VALUES
                (:id, :tid, :name, :pid, :pname,
                 :orig, :gprice, :gsize,
                 :max_teams, :tlimit, 'active',
                 :start, :end, :now, :now)
        """),
        {
            "id": activity_id,
            "tid": uuid.UUID(tenant_id),
            "name": name,
            "pid": uuid.UUID(product_id),
            "pname": product_name,
            "orig": original_price_fen,
            "gprice": group_price_fen,
            "gsize": group_size,
            "max_teams": max_teams,
            "tlimit": time_limit_minutes,
            "start": start_time,
            "end": end_time,
            "now": now,
        },
    )
    await db.flush()
    logger.info("group_buy.activity_created", activity_id=str(activity_id), name=name)
    return {
        "activity_id": str(activity_id),
        "name": name,
        "product_id": product_id,
        "group_price_fen": group_price_fen,
        "original_price_fen": original_price_fen,
        "group_size": group_size,
        "status": "active",
    }


async def list_activities(
    tenant_id: str,
    db: AsyncSession,
    status: Optional[str] = None,
    page: int = 1,
    size: int = 20,
) -> dict[str, Any]:
    """拼团活动列表"""
    await _set_tenant(db, tenant_id)
    tid = uuid.UUID(tenant_id)
    offset = (page - 1) * size

    count_sql = """
        SELECT COUNT(*) FROM group_buy_activities
        WHERE tenant_id = :tid AND is_deleted = false
    """
    query_sql = """
        SELECT id, name, product_id, product_name, original_price_fen,
               group_price_fen, group_size, max_teams, time_limit_minutes,
               status, team_count, success_count, start_time, end_time,
               created_at
        FROM group_buy_activities
        WHERE tenant_id = :tid AND is_deleted = false
    """
    params: dict[str, Any] = {"tid": tid}

    if status:
        count_sql += " AND status = :status"
        query_sql += " AND status = :status"
        params["status"] = status

    total_row = await db.execute(text(count_sql), params)
    total = total_row.scalar() or 0

    query_sql += " ORDER BY created_at DESC LIMIT :lim OFFSET :off"
    params["lim"] = size
    params["off"] = offset
    rows = await db.execute(text(query_sql), params)

    items = []
    for r in rows:
        items.append({
            "activity_id": str(r.id),
            "name": r.name,
            "product_id": str(r.product_id),
            "product_name": r.product_name,
            "original_price_fen": r.original_price_fen,
            "group_price_fen": r.group_price_fen,
            "group_size": r.group_size,
            "status": r.status,
            "team_count": r.team_count,
            "success_count": r.success_count,
        })
    return {"items": items, "total": total, "page": page, "size": size}


# ═══════════════════════════════════════════════════════════════
# 2. 开团 / 参团
# ═══════════════════════════════════════════════════════════════

async def create_team(
    activity_id: str,
    initiator_id: str,
    tenant_id: str,
    db: AsyncSession,
) -> dict[str, Any]:
    """发起拼团（开团）"""
    await _set_tenant(db, tenant_id)
    tid = uuid.UUID(tenant_id)
    aid = uuid.UUID(activity_id)

    # 查活动详情
    row = await db.execute(
        text("""
            SELECT id, group_size, time_limit_minutes, max_teams, team_count, status
            FROM group_buy_activities
            WHERE id = :aid AND tenant_id = :tid AND is_deleted = false
            FOR UPDATE
        """),
        {"aid": aid, "tid": tid},
    )
    activity = row.fetchone()
    if not activity:
        raise ValueError("activity_not_found")
    if activity.status != "active":
        raise ValueError("activity_not_active")
    if activity.team_count >= activity.max_teams:
        raise ValueError("max_teams_reached")

    team_id = uuid.uuid4()
    now = _now_utc()
    expired_at = now + timedelta(minutes=activity.time_limit_minutes)

    # 创建团队
    await db.execute(
        text("""
            INSERT INTO group_buy_teams
                (id, tenant_id, activity_id, initiator_id, target_size,
                 current_size, status, expired_at, created_at, updated_at)
            VALUES
                (:id, :tid, :aid, :uid, :target, 1, 'forming', :expired, :now, :now)
        """),
        {
            "id": team_id, "tid": tid, "aid": aid,
            "uid": uuid.UUID(initiator_id),
            "target": activity.group_size,
            "expired": expired_at, "now": now,
        },
    )

    # 写入发起人为第一个成员
    await db.execute(
        text("""
            INSERT INTO group_buy_members
                (id, tenant_id, team_id, customer_id, paid, joined_at)
            VALUES
                (:id, :tid, :team_id, :uid, false, :now)
        """),
        {
            "id": uuid.uuid4(), "tid": tid, "team_id": team_id,
            "uid": uuid.UUID(initiator_id), "now": now,
        },
    )

    # 原子递增活动开团数
    await db.execute(
        text("""
            UPDATE group_buy_activities
            SET team_count = team_count + 1, updated_at = NOW()
            WHERE id = :aid AND tenant_id = :tid
        """),
        {"aid": aid, "tid": tid},
    )
    await db.flush()

    logger.info("group_buy.team_created", team_id=str(team_id), activity_id=activity_id)
    return {
        "team_id": str(team_id),
        "activity_id": activity_id,
        "initiator_id": initiator_id,
        "current_size": 1,
        "target_size": activity.group_size,
        "status": "forming",
        "expired_at": expired_at.isoformat(),
    }


async def join_team(
    team_id: str,
    customer_id: str,
    tenant_id: str,
    db: AsyncSession,
) -> dict[str, Any]:
    """参与拼团 — 使用行锁防止并发超员"""
    await _set_tenant(db, tenant_id)
    tid = uuid.UUID(tenant_id)
    tmid = uuid.UUID(team_id)
    uid = uuid.UUID(customer_id)
    now = _now_utc()

    # 行锁查询团队
    row = await db.execute(
        text("""
            SELECT id, activity_id, current_size, target_size, status, expired_at
            FROM group_buy_teams
            WHERE id = :id AND tenant_id = :tid AND is_deleted = false
            FOR UPDATE
        """),
        {"id": tmid, "tid": tid},
    )
    team = row.fetchone()
    if not team:
        raise ValueError("team_not_found")
    if team.status != "forming":
        raise ValueError(f"team_status_invalid:{team.status}")
    if now > team.expired_at:
        raise ValueError("team_expired")
    if team.current_size >= team.target_size:
        raise ValueError("team_full")

    # 检查是否已参团
    dup_row = await db.execute(
        text("""
            SELECT id FROM group_buy_members
            WHERE team_id = :tmid AND customer_id = :uid AND is_deleted = false
        """),
        {"tmid": tmid, "uid": uid},
    )
    if dup_row.fetchone():
        raise ValueError("already_joined")

    # 加入成员
    await db.execute(
        text("""
            INSERT INTO group_buy_members
                (id, tenant_id, team_id, customer_id, paid, joined_at)
            VALUES
                (:id, :tid, :tmid, :uid, false, :now)
        """),
        {"id": uuid.uuid4(), "tid": tid, "tmid": tmid, "uid": uid, "now": now},
    )

    new_size = team.current_size + 1
    succeeded = new_size >= team.target_size

    # 更新团队人数（可能触发成团）
    update_sql = """
        UPDATE group_buy_teams
        SET current_size = :new_size, updated_at = NOW()
    """
    if succeeded:
        update_sql += ", status = 'succeeded', succeeded_at = NOW()"
    update_sql += " WHERE id = :id AND tenant_id = :tid"

    await db.execute(text(update_sql), {"new_size": new_size, "id": tmid, "tid": tid})

    # 成团：递增活动成功数
    if succeeded:
        await db.execute(
            text("""
                UPDATE group_buy_activities
                SET success_count = success_count + 1, updated_at = NOW()
                WHERE id = :aid AND tenant_id = :tid
            """),
            {"aid": team.activity_id, "tid": tid},
        )

    await db.flush()
    logger.info(
        "group_buy.member_joined",
        team_id=team_id, customer_id=customer_id,
        new_size=new_size, succeeded=succeeded,
    )

    return {
        "team_id": team_id,
        "customer_id": customer_id,
        "current_size": new_size,
        "target_size": team.target_size,
        "status": "succeeded" if succeeded else "forming",
        "succeeded": succeeded,
    }


async def get_team_detail(
    team_id: str, tenant_id: str, db: AsyncSession,
) -> Optional[dict[str, Any]]:
    """查询拼团详情（含成员列表）"""
    await _set_tenant(db, tenant_id)
    tid = uuid.UUID(tenant_id)
    tmid = uuid.UUID(team_id)

    row = await db.execute(
        text("""
            SELECT t.id, t.activity_id, t.initiator_id, t.current_size,
                   t.target_size, t.status, t.expired_at, t.succeeded_at, t.created_at,
                   a.name AS activity_name, a.product_name,
                   a.group_price_fen, a.original_price_fen
            FROM group_buy_teams t
            JOIN group_buy_activities a ON a.id = t.activity_id
            WHERE t.id = :id AND t.tenant_id = :tid AND t.is_deleted = false
        """),
        {"id": tmid, "tid": tid},
    )
    team = row.fetchone()
    if not team:
        return None

    members_row = await db.execute(
        text("""
            SELECT customer_id, paid, joined_at
            FROM group_buy_members
            WHERE team_id = :tmid AND tenant_id = :tid AND is_deleted = false
            ORDER BY joined_at
        """),
        {"tmid": tmid, "tid": tid},
    )
    members = [
        {
            "customer_id": str(m.customer_id),
            "paid": m.paid,
            "joined_at": m.joined_at.isoformat(),
        }
        for m in members_row
    ]

    return {
        "team_id": str(team.id),
        "activity_id": str(team.activity_id),
        "activity_name": team.activity_name,
        "product_name": team.product_name,
        "group_price_fen": team.group_price_fen,
        "original_price_fen": team.original_price_fen,
        "initiator_id": str(team.initiator_id),
        "current_size": team.current_size,
        "target_size": team.target_size,
        "status": team.status,
        "expired_at": team.expired_at.isoformat(),
        "succeeded_at": team.succeeded_at.isoformat() if team.succeeded_at else None,
        "members": members,
    }


# ═══════════════════════════════════════════════════════════════
# 3. 超时处理（定时任务调用）
# ═══════════════════════════════════════════════════════════════

async def expire_teams(
    tenant_id: str, db: AsyncSession,
) -> dict[str, Any]:
    """批量过期超时未成团的团队 — 定时任务每分钟调用"""
    await _set_tenant(db, tenant_id)
    tid = uuid.UUID(tenant_id)
    now = _now_utc()

    result = await db.execute(
        text("""
            UPDATE group_buy_teams
            SET status = 'expired', updated_at = NOW()
            WHERE tenant_id = :tid
              AND status = 'forming'
              AND expired_at < :now
              AND is_deleted = false
            RETURNING id
        """),
        {"tid": tid, "now": now},
    )
    expired_ids = [str(r.id) for r in result.fetchall()]
    if expired_ids:
        logger.info("group_buy.teams_expired", count=len(expired_ids), tenant_id=tenant_id)
    return {"expired_count": len(expired_ids), "expired_team_ids": expired_ids}
