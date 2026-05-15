"""share_split_service — POS 销售分成转入库（PRD-11 sub-A / Phase 2 W11 / T2 + Tier 1 邻接）

核心业务逻辑：
  1. CRUD 配置 (create_rule / get_rule / get_rule_by_dish / list_rules / update_rule / delete_rule)
  2. resolve_split 核心算法 (3-way enum: even / weighted / manual)
  3. apply_split (rule + spec 综合校验 + 计算)

设计要点：
  - RLS 标准模式：每次操作前 set_config('app.tenant_id', :tid, true)
  - text() 全部用 :param + 预构造常量 (避 f-string baseline 守门 / L011)
  - asyncpg IntegrityError rollback + RLS 重设模式 (PRD-08 §19 round-2 P0-3 lesson:
    feedback_asyncpg_rollback_after_integrity_error.md)
  - resolve_split 余数 fen 分摊到 share[0..r-1] (确保 sum == bom_cost_total_fen)
  - manual mode strict checksum: sum(amounts_fen) MUST == bom_cost_total_fen
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional, Union

import structlog
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

from ..models.share_split_models import (
    ResolvedShare,
    ResolvedSplitResult,
    ShareSplitMethod,
    ShareSplitSpec,
)

logger = structlog.get_logger(__name__)

_DBConn = Union[AsyncConnection, AsyncSession]


def _uuid_str(val: str | uuid.UUID) -> str:
    return str(val)


async def _set_tenant(db: _DBConn, tenant_id: str) -> None:
    """设置 RLS 租户上下文。"""
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": str(tenant_id)},
    )


# ─── 预构造 SQL ───────────────────────────────────────────────────────────────


_INSERT_RULE_SQL = """
    INSERT INTO share_split_rules (
        id, tenant_id, dish_id, allow_share, default_method,
        max_share_count, is_active, notes, created_by,
        created_at, updated_at, is_deleted
    )
    VALUES (
        :id, :tenant_id, :dish_id, :allow_share, :default_method,
        :max_share_count, TRUE, :notes, :created_by,
        :now, :now, FALSE
    )
    RETURNING
        id::text                    AS id,
        tenant_id::text             AS tenant_id,
        dish_id::text               AS dish_id,
        allow_share,
        default_method,
        max_share_count,
        is_active,
        notes,
        created_by::text            AS created_by,
        created_at,
        updated_at,
        is_deleted
"""

_GET_RULE_BY_ID_SQL = """
    SELECT
        id::text                AS id,
        tenant_id::text         AS tenant_id,
        dish_id::text           AS dish_id,
        allow_share,
        default_method,
        max_share_count,
        is_active,
        notes,
        created_by::text        AS created_by,
        created_at,
        updated_at,
        is_deleted
    FROM share_split_rules
    WHERE id        = :rule_id
      AND tenant_id = :tenant_id
      AND is_deleted = FALSE
    LIMIT 1
"""

_GET_RULE_BY_DISH_SQL = """
    SELECT
        id::text                AS id,
        tenant_id::text         AS tenant_id,
        dish_id::text           AS dish_id,
        allow_share,
        default_method,
        max_share_count,
        is_active,
        notes,
        created_by::text        AS created_by,
        created_at,
        updated_at,
        is_deleted
    FROM share_split_rules
    WHERE dish_id    = :dish_id
      AND tenant_id  = :tenant_id
      AND is_deleted = FALSE
    LIMIT 1
"""

_LIST_RULES_BASE_SQL = """
    SELECT
        id::text                AS id,
        tenant_id::text         AS tenant_id,
        dish_id::text           AS dish_id,
        allow_share,
        default_method,
        max_share_count,
        is_active,
        notes,
        created_by::text        AS created_by,
        created_at,
        updated_at,
        is_deleted
    FROM share_split_rules
    WHERE tenant_id  = :tenant_id
      AND is_deleted = FALSE
"""

_LIST_RULES_ALL_SQL = (
    _LIST_RULES_BASE_SQL
    + " ORDER BY created_at DESC LIMIT :limit OFFSET :offset"
)
_LIST_RULES_ACTIVE_SQL = (
    _LIST_RULES_BASE_SQL
    + " AND is_active = TRUE ORDER BY created_at DESC LIMIT :limit OFFSET :offset"
)


# §19 PRD-08 P0-1 lesson: 动态 SQL 拼接 — 仅 SET 用户实际提供的字段, 让 NULL 也能写入
_UPDATE_RULE_PREFIX_SQL = (
    "UPDATE share_split_rules SET updated_at = :now"
)
_UPDATE_RULE_SUFFIX_SQL = (
    " WHERE id = :rule_id"
    " AND tenant_id = :tenant_id"
    " AND is_deleted = FALSE"
)
_UPDATE_FIELD_FRAGMENTS: dict[str, str] = {
    "allow_share": ", allow_share = :allow_share",
    "default_method": ", default_method = :default_method",
    "max_share_count": ", max_share_count = :max_share_count",
    "is_active": ", is_active = :is_active",
    "notes": ", notes = :notes",
}


_DELETE_RULE_SQL = """
    UPDATE share_split_rules
    SET is_deleted = TRUE,
        is_active  = FALSE,
        updated_at = :now
    WHERE id        = :rule_id
      AND tenant_id = :tenant_id
      AND is_deleted = FALSE
"""


# ─── CRUD ────────────────────────────────────────────────────────────────────


async def create_rule(
    db: AsyncSession,
    tenant_id: str,
    *,
    dish_id: str,
    created_by: str,
    allow_share: bool = True,
    default_method: str = "even",
    max_share_count: Optional[int] = None,
    notes: Optional[str] = None,
) -> dict:
    """新建分享规则。UNIQUE (tenant_id, dish_id) WHERE is_deleted=FALSE — 重复 ValueError, 路由 409。

    §19 PRD-08 P0-3 lesson: IntegrityError 后必须 rollback + _set_tenant 重设 RLS,
    否则 asyncpg 触 InFailedSqlTransactionError → 500.
    """
    if default_method not in ("even", "weighted", "manual"):
        raise ValueError(
            f"default_method 必须是 even/weighted/manual, 实际 {default_method}"
        )
    if max_share_count is not None and max_share_count < 2:
        raise ValueError("max_share_count 必须 >= 2 或 NULL (不限人数)")

    await _set_tenant(db, tenant_id)

    rule_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)

    try:
        result = await db.execute(
            text(_INSERT_RULE_SQL),
            {
                "id": rule_id,
                "tenant_id": _uuid_str(tenant_id),
                "dish_id": _uuid_str(dish_id),
                "allow_share": allow_share,
                "default_method": default_method,
                "max_share_count": max_share_count,
                "notes": notes,
                "created_by": _uuid_str(created_by),
                "now": now,
            },
        )
    except IntegrityError as exc:
        # PRD-08 P0-3 fix 同模式: rollback + 重设 RLS, 再查 (dish_id) 是否已有
        # is_active=FALSE 软禁用 row, 给出 PATCH 引导 vs 单纯"已存在".
        await db.rollback()
        await _set_tenant(db, tenant_id)
        existing_result = await db.execute(
            text(_GET_RULE_BY_DISH_SQL),
            {
                "dish_id": _uuid_str(dish_id),
                "tenant_id": _uuid_str(tenant_id),
            },
        )
        existing_row = existing_result.mappings().first()
        if existing_row is not None and not existing_row.get("is_active"):
            raise ValueError(
                f"分享规则已存在但被禁用 (rule_id={existing_row['id']}); "
                f"请用 PATCH /api/v1/supply/share-split-rules/{existing_row['id']} "
                f'body {{"is_active": true}} 重新激活, 而非新建'
            ) from exc
        raise ValueError(
            f"分享规则已存在: dish_id={dish_id} (同 dish 一条 active rule)"
        ) from exc

    row = result.mappings().first()
    if row is None:
        raise ValueError("create_rule failed — RETURNING 无结果")

    logger.info(
        "share_split_rule_created",
        rule_id=rule_id,
        tenant_id=str(tenant_id),
        dish_id=str(dish_id),
        allow_share=allow_share,
        default_method=default_method,
    )
    return dict(row)


async def get_rule(
    db: AsyncSession,
    tenant_id: str,
    rule_id: str,
) -> Optional[dict]:
    """按 ID 查规则。"""
    await _set_tenant(db, tenant_id)
    result = await db.execute(
        text(_GET_RULE_BY_ID_SQL),
        {"rule_id": rule_id, "tenant_id": _uuid_str(tenant_id)},
    )
    row = result.mappings().first()
    return dict(row) if row else None


async def get_rule_by_dish(
    db: AsyncSession,
    tenant_id: str,
    dish_id: str,
) -> Optional[dict]:
    """按 dish_id 查规则 (auto_deduction 集成入口)。"""
    await _set_tenant(db, tenant_id)
    result = await db.execute(
        text(_GET_RULE_BY_DISH_SQL),
        {"dish_id": _uuid_str(dish_id), "tenant_id": _uuid_str(tenant_id)},
    )
    row = result.mappings().first()
    return dict(row) if row else None


async def list_rules(
    db: AsyncSession,
    tenant_id: str,
    *,
    only_active: bool = True,
    limit: int = 50,
    offset: int = 0,
) -> list[dict]:
    """列表 (按 created_at 倒序)."""
    if limit <= 0 or limit > 200:
        raise ValueError(f"limit 必须 in (0, 200], 实际 {limit}")
    if offset < 0:
        raise ValueError(f"offset 必须 >= 0, 实际 {offset}")

    await _set_tenant(db, tenant_id)

    prepared_text = _LIST_RULES_ACTIVE_SQL if only_active else _LIST_RULES_ALL_SQL
    result = await db.execute(
        text(prepared_text),
        {
            "tenant_id": _uuid_str(tenant_id),
            "limit": limit,
            "offset": offset,
        },
    )
    return [dict(r) for r in result.mappings().all()]


async def update_rule(
    db: AsyncSession,
    tenant_id: str,
    rule_id: str,
    *,
    updates: dict,
) -> dict:
    """更新规则 (PRD-08 P0-1 lesson 同模式: dict updates + 动态 SQL 拼接)。

    允许字段: allow_share / default_method / max_share_count / is_active / notes
    """
    allowed = set(_UPDATE_FIELD_FRAGMENTS.keys())
    set_keys = sorted(set(updates.keys()) & allowed)
    if not set_keys:
        raise ValueError("至少提供一个更新字段")

    # §19 round-1 P1-1 fix: default_method=None 必须拦截 (schema NOT NULL, 否则
    # asyncpg IntegrityError → 路由 500 而非 422)
    if "default_method" in updates:
        m = updates["default_method"]
        if m is None:
            raise ValueError(
                "default_method 不能为 NULL — 允许值: even/weighted/manual"
            )
        if m not in ("even", "weighted", "manual"):
            raise ValueError(
                f"default_method 必须是 even/weighted/manual, 实际 {m}"
            )
    # §19 round-1 P1-1 fix 同模式: allow_share=None (schema NOT NULL) → ValueError
    if "allow_share" in updates and updates["allow_share"] is None:
        raise ValueError("allow_share 不能为 NULL — 允许值: true/false")
    if "is_active" in updates and updates["is_active"] is None:
        raise ValueError("is_active 不能为 NULL — 允许值: true/false")
    # 校验 max_share_count
    if "max_share_count" in updates:
        msc = updates["max_share_count"]
        if msc is not None and msc < 2:
            raise ValueError("max_share_count 必须 >= 2 或显式 None (NULL = 不限人数)")

    await _set_tenant(db, tenant_id)

    existing = await get_rule(db, tenant_id, rule_id)
    if existing is None:
        raise ValueError(f"rule_id={rule_id} 不存在或已删除")

    sql_parts = [_UPDATE_RULE_PREFIX_SQL]
    params: dict[str, object] = {
        "rule_id": rule_id,
        "tenant_id": _uuid_str(tenant_id),
        "now": datetime.now(timezone.utc),
    }
    for key in set_keys:
        sql_parts.append(_UPDATE_FIELD_FRAGMENTS[key])
        params[key] = updates[key]
    sql_parts.append(_UPDATE_RULE_SUFFIX_SQL)
    prepared_text = "".join(sql_parts)

    await db.execute(text(prepared_text), params)

    logger.info(
        "share_split_rule_updated",
        rule_id=rule_id,
        tenant_id=str(tenant_id),
        fields=set_keys,
    )
    return (await get_rule(db, tenant_id, rule_id)) or {}


async def delete_rule(
    db: AsyncSession,
    tenant_id: str,
    rule_id: str,
) -> bool:
    """软删 (is_deleted=TRUE + is_active=FALSE)."""
    await _set_tenant(db, tenant_id)
    result = await db.execute(
        text(_DELETE_RULE_SQL),
        {
            "rule_id": rule_id,
            "tenant_id": _uuid_str(tenant_id),
            "now": datetime.now(timezone.utc),
        },
    )
    return bool(result.rowcount)


# ─── resolve_split — 核心分配算法 ─────────────────────────────────────────────


def resolve_split(
    spec: ShareSplitSpec,
    bom_cost_total_fen: int,
) -> ResolvedSplitResult:
    """根据 spec 把 bom_cost_total_fen 分摊到 spec.count 个 share.

    严格保证 sum(shares.attributed_cost_fen) == bom_cost_total_fen.

    EVEN:
      base = bom_cost_total_fen // count
      remainder = bom_cost_total_fen % count
      share[0..remainder-1] 各 +1 fen
      weight = Decimal(1) / count (统一)

    WEIGHTED:
      total_weight = sum(weights)
      tmp_amounts[i] = bom_cost_total_fen * weights[i] / total_weight (Decimal 精算后 truncate to int)
      remainder = bom_cost_total_fen - sum(tmp_amounts)
      remainder fen 分给 weights 最大的前 remainder 个 share
      weight = weights[i] / total_weight (归一)

    MANUAL:
      sum(amounts_fen) MUST == bom_cost_total_fen, 否则 ValueError
      weight = amounts_fen[i] / bom_cost_total_fen (反推, 0 时为 Decimal(0))
    """
    if bom_cost_total_fen < 0:
        raise ValueError(f"bom_cost_total_fen 必须 >= 0, 实际 {bom_cost_total_fen}")

    method = spec.method
    count = spec.count

    if method == ShareSplitMethod.EVEN:
        base = bom_cost_total_fen // count
        remainder = bom_cost_total_fen % count
        amounts = [base + (1 if i < remainder else 0) for i in range(count)]
        weight_each = Decimal(1) / Decimal(count)
        shares = [
            ResolvedShare(
                share_index=i,
                weight=weight_each,
                attributed_cost_fen=amounts[i],
            )
            for i in range(count)
        ]
    elif method == ShareSplitMethod.WEIGHTED:
        weights = spec.weights or []
        total_weight = sum(weights)
        if total_weight <= 0:
            raise ValueError("WEIGHTED resolve_split: sum(weights) 必须 > 0")
        # 精算 amounts (整数 fen, truncate 向下)
        tmp_amounts: list[int] = []
        bom_decimal = Decimal(bom_cost_total_fen)
        for w in weights:
            portion = bom_decimal * w / total_weight
            tmp_amounts.append(int(portion))
        # 余数分配给 weights 最大的前 r 个 share (公平 + 偏好大权重)
        remainder = bom_cost_total_fen - sum(tmp_amounts)
        if remainder > 0:
            # 按 weight 降序拿前 remainder 个 index
            indexed_weights = sorted(
                enumerate(weights), key=lambda x: x[1], reverse=True
            )
            for i in range(remainder):
                target_idx = indexed_weights[i][0]
                tmp_amounts[target_idx] += 1
        # 归一化 weight 输出
        shares = [
            ResolvedShare(
                share_index=i,
                weight=weights[i] / total_weight,
                attributed_cost_fen=tmp_amounts[i],
            )
            for i in range(count)
        ]
    elif method == ShareSplitMethod.MANUAL:
        amounts_fen = spec.amounts_fen or []
        total = sum(amounts_fen)
        if total != bom_cost_total_fen:
            raise ValueError(
                f"MANUAL resolve_split: sum(amounts_fen)={total} != "
                f"bom_cost_total_fen={bom_cost_total_fen} (严格相等校验)"
            )
        # weight = amounts_fen[i] / bom_cost_total_fen (反推, 0 时为 Decimal(0))
        if bom_cost_total_fen == 0:
            weights_norm = [Decimal(0)] * count
        else:
            weights_norm = [
                Decimal(a) / Decimal(bom_cost_total_fen) for a in amounts_fen
            ]
        shares = [
            ResolvedShare(
                share_index=i,
                weight=weights_norm[i],
                attributed_cost_fen=amounts_fen[i],
            )
            for i in range(count)
        ]
    else:  # pragma: no cover — Pydantic enum 已守门
        raise ValueError(f"未知 ShareSplitMethod: {method}")

    # 守门: sum 必须等于 total
    actual_sum = sum(s.attributed_cost_fen for s in shares)
    if actual_sum != bom_cost_total_fen:
        raise RuntimeError(
            f"resolve_split 内部错误: sum(shares)={actual_sum} != "
            f"bom_cost_total_fen={bom_cost_total_fen}"
        )

    return ResolvedSplitResult(
        method=method,
        count=count,
        bom_cost_total_fen=bom_cost_total_fen,
        shares=shares,
    )


# ─── apply_split: rule + spec 综合 ────────────────────────────────────────────


async def apply_split(
    db: AsyncSession,
    tenant_id: str,
    *,
    dish_id: str,
    spec: ShareSplitSpec,
    bom_cost_total_fen: int,
) -> ResolvedSplitResult:
    """综合 rule (查 dish_id 配置) + spec (caller 传入) 校验 + resolve.

    校验顺序:
      1. 查 share_split_rule by dish_id → 必存在且 is_active=TRUE
      2. rule.allow_share=FALSE → raise (此 dish 不允许分享)
      3. spec.count > rule.max_share_count (若 rule 设了上限) → raise
      4. spec.method 不影响 rule.default_method (caller 可覆盖)
      5. resolve_split() 计算分配
    """
    rule = await get_rule_by_dish(db, tenant_id, dish_id)
    if rule is None:
        raise ValueError(
            f"dish_id={dish_id} 未配置 share_split_rule — "
            f"请先创建规则才能拆单 (或将菜品 allow_share=FALSE)"
        )
    if not rule.get("is_active"):
        raise ValueError(
            f"dish_id={dish_id} share_split_rule 已禁用 (is_active=FALSE)"
        )
    if not rule.get("allow_share"):
        raise ValueError(
            f"dish_id={dish_id} 不允许分享 (allow_share=FALSE) — 单人套餐 / 不可拆分项"
        )
    max_share = rule.get("max_share_count")
    if max_share is not None and spec.count > max_share:
        raise ValueError(
            f"分享人数 {spec.count} 超过 dish {dish_id} 上限 {max_share}"
        )

    return resolve_split(spec, bom_cost_total_fen)


__all__ = [
    "create_rule",
    "get_rule",
    "get_rule_by_dish",
    "list_rules",
    "update_rule",
    "delete_rule",
    "resolve_split",
    "apply_split",
]
