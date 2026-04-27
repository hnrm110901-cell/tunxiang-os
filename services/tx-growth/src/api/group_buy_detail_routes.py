"""拼团详情 & 我的团购 — 真实 DB 版
────────────────────────
GET  /api/v1/group-buy/campaigns/{campaign_id}  — 拼团活动详情
POST /api/v1/group-buy/join                      — 参团
GET  /api/v1/group-buy/my-orders                 — 我的团购记录

v101 表：group_buy_activities / group_buy_teams / group_buy_members
"""

import uuid
from datetime import datetime, timezone
from typing import Any, Optional

import structlog
from fastapi import APIRouter, Depends, Header, Query
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

logger = structlog.get_logger(__name__)

router = APIRouter(tags=["group-buy"])


# ---------------------------------------------------------------------------
# 统一响应
# ---------------------------------------------------------------------------


def ok_response(data: Any) -> dict:
    return {"ok": True, "data": data}


def error_response(code: str, message: str) -> dict:
    return {"ok": False, "error": {"code": code, "message": message}}


# ---------------------------------------------------------------------------
# 内部工具
# ---------------------------------------------------------------------------


async def _set_tenant(db: AsyncSession, tenant_id: str) -> None:
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": tenant_id},
    )


def _is_table_missing(exc: SQLAlchemyError) -> bool:
    msg = str(exc).lower()
    return "does not exist" in msg or ("relation" in msg and "exist" in msg)


# ---------------------------------------------------------------------------
# 请求模型
# ---------------------------------------------------------------------------


class JoinGroupRequest(BaseModel):
    campaign_id: str  # group_buy_activities.id
    team_id: Optional[str] = None  # 指定加入某团，None 则开新团
    customer_id: str
    quantity: int = 1


# ---------------------------------------------------------------------------
# 端点
# ---------------------------------------------------------------------------


@router.get("/api/v1/group-buy/campaigns/{campaign_id}")
async def get_campaign_detail(
    campaign_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """获取拼团活动详情（含进行中的团列表）。"""
    try:
        await _set_tenant(db, x_tenant_id)
        tid = uuid.UUID(x_tenant_id)
        act_id = uuid.UUID(campaign_id)

        # ① 活动基础信息
        act_result = await db.execute(
            text("""
                SELECT id, name, product_id, product_name,
                       original_price_fen, group_price_fen, group_size,
                       max_teams, time_limit_minutes, status,
                       start_time, end_time, team_count, success_count
                FROM group_buy_activities
                WHERE id = :id AND tenant_id = :tid AND is_deleted = false
            """),
            {"id": act_id, "tid": tid},
        )
        act = act_result.fetchone()
        if not act:
            return error_response("NOT_FOUND", f"拼团活动不存在: {campaign_id}")

        # ② 进行中的团（forming 且未过期，最多取 10 个）
        now = datetime.now(timezone.utc)
        teams_result = await db.execute(
            text("""
                SELECT t.id, t.target_size, t.current_size, t.expired_at,
                       t.created_at
                FROM group_buy_teams t
                WHERE t.tenant_id = :tid
                  AND t.activity_id = :act_id
                  AND t.status = 'forming'
                  AND t.expired_at > :now
                  AND t.is_deleted = false
                ORDER BY t.created_at DESC
                LIMIT 10
            """),
            {"tid": tid, "act_id": act_id, "now": now},
        )
        teams = []
        for t in teams_result.fetchall():
            # 获取团成员（只取 nickname 概要）
            members_result = await db.execute(
                text("""
                    SELECT customer_id, joined_at
                    FROM group_buy_members
                    WHERE tenant_id = :tid AND team_id = :team_id AND is_deleted = false
                    ORDER BY joined_at ASC
                """),
                {"tid": tid, "team_id": t.id},
            )
            members = [
                {"customer_id": str(m.customer_id), "joined_at": m.joined_at.isoformat() if m.joined_at else None}
                for m in members_result.fetchall()
            ]
            teams.append(
                {
                    "team_id": str(t.id),
                    "target_size": t.target_size,
                    "current_size": t.current_size,
                    "expired_at": t.expired_at.isoformat() if t.expired_at else None,
                    "members": members,
                }
            )

        campaign_data = {
            "id": str(act.id),
            "name": act.name,
            "product_id": str(act.product_id) if act.product_id else None,
            "product_name": act.product_name,
            "status": act.status,
            "original_price_fen": act.original_price_fen,
            "group_price_fen": act.group_price_fen,
            "group_size": act.group_size,
            "max_teams": act.max_teams,
            "time_limit_minutes": act.time_limit_minutes,
            "start_time": act.start_time.isoformat() if act.start_time else None,
            "end_time": act.end_time.isoformat() if act.end_time else None,
            "team_count": act.team_count,
            "success_count": act.success_count,
            "forming_teams": teams,
        }
        return ok_response(campaign_data)

    except ValueError as exc:
        return error_response("INVALID_PARAM", f"参数格式错误: {exc}")
    except SQLAlchemyError as exc:
        if _is_table_missing(exc):
            logger.warning("group_buy.table_not_ready", error=str(exc))
            return error_response("TABLE_NOT_READY", "拼团功能尚未初始化")
        logger.error("group_buy.detail_error", error=str(exc), exc_info=True)
        return error_response("DB_ERROR", "查询拼团详情失败")


@router.post("/api/v1/group-buy/join")
async def join_group(
    req: JoinGroupRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """参团

    逻辑：
    1. 校验活动状态（active + 未过期）
    2. 若无指定 team_id，新建一个团
    3. 若指定 team_id，校验团状态并加入
    4. 写入 group_buy_members 记录
    5. 团满则更新 team.status='succeeded'
    """
    try:
        await _set_tenant(db, x_tenant_id)
        tid = uuid.UUID(x_tenant_id)
        act_id = uuid.UUID(req.campaign_id)
        cid = uuid.UUID(req.customer_id)
        now = datetime.now(timezone.utc)

        # ① 校验活动
        act_result = await db.execute(
            text("""
                SELECT id, status, group_size, max_teams, team_count,
                       time_limit_minutes, end_time
                FROM group_buy_activities
                WHERE id = :id AND tenant_id = :tid AND is_deleted = false
                FOR UPDATE
            """),
            {"id": act_id, "tid": tid},
        )
        act = act_result.fetchone()
        if not act:
            return error_response("NOT_FOUND", "拼团活动不存在")
        if act.status != "active":
            return error_response("NOT_ACTIVE", f"活动当前状态: {act.status}")
        if act.end_time and act.end_time < now:
            return error_response("EXPIRED", "活动已结束")

        if req.team_id:
            # ── 加入已有团 ──
            team_uuid = uuid.UUID(req.team_id)
            team_result = await db.execute(
                text("""
                    SELECT id, current_size, target_size, status, expired_at
                    FROM group_buy_teams
                    WHERE id = :team_id AND tenant_id = :tid
                      AND activity_id = :act_id AND is_deleted = false
                    FOR UPDATE
                """),
                {"team_id": team_uuid, "tid": tid, "act_id": act_id},
            )
            team = team_result.fetchone()
            if not team:
                return error_response("TEAM_NOT_FOUND", "团不存在")
            if team.status != "forming":
                return error_response("TEAM_NOT_FORMING", f"团当前状态: {team.status}")
            if team.expired_at and team.expired_at < now:
                return error_response("TEAM_EXPIRED", "该团已过期")
            if team.current_size >= team.target_size:
                return error_response("TEAM_FULL", "该团已满")

            # 幂等检查
            dup_result = await db.execute(
                text("""
                    SELECT id FROM group_buy_members
                    WHERE tenant_id = :tid AND team_id = :team_id AND customer_id = :cid
                      AND is_deleted = false
                """),
                {"tid": tid, "team_id": team_uuid, "cid": cid},
            )
            if dup_result.fetchone():
                return error_response("ALREADY_JOINED", "已加入该团")

            team_id_val = team_uuid
            new_size = team.current_size + 1
            target = team.target_size
        else:
            # ── 开新团 ──
            if act.team_count >= act.max_teams:
                return error_response("MAX_TEAMS", "活动开团数已达上限")

            from datetime import timedelta

            team_id_val = uuid.uuid4()
            expired_at = now + timedelta(minutes=act.time_limit_minutes)

            await db.execute(
                text("""
                    INSERT INTO group_buy_teams
                        (id, tenant_id, activity_id, initiator_id,
                         target_size, current_size, status, expired_at)
                    VALUES
                        (:id, :tid, :act_id, :cid,
                         :target, 1, 'forming', :expired_at)
                """),
                {
                    "id": team_id_val,
                    "tid": tid,
                    "act_id": act_id,
                    "cid": cid,
                    "target": act.group_size,
                    "expired_at": expired_at,
                },
            )

            # 递增活动 team_count
            await db.execute(
                text("""
                    UPDATE group_buy_activities
                    SET team_count = team_count + 1, updated_at = NOW()
                    WHERE id = :act_id AND tenant_id = :tid
                """),
                {"act_id": act_id, "tid": tid},
            )

            new_size = 1
            target = act.group_size

        # ② 写入成员记录
        member_id = uuid.uuid4()
        await db.execute(
            text("""
                INSERT INTO group_buy_members
                    (id, tenant_id, team_id, customer_id, joined_at)
                VALUES
                    (:id, :tid, :team_id, :cid, :now)
            """),
            {"id": member_id, "tid": tid, "team_id": team_id_val, "cid": cid, "now": now},
        )

        # ③ 若是加入已有团，递增 current_size
        if req.team_id:
            await db.execute(
                text("""
                    UPDATE group_buy_teams
                    SET current_size = current_size + 1, updated_at = NOW()
                    WHERE id = :team_id AND tenant_id = :tid
                """),
                {"team_id": team_id_val, "tid": tid},
            )

        # ④ 检查是否满团
        team_status = "forming"
        if new_size >= target:
            team_status = "succeeded"
            await db.execute(
                text("""
                    UPDATE group_buy_teams
                    SET status = 'succeeded', succeeded_at = :now, updated_at = NOW()
                    WHERE id = :team_id AND tenant_id = :tid
                """),
                {"team_id": team_id_val, "tid": tid, "now": now},
            )
            # 递增活动 success_count
            await db.execute(
                text("""
                    UPDATE group_buy_activities
                    SET success_count = success_count + 1, updated_at = NOW()
                    WHERE id = :act_id AND tenant_id = :tid
                """),
                {"act_id": act_id, "tid": tid},
            )

        await db.commit()

        logger.info(
            "group_buy.joined",
            team_id=str(team_id_val),
            customer_id=str(cid),
            team_status=team_status,
            tenant_id=x_tenant_id,
        )
        return ok_response(
            {
                "member_id": str(member_id),
                "team_id": str(team_id_val),
                "campaign_id": str(act_id),
                "current_size": new_size,
                "target_size": target,
                "status": team_status,
            }
        )

    except ValueError as exc:
        return error_response("INVALID_PARAM", f"参数格式错误: {exc}")
    except SQLAlchemyError as exc:
        await db.rollback()
        if _is_table_missing(exc):
            logger.warning("group_buy.table_not_ready", error=str(exc))
            return error_response("TABLE_NOT_READY", "拼团功能尚未初始化")
        logger.error("group_buy.join_error", error=str(exc), exc_info=True)
        return error_response("DB_ERROR", "参团失败，请稍后重试")


@router.get("/api/v1/group-buy/my-orders")
async def get_my_orders(
    customer_id: str,
    status: str = Query("forming", description="筛选状态：forming / succeeded / expired / cancelled"),
    page: int = Query(1, ge=1),
    size: int = Query(10, ge=1, le=50),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """获取我的团购记录"""
    try:
        await _set_tenant(db, x_tenant_id)
        tid = uuid.UUID(x_tenant_id)
        cid = uuid.UUID(customer_id)
        offset = (page - 1) * size

        # 映射前端 status 到团队 status
        status_map = {
            "active": "forming",
            "forming": "forming",
            "completed": "succeeded",
            "succeeded": "succeeded",
            "cancelled": "cancelled",
            "expired": "expired",
        }
        db_status = status_map.get(status, status)

        count_result = await db.execute(
            text("""
                SELECT COUNT(*)
                FROM group_buy_members m
                JOIN group_buy_teams t ON t.id = m.team_id AND t.tenant_id = m.tenant_id
                WHERE m.tenant_id = :tid
                  AND m.customer_id = :cid
                  AND t.status = :status
                  AND m.is_deleted = false
                  AND t.is_deleted = false
            """),
            {"tid": tid, "cid": cid, "status": db_status},
        )
        total = count_result.scalar() or 0

        result = await db.execute(
            text("""
                SELECT t.id AS team_id, t.activity_id, t.target_size, t.current_size,
                       t.status AS team_status, t.expired_at, t.succeeded_at,
                       a.name AS activity_name, a.group_price_fen, a.original_price_fen,
                       a.product_name, m.joined_at
                FROM group_buy_members m
                JOIN group_buy_teams t ON t.id = m.team_id AND t.tenant_id = m.tenant_id
                JOIN group_buy_activities a ON a.id = t.activity_id AND a.tenant_id = t.tenant_id
                WHERE m.tenant_id = :tid
                  AND m.customer_id = :cid
                  AND t.status = :status
                  AND m.is_deleted = false
                  AND t.is_deleted = false
                ORDER BY m.joined_at DESC
                LIMIT :limit OFFSET :offset
            """),
            {"tid": tid, "cid": cid, "status": db_status, "limit": size, "offset": offset},
        )
        rows = result.fetchall()
        items = [
            {
                "team_id": str(r.team_id),
                "activity_id": str(r.activity_id),
                "name": r.activity_name,
                "product_name": r.product_name,
                "group_price_fen": r.group_price_fen,
                "original_price_fen": r.original_price_fen,
                "target_size": r.target_size,
                "current_size": r.current_size,
                "status": r.team_status,
                "expired_at": r.expired_at.isoformat() if r.expired_at else None,
                "succeeded_at": r.succeeded_at.isoformat() if r.succeeded_at else None,
                "joined_at": r.joined_at.isoformat() if r.joined_at else None,
            }
            for r in rows
        ]
        return ok_response({"items": items, "total": total, "page": page, "size": size})

    except ValueError as exc:
        return error_response("INVALID_PARAM", f"参数格式错误: {exc}")
    except SQLAlchemyError as exc:
        if _is_table_missing(exc):
            logger.warning("group_buy.table_not_ready", error=str(exc))
            return ok_response({"items": [], "total": 0, "page": page, "size": size, "_note": "TABLE_NOT_READY"})
        logger.error("group_buy.my_orders_error", error=str(exc), exc_info=True)
        return error_response("DB_ERROR", "查询团购记录失败")
