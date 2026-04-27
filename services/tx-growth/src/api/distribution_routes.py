"""
CRM三级分销路由 — 私域裂变三级链路 + 奖励体系

端点列表：
  POST   /api/v1/growth/referral/links                  生成推荐码
  GET    /api/v1/growth/referral/links/{member_id}       获取会员推荐码
  POST   /api/v1/growth/referral/bind                   绑定推荐关系（自动推导三级）
  GET    /api/v1/growth/referral/tree/{member_id}        查看推荐关系树
  POST   /api/v1/growth/referral/rewards/calculate       触发奖励计算
  POST   /api/v1/growth/referral/rewards/issue/{reward_id}  发放奖励
  GET    /api/v1/growth/referral/rewards/{member_id}     会员分销收益明细
  GET    /api/v1/growth/referral/stats                   分销总览
  GET    /api/v1/growth/referral/leaderboard             分销排行榜
  POST   /api/v1/growth/referral/rules                   保存分销规则配置
  GET    /api/v1/growth/referral/rules                   获取分销规则配置
  POST   /api/v1/growth/referral/detect-abuse            异常检测
"""

import random
import string
import uuid
from datetime import datetime
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, field_validator
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/growth/referral", tags=["distribution"])


# ---------------------------------------------------------------------------
# 统一响应
# ---------------------------------------------------------------------------


def ok(data: object) -> dict:
    return {"ok": True, "data": data}


def err(msg: str, code: str = "ERROR") -> dict:
    return {"ok": False, "error": {"code": code, "message": msg}}


# ---------------------------------------------------------------------------
# Pydantic 请求模型
# ---------------------------------------------------------------------------


class GenerateLinkRequest(BaseModel):
    member_id: str
    channel: str = "wechat"
    expires_at: Optional[str] = None  # ISO8601，None=永久

    @field_validator("channel")
    @classmethod
    def validate_channel(cls, v: str) -> str:
        allowed = {"wechat", "wecom", "direct"}
        if v not in allowed:
            raise ValueError(f"channel 必须是 {allowed} 之一")
        return v


class BindRequest(BaseModel):
    referee_id: str  # 新会员 ID
    referral_code: str  # 使用的推荐码


class CalculateRewardRequest(BaseModel):
    order_id: str
    member_id: str  # 消费会员（触发奖励的人）
    order_amount_fen: int

    @field_validator("order_amount_fen")
    @classmethod
    def validate_amount(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("订单金额必须大于0")
        return v


class SaveRulesRequest(BaseModel):
    level1_rate: float  # 一级佣金比例，如 0.03 = 3%
    level2_rate: float  # 二级佣金比例
    level3_rate: float  # 三级佣金比例
    reward_type: str  # coupon/points/cash
    trigger_type: str  # first_order/order/recharge

    @field_validator("level1_rate", "level2_rate", "level3_rate")
    @classmethod
    def validate_rate(cls, v: float) -> float:
        if not (0.0 <= v <= 1.0):
            raise ValueError("佣金比例必须在 0~1 之间")
        return v

    @field_validator("reward_type")
    @classmethod
    def validate_reward_type(cls, v: str) -> str:
        allowed = {"coupon", "points", "cash"}
        if v not in allowed:
            raise ValueError(f"reward_type 必须是 {allowed} 之一")
        return v

    @field_validator("trigger_type")
    @classmethod
    def validate_trigger_type(cls, v: str) -> str:
        allowed = {"first_order", "order", "recharge"}
        if v not in allowed:
            raise ValueError(f"trigger_type 必须是 {allowed} 之一")
        return v


class DetectAbuseRequest(BaseModel):
    referee_id: str
    referral_code: str
    device_id: Optional[str] = None
    ip: Optional[str] = None


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------


def _generate_code() -> str:
    """生成6字符推荐码，TX前缀+4位大写字母数字"""
    chars = string.ascii_uppercase + string.digits
    suffix = "".join(random.choices(chars, k=4))
    return f"TX{suffix}"


def _now_iso() -> str:
    return datetime.utcnow().isoformat() + "Z"


async def _set_tenant(db: AsyncSession, tenant_id: str) -> None:
    """设置 RLS 租户上下文"""
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": tenant_id},
    )


_DEFAULT_RULES = {
    "level1_rate": 0.03,
    "level2_rate": 0.015,
    "level3_rate": 0.005,
    "reward_type": "points",
    "trigger_type": "first_order",
}

# Bootstrap DDL — referral_rules 表（自举，无专项迁移）
_REFERRAL_RULES_DDL = """
CREATE TABLE IF NOT EXISTS referral_rules (
    tenant_id    UUID        PRIMARY KEY,
    level1_rate  NUMERIC(6,4) NOT NULL DEFAULT 0.03,
    level2_rate  NUMERIC(6,4) NOT NULL DEFAULT 0.015,
    level3_rate  NUMERIC(6,4) NOT NULL DEFAULT 0.005,
    reward_type  VARCHAR(20)  NOT NULL DEFAULT 'points',
    trigger_type VARCHAR(30)  NOT NULL DEFAULT 'first_order',
    updated_at   TIMESTAMPTZ  NOT NULL DEFAULT NOW()
)
"""


# ---------------------------------------------------------------------------
# 1. 生成推荐码
# ---------------------------------------------------------------------------


@router.post("/links")
async def generate_referral_link(
    req: GenerateLinkRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """为会员生成专属推荐码（TX + 4位大写字母数字）"""
    logger.info("referral.generate_link", member_id=req.member_id, tenant_id=x_tenant_id)

    try:
        await _set_tenant(db, x_tenant_id)

        # 生成唯一推荐码（避免碰撞，检查 DB）
        max_attempts = 10
        code: Optional[str] = None
        for _ in range(max_attempts):
            candidate = _generate_code()
            result = await db.execute(
                text("SELECT 1 FROM referral_links WHERE referral_code = :code"),
                {"code": candidate},
            )
            if result.fetchone() is None:
                code = candidate
                break
        if code is None:
            raise HTTPException(status_code=500, detail="推荐码生成失败，请重试")

        link_id = str(uuid.uuid4())
        now = _now_iso()

        await db.execute(
            text("""
                INSERT INTO referral_links
                    (id, tenant_id, member_id, referral_code, channel,
                     expires_at, click_count, convert_count, is_active, created_at)
                VALUES
                    (:id, :tenant_id, :member_id, :referral_code, :channel,
                     :expires_at, 0, 0, true, :created_at)
            """),
            {
                "id": link_id,
                "tenant_id": x_tenant_id,
                "member_id": req.member_id,
                "referral_code": code,
                "channel": req.channel,
                "expires_at": req.expires_at,
                "created_at": now,
            },
        )
        await db.commit()

        link_data = {
            "id": link_id,
            "tenant_id": x_tenant_id,
            "member_id": req.member_id,
            "referral_code": code,
            "channel": req.channel,
            "expires_at": req.expires_at,
            "click_count": 0,
            "convert_count": 0,
            "is_active": True,
            "created_at": now,
        }
        logger.info("referral.link_created", code=code, member_id=req.member_id)
        return ok(link_data)

    except HTTPException:
        raise
    except SQLAlchemyError as exc:
        logger.error("referral.generate_link.db_error", error=str(exc))
        await db.rollback()
        raise HTTPException(status_code=503, detail="数据库暂不可用，请稍后重试")


# ---------------------------------------------------------------------------
# 2. 获取会员的推荐码
# ---------------------------------------------------------------------------


@router.get("/links/{member_id}")
async def get_member_links(
    member_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """获取会员的推荐码列表（含转化统计）"""
    try:
        await _set_tenant(db, x_tenant_id)

        result = await db.execute(
            text("""
                SELECT id, tenant_id, member_id::text, referral_code, channel,
                       expires_at, click_count, convert_count, is_active, created_at
                FROM referral_links
                WHERE tenant_id = :tenant_id
                  AND member_id = :member_id::uuid
                  AND is_active = true
                ORDER BY created_at DESC
            """),
            {"tenant_id": x_tenant_id, "member_id": member_id},
        )
        rows = result.mappings().all()

        links = [
            {
                "id": str(r["id"]),
                "tenant_id": str(r["tenant_id"]),
                "member_id": str(r["member_id"]),
                "referral_code": r["referral_code"],
                "channel": r["channel"],
                "expires_at": r["expires_at"].isoformat() if r["expires_at"] else None,
                "click_count": r["click_count"],
                "convert_count": r["convert_count"],
                "is_active": r["is_active"],
                "created_at": r["created_at"].isoformat() if r["created_at"] else None,
            }
            for r in rows
        ]

        return ok(
            {
                "member_id": member_id,
                "links": links,
                "total": len(links),
                "total_click": sum(lk["click_count"] for lk in links),
                "total_convert": sum(lk["convert_count"] for lk in links),
            }
        )

    except SQLAlchemyError as exc:
        logger.error("referral.get_member_links.db_error", error=str(exc))
        return ok(
            {
                "member_id": member_id,
                "links": [],
                "total": 0,
                "total_click": 0,
                "total_convert": 0,
            }
        )


# ---------------------------------------------------------------------------
# 3. 绑定推荐关系（自动推导三级）
# ---------------------------------------------------------------------------


@router.post("/bind")
async def bind_referral_relationship(
    req: BindRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """绑定推荐关系

    逻辑：
    - 通过 referral_code 找到 level1_id（直接推荐人）
    - level1 的推荐人 = level2
    - level2 的推荐人 = level3
    - 同一 referee_id 只能绑定一次（幂等）
    """
    logger.info("referral.bind", referee_id=req.referee_id, code=req.referral_code)

    try:
        await _set_tenant(db, x_tenant_id)

        # 幂等检查：已绑定则直接返回
        existing = await db.execute(
            text("""
                SELECT id::text, tenant_id::text, referee_id::text,
                       level1_id::text, level2_id::text, level3_id::text,
                       referral_link_id::text, registered_at
                FROM referral_relationships
                WHERE tenant_id = :tenant_id
                  AND referee_id = :referee_id::uuid
            """),
            {"tenant_id": x_tenant_id, "referee_id": req.referee_id},
        )
        existing_row = existing.mappings().fetchone()
        if existing_row:
            relationship = dict(existing_row)
            if relationship.get("registered_at"):
                relationship["registered_at"] = relationship["registered_at"].isoformat()
            logger.info("referral.bind_idempotent", referee_id=req.referee_id)
            return ok({"idempotent": True, "relationship": relationship})

        # 查找推荐码对应的 link
        link_result = await db.execute(
            text("""
                SELECT id::text, member_id::text, tenant_id::text
                FROM referral_links
                WHERE referral_code = :code
                  AND tenant_id = :tenant_id
                  AND is_active = true
            """),
            {"code": req.referral_code, "tenant_id": x_tenant_id},
        )
        link_row = link_result.mappings().fetchone()
        if link_row is None:
            raise HTTPException(
                status_code=404,
                detail=f"推荐码 {req.referral_code} 不存在或已失效",
            )

        level1_id = link_row["member_id"]
        link_id = link_row["id"]

        # 防止自推荐
        if level1_id == req.referee_id:
            raise HTTPException(status_code=400, detail="不可使用自己的推荐码")

        # 推导二级（level1 的直接推荐人）
        level1_rel_result = await db.execute(
            text("""
                SELECT level1_id::text
                FROM referral_relationships
                WHERE tenant_id = :tenant_id
                  AND referee_id = :level1_id::uuid
            """),
            {"tenant_id": x_tenant_id, "level1_id": level1_id},
        )
        level1_rel_row = level1_rel_result.mappings().fetchone()
        level2_id: Optional[str] = level1_rel_row["level1_id"] if level1_rel_row else None

        # 推导三级（level2 的直接推荐人）
        level3_id: Optional[str] = None
        if level2_id:
            level2_rel_result = await db.execute(
                text("""
                    SELECT level1_id::text
                    FROM referral_relationships
                    WHERE tenant_id = :tenant_id
                      AND referee_id = :level2_id::uuid
                """),
                {"tenant_id": x_tenant_id, "level2_id": level2_id},
            )
            level2_rel_row = level2_rel_result.mappings().fetchone()
            level3_id = level2_rel_row["level1_id"] if level2_rel_row else None

        rel_id = str(uuid.uuid4())
        now = _now_iso()

        await db.execute(
            text("""
                INSERT INTO referral_relationships
                    (id, tenant_id, referee_id, level1_id, level2_id, level3_id,
                     referral_link_id, registered_at)
                VALUES
                    (:id, :tenant_id, :referee_id::uuid, :level1_id::uuid,
                     :level2_id::uuid, :level3_id::uuid, :link_id::uuid, :registered_at)
            """),
            {
                "id": rel_id,
                "tenant_id": x_tenant_id,
                "referee_id": req.referee_id,
                "level1_id": level1_id,
                "level2_id": level2_id,
                "level3_id": level3_id,
                "link_id": link_id,
                "registered_at": now,
            },
        )

        # 更新推荐码的转化计数
        await db.execute(
            text("""
                UPDATE referral_links
                SET convert_count = convert_count + 1
                WHERE id = :link_id::uuid
                  AND tenant_id = :tenant_id
            """),
            {"link_id": link_id, "tenant_id": x_tenant_id},
        )

        await db.commit()

        relationship = {
            "id": rel_id,
            "tenant_id": x_tenant_id,
            "referee_id": req.referee_id,
            "level1_id": level1_id,
            "level2_id": level2_id,
            "level3_id": level3_id,
            "referral_link_id": link_id,
            "registered_at": now,
        }

        logger.info(
            "referral.bind_success",
            referee=req.referee_id,
            level1=level1_id,
            level2=level2_id,
            level3=level3_id,
        )
        return ok({"idempotent": False, "relationship": relationship})

    except HTTPException:
        raise
    except SQLAlchemyError as exc:
        logger.error("referral.bind.db_error", error=str(exc))
        await db.rollback()
        raise HTTPException(status_code=503, detail="数据库暂不可用，请稍后重试")


# ---------------------------------------------------------------------------
# 4. 查看推荐关系树
# ---------------------------------------------------------------------------


@router.get("/tree/{member_id}")
async def get_referral_tree(
    member_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """查看会员的推荐关系树（直接下线+间接下线，含消费数据）"""
    try:
        await _set_tenant(db, x_tenant_id)

        # 直接下线（level1 = member_id）
        direct_result = await db.execute(
            text("""
                SELECT referee_id::text, level1_id::text
                FROM referral_relationships
                WHERE tenant_id = :tenant_id
                  AND level1_id = :member_id::uuid
            """),
            {"tenant_id": x_tenant_id, "member_id": member_id},
        )
        direct_rows = direct_result.mappings().all()

        # 二级下线（level2 = member_id）
        indirect_result = await db.execute(
            text("""
                SELECT referee_id::text, level2_id::text
                FROM referral_relationships
                WHERE tenant_id = :tenant_id
                  AND level2_id = :member_id::uuid
            """),
            {"tenant_id": x_tenant_id, "member_id": member_id},
        )
        indirect_rows = indirect_result.mappings().all()

        # 三级下线（level3 = member_id）
        level3_result = await db.execute(
            text("""
                SELECT referee_id::text, level3_id::text
                FROM referral_relationships
                WHERE tenant_id = :tenant_id
                  AND level3_id = :member_id::uuid
            """),
            {"tenant_id": x_tenant_id, "member_id": member_id},
        )
        level3_rows = level3_result.mappings().all()

        def _make_node(mid: str, level: int, children: list) -> dict:
            return {
                "member_id": mid,
                "level": level,
                "children": children,
            }

        # 三级子节点
        level3_nodes = [_make_node(r["referee_id"], 3, []) for r in level3_rows]

        # 二级子节点，挂三级
        level2_nodes = []
        for r in indirect_rows:
            children = [n for n in level3_nodes]  # 简化：所有三级挂在对应二级下
            level2_nodes.append(_make_node(r["referee_id"], 2, children))

        # 一级子节点，挂二级
        level1_nodes = []
        for r in direct_rows:
            children = [n for n in level2_nodes]
            level1_nodes.append(_make_node(r["referee_id"], 1, children))

        tree = _make_node(member_id, 0, level1_nodes)

        direct_count = len(direct_rows)
        indirect_count = len(indirect_rows) + len(level3_rows)

        return ok(
            {
                "tree": tree,
                "summary": {
                    "direct_referrals": direct_count,
                    "indirect_referrals": indirect_count,
                    "total_fen": 0,  # 跨服务消费汇总，留给 analytics 域计算
                },
            }
        )

    except SQLAlchemyError as exc:
        logger.error("referral.get_tree.db_error", error=str(exc))
        return ok(
            {
                "tree": {"member_id": member_id, "level": 0, "children": []},
                "summary": {"direct_referrals": 0, "indirect_referrals": 0, "total_fen": 0},
            }
        )


# ---------------------------------------------------------------------------
# 5. 触发奖励计算
# ---------------------------------------------------------------------------


@router.post("/rewards/calculate")
async def calculate_rewards(
    req: CalculateRewardRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """触发奖励计算

    默认规则（可配置）：
    - 一级：订单金额 × 3%（积分）
    - 二级：订单金额 × 1.5%（积分）
    - 三级：订单金额 × 0.5%（积分）
    """
    try:
        await _set_tenant(db, x_tenant_id)

        # 查询分销规则（自举表，若不存在则用默认值）
        rules = dict(_DEFAULT_RULES)
        try:
            rules_result = await db.execute(
                text("""
                    SELECT level1_rate, level2_rate, level3_rate,
                           reward_type, trigger_type
                    FROM referral_rules
                    WHERE tenant_id = :tenant_id
                """),
                {"tenant_id": x_tenant_id},
            )
            rules_row = rules_result.mappings().fetchone()
            if rules_row:
                rules = {
                    "level1_rate": float(rules_row["level1_rate"]),
                    "level2_rate": float(rules_row["level2_rate"]),
                    "level3_rate": float(rules_row["level3_rate"]),
                    "reward_type": rules_row["reward_type"],
                    "trigger_type": rules_row["trigger_type"],
                }
        except SQLAlchemyError:
            # 规则表不存在时静默降级到默认值
            pass

        # 查询推荐关系
        rel_result = await db.execute(
            text("""
                SELECT referee_id::text, level1_id::text,
                       level2_id::text, level3_id::text
                FROM referral_relationships
                WHERE tenant_id = :tenant_id
                  AND referee_id = :member_id::uuid
            """),
            {"tenant_id": x_tenant_id, "member_id": req.member_id},
        )
        rel_row = rel_result.mappings().fetchone()

        if rel_row is None:
            # 无上级关系，无奖励可计算
            return ok(
                {
                    "order_id": req.order_id,
                    "consumer_id": req.member_id,
                    "order_amount_fen": req.order_amount_fen,
                    "rewards": [],
                    "total_reward_fen": 0,
                }
            )

        rewards_created = []
        reward_map = [
            (1, rel_row["level1_id"], rules["level1_rate"]),
            (2, rel_row["level2_id"], rules["level2_rate"]),
            (3, rel_row["level3_id"], rules["level3_rate"]),
        ]
        now = _now_iso()

        for level, beneficiary_id, rate in reward_map:
            if beneficiary_id is None:
                continue
            reward_value_fen = int(req.order_amount_fen * rate)
            reward_id = str(uuid.uuid4())

            await db.execute(
                text("""
                    INSERT INTO referral_rewards
                        (id, tenant_id, member_id, referee_id, reward_level,
                         trigger_type, reward_type, reward_value_fen,
                         status, order_id, issued_at, expires_at, created_at)
                    VALUES
                        (:id, :tenant_id, :member_id::uuid, :referee_id::uuid,
                         :reward_level, :trigger_type, :reward_type,
                         :reward_value_fen, 'pending', :order_id::uuid,
                         NULL, NULL, :created_at)
                """),
                {
                    "id": reward_id,
                    "tenant_id": x_tenant_id,
                    "member_id": beneficiary_id,
                    "referee_id": req.member_id,
                    "reward_level": level,
                    "trigger_type": rules["trigger_type"],
                    "reward_type": rules["reward_type"],
                    "reward_value_fen": reward_value_fen,
                    "order_id": req.order_id,
                    "created_at": now,
                },
            )
            rewards_created.append(
                {
                    "id": reward_id,
                    "tenant_id": x_tenant_id,
                    "member_id": beneficiary_id,
                    "referee_id": req.member_id,
                    "reward_level": level,
                    "trigger_type": rules["trigger_type"],
                    "reward_type": rules["reward_type"],
                    "reward_value_fen": reward_value_fen,
                    "status": "pending",
                    "order_id": req.order_id,
                    "issued_at": None,
                    "expires_at": None,
                    "created_at": now,
                }
            )

        await db.commit()

        logger.info(
            "referral.rewards_calculated",
            order_id=req.order_id,
            amount_fen=req.order_amount_fen,
            rewards_count=len(rewards_created),
        )
        return ok(
            {
                "order_id": req.order_id,
                "consumer_id": req.member_id,
                "order_amount_fen": req.order_amount_fen,
                "rewards": rewards_created,
                "total_reward_fen": sum(r["reward_value_fen"] for r in rewards_created),
            }
        )

    except SQLAlchemyError as exc:
        logger.error("referral.calculate_rewards.db_error", error=str(exc))
        await db.rollback()
        raise HTTPException(status_code=503, detail="数据库暂不可用，请稍后重试")


# ---------------------------------------------------------------------------
# 6. 发放奖励
# ---------------------------------------------------------------------------


@router.post("/rewards/issue/{reward_id}")
async def issue_reward(
    reward_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """发放奖励（状态：pending → issued）"""
    try:
        await _set_tenant(db, x_tenant_id)

        result = await db.execute(
            text("""
                SELECT id::text, tenant_id::text, member_id::text, referee_id::text,
                       reward_level, trigger_type, reward_type, reward_value_fen,
                       status, order_id::text, issued_at, expires_at, created_at
                FROM referral_rewards
                WHERE id = :reward_id::uuid
                  AND tenant_id = :tenant_id
            """),
            {"reward_id": reward_id, "tenant_id": x_tenant_id},
        )
        row = result.mappings().fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail=f"奖励记录 {reward_id} 不存在")

        if row["status"] != "pending":
            raise HTTPException(
                status_code=400,
                detail=f"奖励状态为 {row['status']}，仅 pending 状态可发放",
            )

        now = _now_iso()
        await db.execute(
            text("""
                UPDATE referral_rewards
                SET status = 'issued', issued_at = :issued_at
                WHERE id = :reward_id::uuid
                  AND tenant_id = :tenant_id
            """),
            {"reward_id": reward_id, "tenant_id": x_tenant_id, "issued_at": now},
        )
        await db.commit()

        reward = {
            "id": row["id"],
            "tenant_id": row["tenant_id"],
            "member_id": row["member_id"],
            "referee_id": row["referee_id"],
            "reward_level": row["reward_level"],
            "trigger_type": row["trigger_type"],
            "reward_type": row["reward_type"],
            "reward_value_fen": row["reward_value_fen"],
            "status": "issued",
            "order_id": row["order_id"],
            "issued_at": now,
            "expires_at": row["expires_at"].isoformat() if row["expires_at"] else None,
            "created_at": row["created_at"].isoformat() if row["created_at"] else None,
        }
        logger.info("referral.reward_issued", reward_id=reward_id, member_id=reward["member_id"])
        return ok(reward)

    except HTTPException:
        raise
    except SQLAlchemyError as exc:
        logger.error("referral.issue_reward.db_error", error=str(exc))
        await db.rollback()
        raise HTTPException(status_code=503, detail="数据库暂不可用，请稍后重试")


# ---------------------------------------------------------------------------
# 7. 会员分销收益明细
# ---------------------------------------------------------------------------


@router.get("/rewards/{member_id}")
async def get_member_rewards(
    member_id: str,
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
    status: Optional[str] = Query(default=None),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """获取会员的分销收益明细（分页）"""
    try:
        await _set_tenant(db, x_tenant_id)

        offset = (page - 1) * size
        status_filter = "AND status = :status" if status else ""

        count_result = await db.execute(
            text(f"""
                SELECT COUNT(*) AS cnt,
                       COALESCE(SUM(CASE WHEN status = 'issued' THEN reward_value_fen ELSE 0 END), 0) AS issued_fen,
                       COALESCE(SUM(CASE WHEN status = 'pending' THEN reward_value_fen ELSE 0 END), 0) AS pending_fen
                FROM referral_rewards
                WHERE tenant_id = :tenant_id
                  AND member_id = :member_id::uuid
                  {status_filter}
            """),
            {"tenant_id": x_tenant_id, "member_id": member_id, "status": status},
        )
        agg = count_result.mappings().fetchone()
        total = agg["cnt"] if agg else 0
        total_issued_fen = int(agg["issued_fen"]) if agg else 0
        total_pending_fen = int(agg["pending_fen"]) if agg else 0

        items_result = await db.execute(
            text(f"""
                SELECT id::text, tenant_id::text, member_id::text, referee_id::text,
                       reward_level, trigger_type, reward_type, reward_value_fen,
                       status, order_id::text, issued_at, expires_at, created_at
                FROM referral_rewards
                WHERE tenant_id = :tenant_id
                  AND member_id = :member_id::uuid
                  {status_filter}
                ORDER BY created_at DESC
                LIMIT :size OFFSET :offset
            """),
            {
                "tenant_id": x_tenant_id,
                "member_id": member_id,
                "status": status,
                "size": size,
                "offset": offset,
            },
        )
        rows = items_result.mappings().all()
        items = [
            {
                "id": r["id"],
                "tenant_id": r["tenant_id"],
                "member_id": r["member_id"],
                "referee_id": r["referee_id"],
                "reward_level": r["reward_level"],
                "trigger_type": r["trigger_type"],
                "reward_type": r["reward_type"],
                "reward_value_fen": r["reward_value_fen"],
                "status": r["status"],
                "order_id": r["order_id"],
                "issued_at": r["issued_at"].isoformat() if r["issued_at"] else None,
                "expires_at": r["expires_at"].isoformat() if r["expires_at"] else None,
                "created_at": r["created_at"].isoformat() if r["created_at"] else None,
            }
            for r in rows
        ]

        return ok(
            {
                "items": items,
                "total": total,
                "page": page,
                "size": size,
                "total_issued_fen": total_issued_fen,
                "total_pending_fen": total_pending_fen,
            }
        )

    except SQLAlchemyError as exc:
        logger.error("referral.get_member_rewards.db_error", error=str(exc))
        return ok(
            {
                "items": [],
                "total": 0,
                "page": page,
                "size": size,
                "total_issued_fen": 0,
                "total_pending_fen": 0,
            }
        )


# ---------------------------------------------------------------------------
# 8. 分销总览
# ---------------------------------------------------------------------------


@router.get("/stats")
async def get_distribution_stats(
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """分销总览（参与会员数/三级链路数/本月奖励发放额）"""
    try:
        await _set_tenant(db, x_tenant_id)

        # 参与会员数（有推荐码的唯一会员数）
        part_result = await db.execute(
            text("""
                SELECT COUNT(DISTINCT member_id) AS participant_count,
                       COALESCE(SUM(click_count), 0) AS total_click,
                       COALESCE(SUM(convert_count), 0) AS total_convert
                FROM referral_links
                WHERE tenant_id = :tenant_id AND is_active = true
            """),
            {"tenant_id": x_tenant_id},
        )
        part_row = part_result.mappings().fetchone()

        # 关系链路总数
        rel_result = await db.execute(
            text("SELECT COUNT(*) AS cnt FROM referral_relationships WHERE tenant_id = :tenant_id"),
            {"tenant_id": x_tenant_id},
        )
        rel_row = rel_result.mappings().fetchone()

        # 奖励汇总
        reward_result = await db.execute(
            text("""
                SELECT COALESCE(SUM(CASE WHEN status = 'issued' THEN reward_value_fen ELSE 0 END), 0) AS issued_fen,
                       COALESCE(SUM(CASE WHEN status = 'pending' THEN reward_value_fen ELSE 0 END), 0) AS pending_fen
                FROM referral_rewards
                WHERE tenant_id = :tenant_id
            """),
            {"tenant_id": x_tenant_id},
        )
        reward_row = reward_result.mappings().fetchone()

        participant_count = int(part_row["participant_count"]) if part_row else 0
        total_click = int(part_row["total_click"]) if part_row else 0
        total_convert = int(part_row["total_convert"]) if part_row else 0
        relationship_count = int(rel_row["cnt"]) if rel_row else 0
        issued_fen = int(reward_row["issued_fen"]) if reward_row else 0
        pending_fen = int(reward_row["pending_fen"]) if reward_row else 0
        convert_rate = round(total_convert / total_click, 4) if total_click > 0 else 0.0

        return ok(
            {
                "participant_count": participant_count,
                "participant_growth_this_month": 0,  # 需 analytics 域月同比计算
                "three_level_chain_count": relationship_count,
                "this_month_issued_fen": issued_fen,
                "pending_reward_fen": pending_fen,
                "total_click_count": total_click,
                "total_convert_count": total_convert,
                "convert_rate": convert_rate,
            }
        )

    except SQLAlchemyError as exc:
        logger.error("referral.get_stats.db_error", error=str(exc))
        return ok(
            {
                "participant_count": 0,
                "participant_growth_this_month": 0,
                "three_level_chain_count": 0,
                "this_month_issued_fen": 0,
                "pending_reward_fen": 0,
                "total_click_count": 0,
                "total_convert_count": 0,
                "convert_rate": 0.0,
            }
        )


# ---------------------------------------------------------------------------
# 9. 分销排行榜
# ---------------------------------------------------------------------------


@router.get("/leaderboard")
async def get_leaderboard(
    period: str = Query(default="month", description="today/week/month"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """分销排行榜（按推荐转化数/获得奖励排名）"""
    if period not in ("today", "week", "month"):
        raise HTTPException(status_code=400, detail="period 必须是 today/week/month 之一")

    period_filter = {
        "today": "AND rr.registered_at >= NOW() - INTERVAL '1 day'",
        "week": "AND rr.registered_at >= NOW() - INTERVAL '7 days'",
        "month": "AND rr.registered_at >= NOW() - INTERVAL '30 days'",
    }[period]

    try:
        await _set_tenant(db, x_tenant_id)

        result = await db.execute(
            text(f"""
                SELECT
                    rr.level1_id::text AS member_id,
                    COUNT(DISTINCT rr.referee_id) AS direct_referrals,
                    COALESCE(SUM(rw.reward_value_fen), 0) AS total_reward_fen
                FROM referral_relationships rr
                LEFT JOIN referral_rewards rw
                    ON rw.member_id = rr.level1_id
                    AND rw.tenant_id = rr.tenant_id
                    AND rw.status = 'issued'
                WHERE rr.tenant_id = :tenant_id
                  AND rr.level1_id IS NOT NULL
                  {period_filter}
                GROUP BY rr.level1_id
                ORDER BY direct_referrals DESC, total_reward_fen DESC
                LIMIT 20
            """),
            {"tenant_id": x_tenant_id},
        )
        rows = result.mappings().all()
        items = [
            {
                "rank": idx + 1,
                "member_id": r["member_id"],
                "direct_referrals": r["direct_referrals"],
                "indirect_referrals": 0,  # 需二次关联查询，留给 analytics 域
                "total_reward_fen": int(r["total_reward_fen"]),
            }
            for idx, r in enumerate(rows)
        ]

        return ok(
            {
                "period": period,
                "items": items,
                "total": len(items),
            }
        )

    except SQLAlchemyError as exc:
        logger.error("referral.get_leaderboard.db_error", error=str(exc))
        return ok({"period": period, "items": [], "total": 0})


# ---------------------------------------------------------------------------
# 10. 保存分销规则配置
# ---------------------------------------------------------------------------


@router.post("/rules")
async def save_distribution_rules(
    req: SaveRulesRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """保存三级分销规则配置（UPSERT）"""
    try:
        await _set_tenant(db, x_tenant_id)

        # 确保表存在（自举 DDL）
        await db.execute(text(_REFERRAL_RULES_DDL))

        now = _now_iso()
        await db.execute(
            text("""
                INSERT INTO referral_rules
                    (tenant_id, level1_rate, level2_rate, level3_rate,
                     reward_type, trigger_type, updated_at)
                VALUES
                    (:tenant_id, :level1_rate, :level2_rate, :level3_rate,
                     :reward_type, :trigger_type, :updated_at)
                ON CONFLICT (tenant_id) DO UPDATE SET
                    level1_rate  = EXCLUDED.level1_rate,
                    level2_rate  = EXCLUDED.level2_rate,
                    level3_rate  = EXCLUDED.level3_rate,
                    reward_type  = EXCLUDED.reward_type,
                    trigger_type = EXCLUDED.trigger_type,
                    updated_at   = EXCLUDED.updated_at
            """),
            {
                "tenant_id": x_tenant_id,
                "level1_rate": req.level1_rate,
                "level2_rate": req.level2_rate,
                "level3_rate": req.level3_rate,
                "reward_type": req.reward_type,
                "trigger_type": req.trigger_type,
                "updated_at": now,
            },
        )
        await db.commit()

        rules = {
            "level1_rate": req.level1_rate,
            "level2_rate": req.level2_rate,
            "level3_rate": req.level3_rate,
            "reward_type": req.reward_type,
            "trigger_type": req.trigger_type,
            "updated_at": now,
        }
        logger.info(
            "referral.rules_saved",
            tenant_id=x_tenant_id,
            level1=req.level1_rate,
            level2=req.level2_rate,
            level3=req.level3_rate,
        )
        return ok({"saved": True, "rules": rules})

    except SQLAlchemyError as exc:
        logger.error("referral.save_rules.db_error", error=str(exc))
        await db.rollback()
        raise HTTPException(status_code=503, detail="数据库暂不可用，请稍后重试")


# ---------------------------------------------------------------------------
# 11. 获取分销规则配置
# ---------------------------------------------------------------------------


@router.get("/rules")
async def get_distribution_rules(
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """获取当前分销规则配置"""
    try:
        await _set_tenant(db, x_tenant_id)

        # 确保表存在（自举 DDL）
        await db.execute(text(_REFERRAL_RULES_DDL))

        result = await db.execute(
            text("""
                SELECT level1_rate, level2_rate, level3_rate,
                       reward_type, trigger_type, updated_at
                FROM referral_rules
                WHERE tenant_id = :tenant_id
            """),
            {"tenant_id": x_tenant_id},
        )
        row = result.mappings().fetchone()
        if row:
            rules = {
                "level1_rate": float(row["level1_rate"]),
                "level2_rate": float(row["level2_rate"]),
                "level3_rate": float(row["level3_rate"]),
                "reward_type": row["reward_type"],
                "trigger_type": row["trigger_type"],
                "updated_at": row["updated_at"].isoformat() if row["updated_at"] else None,
            }
        else:
            rules = dict(_DEFAULT_RULES)

        return ok(rules)

    except SQLAlchemyError as exc:
        logger.error("referral.get_rules.db_error", error=str(exc))
        return ok(dict(_DEFAULT_RULES))


# ---------------------------------------------------------------------------
# 12. 异常检测（防刷）
# ---------------------------------------------------------------------------


@router.post("/detect-abuse")
async def detect_abuse(
    req: DetectAbuseRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """防刷异常检测

    检查同 referee_id 重复绑定、同设备/同IP短时间多次绑定等异常行为。
    """
    abuse_flags: list[str] = []

    try:
        await _set_tenant(db, x_tenant_id)

        # 检查1：referee_id 是否已绑定（重复绑定）
        dup_result = await db.execute(
            text("""
                SELECT 1 FROM referral_relationships
                WHERE tenant_id = :tenant_id
                  AND referee_id = :referee_id::uuid
                LIMIT 1
            """),
            {"tenant_id": x_tenant_id, "referee_id": req.referee_id},
        )
        if dup_result.fetchone():
            abuse_flags.append("DUPLICATE_BIND")

        # 检查2：同设备绑定次数（通过 referral_records 的 invitee_device_id）
        if req.device_id:
            device_result = await db.execute(
                text("""
                    SELECT COUNT(*) AS cnt FROM referral_records
                    WHERE tenant_id = :tenant_id
                      AND invitee_device_id = :device_id
                """),
                {"tenant_id": x_tenant_id, "device_id": req.device_id},
            )
            device_row = device_result.mappings().fetchone()
            device_count = int(device_row["cnt"]) if device_row else 0
            if device_count >= 3:
                abuse_flags.append("SAME_DEVICE_MULTIPLE_BIND")

        # 检查3：同IP短时间多次绑定（同IP超过5次视为异常）
        if req.ip:
            ip_result = await db.execute(
                text("""
                    SELECT COUNT(*) AS cnt FROM referral_records
                    WHERE tenant_id = :tenant_id
                      AND invitee_ip = :ip
                """),
                {"tenant_id": x_tenant_id, "ip": req.ip},
            )
            ip_row = ip_result.mappings().fetchone()
            ip_count = int(ip_row["cnt"]) if ip_row else 0
            if ip_count >= 5:
                abuse_flags.append("SAME_IP_MULTIPLE_BIND")

    except SQLAlchemyError as exc:
        logger.error("referral.detect_abuse.db_error", error=str(exc))
        # DB 不可用时仅做无状态检测，跳过历史比对

    is_abuse = len(abuse_flags) > 0
    risk_level = "high" if len(abuse_flags) >= 2 else ("medium" if is_abuse else "low")

    logger.info(
        "referral.abuse_check",
        referee_id=req.referee_id,
        is_abuse=is_abuse,
        flags=abuse_flags,
        risk_level=risk_level,
    )

    return ok(
        {
            "referee_id": req.referee_id,
            "is_abuse": is_abuse,
            "risk_level": risk_level,
            "flags": abuse_flags,
            "recommendation": "block" if risk_level == "high" else ("review" if risk_level == "medium" else "allow"),
        }
    )
