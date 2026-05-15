"""dept_whitelist_service — 部门用料白名单服务（PRD-08 / Phase 2 W11 / T2 + Tier 1 邻接）

核心业务逻辑：
  1. CRUD 白名单 (create_whitelist / get_whitelist / list_whitelists / update_whitelist / delete_whitelist)
  2. 批量授权 (bulk_authorize) — 矩阵编辑器场景；upsert 已存在的 (dept_id, ingredient_id)
  3. 校验入口 (validate_ingredient_allowed) — 内部 service-to-service 调用入口
     供 dept_issue.create_issue_order / auto_deduction.deduct_for_dish 接入

设计要点：
  - RLS 标准模式：每次操作前 set_config('app.tenant_id', :tid, true)
  - text() 全部用 :param + 预构造常量（避 f-string baseline 守门 / L011）
  - max_qty_per_day NULL = 不限量；非 NULL + qty 提供时校验上限
  - is_active=FALSE 视为白名单不存在（软禁用语义）
  - 违反 raise IngredientNotAllowedError（typed），路由层映射 403 Forbidden
  - validate 路径包含 structlog WARN（食安总监 / 采购总监审计追踪）
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

from ..models.dept_whitelist_models import IngredientNotAllowedError

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


# ─── 预构造 SQL（避 f-string baseline 守门）────────────────────────────────


_INSERT_WHITELIST_SQL = """
    INSERT INTO department_ingredient_whitelists (
        id, tenant_id, dept_id, ingredient_id, max_qty_per_day,
        is_active, notes, created_by, created_at, updated_at, is_deleted
    )
    VALUES (
        :id, :tenant_id, :dept_id, :ingredient_id, :max_qty_per_day,
        TRUE, :notes, :created_by, :now, :now, FALSE
    )
    RETURNING
        id::text                    AS id,
        tenant_id::text             AS tenant_id,
        dept_id::text               AS dept_id,
        ingredient_id::text         AS ingredient_id,
        max_qty_per_day,
        is_active,
        notes,
        created_by::text            AS created_by,
        created_at,
        updated_at,
        is_deleted
"""

_GET_WHITELIST_BY_ID_SQL = """
    SELECT
        id::text                AS id,
        tenant_id::text         AS tenant_id,
        dept_id::text           AS dept_id,
        ingredient_id::text     AS ingredient_id,
        max_qty_per_day,
        is_active,
        notes,
        created_by::text        AS created_by,
        created_at,
        updated_at,
        is_deleted
    FROM department_ingredient_whitelists
    WHERE id        = :whitelist_id
      AND tenant_id = :tenant_id
      AND is_deleted = FALSE
    LIMIT 1
"""

_GET_WHITELIST_BY_PAIR_SQL = """
    SELECT
        id::text                AS id,
        tenant_id::text         AS tenant_id,
        dept_id::text           AS dept_id,
        ingredient_id::text     AS ingredient_id,
        max_qty_per_day,
        is_active,
        notes,
        created_by::text        AS created_by,
        created_at,
        updated_at,
        is_deleted
    FROM department_ingredient_whitelists
    WHERE dept_id       = :dept_id
      AND ingredient_id = :ingredient_id
      AND tenant_id     = :tenant_id
      AND is_deleted    = FALSE
    LIMIT 1
"""

_LIST_WHITELIST_BASE_SQL = """
    SELECT
        id::text                AS id,
        tenant_id::text         AS tenant_id,
        dept_id::text           AS dept_id,
        ingredient_id::text     AS ingredient_id,
        max_qty_per_day,
        is_active,
        notes,
        created_by::text        AS created_by,
        created_at,
        updated_at,
        is_deleted
    FROM department_ingredient_whitelists
    WHERE tenant_id  = :tenant_id
      AND is_deleted = FALSE
"""

_LIST_WHITELIST_ALL_SQL = (
    _LIST_WHITELIST_BASE_SQL
    + " ORDER BY created_at DESC LIMIT :limit OFFSET :offset"
)
_LIST_WHITELIST_DEPT_SQL = (
    _LIST_WHITELIST_BASE_SQL
    + " AND dept_id = :dept_id ORDER BY created_at DESC LIMIT :limit OFFSET :offset"
)
_LIST_WHITELIST_ACTIVE_SQL = (
    _LIST_WHITELIST_BASE_SQL
    + " AND is_active = TRUE ORDER BY created_at DESC LIMIT :limit OFFSET :offset"
)
_LIST_WHITELIST_DEPT_ACTIVE_SQL = (
    _LIST_WHITELIST_BASE_SQL
    + " AND dept_id = :dept_id AND is_active = TRUE"
    + " ORDER BY created_at DESC LIMIT :limit OFFSET :offset"
)


def _select_list_whitelists_sql(
    *, dept_id: Optional[str], only_active: bool
) -> str:
    """4 预构造 SQL 按 dept_id / only_active 选 — 完全避 f-string。"""
    if dept_id is not None and only_active:
        return _LIST_WHITELIST_DEPT_ACTIVE_SQL
    if dept_id is not None:
        return _LIST_WHITELIST_DEPT_SQL
    if only_active:
        return _LIST_WHITELIST_ACTIVE_SQL
    return _LIST_WHITELIST_ALL_SQL


_UPDATE_WHITELIST_SQL = """
    UPDATE department_ingredient_whitelists
    SET max_qty_per_day = COALESCE(:max_qty_per_day, max_qty_per_day),
        is_active       = COALESCE(:is_active, is_active),
        notes           = COALESCE(:notes, notes),
        updated_at      = :now
    WHERE id        = :whitelist_id
      AND tenant_id = :tenant_id
      AND is_deleted = FALSE
"""

_DELETE_WHITELIST_SQL = """
    UPDATE department_ingredient_whitelists
    SET is_deleted = TRUE,
        is_active  = FALSE,
        updated_at = :now
    WHERE id        = :whitelist_id
      AND tenant_id = :tenant_id
      AND is_deleted = FALSE
"""

# Upsert by (dept_id, ingredient_id) — 已 soft-deleted 的也恢复
_UPSERT_WHITELIST_BY_PAIR_SQL = """
    UPDATE department_ingredient_whitelists
    SET max_qty_per_day = :max_qty_per_day,
        is_active       = TRUE,
        is_deleted      = FALSE,
        notes           = :notes,
        updated_at      = :now
    WHERE dept_id       = :dept_id
      AND ingredient_id = :ingredient_id
      AND tenant_id     = :tenant_id
    RETURNING
        id::text                AS id,
        tenant_id::text         AS tenant_id,
        dept_id::text           AS dept_id,
        ingredient_id::text     AS ingredient_id,
        max_qty_per_day,
        is_active,
        notes,
        created_by::text        AS created_by,
        created_at,
        updated_at,
        is_deleted
"""


# ─── CRUD ────────────────────────────────────────────────────────────────────


async def create_whitelist(
    db: AsyncSession,
    tenant_id: str,
    *,
    dept_id: str,
    ingredient_id: str,
    created_by: str,
    max_qty_per_day: Optional[Decimal] = None,
    notes: Optional[str] = None,
) -> dict:
    """新建白名单。

    NULL max_qty_per_day = 不限量（D1 锁定语义）。
    UNIQUE (tenant_id, dept_id, ingredient_id) WHERE is_deleted=FALSE —
    重复 raise ValueError("已存在")，路由层映射 409 Conflict。
    """
    if max_qty_per_day is not None and max_qty_per_day <= 0:
        raise ValueError("max_qty_per_day 必须 > 0 或 NULL（不限量）")

    await _set_tenant(db, tenant_id)

    whitelist_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)

    try:
        result = await db.execute(
            text(_INSERT_WHITELIST_SQL),
            {
                "id": whitelist_id,
                "tenant_id": _uuid_str(tenant_id),
                "dept_id": _uuid_str(dept_id),
                "ingredient_id": _uuid_str(ingredient_id),
                "max_qty_per_day": max_qty_per_day,
                "notes": notes,
                "created_by": _uuid_str(created_by),
                "now": now,
            },
        )
    except IntegrityError as exc:
        raise ValueError(
            f"白名单已存在：dept_id={dept_id}, ingredient_id={ingredient_id}"
        ) from exc

    row = result.mappings().first()
    if row is None:
        raise ValueError("create_whitelist failed — RETURNING 无结果")

    logger.info(
        "dept_whitelist_created",
        whitelist_id=whitelist_id,
        tenant_id=str(tenant_id),
        dept_id=str(dept_id),
        ingredient_id=str(ingredient_id),
        max_qty_per_day=str(max_qty_per_day) if max_qty_per_day else None,
    )
    return dict(row)


async def get_whitelist(
    db: AsyncSession,
    tenant_id: str,
    whitelist_id: str,
) -> Optional[dict]:
    """按 ID 查白名单。"""
    await _set_tenant(db, tenant_id)
    result = await db.execute(
        text(_GET_WHITELIST_BY_ID_SQL),
        {"whitelist_id": whitelist_id, "tenant_id": _uuid_str(tenant_id)},
    )
    row = result.mappings().first()
    return dict(row) if row else None


async def list_whitelists(
    db: AsyncSession,
    tenant_id: str,
    *,
    dept_id: Optional[str] = None,
    only_active: bool = True,
    limit: int = 50,
    offset: int = 0,
) -> list[dict]:
    """白名单列表（按 created_at 倒序; 支持 dept_id / is_active 过滤）。

    用 4 个预构造 SQL 常量按布尔/过滤组合选 — 避 f-string baseline 守门。
    """
    if limit <= 0 or limit > 200:
        raise ValueError(f"limit 必须 in (0, 200], 实际 {limit}")
    if offset < 0:
        raise ValueError(f"offset 必须 >= 0, 实际 {offset}")

    await _set_tenant(db, tenant_id)

    prepared_text = _select_list_whitelists_sql(
        dept_id=dept_id, only_active=only_active
    )
    params: dict[str, object] = {
        "tenant_id": _uuid_str(tenant_id),
        "limit": limit,
        "offset": offset,
    }
    if dept_id is not None:
        params["dept_id"] = _uuid_str(dept_id)

    result = await db.execute(text(prepared_text), params)
    return [dict(r) for r in result.mappings().all()]


async def update_whitelist(
    db: AsyncSession,
    tenant_id: str,
    whitelist_id: str,
    *,
    max_qty_per_day: Optional[Decimal] = None,
    is_active: Optional[bool] = None,
    notes: Optional[str] = None,
) -> dict:
    """更新白名单。任一字段为 None 时 COALESCE 保留原值。"""
    fields = {
        "max_qty_per_day": max_qty_per_day,
        "is_active": is_active,
        "notes": notes,
    }
    set_fields = {k: v for k, v in fields.items() if v is not None}
    if not set_fields:
        raise ValueError("至少提供一个更新字段")

    if max_qty_per_day is not None and max_qty_per_day <= 0:
        raise ValueError("max_qty_per_day 必须 > 0 或不传（保留原值）")

    await _set_tenant(db, tenant_id)

    existing = await get_whitelist(db, tenant_id, whitelist_id)
    if existing is None:
        raise ValueError(f"whitelist_id={whitelist_id} 不存在或已删除")

    now = datetime.now(timezone.utc)
    await db.execute(
        text(_UPDATE_WHITELIST_SQL),
        {
            "whitelist_id": whitelist_id,
            "tenant_id": _uuid_str(tenant_id),
            "max_qty_per_day": max_qty_per_day,
            "is_active": is_active,
            "notes": notes,
            "now": now,
        },
    )

    logger.info(
        "dept_whitelist_updated",
        whitelist_id=whitelist_id,
        tenant_id=str(tenant_id),
        fields=list(set_fields.keys()),
    )
    return (await get_whitelist(db, tenant_id, whitelist_id)) or {}


async def delete_whitelist(
    db: AsyncSession,
    tenant_id: str,
    whitelist_id: str,
) -> bool:
    """软删白名单（is_deleted=TRUE + is_active=FALSE）。"""
    await _set_tenant(db, tenant_id)
    now = datetime.now(timezone.utc)
    result = await db.execute(
        text(_DELETE_WHITELIST_SQL),
        {
            "whitelist_id": whitelist_id,
            "tenant_id": _uuid_str(tenant_id),
            "now": now,
        },
    )
    return bool(result.rowcount)


# ─── 批量授权（矩阵编辑器）────────────────────────────────────────────────


async def bulk_authorize(
    db: AsyncSession,
    tenant_id: str,
    *,
    dept_id: str,
    items: list[dict],
    created_by: str,
) -> dict:
    """一个部门一次性授权多个食材（矩阵编辑器场景）。

    items[i]:
      - ingredient_id: str (UUID)
      - max_qty_per_day: Optional[Decimal]
      - notes: Optional[str]

    upsert 语义：
      - (dept_id, ingredient_id) 已存在（含 soft-deleted）→ UPDATE max_qty_per_day +
        is_active=TRUE + is_deleted=FALSE
      - 不存在 → INSERT 新行

    返回 {dept_id, created_count, updated_count, items}。
    """
    if not items:
        raise ValueError("bulk_authorize items 不可为空")
    if len(items) > 200:
        raise ValueError(f"bulk_authorize items 数量超限 200, 实际 {len(items)}")

    for it in items:
        mqd = it.get("max_qty_per_day")
        if mqd is not None and Decimal(str(mqd)) <= 0:
            raise ValueError(
                f"max_qty_per_day 必须 > 0 或 NULL（ingredient_id={it.get('ingredient_id')}）"
            )

    await _set_tenant(db, tenant_id)

    now = datetime.now(timezone.utc)
    created_rows: list[dict] = []
    updated_rows: list[dict] = []

    for it in items:
        ingredient_id = str(it["ingredient_id"])
        max_qty_per_day = (
            Decimal(str(it["max_qty_per_day"]))
            if it.get("max_qty_per_day") is not None
            else None
        )
        notes = it.get("notes")

        # 1. 尝试 upsert by (dept_id, ingredient_id)
        upd_result = await db.execute(
            text(_UPSERT_WHITELIST_BY_PAIR_SQL),
            {
                "dept_id": _uuid_str(dept_id),
                "ingredient_id": ingredient_id,
                "tenant_id": _uuid_str(tenant_id),
                "max_qty_per_day": max_qty_per_day,
                "notes": notes,
                "now": now,
            },
        )
        upd_row = upd_result.mappings().first()
        if upd_row is not None:
            updated_rows.append(dict(upd_row))
            continue

        # 2. 不存在 → INSERT
        whitelist_id = str(uuid.uuid4())
        ins_result = await db.execute(
            text(_INSERT_WHITELIST_SQL),
            {
                "id": whitelist_id,
                "tenant_id": _uuid_str(tenant_id),
                "dept_id": _uuid_str(dept_id),
                "ingredient_id": ingredient_id,
                "max_qty_per_day": max_qty_per_day,
                "notes": notes,
                "created_by": _uuid_str(created_by),
                "now": now,
            },
        )
        ins_row = ins_result.mappings().first()
        if ins_row is not None:
            created_rows.append(dict(ins_row))

    logger.info(
        "dept_whitelist_bulk_authorized",
        dept_id=str(dept_id),
        tenant_id=str(tenant_id),
        created_count=len(created_rows),
        updated_count=len(updated_rows),
    )

    return {
        "dept_id": dept_id,
        "created_count": len(created_rows),
        "updated_count": len(updated_rows),
        "items": created_rows + updated_rows,
    }


# ─── 校验入口 ────────────────────────────────────────────────────────────────


async def validate_ingredient_allowed(
    db: AsyncSession,
    tenant_id: str,
    *,
    dept_id: str,
    ingredient_id: str,
    qty: Optional[Decimal] = None,
    raise_on_violation: bool = True,
    ingredient_name_hint: Optional[str] = None,
) -> dict:
    """校验某部门是否可领某食材（指定数量可选）。

    内部 service-to-service 调用入口 — 供 dept_issue.create_issue_order /
    auto_deduction.deduct_for_dish 接入。

    Args:
        db: 数据库会话
        tenant_id: 租户 ID
        dept_id: 部门 ID
        ingredient_id: 食材 ID
        qty: 本次领取/扣料数量 — 与 max_qty_per_day 比较；None 时仅校验白名单存在性
        raise_on_violation: True = 违反 raise IngredientNotAllowedError；
                            False = 返回 {allowed: False, reason: ...}
        ingredient_name_hint: 错误消息辅助显示的食材名（可选）

    Returns:
        {allowed: bool, reason: str, max_qty_per_day: Decimal | None}

    Raises:
        IngredientNotAllowedError: raise_on_violation=True 且违反时
    """
    await _set_tenant(db, tenant_id)

    result = await db.execute(
        text(_GET_WHITELIST_BY_PAIR_SQL),
        {
            "dept_id": _uuid_str(dept_id),
            "ingredient_id": _uuid_str(ingredient_id),
            "tenant_id": _uuid_str(tenant_id),
        },
    )
    row = result.mappings().first()

    # Case 1: 无 active 白名单 → 拒绝
    if row is None or not row.get("is_active"):
        reason = (
            "白名单不存在"
            if row is None
            else "白名单已禁用（is_active=FALSE）"
        )
        logger.warning(
            "dept_whitelist_violation",
            tenant_id=str(tenant_id),
            dept_id=str(dept_id),
            ingredient_id=str(ingredient_id),
            qty=str(qty) if qty else None,
            reason=reason,
        )
        if raise_on_violation:
            raise IngredientNotAllowedError(
                dept_id=str(dept_id),
                ingredient_id=str(ingredient_id),
                ingredient_name=ingredient_name_hint,
                message=(
                    f"部门 dept_id={dept_id} 未授权食材 ingredient_id={ingredient_id}"
                    f" — 原因：{reason}"
                ),
            )
        return {"allowed": False, "reason": reason, "max_qty_per_day": None}

    max_qty = row.get("max_qty_per_day")

    # Case 2: 白名单存在，max_qty_per_day NULL（不限量）→ 允许
    if max_qty is None:
        return {"allowed": True, "reason": "OK", "max_qty_per_day": None}

    # Case 3: 白名单存在，max_qty_per_day 非 NULL，qty 未提供 → 仅校验存在性，允许
    if qty is None:
        return {"allowed": True, "reason": "OK", "max_qty_per_day": max_qty}

    # Case 4: 白名单存在，max_qty_per_day 非 NULL，qty 超限 → 拒绝
    qty_decimal = Decimal(str(qty))
    max_qty_decimal = Decimal(str(max_qty))
    if qty_decimal > max_qty_decimal:
        reason = (
            f"领取量 {qty_decimal} 超过白名单日上限 {max_qty_decimal}"
        )
        logger.warning(
            "dept_whitelist_qty_exceeded",
            tenant_id=str(tenant_id),
            dept_id=str(dept_id),
            ingredient_id=str(ingredient_id),
            qty=str(qty_decimal),
            max_qty_per_day=str(max_qty_decimal),
        )
        if raise_on_violation:
            raise IngredientNotAllowedError(
                dept_id=str(dept_id),
                ingredient_id=str(ingredient_id),
                ingredient_name=ingredient_name_hint,
                message=(
                    f"部门 dept_id={dept_id} 食材 ingredient_id={ingredient_id} "
                    f"超过白名单日上限：{qty_decimal} > {max_qty_decimal}"
                ),
            )
        return {
            "allowed": False,
            "reason": reason,
            "max_qty_per_day": max_qty_decimal,
        }

    return {"allowed": True, "reason": "OK", "max_qty_per_day": max_qty_decimal}


__all__ = [
    "create_whitelist",
    "get_whitelist",
    "list_whitelists",
    "update_whitelist",
    "delete_whitelist",
    "bulk_authorize",
    "validate_ingredient_allowed",
]
