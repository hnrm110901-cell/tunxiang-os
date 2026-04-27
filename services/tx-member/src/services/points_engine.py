"""积分引擎 — 积分获取/消耗/规则/倍数/成长值/余额/明细/跨店结算

积分为整数，不支持小数。
成长值为累计制，只增不减。
所有金额单位：分(fen)。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger(__name__)


# ── 常量 ──────────────────────────────────────────────────────

EARN_SOURCES = ("consume", "recharge", "activity", "sign_in")
SPEND_PURPOSES = ("cash_offset", "exchange")
DEFAULT_EARN_RATIO = 1  # 每消费100分（1元）获1积分
DEFAULT_SPEND_RATIO = 100  # 100积分抵1元（100分）


# ── 工具函数 ──────────────────────────────────────────────────


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


async def _set_tenant(db: AsyncSession, tenant_id: str) -> None:
    """设置 RLS tenant 上下文"""
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": tenant_id},
    )


def calculate_earn_points(
    amount_fen: int,
    earn_ratio: int,
    earn_unit_fen: int,
    multiplier: float = 1.0,
) -> int:
    """计算消费获取的积分（整数）

    Args:
        amount_fen: 消费金额（分）
        earn_ratio: 每 earn_unit_fen 获得的积分数
        earn_unit_fen: 消费单位（分），如 10000 表示每消费100元
        multiplier: 积分倍数

    Returns:
        积分数（整数，向下取整）
    """
    if earn_unit_fen <= 0 or earn_ratio <= 0:
        return 0
    base_points = (amount_fen // earn_unit_fen) * earn_ratio
    return int(base_points * multiplier)


def calculate_cash_offset_fen(
    points: int,
    spend_ratio: int,
    spend_value_fen: int,
) -> int:
    """计算积分可抵扣的金额（分）

    Args:
        points: 积分数
        spend_ratio: 每 spend_ratio 积分可抵扣 spend_value_fen
        spend_value_fen: 抵扣金额（分）

    Returns:
        抵扣金额（分）
    """
    if spend_ratio <= 0:
        return 0
    return (points // spend_ratio) * spend_value_fen


def validate_earn_rules(rules: dict) -> bool:
    """校验积分获取规则"""
    if not rules:
        return False
    earn_ratio = rules.get("earn_ratio")
    earn_unit_fen = rules.get("earn_unit_fen")
    if earn_ratio is None or earn_unit_fen is None:
        return False
    if not isinstance(earn_ratio, int) or earn_ratio <= 0:
        return False
    if not isinstance(earn_unit_fen, int) or earn_unit_fen <= 0:
        return False
    return True


def validate_spend_rules(rules: dict) -> bool:
    """校验积分消耗规则"""
    if not rules:
        return False
    spend_ratio = rules.get("spend_ratio")
    spend_value_fen = rules.get("spend_value_fen")
    if spend_ratio is None or spend_value_fen is None:
        return False
    if not isinstance(spend_ratio, int) or spend_ratio <= 0:
        return False
    if not isinstance(spend_value_fen, int) or spend_value_fen <= 0:
        return False
    return True


def validate_multiplier_conditions(conditions: dict) -> bool:
    """校验积分倍数条件"""
    if not conditions:
        return False
    trigger = conditions.get("trigger")
    if trigger not in ("member_day", "activity", "level", "always"):
        return False
    return True


# ── 服务函数 ──────────────────────────────────────────────────


async def earn_points(
    card_id: str,
    source: str,
    amount: int,
    tenant_id: str,
    db: AsyncSession,
) -> dict[str, Any]:
    """积分获取（消费/充值/活动/签到）

    Args:
        card_id: 会员卡 ID
        source: 来源类型 consume|recharge|activity|sign_in
        amount: 获取积分数（整数）
        tenant_id: 租户 ID
        db: 数据库会话

    Returns:
        {"card_id", "source", "earned", "new_balance"}
    """
    await _set_tenant(db, tenant_id)

    if source not in EARN_SOURCES:
        raise ValueError(f"invalid_source:{source}")
    if not isinstance(amount, int) or amount <= 0:
        raise ValueError("points_must_be_positive_integer")

    now = _now_utc()

    # 更新积分余额
    await db.execute(
        text("""
            UPDATE member_cards
            SET points = points + :pts, updated_at = :now
            WHERE id = :cid AND tenant_id = :tid AND is_deleted = false
        """),
        {"pts": amount, "cid": card_id, "tid": tenant_id, "now": now},
    )

    # 记录积分流水
    log_id = str(uuid.uuid4())
    await db.execute(
        text("""
            INSERT INTO points_log
                (id, tenant_id, card_id, direction, source, points, created_at)
            VALUES (:id, :tid, :cid, 'earn', :src, :pts, :now)
        """),
        {
            "id": log_id,
            "tid": tenant_id,
            "cid": card_id,
            "src": source,
            "pts": amount,
            "now": now,
        },
    )
    await db.flush()

    # 查询新余额
    bal_row = await db.execute(
        text("SELECT points FROM member_cards WHERE id = :cid AND tenant_id = :tid"),
        {"cid": card_id, "tid": tenant_id},
    )
    new_balance = bal_row.scalar() or 0

    logger.info(
        "points_earned",
        tenant_id=tenant_id,
        card_id=card_id,
        source=source,
        earned=amount,
        new_balance=new_balance,
    )

    return {
        "card_id": card_id,
        "source": source,
        "earned": amount,
        "new_balance": new_balance,
    }


async def spend_points(
    card_id: str,
    amount: int,
    purpose: str,
    tenant_id: str,
    db: AsyncSession,
) -> dict[str, Any]:
    """积分消耗（抵现/兑换）

    Args:
        card_id: 会员卡 ID
        amount: 消耗积分数（整数）
        purpose: 用途 cash_offset|exchange
        tenant_id: 租户 ID
        db: 数据库会话

    Returns:
        {"card_id", "purpose", "spent", "new_balance"}
    """
    await _set_tenant(db, tenant_id)

    if purpose not in SPEND_PURPOSES:
        raise ValueError(f"invalid_purpose:{purpose}")
    if not isinstance(amount, int) or amount <= 0:
        raise ValueError("points_must_be_positive_integer")

    # 检查余额
    bal_row = await db.execute(
        text("SELECT points FROM member_cards WHERE id = :cid AND tenant_id = :tid AND is_deleted = false"),
        {"cid": card_id, "tid": tenant_id},
    )
    current = bal_row.scalar()
    if current is None:
        raise ValueError("card_not_found")
    if current < amount:
        raise ValueError("insufficient_points")

    now = _now_utc()

    await db.execute(
        text("""
            UPDATE member_cards
            SET points = points - :pts, updated_at = :now
            WHERE id = :cid AND tenant_id = :tid AND is_deleted = false
        """),
        {"pts": amount, "cid": card_id, "tid": tenant_id, "now": now},
    )

    log_id = str(uuid.uuid4())
    await db.execute(
        text("""
            INSERT INTO points_log
                (id, tenant_id, card_id, direction, source, points, created_at)
            VALUES (:id, :tid, :cid, 'spend', :src, :pts, :now)
        """),
        {
            "id": log_id,
            "tid": tenant_id,
            "cid": card_id,
            "src": purpose,
            "pts": amount,
            "now": now,
        },
    )
    await db.flush()

    new_balance = current - amount

    logger.info(
        "points_spent",
        tenant_id=tenant_id,
        card_id=card_id,
        purpose=purpose,
        spent=amount,
        new_balance=new_balance,
    )

    return {
        "card_id": card_id,
        "purpose": purpose,
        "spent": amount,
        "new_balance": new_balance,
    }


async def set_earn_rules(
    card_type_id: str,
    rules: dict,
    tenant_id: str,
    db: AsyncSession,
) -> dict[str, Any]:
    """设置积分获取规则（每消费X元获Y积分）

    Args:
        card_type_id: 卡类型 ID
        rules: {"earn_ratio": 1, "earn_unit_fen": 10000, "sources": ["consume", "recharge"]}
        tenant_id: 租户 ID
        db: 数据库会话

    Returns:
        {"card_type_id", "earn_rules"}
    """
    await _set_tenant(db, tenant_id)

    if not validate_earn_rules(rules):
        raise ValueError("invalid_earn_rules")

    import json

    now = _now_utc()

    await db.execute(
        text("""
            UPDATE card_types SET earn_rules = :rules::jsonb, updated_at = :now
            WHERE id = :ctid AND tenant_id = :tid AND is_deleted = false
        """),
        {
            "ctid": card_type_id,
            "tid": tenant_id,
            "rules": json.dumps(rules, ensure_ascii=False),
            "now": now,
        },
    )
    await db.flush()

    logger.info(
        "earn_rules_set",
        tenant_id=tenant_id,
        card_type_id=card_type_id,
        earn_ratio=rules.get("earn_ratio"),
    )

    return {"card_type_id": card_type_id, "earn_rules": rules}


async def set_spend_rules(
    card_type_id: str,
    rules: dict,
    tenant_id: str,
    db: AsyncSession,
) -> dict[str, Any]:
    """设置积分消耗规则（X积分抵1元）

    Args:
        card_type_id: 卡类型 ID
        rules: {"spend_ratio": 100, "spend_value_fen": 100, "max_offset_ratio": 0.5}
        tenant_id: 租户 ID
        db: 数据库会话

    Returns:
        {"card_type_id", "spend_rules"}
    """
    await _set_tenant(db, tenant_id)

    if not validate_spend_rules(rules):
        raise ValueError("invalid_spend_rules")

    import json

    now = _now_utc()

    await db.execute(
        text("""
            UPDATE card_types SET spend_rules = :rules::jsonb, updated_at = :now
            WHERE id = :ctid AND tenant_id = :tid AND is_deleted = false
        """),
        {
            "ctid": card_type_id,
            "tid": tenant_id,
            "rules": json.dumps(rules, ensure_ascii=False),
            "now": now,
        },
    )
    await db.flush()

    logger.info(
        "spend_rules_set",
        tenant_id=tenant_id,
        card_type_id=card_type_id,
        spend_ratio=rules.get("spend_ratio"),
    )

    return {"card_type_id": card_type_id, "spend_rules": rules}


async def set_multiplier(
    card_type_id: str,
    multiplier: float,
    conditions: dict,
    tenant_id: str,
    db: AsyncSession,
) -> dict[str, Any]:
    """积分倍数设置（会员日/活动期）

    Args:
        card_type_id: 卡类型 ID
        multiplier: 倍数（如 2.0 表示双倍积分）
        conditions: {"trigger": "member_day"|"activity"|"level"|"always", ...}
        tenant_id: 租户 ID
        db: 数据库会话

    Returns:
        {"card_type_id", "multiplier", "conditions"}
    """
    await _set_tenant(db, tenant_id)

    if multiplier <= 0:
        raise ValueError("multiplier_must_be_positive")
    if not validate_multiplier_conditions(conditions):
        raise ValueError("invalid_multiplier_conditions")

    import json

    now = _now_utc()
    config = {"multiplier": multiplier, "conditions": conditions}

    await db.execute(
        text("""
            UPDATE card_types SET multiplier_config = :cfg::jsonb, updated_at = :now
            WHERE id = :ctid AND tenant_id = :tid AND is_deleted = false
        """),
        {
            "ctid": card_type_id,
            "tid": tenant_id,
            "cfg": json.dumps(config, ensure_ascii=False),
            "now": now,
        },
    )
    await db.flush()

    logger.info(
        "multiplier_set",
        tenant_id=tenant_id,
        card_type_id=card_type_id,
        multiplier=multiplier,
        trigger=conditions.get("trigger"),
    )

    return {
        "card_type_id": card_type_id,
        "multiplier": multiplier,
        "conditions": conditions,
    }


async def manage_growth_value(
    card_id: str,
    action: str,
    amount: int,
    tenant_id: str,
    db: AsyncSession,
) -> dict[str, Any]:
    """成长值管理（只增不减）

    Args:
        card_id: 会员卡 ID
        action: "add"（成长值只增不减，仅支持 add）
        amount: 增加的成长值（正整数）
        tenant_id: 租户 ID
        db: 数据库会话

    Returns:
        {"card_id", "added", "new_growth_value"}
    """
    await _set_tenant(db, tenant_id)

    if action != "add":
        raise ValueError("growth_value_only_supports_add")
    if not isinstance(amount, int) or amount <= 0:
        raise ValueError("amount_must_be_positive_integer")

    now = _now_utc()

    await db.execute(
        text("""
            UPDATE member_cards
            SET growth_value = growth_value + :amt, updated_at = :now
            WHERE id = :cid AND tenant_id = :tid AND is_deleted = false
        """),
        {"amt": amount, "cid": card_id, "tid": tenant_id, "now": now},
    )
    await db.flush()

    row = await db.execute(
        text("SELECT growth_value FROM member_cards WHERE id = :cid AND tenant_id = :tid"),
        {"cid": card_id, "tid": tenant_id},
    )
    new_gv = row.scalar() or 0

    logger.info(
        "growth_value_added",
        tenant_id=tenant_id,
        card_id=card_id,
        added=amount,
        new_growth_value=new_gv,
    )

    return {
        "card_id": card_id,
        "added": amount,
        "new_growth_value": new_gv,
    }


async def get_points_balance(
    card_id: str,
    tenant_id: str,
    db: AsyncSession,
) -> dict[str, Any]:
    """积分余额查询

    Returns:
        {"card_id", "points", "growth_value"}
    """
    await _set_tenant(db, tenant_id)

    row = await db.execute(
        text("""
            SELECT points, growth_value
            FROM member_cards
            WHERE id = :cid AND tenant_id = :tid AND is_deleted = false
        """),
        {"cid": card_id, "tid": tenant_id},
    )
    result = row.mappings().first()
    if not result:
        raise ValueError("card_not_found")

    return {
        "card_id": card_id,
        "points": result["points"],
        "growth_value": result["growth_value"],
    }


async def get_points_history(
    card_id: str,
    tenant_id: str,
    db: AsyncSession,
    page: int = 1,
    size: int = 20,
) -> dict[str, Any]:
    """积分明细查询

    Returns:
        {"card_id", "items": [...], "total", "page", "size"}
    """
    await _set_tenant(db, tenant_id)

    offset = (page - 1) * size

    # 总数
    cnt_row = await db.execute(
        text("SELECT COUNT(*) FROM points_log WHERE card_id = :cid AND tenant_id = :tid"),
        {"cid": card_id, "tid": tenant_id},
    )
    total = cnt_row.scalar() or 0

    # 明细
    rows = await db.execute(
        text("""
            SELECT id, direction, source, points, created_at
            FROM points_log
            WHERE card_id = :cid AND tenant_id = :tid
            ORDER BY created_at DESC
            LIMIT :lim OFFSET :off
        """),
        {"cid": card_id, "tid": tenant_id, "lim": size, "off": offset},
    )
    items = [
        {
            "id": str(r["id"]),
            "direction": r["direction"],
            "source": r["source"],
            "points": r["points"],
            "created_at": r["created_at"].isoformat()
            if hasattr(r["created_at"], "isoformat")
            else str(r["created_at"]),
        }
        for r in rows.mappings().all()
    ]

    return {
        "card_id": card_id,
        "items": items,
        "total": total,
        "page": page,
        "size": size,
    }


async def cross_store_settlement(
    tenant_id: str,
    month: str,
    db: AsyncSession,
) -> dict[str, Any]:
    """跨店积分结算

    Args:
        tenant_id: 租户 ID
        month: 月份 YYYY-MM
        db: 数据库会话

    Returns:
        {"month", "store_settlements": [...], "total_points_earned", "total_points_spent"}
    """
    await _set_tenant(db, tenant_id)

    start_date = f"{month}-01"
    # 计算月末
    year, mon = int(month[:4]), int(month[5:7])
    if mon == 12:
        end_date = f"{year + 1}-01-01"
    else:
        end_date = f"{year}-{mon + 1:02d}-01"

    # 按门店汇总获取积分
    earn_rows = await db.execute(
        text("""
            SELECT pl.source AS store_context, SUM(pl.points) AS total_earned
            FROM points_log pl
            WHERE pl.tenant_id = :tid
              AND pl.direction = 'earn'
              AND pl.created_at >= :start::timestamptz
              AND pl.created_at < :end::timestamptz
            GROUP BY pl.source
        """),
        {"tid": tenant_id, "start": start_date, "end": end_date},
    )
    earn_by_source = {r["store_context"]: int(r["total_earned"]) for r in earn_rows.mappings().all()}

    # 按门店汇总消耗积分
    spend_rows = await db.execute(
        text("""
            SELECT pl.source AS store_context, SUM(pl.points) AS total_spent
            FROM points_log pl
            WHERE pl.tenant_id = :tid
              AND pl.direction = 'spend'
              AND pl.created_at >= :start::timestamptz
              AND pl.created_at < :end::timestamptz
            GROUP BY pl.source
        """),
        {"tid": tenant_id, "start": start_date, "end": end_date},
    )
    spend_by_source = {r["store_context"]: int(r["total_spent"]) for r in spend_rows.mappings().all()}

    all_sources = set(earn_by_source.keys()) | set(spend_by_source.keys())
    total_earned = sum(earn_by_source.values())
    total_spent = sum(spend_by_source.values())

    store_settlements = [
        {
            "store_context": src,
            "earned": earn_by_source.get(src, 0),
            "spent": spend_by_source.get(src, 0),
            "net": earn_by_source.get(src, 0) - spend_by_source.get(src, 0),
        }
        for src in sorted(all_sources)
    ]

    logger.info(
        "cross_store_settlement_completed",
        tenant_id=tenant_id,
        month=month,
        store_count=len(store_settlements),
        total_earned=total_earned,
        total_spent=total_spent,
    )

    return {
        "month": month,
        "store_settlements": store_settlements,
        "total_points_earned": total_earned,
        "total_points_spent": total_spent,
    }
