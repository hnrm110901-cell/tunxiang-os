"""邀请有礼 API 端点

3 个端点：
  GET  /api/v1/member/invite/my-code     → 获取我的邀请码 + 邀请人数 + 奖励规则
  GET  /api/v1/member/invite/records     → 邀请记录列表（分页）
  POST /api/v1/member/invite/claim       → 新用户使用邀请码（触发积分发放）

数据表：invite_codes / invite_records（v146 迁移）
"""

from typing import Any

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/api/v1/member/invite", tags=["member-invite"])


# ── 邀请奖励规则（静态配置，后续可从 DB 拉取） ────────────────────
_REWARD_RULES: list[dict[str, Any]] = [
    {
        "id": "rule-1",
        "title": "邀请1位好友",
        "desc": "好友完成首次消费后积分自动到账",
        "points": 50,
    },
    {
        "id": "rule-2",
        "title": "邀请5位好友",
        "desc": "累计邀请满5人，额外赠送积分",
        "points": 300,
    },
    {
        "id": "rule-3",
        "title": "邀请10位好友",
        "desc": "达成邀请达人成就，解锁专属奖励",
        "points": 800,
    },
    {
        "id": "rule-4",
        "title": "被邀请好友奖励",
        "desc": "使用邀请码注册并完成首次消费",
        "points": 50,
    },
]

# 每次邀请成功双方获得积分（pending 状态，首单后结算）
_INVITER_POINTS = 50
_INVITEE_POINTS = 50


# ── 请求模型 ──────────────────────────────────────────────────


class ClaimInviteRequest(BaseModel):
    invite_code: str = Field(..., description="邀请码")
    new_member_id: str = Field(..., description="新注册会员ID（UUID）")


# ── 辅助函数 ──────────────────────────────────────────────────


async def _set_rls(db: AsyncSession, tenant_id: str) -> None:
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": tenant_id},
    )


def _generate_code(member_id: str) -> str:
    """根据 member_id 生成确定性邀请码（TX + 6字符）"""
    chars = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    seed = abs(hash(member_id or "default")) if member_id else 12345678
    code = ""
    for _ in range(6):
        code += chars[seed % len(chars)]
        seed = seed // len(chars) + (seed % 7) * 31
    return "TX" + code


# ── 端点 ──────────────────────────────────────────────────────


@router.get("/my-code")
async def get_my_invite_code(
    member_id: str = Query(..., description="会员ID（UUID）"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """
    获取（或创建）我的邀请码 + 已邀请人数 + 奖励规则。

    首次调用时在 invite_codes 中创建一条记录。
    返回格式：
      {"ok": true, "data": {"code": "TX8A3F9K", "invited_count": 3, "reward_rules": [...]}}
    """
    if not x_tenant_id:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header is required")
    if not member_id:
        raise HTTPException(status_code=400, detail="member_id is required")

    logger.info("invite.my_code", member_id=member_id, tenant_id=x_tenant_id)

    try:
        await _set_rls(db, x_tenant_id)

        # 查询已有邀请码
        row = await db.execute(
            text("""
                SELECT code, invited_count, total_points_earned
                FROM invite_codes
                WHERE tenant_id = :tid AND member_id = :mid AND is_active = true
                LIMIT 1
            """),
            {"tid": x_tenant_id, "mid": member_id},
        )
        existing = row.first()

        if existing:
            code = existing[0]
            invited_count = existing[1]
            total_points = existing[2]
        else:
            # 首次：生成并写入邀请码
            code = _generate_code(member_id)
            await db.execute(
                text("""
                    INSERT INTO invite_codes
                        (tenant_id, member_id, code, invited_count, total_points_earned)
                    VALUES (:tid, :mid, :code, 0, 0)
                    ON CONFLICT (tenant_id, member_id) DO NOTHING
                """),
                {"tid": x_tenant_id, "mid": member_id, "code": code},
            )
            await db.commit()
            invited_count = 0
            total_points = 0

        logger.info(
            "invite.my_code.ok",
            member_id=member_id,
            code=code,
            invited_count=invited_count,
        )
        return {
            "ok": True,
            "data": {
                "code": code,
                "invite_code": code,
                "invited_count": invited_count,
                "total_points_earned": total_points,
                "reward_rules": _REWARD_RULES,
            },
        }

    except SQLAlchemyError as exc:
        logger.error("invite.my_code.db_error", exc_info=True, error=str(exc))
        return {
            "ok": True,
            "data": {"code": "", "invited_count": 0, "reward_rules": _REWARD_RULES},
        }


@router.get("/records")
async def get_invite_records(
    member_id: str = Query(..., description="会员ID（UUID）"),
    page: int = Query(1, ge=1, description="页码"),
    size: int = Query(20, ge=1, le=100, description="每页数量"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """
    获取邀请记录列表（分页）+ 汇总统计。

    返回格式：
      {"ok": true, "data": {"summary": {...}, "items": [...], "total": N}}
    """
    if not x_tenant_id:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header is required")

    logger.info(
        "invite.records",
        member_id=member_id,
        page=page,
        size=size,
        tenant_id=x_tenant_id,
    )

    try:
        await _set_rls(db, x_tenant_id)

        # 汇总统计
        summary_row = await db.execute(
            text("""
                SELECT
                    COUNT(*)                                                              AS invited_count,
                    COALESCE(SUM(inviter_points) FILTER (WHERE status = 'credited'), 0)  AS earned_points,
                    COALESCE(SUM(inviter_points) FILTER (WHERE status = 'pending'), 0)   AS pending_points
                FROM invite_records
                WHERE tenant_id = :tid AND inviter_member_id = :mid
            """),
            {"tid": x_tenant_id, "mid": member_id},
        )
        s = summary_row.first()
        summary: dict[str, Any] = {
            "invited_count": s[0] or 0,
            "earned_points": s[1] or 0,
            "pending_points": s[2] or 0,
        }

        # 总数
        cnt_row = await db.execute(
            text("""
                SELECT COUNT(*) FROM invite_records
                WHERE tenant_id = :tid AND inviter_member_id = :mid
            """),
            {"tid": x_tenant_id, "mid": member_id},
        )
        total: int = cnt_row.scalar() or 0

        # 明细（left join customers 取 nickname）
        offset = (page - 1) * size
        rows = await db.execute(
            text("""
                SELECT
                    ir.id,
                    COALESCE(c.nickname, '用户' || LEFT(ir.invitee_member_id::text, 6)) AS nickname,
                    ir.created_at,
                    ir.inviter_points                                                    AS reward_points,
                    ir.status
                FROM invite_records ir
                LEFT JOIN customers c
                    ON c.id = ir.invitee_member_id AND c.tenant_id = ir.tenant_id
                WHERE ir.tenant_id = :tid AND ir.inviter_member_id = :mid
                ORDER BY ir.created_at DESC
                LIMIT :lim OFFSET :off
            """),
            {"tid": x_tenant_id, "mid": member_id, "lim": size, "off": offset},
        )

        items = [
            {
                "id": str(row[0]),
                "nickname": row[1] or "匿名用户",
                "register_time": row[2].strftime("%Y-%m-%d %H:%M") if row[2] else "",
                "reward_points": row[3] or 0,
                "status": row[4] or "pending",
            }
            for row in rows.all()
        ]

        logger.info("invite.records.ok", member_id=member_id, total=total)
        return {
            "ok": True,
            "data": {
                "summary": summary,
                "items": items,
                "total": total,
            },
        }

    except SQLAlchemyError as exc:
        logger.error("invite.records.db_error", exc_info=True, error=str(exc))
        return {"ok": True, "data": {"summary": {}, "items": [], "total": 0}}


@router.post("/claim")
async def claim_invite(
    payload: ClaimInviteRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """
    新用户使用邀请码注册 → 创建邀请关系（status=pending），首单后变 credited。

    防刷：DB 唯一约束（tenant_id + invitee_member_id），确保每人只能被邀请一次。
    """
    if not x_tenant_id:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header is required")

    logger.info(
        "invite.claim",
        invite_code=payload.invite_code,
        new_member_id=payload.new_member_id,
        tenant_id=x_tenant_id,
    )

    try:
        await _set_rls(db, x_tenant_id)

        # 1. 根据邀请码查找邀请码记录
        code_row = await db.execute(
            text("""
                SELECT id, member_id
                FROM invite_codes
                WHERE code = :code AND tenant_id = :tid AND is_active = true
                LIMIT 1
            """),
            {"code": payload.invite_code, "tid": x_tenant_id},
        )
        code_rec = code_row.first()
        if not code_rec:
            raise HTTPException(status_code=404, detail="邀请码无效或已失效")

        invite_code_id = str(code_rec[0])
        inviter_member_id = str(code_rec[1])

        # 2. 防止自己邀请自己
        if inviter_member_id == payload.new_member_id:
            raise HTTPException(status_code=400, detail="不能使用自己的邀请码")

        # 3. 创建邀请记录（唯一约束防重复）
        await db.execute(
            text("""
                INSERT INTO invite_records
                    (tenant_id, invite_code_id, inviter_member_id, invitee_member_id,
                     invite_code, status, inviter_points, invitee_points)
                VALUES
                    (:tid, :code_id, :inviter, :invitee,
                     :code, 'pending', :ipts, :epts)
            """),
            {
                "tid": x_tenant_id,
                "code_id": invite_code_id,
                "inviter": inviter_member_id,
                "invitee": payload.new_member_id,
                "code": payload.invite_code,
                "ipts": _INVITER_POINTS,
                "epts": _INVITEE_POINTS,
            },
        )

        # 4. 更新邀请码使用计数
        await db.execute(
            text("""
                UPDATE invite_codes
                SET invited_count = invited_count + 1,
                    updated_at    = NOW()
                WHERE id = :code_id AND tenant_id = :tid
            """),
            {"code_id": invite_code_id, "tid": x_tenant_id},
        )

        await db.commit()

        logger.info(
            "invite.claim.ok",
            invite_code=payload.invite_code,
            inviter_member_id=inviter_member_id,
            new_member_id=payload.new_member_id,
        )
        return {
            "ok": True,
            "data": {
                "inviter_points_granted": _INVITER_POINTS,
                "invitee_points_granted": _INVITEE_POINTS,
                "message": "邀请成功，积分将在好友首次消费后发放",
            },
        }

    except HTTPException:
        raise
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="该用户已使用过邀请码")
    except SQLAlchemyError as exc:
        await db.rollback()
        logger.error("invite.claim.db_error", exc_info=True, error=str(exc))
        raise HTTPException(status_code=500, detail="服务暂时不可用，请稍后重试")
