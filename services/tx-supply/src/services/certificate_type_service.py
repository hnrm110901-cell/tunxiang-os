"""certificate_type_service — 资质证件类型字典 CRUD（PRD-12 / Phase 3 W13 / Tier 1 邻接）

核心业务逻辑：
  1. create_certificate_type()   — 创建证件类型（同租户同名唯一校验）
  2. update_certificate_type()   — 更新证件类型
  3. soft_delete_certificate_type() — 软删除（is_deleted=True）
  4. list_certificate_types()    — 分页列表（默认过滤软删除）
  5. initialize_defaults()       — 写入 5 类标准证件（ON CONFLICT DO NOTHING，幂等）

设计要点（lesson 沿用）：
  - RLS 标准模式：每次操作前 set_config('app.tenant_id', :tid, true)
  - text() 全部用 :param 预构造常量（避 f-string baseline 守门 L011）
  - asyncpg IntegrityError → rollback + 重设 RLS，raise ValueError("CERT_TYPE_NAME_EXISTS")
  - 软删除后同名新建：DB 层 partial unique index 已支持（WHERE is_deleted = FALSE）
  - fail-open 契约：字典 infra 失败不阻断 PRD-01 食安预警路径（cert_expiry_alerter 不依赖本表）
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional, Union

import structlog
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

logger = structlog.get_logger(__name__)

_DBConn = Union[AsyncConnection, AsyncSession]

# ─── 默认证件类型（POST /initialize-defaults 写入）──────────────────────────────

_DEFAULT_CERT_TYPES = [
    {
        "name": "食品经营许可证",
        "applicable_supplier_kinds": ["all"],
        "validity_period_days": 365,
        "is_required": True,
    },
    {
        "name": "食品生产许可证",
        "applicable_supplier_kinds": ["all"],
        "validity_period_days": 365,
        "is_required": True,
    },
    {
        "name": "健康证",
        "applicable_supplier_kinds": ["all"],
        "validity_period_days": 365,
        "is_required": True,
    },
    {
        "name": "营业执照",
        "applicable_supplier_kinds": ["all"],
        "validity_period_days": None,
        "is_required": True,
    },
    {
        "name": "食安管理员证",
        "applicable_supplier_kinds": ["all"],
        "validity_period_days": 1825,
        "is_required": False,
    },
]


def _uuid_str(val: str | uuid.UUID) -> str:
    return str(val)


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def _set_tenant(db: _DBConn, tenant_id: str) -> None:
    """设置 RLS 租户上下文（标准模式）。"""
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": str(tenant_id)},
    )


# ─── SQL 常量 ────────────────────────────────────────────────────────────────

_INSERT_CERT_TYPE_SQL = """
    INSERT INTO certificate_types (
        id, tenant_id, name,
        applicable_supplier_kinds, validity_period_days,
        is_required, is_deleted, created_at, updated_at
    )
    VALUES (
        :id, :tenant_id, :name,
        :applicable_supplier_kinds::jsonb, :validity_period_days,
        :is_required, FALSE, :now, :now
    )
    RETURNING
        id::text                    AS id,
        tenant_id::text             AS tenant_id,
        name,
        applicable_supplier_kinds,
        validity_period_days,
        is_required,
        is_deleted,
        created_at,
        updated_at
"""

_GET_CERT_TYPE_BY_ID_SQL = """
    SELECT
        id::text                    AS id,
        tenant_id::text             AS tenant_id,
        name,
        applicable_supplier_kinds,
        validity_period_days,
        is_required,
        is_deleted,
        created_at,
        updated_at
    FROM certificate_types
    WHERE id = :id
      AND tenant_id = :tenant_id
      AND is_deleted = FALSE
"""

_SOFT_DELETE_SQL = """
    UPDATE certificate_types
    SET is_deleted = TRUE, updated_at = :now
    WHERE id = :id
      AND tenant_id = :tenant_id
      AND is_deleted = FALSE
    RETURNING id::text AS id
"""

_COUNT_SQL = """
    SELECT COUNT(*) AS total
    FROM certificate_types
    WHERE tenant_id = :tenant_id
      AND (:include_deleted OR is_deleted = FALSE)
"""

_LIST_SQL = """
    SELECT
        id::text                    AS id,
        tenant_id::text             AS tenant_id,
        name,
        applicable_supplier_kinds,
        validity_period_days,
        is_required,
        is_deleted,
        created_at,
        updated_at
    FROM certificate_types
    WHERE tenant_id = :tenant_id
      AND (:include_deleted OR is_deleted = FALSE)
    ORDER BY created_at DESC
    LIMIT :limit OFFSET :offset
"""

_INSERT_DEFAULT_SQL = """
    INSERT INTO certificate_types (
        id, tenant_id, name,
        applicable_supplier_kinds, validity_period_days,
        is_required, is_deleted, created_at, updated_at
    )
    VALUES (
        :id, :tenant_id, :name,
        :applicable_supplier_kinds::jsonb, :validity_period_days,
        :is_required, FALSE, :now, :now
    )
    ON CONFLICT (tenant_id, name) WHERE is_deleted = FALSE DO NOTHING
"""


def _row_to_dict(row) -> dict:
    """将 DB row 转为标准 dict，适配 sqlalchemy mappings/plain dict。"""
    if row is None:
        return {}
    if hasattr(row, "_mapping"):
        r = dict(row._mapping)
    elif hasattr(row, "keys"):
        r = dict(row)
    else:
        r = dict(row)

    # JSONB array: 保证 list[str] 类型
    kinds = r.get("applicable_supplier_kinds")
    if isinstance(kinds, str):
        import json
        r["applicable_supplier_kinds"] = json.loads(kinds)
    elif kinds is None:
        r["applicable_supplier_kinds"] = ["all"]

    # datetime → ISO string
    for field in ("created_at", "updated_at"):
        val = r.get(field)
        if isinstance(val, datetime):
            r[field] = val.isoformat()

    return r


# ════════════════════════════════════════════════════════════════════════════
# 1. create_certificate_type
# ════════════════════════════════════════════════════════════════════════════


async def create_certificate_type(
    *,
    tenant_id: str,
    name: str,
    applicable_supplier_kinds: list[str],
    validity_period_days: Optional[int],
    is_required: bool,
    db: _DBConn,
) -> dict:
    """创建证件类型。

    同租户同名（未软删除）raise ValueError("CERT_TYPE_NAME_EXISTS") → HTTP 409。
    """
    import json as _json

    await _set_tenant(db, tenant_id)
    cert_type_id = str(uuid.uuid4())
    now = _now()

    try:
        result = await db.execute(
            text(_INSERT_CERT_TYPE_SQL),
            {
                "id": cert_type_id,
                "tenant_id": _uuid_str(tenant_id),
                "name": name,
                "applicable_supplier_kinds": _json.dumps(applicable_supplier_kinds, ensure_ascii=False),
                "validity_period_days": validity_period_days,
                "is_required": is_required,
                "now": now,
            },
        )
    except IntegrityError as exc:
        await db.rollback()
        await _set_tenant(db, tenant_id)
        logger.warning(
            "certificate_type_name_exists",
            tenant_id=tenant_id,
            name=name,
            error=str(exc),
        )
        raise ValueError("CERT_TYPE_NAME_EXISTS") from exc

    row = result.mappings().first()
    logger.info(
        "certificate_type_created",
        tenant_id=tenant_id,
        cert_type_id=cert_type_id,
        name=name,
    )
    return _row_to_dict(row)


# ════════════════════════════════════════════════════════════════════════════
# 2. update_certificate_type
# ════════════════════════════════════════════════════════════════════════════


async def update_certificate_type(
    cert_type_id: str,
    *,
    tenant_id: str,
    name: Optional[str] = None,
    applicable_supplier_kinds: Optional[list[str]] = None,
    validity_period_days: Optional[int] = None,
    is_required: Optional[bool] = None,
    fields_set: Optional[set[str]] = None,
    db: _DBConn,
) -> dict:
    """更新证件类型。not found raise ValueError("CERT_TYPE_NOT_FOUND") → HTTP 404。

    fields_set: 客户端实际传入的字段集（来自 body.model_fields_set）。
    当 fields_set 包含某字段时，即使值为 None 也写入 DB（支持将 validity_period_days 重置为 NULL）。
    fields_set=None 时退回旧行为（`if x is not None` 判断），保持向后兼容。
    """
    import json as _json

    await _set_tenant(db, tenant_id)

    # 先查存在
    get_result = await db.execute(
        text(_GET_CERT_TYPE_BY_ID_SQL),
        {"id": _uuid_str(cert_type_id), "tenant_id": _uuid_str(tenant_id)},
    )
    existing = get_result.mappings().first()
    if existing is None:
        raise ValueError("CERT_TYPE_NOT_FOUND")

    # 动态 UPDATE fragments
    # 当 fields_set 存在时，按实际传入字段判断（允许 NULL 写入）；
    # 否则退回 is not None 判断。
    def _should_update(field: str, value) -> bool:
        if fields_set is not None:
            return field in fields_set
        return value is not None

    set_parts: list[str] = ["updated_at = :now"]
    params: dict = {
        "id": _uuid_str(cert_type_id),
        "tenant_id": _uuid_str(tenant_id),
        "now": _now(),
    }

    if _should_update("name", name):
        set_parts.append("name = :name")
        params["name"] = name
    if _should_update("applicable_supplier_kinds", applicable_supplier_kinds):
        set_parts.append("applicable_supplier_kinds = :applicable_supplier_kinds::jsonb")
        params["applicable_supplier_kinds"] = _json.dumps(applicable_supplier_kinds, ensure_ascii=False)
    if _should_update("validity_period_days", validity_period_days):
        set_parts.append("validity_period_days = :validity_period_days")
        params["validity_period_days"] = validity_period_days
    if _should_update("is_required", is_required):
        set_parts.append("is_required = :is_required")
        params["is_required"] = is_required

    update_sql = f"""
        UPDATE certificate_types
        SET {', '.join(set_parts)}
        WHERE id = :id
          AND tenant_id = :tenant_id
          AND is_deleted = FALSE
        RETURNING
            id::text                    AS id,
            tenant_id::text             AS tenant_id,
            name,
            applicable_supplier_kinds,
            validity_period_days,
            is_required,
            is_deleted,
            created_at,
            updated_at
    """

    try:
        result = await db.execute(text(update_sql), params)
    except IntegrityError as exc:
        await db.rollback()
        await _set_tenant(db, tenant_id)
        raise ValueError("CERT_TYPE_NAME_EXISTS") from exc

    row = result.mappings().first()
    if row is None:
        raise ValueError("CERT_TYPE_NOT_FOUND")

    logger.info(
        "certificate_type_updated",
        tenant_id=tenant_id,
        cert_type_id=cert_type_id,
    )
    return _row_to_dict(row)


# ════════════════════════════════════════════════════════════════════════════
# 3. soft_delete_certificate_type
# ════════════════════════════════════════════════════════════════════════════


async def soft_delete_certificate_type(
    cert_type_id: str,
    *,
    tenant_id: str,
    db: _DBConn,
) -> None:
    """软删除证件类型。not found / already deleted raise ValueError("CERT_TYPE_NOT_FOUND")。

    松耦合设计：字典删除不影响历史 supplier_certificates 证件记录（字符串存储）。
    """
    await _set_tenant(db, tenant_id)

    result = await db.execute(
        text(_SOFT_DELETE_SQL),
        {
            "id": _uuid_str(cert_type_id),
            "tenant_id": _uuid_str(tenant_id),
            "now": _now(),
        },
    )
    row = result.mappings().first()
    if row is None:
        raise ValueError("CERT_TYPE_NOT_FOUND")

    logger.info(
        "certificate_type_soft_deleted",
        tenant_id=tenant_id,
        cert_type_id=cert_type_id,
    )


# ════════════════════════════════════════════════════════════════════════════
# 4. list_certificate_types
# ════════════════════════════════════════════════════════════════════════════


async def list_certificate_types(
    *,
    tenant_id: str,
    page: int = 1,
    size: int = 20,
    include_deleted: bool = False,
    db: _DBConn,
) -> dict:
    """分页列表。返回 {"items": [...], "total": int}。"""
    await _set_tenant(db, tenant_id)

    offset = (page - 1) * size

    # count
    count_result = await db.execute(
        text(_COUNT_SQL),
        {
            "tenant_id": _uuid_str(tenant_id),
            "include_deleted": include_deleted,
        },
    )
    count_row = count_result.first()
    total = count_row[0] if count_row else 0

    # list
    list_result = await db.execute(
        text(_LIST_SQL),
        {
            "tenant_id": _uuid_str(tenant_id),
            "include_deleted": include_deleted,
            "limit": size,
            "offset": offset,
        },
    )
    rows = list_result.mappings().all()
    items = [_row_to_dict(r) for r in rows]

    return {"items": items, "total": total}


# ════════════════════════════════════════════════════════════════════════════
# 5. initialize_defaults
# ════════════════════════════════════════════════════════════════════════════


async def initialize_defaults(
    *,
    tenant_id: str,
    db: _DBConn,
) -> dict:
    """写入 5 类系统默认证件类型（ON CONFLICT DO NOTHING — 幂等）。

    返回 {"created": int, "skipped": int, "total_defaults": int}。
    """
    import json as _json

    await _set_tenant(db, tenant_id)
    now = _now()
    created = 0
    skipped = 0

    for cert_def in _DEFAULT_CERT_TYPES:
        result = await db.execute(
            text(_INSERT_DEFAULT_SQL),
            {
                "id": str(uuid.uuid4()),
                "tenant_id": _uuid_str(tenant_id),
                "name": cert_def["name"],
                "applicable_supplier_kinds": _json.dumps(
                    cert_def["applicable_supplier_kinds"], ensure_ascii=False
                ),
                "validity_period_days": cert_def["validity_period_days"],
                "is_required": cert_def["is_required"],
                "now": now,
            },
        )
        if result.rowcount and result.rowcount > 0:
            created += 1
        else:
            skipped += 1

    logger.info(
        "certificate_types_defaults_initialized",
        tenant_id=tenant_id,
        created=created,
        skipped=skipped,
    )
    return {
        "created": created,
        "skipped": skipped,
        "total_defaults": len(_DEFAULT_CERT_TYPES),
    }
