"""惊喜奖励引擎 — 第N次到店概率奖励

机制：
  1. 配置 surprise_rule: {nth_visit: 10, probability: 0.3, reward: {...}}
  2. 每次下单后调用 check_surprise
  3. 到达第N次访问 → 按 probability 概率发放奖励
  4. 奖励类型：积分/优惠券/徽章/免单折扣

防刷：同一顾客同一规则只触发一次。

数据源：
  surprise_rules — 规则持久化（v325迁移）
  member_badges  — 触发记录（防重复）
"""

from __future__ import annotations

import json
import random
from datetime import datetime, timezone

import structlog
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger(__name__)


# ─── RLS ────────────────────────────────────────────────────────────────────


async def _set_rls(db: AsyncSession, tenant_id: str) -> None:
    """设置RLS租户上下文"""
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": str(tenant_id)},
    )


# ─── 规则 CRUD（DB持久化） ──────────────────────────────────────────────────


async def register_surprise_rule(
    db: AsyncSession,
    tenant_id: str,
    rule: dict,
) -> str:
    """注册惊喜规则到数据库，返回 rule_id"""
    await _set_rls(db, tenant_id)
    try:
        result = await db.execute(
            text("""
                INSERT INTO surprise_rules
                    (tenant_id, store_id, name, nth_visit, probability, reward, is_active)
                VALUES
                    (:tenant_id, :store_id, :name, :nth_visit, :probability, :reward ::jsonb, :is_active)
                RETURNING id
            """),
            {
                "tenant_id": str(tenant_id),
                "store_id": str(rule["store_id"]) if rule.get("store_id") else None,
                "name": rule.get("name", ""),
                "nth_visit": rule.get("nth_visit", 1),
                "probability": rule.get("probability", 1.0),
                "reward": json.dumps(rule.get("reward", {})),
                "is_active": rule.get("is_active", True),
            },
        )
        row = result.mappings().fetchone()
        await db.commit()
        rule_id = str(row["id"])
        logger.info("surprise_rule_registered", tenant_id=tenant_id, rule_id=rule_id)
        return rule_id
    except SQLAlchemyError:
        await db.rollback()
        logger.exception("surprise_rule_register_error")
        raise


async def get_surprise_rules(
    db: AsyncSession,
    tenant_id: str,
    store_id: str | None = None,
) -> list[dict]:
    """从数据库获取租户活跃的惊喜规则"""
    await _set_rls(db, tenant_id)

    conditions = ["tenant_id = :tid", "is_active = true", "is_deleted = false"]
    params: dict = {"tid": str(tenant_id)}

    if store_id:
        conditions.append("(store_id = :sid OR store_id IS NULL)")
        params["sid"] = str(store_id)

    where = " AND ".join(conditions)
    result = await db.execute(
        text(f"""
            SELECT id, nth_visit, probability, reward, name, store_id
            FROM surprise_rules
            WHERE {where}
            ORDER BY display_order ASC, created_at ASC
        """),
        params,
    )
    rows = result.mappings().all()
    return [
        {
            "rule_id": str(r["id"]),
            "nth_visit": r["nth_visit"],
            "probability": float(r["probability"]),
            "reward": r["reward"] if isinstance(r["reward"], dict) else json.loads(r["reward"]),
            "name": r["name"],
            "store_id": str(r["store_id"]) if r["store_id"] else None,
        }
        for r in rows
    ]


async def delete_surprise_rule(
    db: AsyncSession,
    tenant_id: str,
    rule_id: str,
) -> bool:
    """软删除惊喜规则"""
    await _set_rls(db, tenant_id)
    try:
        result = await db.execute(
            text("""
                UPDATE surprise_rules
                SET is_deleted = true, updated_at = NOW()
                WHERE id = :rid AND tenant_id = :tid AND is_deleted = false
            """),
            {"rid": str(rule_id), "tid": str(tenant_id)},
        )
        await db.commit()
        return result.rowcount > 0
    except SQLAlchemyError:
        await db.rollback()
        logger.exception("surprise_rule_delete_error")
        raise


# ─── 核心逻辑 ────────────────────────────────────────────────────────────────


async def check_surprise(
    db: AsyncSession,
    tenant_id: str,
    customer_id: str,
    visit_count: int | None = None,
    store_id: str | None = None,
) -> dict | None:
    """检查是否触发惊喜奖励，返回奖励详情或 None

    Args:
        db: 数据库会话
        tenant_id: 租户ID
        customer_id: 顾客ID
        visit_count: 当前访问次数（如不传则从DB查）
        store_id: 门店ID（用于筛选门店级规则）
    """
    await _set_rls(db, tenant_id)
    logger.info("surprise_check", tenant_id=tenant_id, customer_id=customer_id)

    if visit_count is None:
        row = await db.execute(
            text("""
                SELECT COUNT(DISTINCT DATE(created_at)) AS cnt
                FROM orders
                WHERE tenant_id = :tid AND customer_id = :cid
                  AND is_deleted = false AND status = 'paid'
            """),
            {"tid": tenant_id, "cid": customer_id},
        )
        r = row.mappings().first()
        visit_count = int(r["cnt"]) if r else 0

    rules = await get_surprise_rules(db, tenant_id, store_id=store_id)
    if not rules:
        return None

    for rule in rules:
        nth = rule.get("nth_visit", 0)
        if nth <= 0 or visit_count != nth:
            continue

        # 检查是否已触发过
        rule_id = rule.get("rule_id", "")
        already = await _check_already_triggered(db, tenant_id, customer_id, rule_id)
        if already:
            logger.debug("surprise_already_triggered", rule_id=rule_id)
            continue

        # 概率判定
        probability = rule.get("probability", 1.0)
        roll = random.random()
        if roll > probability:
            logger.info("surprise_probability_miss", probability=probability, roll=roll)
            continue

        # 触发奖励
        reward = rule.get("reward", {})
        await _record_trigger(db, tenant_id, customer_id, rule_id, reward)

        logger.info(
            "surprise_triggered",
            tenant_id=tenant_id,
            customer_id=customer_id,
            rule_id=rule_id,
            reward_type=reward.get("type"),
        )
        return {
            "triggered": True,
            "rule_id": rule_id,
            "nth_visit": nth,
            "reward": reward,
            "visit_count": visit_count,
        }

    return None


async def _check_already_triggered(
    db: AsyncSession,
    tenant_id: str,
    customer_id: str,
    rule_id: str,
) -> bool:
    """检查是否已触发过（查 member_badges 或用通用日志表）"""
    try:
        row = await db.execute(
            text("""
                SELECT 1 FROM member_badges
                WHERE tenant_id = :tid AND customer_id = :cid
                  AND unlock_context->>'surprise_rule_id' = :rid
                  AND is_deleted = false
                LIMIT 1
            """),
            {"tid": tenant_id, "cid": customer_id, "rid": rule_id},
        )
        return row.first() is not None
    except SQLAlchemyError:
        logger.exception("surprise_check_trigger_error")
        return False


async def _record_trigger(
    db: AsyncSession,
    tenant_id: str,
    customer_id: str,
    rule_id: str,
    reward: dict,
) -> None:
    """记录惊喜奖励触发"""
    try:
        context = {
            "surprise_rule_id": rule_id,
            "reward": reward,
            "triggered_at": datetime.now(timezone.utc).isoformat(),
        }
        # 如果奖励包含徽章，写入 member_badges
        badge_id = reward.get("badge_id")
        if badge_id:
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
                    "ctx": json.dumps(context),
                },
            )
        await db.commit()
    except SQLAlchemyError:
        await db.rollback()
        logger.exception("surprise_record_trigger_error")
        raise


async def get_surprise_history(
    db: AsyncSession,
    tenant_id: str,
    customer_id: str,
) -> list[dict]:
    """获取顾客的惊喜奖励历史"""
    rows = await db.execute(
        text("""
            SELECT id, badge_id, unlock_context, unlocked_at
            FROM member_badges
            WHERE tenant_id = :tid AND customer_id = :cid
              AND unlock_context ? 'surprise_rule_id'
              AND is_deleted = false
            ORDER BY unlocked_at DESC
        """),
        {"tid": tenant_id, "cid": customer_id},
    )
    return [dict(r) for r in rows.mappings().all()]
