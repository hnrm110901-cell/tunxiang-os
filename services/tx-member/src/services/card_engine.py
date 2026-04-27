"""会员卡引擎 — 卡类型/等级/发卡/升降级/会员日/权益/批量操作

所有金额单位：分(fen)。
等级升降级支持：按消费金额/次数/成长值。
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger(__name__)


# ── 常量 ──────────────────────────────────────────────────────

UPGRADE_CRITERIA = ("spend_amount_fen", "order_count", "growth_value")
DOWNGRADE_CRITERIA = ("spend_amount_fen", "order_count", "growth_value")
MEMBER_DAY_TYPES = ("weekly", "monthly")
BATCH_OP_TYPES = ("recharge", "deduct", "transfer")


# ── 工具函数 ──────────────────────────────────────────────────


def _to_uuid(val: str) -> uuid.UUID:
    return uuid.UUID(val)


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


async def _set_tenant(db: AsyncSession, tenant_id: str) -> None:
    """设置 RLS tenant 上下文"""
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": tenant_id},
    )


def validate_level_rules(levels: list[dict]) -> bool:
    """校验等级规则列表结构是否合法"""
    if not levels:
        return False
    for lvl in levels:
        if "name" not in lvl or "rank" not in lvl:
            return False
        if not isinstance(lvl["rank"], int) or lvl["rank"] < 0:
            return False
    # rank 不能重复
    ranks = [lvl["rank"] for lvl in levels]
    if len(ranks) != len(set(ranks)):
        return False
    return True


def check_upgrade_eligible(
    current_rank: int,
    levels: list[dict],
    customer_stats: dict,
) -> Optional[dict]:
    """检查是否满足升级条件，返回目标等级或 None

    Args:
        current_rank: 当前等级 rank
        levels: 等级配置列表（按 rank 升序）
        customer_stats: {"spend_amount_fen": int, "order_count": int, "growth_value": int}

    Returns:
        目标等级 dict 或 None
    """
    sorted_levels = sorted(levels, key=lambda x: x["rank"], reverse=True)
    for lvl in sorted_levels:
        if lvl["rank"] <= current_rank:
            break
        upgrade_rules = lvl.get("upgrade_rules", {})
        if _meets_criteria(upgrade_rules, customer_stats):
            return lvl
    return None


def check_downgrade_eligible(
    current_rank: int,
    levels: list[dict],
    customer_stats: dict,
) -> Optional[dict]:
    """检查是否需要降级，返回目标等级或 None"""
    sorted_levels = sorted(levels, key=lambda x: x["rank"])
    current_level = None
    for lvl in sorted_levels:
        if lvl["rank"] == current_rank:
            current_level = lvl
            break

    if current_level is None:
        return None

    downgrade_rules = current_level.get("downgrade_rules", {})
    if not downgrade_rules:
        return None

    if _fails_criteria(downgrade_rules, customer_stats):
        # 降到下一个更低等级
        lower_levels = [lv for lv in sorted_levels if lv["rank"] < current_rank]
        if lower_levels:
            return lower_levels[-1]  # 最高的下级
    return None


def _meets_criteria(rules: dict, stats: dict) -> bool:
    """检查是否满足所有升级条件（任一条件满足即可升级）"""
    if not rules:
        return False
    for criterion in UPGRADE_CRITERIA:
        threshold = rules.get(criterion)
        if threshold is not None and stats.get(criterion, 0) >= threshold:
            return True
    return False


def _fails_criteria(rules: dict, stats: dict) -> bool:
    """检查是否跌破降级阈值（所有条件都低于阈值才降级）"""
    if not rules:
        return False
    for criterion in DOWNGRADE_CRITERIA:
        threshold = rules.get(criterion)
        if threshold is not None and stats.get(criterion, 0) >= threshold:
            return False
    return True


def validate_member_day_config(config: dict) -> bool:
    """校验会员日配置"""
    day_type = config.get("type")
    if day_type not in MEMBER_DAY_TYPES:
        return False
    if day_type == "weekly":
        day_value = config.get("day_of_week")
        if not isinstance(day_value, int) or day_value < 0 or day_value > 6:
            return False
    elif day_type == "monthly":
        day_value = config.get("day_of_month")
        if not isinstance(day_value, int) or day_value < 1 or day_value > 28:
            return False
    return True


def resolve_store_benefits(
    base_benefits: list[dict],
    store_overrides: dict,
    store_id: str,
) -> list[dict]:
    """合并基础权益与门店差异化配置

    Args:
        base_benefits: 卡类型的基础权益列表
        store_overrides: {store_id: {benefit_key: override_value}}
        store_id: 当前门店 ID

    Returns:
        合并后的权益列表
    """
    overrides = store_overrides.get(store_id, {})
    if not overrides:
        return base_benefits

    result = []
    for benefit in base_benefits:
        merged = {**benefit}
        bkey = benefit.get("key", "")
        if bkey in overrides:
            merged.update(overrides[bkey])
        result.append(merged)
    return result


def validate_batch_operations(operations: list[dict]) -> tuple[bool, str]:
    """校验批量操作列表"""
    if not operations:
        return False, "operations_empty"
    for i, op in enumerate(operations):
        op_type = op.get("type")
        if op_type not in BATCH_OP_TYPES:
            return False, f"invalid_op_type_at_{i}:{op_type}"
        amount = op.get("amount_fen", 0)
        if not isinstance(amount, int) or amount <= 0:
            return False, f"invalid_amount_at_{i}:{amount}"
        if "card_id" not in op:
            return False, f"missing_card_id_at_{i}"
    return True, "ok"


# ── 服务函数 ──────────────────────────────────────────────────


async def create_card_type(
    name: str,
    rules: dict,
    tenant_id: str,
    db: AsyncSession,
) -> dict[str, Any]:
    """创建卡类型（含储值/积分使用规则）

    Args:
        name: 卡类型名称
        rules: {"stored_value_enabled": bool, "points_enabled": bool, ...}
        tenant_id: 租户 ID
        db: 数据库会话

    Returns:
        {"card_type_id", "name", "rules", "created_at"}
    """
    await _set_tenant(db, tenant_id)
    card_type_id = str(uuid.uuid4())
    now = _now_utc()

    await db.execute(
        text("""
            INSERT INTO card_types (id, tenant_id, name, rules, created_at, updated_at, is_deleted)
            VALUES (:id, :tid, :name, :rules::jsonb, :now, :now, false)
        """),
        {
            "id": card_type_id,
            "tid": tenant_id,
            "name": name,
            "rules": json.dumps(rules, ensure_ascii=False),
            "now": now,
        },
    )
    await db.flush()

    logger.info(
        "card_type_created",
        tenant_id=tenant_id,
        card_type_id=card_type_id,
        name=name,
    )

    return {
        "card_type_id": card_type_id,
        "name": name,
        "rules": rules,
        "created_at": now.isoformat(),
    }


async def set_card_levels(
    card_type_id: str,
    levels: list[dict],
    tenant_id: str,
    db: AsyncSession,
) -> dict[str, Any]:
    """设置卡等级（权益/升级规则/降级规则）

    Args:
        card_type_id: 卡类型 ID
        levels: [{"name": "银卡", "rank": 1, "benefits": [...],
                  "upgrade_rules": {"spend_amount_fen": 100000}, "downgrade_rules": {...}}]
        tenant_id: 租户 ID
        db: 数据库会话

    Returns:
        {"card_type_id", "levels_count", "levels"}
    """
    await _set_tenant(db, tenant_id)

    if not validate_level_rules(levels):
        raise ValueError("invalid_level_rules")

    import json

    now = _now_utc()

    await db.execute(
        text("""
            UPDATE card_types SET levels = :levels::jsonb, updated_at = :now
            WHERE id = :ctid AND tenant_id = :tid AND is_deleted = false
        """),
        {
            "ctid": card_type_id,
            "tid": tenant_id,
            "levels": json.dumps(levels, ensure_ascii=False),
            "now": now,
        },
    )
    await db.flush()

    logger.info(
        "card_levels_set",
        tenant_id=tenant_id,
        card_type_id=card_type_id,
        levels_count=len(levels),
    )

    return {
        "card_type_id": card_type_id,
        "levels_count": len(levels),
        "levels": levels,
    }


async def create_anonymous_card(
    card_type_id: str,
    batch_no: str,
    count: int,
    tenant_id: str,
    db: AsyncSession,
) -> dict[str, Any]:
    """批量创建匿名实体卡

    Args:
        card_type_id: 卡类型 ID
        batch_no: 批次号
        count: 数量
        tenant_id: 租户 ID
        db: 数据库会话

    Returns:
        {"batch_no", "count", "card_ids"}
    """
    await _set_tenant(db, tenant_id)

    if count <= 0 or count > 10000:
        raise ValueError("count_must_be_1_to_10000")

    now = _now_utc()
    card_ids: list[str] = []

    for _ in range(count):
        card_id = str(uuid.uuid4())
        card_ids.append(card_id)
        await db.execute(
            text("""
                INSERT INTO member_cards
                    (id, tenant_id, card_type_id, batch_no, status, is_anonymous,
                     created_at, updated_at, is_deleted)
                VALUES (:id, :tid, :ctid, :batch, 'inactive', true, :now, :now, false)
            """),
            {
                "id": card_id,
                "tid": tenant_id,
                "ctid": card_type_id,
                "batch": batch_no,
                "now": now,
            },
        )

    await db.flush()

    logger.info(
        "anonymous_cards_created",
        tenant_id=tenant_id,
        card_type_id=card_type_id,
        batch_no=batch_no,
        count=count,
    )

    return {
        "batch_no": batch_no,
        "count": count,
        "card_ids": card_ids,
    }


async def issue_card(
    customer_id: str,
    card_type_id: str,
    tenant_id: str,
    db: AsyncSession,
) -> dict[str, Any]:
    """发卡

    Args:
        customer_id: 客户 ID
        card_type_id: 卡类型 ID
        tenant_id: 租户 ID
        db: 数据库会话

    Returns:
        {"card_id", "customer_id", "card_type_id", "status", "issued_at"}
    """
    await _set_tenant(db, tenant_id)
    card_id = str(uuid.uuid4())
    now = _now_utc()

    await db.execute(
        text("""
            INSERT INTO member_cards
                (id, tenant_id, card_type_id, customer_id, status, is_anonymous,
                 level_rank, balance_fen, points, growth_value,
                 issued_at, created_at, updated_at, is_deleted)
            VALUES (:id, :tid, :ctid, :cid, 'active', false,
                    0, 0, 0, 0,
                    :now, :now, :now, false)
        """),
        {
            "id": card_id,
            "tid": tenant_id,
            "ctid": card_type_id,
            "cid": customer_id,
            "now": now,
        },
    )
    await db.flush()

    logger.info(
        "card_issued",
        tenant_id=tenant_id,
        card_id=card_id,
        customer_id=customer_id,
        card_type_id=card_type_id,
    )

    return {
        "card_id": card_id,
        "customer_id": customer_id,
        "card_type_id": card_type_id,
        "status": "active",
        "issued_at": now.isoformat(),
    }


async def upgrade_level(
    card_id: str,
    tenant_id: str,
    db: AsyncSession,
) -> dict[str, Any]:
    """等级升级（根据规则自动判定）

    Returns:
        {"card_id", "old_rank", "new_rank", "upgraded": bool}
    """
    await _set_tenant(db, tenant_id)

    # 获取卡信息
    card_row = await db.execute(
        text("""
            SELECT mc.level_rank, mc.card_type_id, mc.growth_value,
                   ct.levels::text
            FROM member_cards mc
            JOIN card_types ct ON ct.id = mc.card_type_id
            WHERE mc.id = :cid AND mc.tenant_id = :tid AND mc.is_deleted = false
        """),
        {"cid": card_id, "tid": tenant_id},
    )
    row = card_row.mappings().first()
    if not row:
        raise ValueError("card_not_found")

    import json

    current_rank = row["level_rank"]
    levels = json.loads(row["levels"]) if row["levels"] else []
    growth_value = row["growth_value"] or 0

    # 获取客户消费统计（简化：使用 growth_value 作为主判据）
    customer_stats = {
        "spend_amount_fen": 0,
        "order_count": 0,
        "growth_value": growth_value,
    }

    target = check_upgrade_eligible(current_rank, levels, customer_stats)
    if target is None:
        logger.info(
            "upgrade_not_eligible",
            tenant_id=tenant_id,
            card_id=card_id,
            current_rank=current_rank,
        )
        return {"card_id": card_id, "old_rank": current_rank, "new_rank": current_rank, "upgraded": False}

    new_rank = target["rank"]
    now = _now_utc()
    await db.execute(
        text("""
            UPDATE member_cards SET level_rank = :rank, updated_at = :now
            WHERE id = :cid AND tenant_id = :tid
        """),
        {"rank": new_rank, "cid": card_id, "tid": tenant_id, "now": now},
    )
    await db.flush()

    logger.info(
        "card_upgraded",
        tenant_id=tenant_id,
        card_id=card_id,
        old_rank=current_rank,
        new_rank=new_rank,
    )

    return {"card_id": card_id, "old_rank": current_rank, "new_rank": new_rank, "upgraded": True}


async def downgrade_level(
    card_id: str,
    tenant_id: str,
    db: AsyncSession,
) -> dict[str, Any]:
    """等级降级

    Returns:
        {"card_id", "old_rank", "new_rank", "downgraded": bool}
    """
    await _set_tenant(db, tenant_id)

    card_row = await db.execute(
        text("""
            SELECT mc.level_rank, mc.card_type_id, mc.growth_value,
                   ct.levels::text
            FROM member_cards mc
            JOIN card_types ct ON ct.id = mc.card_type_id
            WHERE mc.id = :cid AND mc.tenant_id = :tid AND mc.is_deleted = false
        """),
        {"cid": card_id, "tid": tenant_id},
    )
    row = card_row.mappings().first()
    if not row:
        raise ValueError("card_not_found")

    import json

    current_rank = row["level_rank"]
    levels = json.loads(row["levels"]) if row["levels"] else []
    growth_value = row["growth_value"] or 0

    customer_stats = {
        "spend_amount_fen": 0,
        "order_count": 0,
        "growth_value": growth_value,
    }

    target = check_downgrade_eligible(current_rank, levels, customer_stats)
    if target is None:
        return {"card_id": card_id, "old_rank": current_rank, "new_rank": current_rank, "downgraded": False}

    new_rank = target["rank"]
    now = _now_utc()
    await db.execute(
        text("""
            UPDATE member_cards SET level_rank = :rank, updated_at = :now
            WHERE id = :cid AND tenant_id = :tid
        """),
        {"rank": new_rank, "cid": card_id, "tid": tenant_id, "now": now},
    )
    await db.flush()

    logger.info(
        "card_downgraded",
        tenant_id=tenant_id,
        card_id=card_id,
        old_rank=current_rank,
        new_rank=new_rank,
    )

    return {"card_id": card_id, "old_rank": current_rank, "new_rank": new_rank, "downgraded": True}


async def set_member_day(
    card_type_id: str,
    config: dict,
    tenant_id: str,
    db: AsyncSession,
) -> dict[str, Any]:
    """会员日设置（周几/每月几号）

    Args:
        card_type_id: 卡类型 ID
        config: {"type": "weekly"|"monthly", "day_of_week": 0-6, "day_of_month": 1-28,
                 "benefits": [...]}
        tenant_id: 租户 ID
        db: 数据库会话

    Returns:
        {"card_type_id", "member_day_config"}
    """
    await _set_tenant(db, tenant_id)

    if not validate_member_day_config(config):
        raise ValueError("invalid_member_day_config")

    import json

    now = _now_utc()

    await db.execute(
        text("""
            UPDATE card_types SET member_day_config = :cfg::jsonb, updated_at = :now
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
        "member_day_set",
        tenant_id=tenant_id,
        card_type_id=card_type_id,
        day_type=config.get("type"),
    )

    return {
        "card_type_id": card_type_id,
        "member_day_config": config,
    }


async def get_card_benefits(
    card_id: str,
    store_id: str,
    tenant_id: str,
    db: AsyncSession,
) -> dict[str, Any]:
    """获取当前卡的所有权益（含门店差异化）

    Returns:
        {"card_id", "level_name", "benefits"}
    """
    await _set_tenant(db, tenant_id)

    row = await db.execute(
        text("""
            SELECT mc.level_rank, ct.levels::text, ct.rules::text
            FROM member_cards mc
            JOIN card_types ct ON ct.id = mc.card_type_id
            WHERE mc.id = :cid AND mc.tenant_id = :tid AND mc.is_deleted = false
        """),
        {"cid": card_id, "tid": tenant_id},
    )
    card = row.mappings().first()
    if not card:
        raise ValueError("card_not_found")

    import json

    level_rank = card["level_rank"]
    levels = json.loads(card["levels"]) if card["levels"] else []
    rules = json.loads(card["rules"]) if card["rules"] else {}

    # 找到当前等级
    current_level = None
    for lvl in levels:
        if lvl["rank"] == level_rank:
            current_level = lvl
            break

    base_benefits = current_level.get("benefits", []) if current_level else []
    store_overrides = rules.get("store_overrides", {})
    benefits = resolve_store_benefits(base_benefits, store_overrides, store_id)

    level_name = current_level["name"] if current_level else "default"

    logger.info(
        "card_benefits_retrieved",
        tenant_id=tenant_id,
        card_id=card_id,
        store_id=store_id,
        level_name=level_name,
        benefits_count=len(benefits),
    )

    return {
        "card_id": card_id,
        "level_name": level_name,
        "level_rank": level_rank,
        "benefits": benefits,
    }


async def batch_card_operations(
    operations: list[dict],
    tenant_id: str,
    db: AsyncSession,
) -> dict[str, Any]:
    """批量操作（充值/扣减/转移）

    Args:
        operations: [{"type": "recharge"|"deduct"|"transfer",
                      "card_id": str, "amount_fen": int, ...}]
        tenant_id: 租户 ID
        db: 数据库会话

    Returns:
        {"total_ops", "success_count", "failed_count", "results"}
    """
    await _set_tenant(db, tenant_id)

    valid, msg = validate_batch_operations(operations)
    if not valid:
        raise ValueError(msg)

    now = _now_utc()
    results: list[dict] = []
    success_count = 0
    failed_count = 0

    for op in operations:
        op_type = op["type"]
        card_id = op["card_id"]
        amount_fen = op["amount_fen"]

        try:
            if op_type == "recharge":
                await db.execute(
                    text("""
                        UPDATE member_cards
                        SET balance_fen = balance_fen + :amt, updated_at = :now
                        WHERE id = :cid AND tenant_id = :tid AND is_deleted = false
                    """),
                    {"amt": amount_fen, "cid": card_id, "tid": tenant_id, "now": now},
                )
            elif op_type == "deduct":
                await db.execute(
                    text("""
                        UPDATE member_cards
                        SET balance_fen = GREATEST(balance_fen - :amt, 0), updated_at = :now
                        WHERE id = :cid AND tenant_id = :tid AND is_deleted = false
                    """),
                    {"amt": amount_fen, "cid": card_id, "tid": tenant_id, "now": now},
                )
            elif op_type == "transfer":
                target_card_id = op.get("target_card_id")
                if not target_card_id:
                    raise ValueError("missing_target_card_id")
                await db.execute(
                    text("""
                        UPDATE member_cards
                        SET balance_fen = GREATEST(balance_fen - :amt, 0), updated_at = :now
                        WHERE id = :cid AND tenant_id = :tid AND is_deleted = false
                    """),
                    {"amt": amount_fen, "cid": card_id, "tid": tenant_id, "now": now},
                )
                await db.execute(
                    text("""
                        UPDATE member_cards
                        SET balance_fen = balance_fen + :amt, updated_at = :now
                        WHERE id = :tcid AND tenant_id = :tid AND is_deleted = false
                    """),
                    {"amt": amount_fen, "tcid": target_card_id, "tid": tenant_id, "now": now},
                )

            success_count += 1
            results.append({"index": len(results), "card_id": card_id, "type": op_type, "status": "ok"})
        except ValueError as e:
            failed_count += 1
            results.append(
                {"index": len(results), "card_id": card_id, "type": op_type, "status": "failed", "error": str(e)}
            )

    await db.flush()

    logger.info(
        "batch_card_operations_completed",
        tenant_id=tenant_id,
        total=len(operations),
        success=success_count,
        failed=failed_count,
    )

    return {
        "total_ops": len(operations),
        "success_count": success_count,
        "failed_count": failed_count,
        "results": results,
    }
