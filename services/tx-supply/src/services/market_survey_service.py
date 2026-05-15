"""market_survey_service — Market Survey 调研双轨（PRD-13 sub-A / Phase 2 W11 / T2 normal）

核心业务逻辑：
  1. 调研主表 CRUD (create_survey / get / list / update / delete / transition_status)
  2. 调研明细 CRUD (add_item / list_items / update_item / delete_item)
  3. 照片 CRUD (add_photo / list_photos / update_photo / delete_photo)
  4. get_survey_detail — 主表 + items + photos 聚合 (UI 详情页)
  5. 工作流: status 三态 guard (draft / submitted / verified)

设计要点 (lesson 沿用)：
  - RLS 标准模式：每次操作前 set_config('app.tenant_id', :tid, true)
  - text() 全部用 :param + 预构造常量 (避 f-string baseline 守门 L011)
  - asyncpg IntegrityError rollback + RLS 重设 (PRD-08 P0-3 lesson)
  - pydantic V2 ValidationError 显式 catch (PRD-11 P1-2 lesson) — service 层只 raise
    ValueError, route 层映射 422; 创建 schema 时在 pydantic 层已守
  - 动态 UPDATE SQL fragments + model_dump(exclude_unset=True) (PRD-08 P0-1 lesson)
  - status 转换规则: draft↔submitted / submitted→verified / verified 终态
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

logger = structlog.get_logger(__name__)

_DBConn = Union[AsyncConnection, AsyncSession]


# ─── 合法 status 转换图 ─────────────────────────────────────────────────────


_STATUS_TRANSITIONS: dict[str, set[str]] = {
    "draft": {"submitted"},
    "submitted": {"verified", "draft"},  # 退回起草也允许
    "verified": set(),  # 终态
}


def _is_valid_transition(current: str, target: str) -> bool:
    return target in _STATUS_TRANSITIONS.get(current, set())


def _uuid_str(val: str | uuid.UUID) -> str:
    return str(val)


async def _set_tenant(db: _DBConn, tenant_id: str) -> None:
    """设置 RLS 租户上下文."""
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": str(tenant_id)},
    )


# ═════════════════════════════════════════════════════════════════════════════
# 1. market_surveys 主表 CRUD
# ═════════════════════════════════════════════════════════════════════════════


_INSERT_SURVEY_SQL = """
    INSERT INTO market_surveys (
        id, tenant_id, surveyor_id, market_type, location_name,
        surveyed_at, status, notes, created_at, updated_at, is_deleted
    )
    VALUES (
        :id, :tenant_id, :surveyor_id, :market_type, :location_name,
        :surveyed_at, 'draft', :notes, :now, :now, FALSE
    )
    RETURNING
        id::text                    AS id,
        tenant_id::text             AS tenant_id,
        surveyor_id::text           AS surveyor_id,
        market_type,
        location_name,
        surveyed_at,
        status,
        notes,
        created_at,
        updated_at,
        is_deleted
"""

_GET_SURVEY_BY_ID_SQL = """
    SELECT
        id::text                AS id,
        tenant_id::text         AS tenant_id,
        surveyor_id::text       AS surveyor_id,
        market_type,
        location_name,
        surveyed_at,
        status,
        notes,
        created_at,
        updated_at,
        is_deleted
    FROM market_surveys
    WHERE id        = :survey_id
      AND tenant_id = :tenant_id
      AND is_deleted = FALSE
    LIMIT 1
"""

_LIST_SURVEYS_BASE_SQL = """
    SELECT
        id::text                AS id,
        tenant_id::text         AS tenant_id,
        surveyor_id::text       AS surveyor_id,
        market_type,
        location_name,
        surveyed_at,
        status,
        notes,
        created_at,
        updated_at,
        is_deleted
    FROM market_surveys
    WHERE tenant_id  = :tenant_id
      AND is_deleted = FALSE
"""


# 动态 UPDATE SQL fragments (PRD-08 P0-1 lesson)
_UPDATE_SURVEY_PREFIX_SQL = "UPDATE market_surveys SET updated_at = :now"
_UPDATE_SURVEY_SUFFIX_SQL = (
    " WHERE id = :survey_id"
    " AND tenant_id = :tenant_id"
    " AND is_deleted = FALSE"
)
_UPDATE_SURVEY_FIELD_FRAGMENTS: dict[str, str] = {
    "market_type": ", market_type = :market_type",
    "location_name": ", location_name = :location_name",
    "surveyed_at": ", surveyed_at = :surveyed_at",
    "notes": ", notes = :notes",
}


_UPDATE_SURVEY_STATUS_SQL = """
    UPDATE market_surveys
    SET status     = :status,
        updated_at = :now
    WHERE id        = :survey_id
      AND tenant_id = :tenant_id
      AND is_deleted = FALSE
      AND status     = :current_status
"""

_DELETE_SURVEY_SQL = """
    UPDATE market_surveys
    SET is_deleted = TRUE,
        updated_at = :now
    WHERE id        = :survey_id
      AND tenant_id = :tenant_id
      AND is_deleted = FALSE
"""


async def create_survey(
    db: AsyncSession,
    tenant_id: str,
    *,
    surveyor_id: str,
    market_type: str,
    location_name: str,
    surveyed_at: datetime,
    notes: Optional[str] = None,
) -> dict:
    """新建调研 (status 默认 draft).

    market_type 必须为 wholesale/wet_market/supermarket/other.
    surveyor_id 由 caller 提供 (employee_id, RLS via tenant 守).
    """
    if market_type not in ("wholesale", "wet_market", "supermarket", "other"):
        raise ValueError(
            f"market_type 必须是 wholesale/wet_market/supermarket/other, 实际 {market_type}"
        )
    if not location_name or not location_name.strip():
        raise ValueError("location_name 不能为空")

    await _set_tenant(db, tenant_id)

    survey_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)

    try:
        result = await db.execute(
            text(_INSERT_SURVEY_SQL),
            {
                "id": survey_id,
                "tenant_id": _uuid_str(tenant_id),
                "surveyor_id": _uuid_str(surveyor_id),
                "market_type": market_type,
                "location_name": location_name.strip(),
                "surveyed_at": surveyed_at,
                "notes": notes,
                "now": now,
            },
        )
    except IntegrityError as exc:
        # PRD-08 P0-3 lesson: rollback + 重设 RLS
        await db.rollback()
        await _set_tenant(db, tenant_id)
        raise ValueError(f"create_survey IntegrityError: {exc.orig}") from exc

    row = result.mappings().first()
    if row is None:
        raise ValueError("create_survey failed — RETURNING 无结果")

    logger.info(
        "market_survey_created",
        survey_id=survey_id,
        tenant_id=str(tenant_id),
        surveyor_id=str(surveyor_id),
        market_type=market_type,
        location_name=location_name,
    )
    return dict(row)


async def get_survey(
    db: AsyncSession,
    tenant_id: str,
    survey_id: str,
) -> Optional[dict]:
    """按 ID 查调研."""
    await _set_tenant(db, tenant_id)
    result = await db.execute(
        text(_GET_SURVEY_BY_ID_SQL),
        {"survey_id": survey_id, "tenant_id": _uuid_str(tenant_id)},
    )
    row = result.mappings().first()
    return dict(row) if row else None


async def list_surveys(
    db: AsyncSession,
    tenant_id: str,
    *,
    market_type: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict]:
    """列表 (按 surveyed_at DESC 时序倒序, 配 idx_market_surveys_tenant_surveyed_at).

    可选过滤: market_type / status.
    """
    if limit <= 0 or limit > 200:
        raise ValueError(f"limit 必须 in (0, 200], 实际 {limit}")
    if offset < 0:
        raise ValueError(f"offset 必须 >= 0, 实际 {offset}")
    if market_type is not None and market_type not in (
        "wholesale", "wet_market", "supermarket", "other"
    ):
        raise ValueError(
            f"market_type 必须是 wholesale/wet_market/supermarket/other, 实际 {market_type}"
        )
    if status is not None and status not in ("draft", "submitted", "verified"):
        raise ValueError(f"status 必须是 draft/submitted/verified, 实际 {status}")

    await _set_tenant(db, tenant_id)

    sql_parts = [_LIST_SURVEYS_BASE_SQL]
    params: dict[str, object] = {
        "tenant_id": _uuid_str(tenant_id),
        "limit": limit,
        "offset": offset,
    }
    if market_type is not None:
        sql_parts.append(" AND market_type = :market_type")
        params["market_type"] = market_type
    if status is not None:
        sql_parts.append(" AND status = :status")
        params["status"] = status
    sql_parts.append(" ORDER BY surveyed_at DESC LIMIT :limit OFFSET :offset")
    prepared_text = "".join(sql_parts)

    result = await db.execute(text(prepared_text), params)
    return [dict(r) for r in result.mappings().all()]


async def update_survey(
    db: AsyncSession,
    tenant_id: str,
    survey_id: str,
    *,
    updates: dict,
) -> dict:
    """更新调研 (PRD-08 P0-1 lesson 模式).

    允许字段: market_type / location_name / surveyed_at / notes.
    status 必须走 transition_status() — 不允许在此路径修改.
    """
    allowed = set(_UPDATE_SURVEY_FIELD_FRAGMENTS.keys())
    set_keys = sorted(set(updates.keys()) & allowed)
    if not set_keys:
        raise ValueError("至少提供一个更新字段")

    # NOT NULL 字段守门 (PRD-11 P1-1 lesson)
    if "market_type" in updates:
        mt = updates["market_type"]
        if mt is None:
            raise ValueError("market_type 不能为 NULL")
        if mt not in ("wholesale", "wet_market", "supermarket", "other"):
            raise ValueError(
                f"market_type 必须是 wholesale/wet_market/supermarket/other, 实际 {mt}"
            )
    if "location_name" in updates:
        ln = updates["location_name"]
        if ln is None or (isinstance(ln, str) and not ln.strip()):
            raise ValueError("location_name 不能为 NULL 或空字符串")
    if "surveyed_at" in updates and updates["surveyed_at"] is None:
        raise ValueError("surveyed_at 不能为 NULL")

    await _set_tenant(db, tenant_id)

    existing = await get_survey(db, tenant_id, survey_id)
    if existing is None:
        raise ValueError(f"survey_id={survey_id} 不存在或已删除")

    sql_parts = [_UPDATE_SURVEY_PREFIX_SQL]
    params: dict[str, object] = {
        "survey_id": survey_id,
        "tenant_id": _uuid_str(tenant_id),
        "now": datetime.now(timezone.utc),
    }
    for key in set_keys:
        sql_parts.append(_UPDATE_SURVEY_FIELD_FRAGMENTS[key])
        params[key] = updates[key]
    sql_parts.append(_UPDATE_SURVEY_SUFFIX_SQL)
    prepared_text = "".join(sql_parts)

    await db.execute(text(prepared_text), params)

    logger.info(
        "market_survey_updated",
        survey_id=survey_id,
        tenant_id=str(tenant_id),
        fields=set_keys,
    )
    return (await get_survey(db, tenant_id, survey_id)) or {}


async def transition_status(
    db: AsyncSession,
    tenant_id: str,
    survey_id: str,
    *,
    target_status: str,
) -> dict:
    """status 转换 (走合法转换图).

    合法路径:
      draft     → submitted (移动端提交)
      submitted → verified  (采购总监审核合格)
      submitted → draft     (退回起草)
      verified  → (终态, 不可改)
    """
    if target_status not in ("draft", "submitted", "verified"):
        raise ValueError(
            f"target_status 必须是 draft/submitted/verified, 实际 {target_status}"
        )

    await _set_tenant(db, tenant_id)

    existing = await get_survey(db, tenant_id, survey_id)
    if existing is None:
        raise ValueError(f"survey_id={survey_id} 不存在或已删除")

    current = existing["status"]
    if current == target_status:
        # idempotent: 同状态视为成功 (但不写 DB)
        return existing
    if not _is_valid_transition(current, target_status):
        raise ValueError(
            f"非法 status 转换: {current} → {target_status} "
            f"(允许: draft↔submitted / submitted→verified / verified=终态)"
        )

    # §19 round-1 P1-1 fix: 乐观锁守卫 — UPDATE WHERE AND status = :current_status,
    # 防并发两 caller 同时 transition 同 survey (e.g. submitted→verified vs
    # submitted→draft) 后者覆写前者 → verified 训练池数据被静默降级到 draft.
    # 实测场景: 200 桌峰值低频但训练池数据完整性是 P1 (AI 训练数据集质量门禁).
    result = await db.execute(
        text(_UPDATE_SURVEY_STATUS_SQL),
        {
            "survey_id": survey_id,
            "tenant_id": _uuid_str(tenant_id),
            "status": target_status,
            "current_status": current,
            "now": datetime.now(timezone.utc),
        },
    )
    if result.rowcount == 0:
        # 并发 race: 另一 worker 已改 status → 让 caller 重试 (而非静默覆写)
        raise ValueError(
            f"status 并发冲突: survey_id={survey_id} 当前 status 已被其他操作修改, 请刷新后重试"
        )

    logger.info(
        "market_survey_status_transitioned",
        survey_id=survey_id,
        tenant_id=str(tenant_id),
        from_status=current,
        to_status=target_status,
    )
    return (await get_survey(db, tenant_id, survey_id)) or {}


async def delete_survey(
    db: AsyncSession,
    tenant_id: str,
    survey_id: str,
) -> bool:
    """软删调研 (is_deleted=TRUE). CASCADE 不动 — items/photos 仍存在但 RLS 隔离."""
    await _set_tenant(db, tenant_id)
    result = await db.execute(
        text(_DELETE_SURVEY_SQL),
        {
            "survey_id": survey_id,
            "tenant_id": _uuid_str(tenant_id),
            "now": datetime.now(timezone.utc),
        },
    )
    return bool(result.rowcount)


# ═════════════════════════════════════════════════════════════════════════════
# 2. market_survey_items CRUD
# ═════════════════════════════════════════════════════════════════════════════


_INSERT_ITEM_SQL = """
    INSERT INTO market_survey_items (
        id, tenant_id, survey_id, ingredient_id, ingredient_name,
        unit_price_fen, qty_per_unit, unit, notes,
        created_at, is_deleted
    )
    VALUES (
        :id, :tenant_id, :survey_id, :ingredient_id, :ingredient_name,
        :unit_price_fen, :qty_per_unit, :unit, :notes,
        :now, FALSE
    )
    RETURNING
        id::text                    AS id,
        tenant_id::text             AS tenant_id,
        survey_id::text             AS survey_id,
        ingredient_id::text         AS ingredient_id,
        ingredient_name,
        unit_price_fen,
        qty_per_unit,
        unit,
        notes,
        created_at,
        is_deleted
"""

_GET_ITEM_BY_ID_SQL = """
    SELECT
        id::text                AS id,
        tenant_id::text         AS tenant_id,
        survey_id::text         AS survey_id,
        ingredient_id::text     AS ingredient_id,
        ingredient_name,
        unit_price_fen,
        qty_per_unit,
        unit,
        notes,
        created_at,
        is_deleted
    FROM market_survey_items
    WHERE id        = :item_id
      AND tenant_id = :tenant_id
      AND is_deleted = FALSE
    LIMIT 1
"""

_LIST_ITEMS_BY_SURVEY_SQL = """
    SELECT
        id::text                AS id,
        tenant_id::text         AS tenant_id,
        survey_id::text         AS survey_id,
        ingredient_id::text     AS ingredient_id,
        ingredient_name,
        unit_price_fen,
        qty_per_unit,
        unit,
        notes,
        created_at,
        is_deleted
    FROM market_survey_items
    WHERE survey_id  = :survey_id
      AND tenant_id  = :tenant_id
      AND is_deleted = FALSE
    ORDER BY created_at ASC
"""


_UPDATE_ITEM_PREFIX_SQL = "UPDATE market_survey_items SET id = id"
_UPDATE_ITEM_SUFFIX_SQL = (
    " WHERE id = :item_id"
    " AND tenant_id = :tenant_id"
    " AND is_deleted = FALSE"
)
_UPDATE_ITEM_FIELD_FRAGMENTS: dict[str, str] = {
    "ingredient_id": ", ingredient_id = :ingredient_id",
    "ingredient_name": ", ingredient_name = :ingredient_name",
    "unit_price_fen": ", unit_price_fen = :unit_price_fen",
    "qty_per_unit": ", qty_per_unit = :qty_per_unit",
    "unit": ", unit = :unit",
    "notes": ", notes = :notes",
}


_DELETE_ITEM_SQL = """
    UPDATE market_survey_items
    SET is_deleted = TRUE
    WHERE id        = :item_id
      AND tenant_id = :tenant_id
      AND is_deleted = FALSE
"""


async def add_item(
    db: AsyncSession,
    tenant_id: str,
    *,
    survey_id: str,
    ingredient_name: str,
    unit_price_fen: int,
    ingredient_id: Optional[str] = None,
    qty_per_unit: Decimal = Decimal("1"),
    unit: str = "斤",
    notes: Optional[str] = None,
) -> dict:
    """新增调研明细. 调研必须存在 (FK CASCADE 守门).

    ingredient_id 可选 — NULL 时为自由文本兜底.
    """
    if not ingredient_name or not ingredient_name.strip():
        raise ValueError("ingredient_name 不能为空")
    if unit_price_fen < 0:
        raise ValueError("unit_price_fen 必须 >= 0")
    if qty_per_unit <= 0:
        raise ValueError("qty_per_unit 必须 > 0")
    if not unit or not unit.strip():
        raise ValueError("unit 不能为空")

    await _set_tenant(db, tenant_id)

    # 父表存在性 + tenant 守 (CASCADE 不替代业务校验)
    parent = await get_survey(db, tenant_id, survey_id)
    if parent is None:
        raise ValueError(f"survey_id={survey_id} 不存在或已删除")

    item_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)

    try:
        result = await db.execute(
            text(_INSERT_ITEM_SQL),
            {
                "id": item_id,
                "tenant_id": _uuid_str(tenant_id),
                "survey_id": _uuid_str(survey_id),
                "ingredient_id": _uuid_str(ingredient_id) if ingredient_id else None,
                "ingredient_name": ingredient_name.strip(),
                "unit_price_fen": unit_price_fen,
                "qty_per_unit": qty_per_unit,
                "unit": unit.strip(),
                "notes": notes,
                "now": now,
            },
        )
    except IntegrityError as exc:
        await db.rollback()
        await _set_tenant(db, tenant_id)
        raise ValueError(f"add_item IntegrityError: {exc.orig}") from exc

    row = result.mappings().first()
    if row is None:
        raise ValueError("add_item failed — RETURNING 无结果")

    logger.info(
        "market_survey_item_added",
        item_id=item_id,
        survey_id=survey_id,
        tenant_id=str(tenant_id),
        ingredient_name=ingredient_name,
        unit_price_fen=unit_price_fen,
    )
    return dict(row)


async def get_item(
    db: AsyncSession,
    tenant_id: str,
    item_id: str,
) -> Optional[dict]:
    """按 ID 查明细."""
    await _set_tenant(db, tenant_id)
    result = await db.execute(
        text(_GET_ITEM_BY_ID_SQL),
        {"item_id": item_id, "tenant_id": _uuid_str(tenant_id)},
    )
    row = result.mappings().first()
    return dict(row) if row else None


async def list_items_by_survey(
    db: AsyncSession,
    tenant_id: str,
    survey_id: str,
) -> list[dict]:
    """列出某 survey 的所有 items (created_at 升序)."""
    await _set_tenant(db, tenant_id)
    result = await db.execute(
        text(_LIST_ITEMS_BY_SURVEY_SQL),
        {
            "survey_id": _uuid_str(survey_id),
            "tenant_id": _uuid_str(tenant_id),
        },
    )
    return [dict(r) for r in result.mappings().all()]


async def update_item(
    db: AsyncSession,
    tenant_id: str,
    item_id: str,
    *,
    updates: dict,
) -> dict:
    """更新明细."""
    allowed = set(_UPDATE_ITEM_FIELD_FRAGMENTS.keys())
    set_keys = sorted(set(updates.keys()) & allowed)
    if not set_keys:
        raise ValueError("至少提供一个更新字段")

    # NOT NULL 字段守门
    if "ingredient_name" in updates:
        nm = updates["ingredient_name"]
        if nm is None or (isinstance(nm, str) and not nm.strip()):
            raise ValueError("ingredient_name 不能为 NULL 或空字符串")
    if "unit_price_fen" in updates:
        p = updates["unit_price_fen"]
        if p is None:
            raise ValueError("unit_price_fen 不能为 NULL")
        if p < 0:
            raise ValueError("unit_price_fen 必须 >= 0")
    if "qty_per_unit" in updates:
        q = updates["qty_per_unit"]
        if q is None:
            raise ValueError("qty_per_unit 不能为 NULL")
        if q <= 0:
            raise ValueError("qty_per_unit 必须 > 0")
    if "unit" in updates:
        u = updates["unit"]
        if u is None or (isinstance(u, str) and not u.strip()):
            raise ValueError("unit 不能为 NULL 或空字符串")
    # ingredient_id 允许 NULL (自由文本兜底)

    await _set_tenant(db, tenant_id)

    existing = await get_item(db, tenant_id, item_id)
    if existing is None:
        raise ValueError(f"item_id={item_id} 不存在或已删除")

    sql_parts = [_UPDATE_ITEM_PREFIX_SQL]
    params: dict[str, object] = {
        "item_id": item_id,
        "tenant_id": _uuid_str(tenant_id),
    }
    for key in set_keys:
        sql_parts.append(_UPDATE_ITEM_FIELD_FRAGMENTS[key])
        params[key] = updates[key]
    sql_parts.append(_UPDATE_ITEM_SUFFIX_SQL)
    prepared_text = "".join(sql_parts)

    await db.execute(text(prepared_text), params)

    logger.info(
        "market_survey_item_updated",
        item_id=item_id,
        tenant_id=str(tenant_id),
        fields=set_keys,
    )
    return (await get_item(db, tenant_id, item_id)) or {}


async def delete_item(
    db: AsyncSession,
    tenant_id: str,
    item_id: str,
) -> bool:
    """软删明细."""
    await _set_tenant(db, tenant_id)
    result = await db.execute(
        text(_DELETE_ITEM_SQL),
        {"item_id": item_id, "tenant_id": _uuid_str(tenant_id)},
    )
    return bool(result.rowcount)


# ═════════════════════════════════════════════════════════════════════════════
# 3. market_survey_photos CRUD
# ═════════════════════════════════════════════════════════════════════════════


_INSERT_PHOTO_SQL = """
    INSERT INTO market_survey_photos (
        id, tenant_id, survey_id, item_id, photo_url, caption,
        exif_meta, uploaded_at, created_at, is_deleted
    )
    VALUES (
        :id, :tenant_id, :survey_id, :item_id, :photo_url, :caption,
        CAST(:exif_meta AS JSONB), :uploaded_at, :now, FALSE
    )
    RETURNING
        id::text                    AS id,
        tenant_id::text             AS tenant_id,
        survey_id::text             AS survey_id,
        item_id::text               AS item_id,
        photo_url,
        caption,
        exif_meta,
        uploaded_at,
        created_at,
        is_deleted
"""

_GET_PHOTO_BY_ID_SQL = """
    SELECT
        id::text                AS id,
        tenant_id::text         AS tenant_id,
        survey_id::text         AS survey_id,
        item_id::text           AS item_id,
        photo_url,
        caption,
        exif_meta,
        uploaded_at,
        created_at,
        is_deleted
    FROM market_survey_photos
    WHERE id        = :photo_id
      AND tenant_id = :tenant_id
      AND is_deleted = FALSE
    LIMIT 1
"""

_LIST_PHOTOS_BY_SURVEY_SQL = """
    SELECT
        id::text                AS id,
        tenant_id::text         AS tenant_id,
        survey_id::text         AS survey_id,
        item_id::text           AS item_id,
        photo_url,
        caption,
        exif_meta,
        uploaded_at,
        created_at,
        is_deleted
    FROM market_survey_photos
    WHERE survey_id  = :survey_id
      AND tenant_id  = :tenant_id
      AND is_deleted = FALSE
    ORDER BY uploaded_at ASC
"""

_UPDATE_PHOTO_PREFIX_SQL = "UPDATE market_survey_photos SET id = id"
_UPDATE_PHOTO_SUFFIX_SQL = (
    " WHERE id = :photo_id"
    " AND tenant_id = :tenant_id"
    " AND is_deleted = FALSE"
)
_UPDATE_PHOTO_FIELD_FRAGMENTS: dict[str, str] = {
    "caption": ", caption = :caption",
    "exif_meta": ", exif_meta = CAST(:exif_meta AS JSONB)",
}


_DELETE_PHOTO_SQL = """
    UPDATE market_survey_photos
    SET is_deleted = TRUE
    WHERE id        = :photo_id
      AND tenant_id = :tenant_id
      AND is_deleted = FALSE
"""


async def add_photo(
    db: AsyncSession,
    tenant_id: str,
    *,
    survey_id: str,
    photo_url: str,
    item_id: Optional[str] = None,
    caption: Optional[str] = None,
    exif_meta: Optional[dict] = None,
    uploaded_at: Optional[datetime] = None,
) -> dict:
    """新增照片. item_id NULL = 调研封面图; 非 NULL = item-level 详细照.

    photo_url 是 caller (sub-B 移动端) 已上传到 COS 后的 URL.
    """
    if not photo_url or not photo_url.strip():
        raise ValueError("photo_url 不能为空")

    await _set_tenant(db, tenant_id)

    # 父表 survey 存在性守门
    parent = await get_survey(db, tenant_id, survey_id)
    if parent is None:
        raise ValueError(f"survey_id={survey_id} 不存在或已删除")
    # item_id 给定时, 它必须属于本 survey (CASCADE 不替代业务校验)
    if item_id is not None:
        parent_item = await get_item(db, tenant_id, item_id)
        if parent_item is None:
            raise ValueError(f"item_id={item_id} 不存在或已删除")
        if parent_item["survey_id"] != str(survey_id):
            raise ValueError(
                f"item_id={item_id} 不属于 survey_id={survey_id}"
            )

    photo_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    actual_uploaded = uploaded_at or now

    import json
    exif_json = json.dumps(exif_meta) if exif_meta is not None else None

    try:
        result = await db.execute(
            text(_INSERT_PHOTO_SQL),
            {
                "id": photo_id,
                "tenant_id": _uuid_str(tenant_id),
                "survey_id": _uuid_str(survey_id),
                "item_id": _uuid_str(item_id) if item_id else None,
                "photo_url": photo_url.strip(),
                "caption": caption,
                "exif_meta": exif_json,
                "uploaded_at": actual_uploaded,
                "now": now,
            },
        )
    except IntegrityError as exc:
        await db.rollback()
        await _set_tenant(db, tenant_id)
        raise ValueError(f"add_photo IntegrityError: {exc.orig}") from exc

    row = result.mappings().first()
    if row is None:
        raise ValueError("add_photo failed — RETURNING 无结果")

    logger.info(
        "market_survey_photo_added",
        photo_id=photo_id,
        survey_id=survey_id,
        item_id=item_id,
        tenant_id=str(tenant_id),
    )
    return dict(row)


async def get_photo(
    db: AsyncSession,
    tenant_id: str,
    photo_id: str,
) -> Optional[dict]:
    """按 ID 查照片."""
    await _set_tenant(db, tenant_id)
    result = await db.execute(
        text(_GET_PHOTO_BY_ID_SQL),
        {"photo_id": photo_id, "tenant_id": _uuid_str(tenant_id)},
    )
    row = result.mappings().first()
    return dict(row) if row else None


async def list_photos_by_survey(
    db: AsyncSession,
    tenant_id: str,
    survey_id: str,
) -> list[dict]:
    """列出某 survey 的所有照片 (uploaded_at 升序)."""
    await _set_tenant(db, tenant_id)
    result = await db.execute(
        text(_LIST_PHOTOS_BY_SURVEY_SQL),
        {
            "survey_id": _uuid_str(survey_id),
            "tenant_id": _uuid_str(tenant_id),
        },
    )
    return [dict(r) for r in result.mappings().all()]


async def update_photo(
    db: AsyncSession,
    tenant_id: str,
    photo_id: str,
    *,
    updates: dict,
) -> dict:
    """更新照片 — 仅 caption / exif_meta (URL/uploaded_at 不可改, 历史溯源稳定)."""
    allowed = set(_UPDATE_PHOTO_FIELD_FRAGMENTS.keys())
    set_keys = sorted(set(updates.keys()) & allowed)
    if not set_keys:
        raise ValueError("至少提供一个更新字段 (允许: caption / exif_meta)")

    await _set_tenant(db, tenant_id)

    existing = await get_photo(db, tenant_id, photo_id)
    if existing is None:
        raise ValueError(f"photo_id={photo_id} 不存在或已删除")

    sql_parts = [_UPDATE_PHOTO_PREFIX_SQL]
    params: dict[str, object] = {
        "photo_id": photo_id,
        "tenant_id": _uuid_str(tenant_id),
    }
    for key in set_keys:
        sql_parts.append(_UPDATE_PHOTO_FIELD_FRAGMENTS[key])
        if key == "exif_meta":
            import json
            val = updates[key]
            params[key] = json.dumps(val) if val is not None else None
        else:
            params[key] = updates[key]
    sql_parts.append(_UPDATE_PHOTO_SUFFIX_SQL)
    prepared_text = "".join(sql_parts)

    await db.execute(text(prepared_text), params)

    logger.info(
        "market_survey_photo_updated",
        photo_id=photo_id,
        tenant_id=str(tenant_id),
        fields=set_keys,
    )
    return (await get_photo(db, tenant_id, photo_id)) or {}


async def delete_photo(
    db: AsyncSession,
    tenant_id: str,
    photo_id: str,
) -> bool:
    """软删照片."""
    await _set_tenant(db, tenant_id)
    result = await db.execute(
        text(_DELETE_PHOTO_SQL),
        {"photo_id": photo_id, "tenant_id": _uuid_str(tenant_id)},
    )
    return bool(result.rowcount)


# ═════════════════════════════════════════════════════════════════════════════
# 4. 聚合详情
# ═════════════════════════════════════════════════════════════════════════════


async def get_survey_detail(
    db: AsyncSession,
    tenant_id: str,
    survey_id: str,
) -> Optional[dict]:
    """返回主表 + items + photos 聚合 (UI 详情页一次性加载)."""
    survey = await get_survey(db, tenant_id, survey_id)
    if survey is None:
        return None
    items = await list_items_by_survey(db, tenant_id, survey_id)
    photos = await list_photos_by_survey(db, tenant_id, survey_id)
    return {"survey": survey, "items": items, "photos": photos}


# ═════════════════════════════════════════════════════════════════════════════
# 5. sub-B: 上传辅助 (复用 delivery_proof_service.upload_to_object_storage mock COS)
# ═════════════════════════════════════════════════════════════════════════════


# 允许的图片 MIME 类型 (与 delivery_proof 模式一致)
_ALLOWED_PHOTO_MIME_TYPES = frozenset(
    [
        "image/jpeg",
        "image/png",
        "image/webp",
        "image/heic",  # iOS 默认相机格式
    ]
)

# 单张照片上限 5 MB (与 delivery_proof MAX_ATTACHMENT_SIZE_BYTES 一致)
_MAX_PHOTO_SIZE_BYTES = 5 * 1024 * 1024


async def upload_photo_for_survey(
    db: AsyncSession,
    tenant_id: str,
    *,
    survey_id: str,
    raw_bytes: bytes,
    mime_type: str,
    item_id: Optional[str] = None,
    caption: Optional[str] = None,
    exif_meta: Optional[dict] = None,
    file_name: Optional[str] = None,
) -> dict:
    """sub-B 移动端上传照片入口 — 服务端代理 (multipart/form-data → 对象存储 → DB).

    流程:
      1. 校验 mime_type ∈ _ALLOWED_PHOTO_MIME_TYPES
      2. 校验 size ≤ _MAX_PHOTO_SIZE_BYTES (防 OOM + 防恶意上传)
      3. 调 delivery_proof_service.upload_to_object_storage (mock COS, 写 /tmp)
      4. 调 add_photo() 入 market_survey_photos 表
      5. 返回 add_photo 结果 (含 photo_id + photo_url + ...)

    设计要点:
      - 沿用 delivery_proof_service.upload_to_object_storage 保证 mock COS 单一入口
      - mime_type 白名单 = 4 类图片 (其他 415 unsupported_media_type)
      - size 校验在 upload 前 + 内核传上来的 spool 文件已读全, 防止大于 _MAX 的恶意 chunk
      - 错误链: ValueError (业务) → 路由 422 / 415
    """
    if mime_type not in _ALLOWED_PHOTO_MIME_TYPES:
        raise ValueError(
            f"不支持的 mime_type: {mime_type} "
            f"(允许: {sorted(_ALLOWED_PHOTO_MIME_TYPES)})"
        )
    if len(raw_bytes) == 0:
        raise ValueError("上传文件为空 (0 字节)")
    if len(raw_bytes) > _MAX_PHOTO_SIZE_BYTES:
        raise ValueError(
            f"上传文件 {len(raw_bytes)} 字节超过单张上限 "
            f"{_MAX_PHOTO_SIZE_BYTES} 字节 (5 MB)"
        )

    # 复用 delivery_proof_service mock COS (与 PR 一致, 单一对象存储入口)
    from .delivery_proof_service import upload_to_object_storage

    upload_meta = upload_to_object_storage(
        tenant_id=tenant_id,
        raw_bytes=raw_bytes,
        mime_type=mime_type,
        file_name=file_name,
    )

    # 调 add_photo (含 父 survey + optional item_id 跨 survey 业务校验 +
    # asyncpg IntegrityError rollback + _set_tenant 重设)
    photo = await add_photo(
        db,
        tenant_id,
        survey_id=survey_id,
        photo_url=upload_meta["url"],
        item_id=item_id,
        caption=caption,
        exif_meta=exif_meta,
    )

    logger.info(
        "market_survey_photo_uploaded",
        survey_id=survey_id,
        item_id=item_id,
        tenant_id=str(tenant_id),
        size=len(raw_bytes),
        mime_type=mime_type,
        photo_url=upload_meta["url"],
    )
    return photo


# ═════════════════════════════════════════════════════════════════════════════
# 6. sub-B: ingredient 自动补全 (减少自由文本兜底比例)
# ═════════════════════════════════════════════════════════════════════════════


_SEARCH_INGREDIENTS_BY_NAME_SQL = """
    SELECT DISTINCT ON (ingredient_name)
        id::text          AS id,
        ingredient_name,
        unit,
        category
    FROM ingredients
    WHERE tenant_id     = :tenant_id
      AND is_deleted    = FALSE
      AND ingredient_name ILIKE :pattern
    ORDER BY ingredient_name ASC, id ASC
    LIMIT :limit
"""


def _escape_like_pattern(q: str) -> str:
    """转义 SQL LIKE/ILIKE 通配符 (% 和 _ 和 \\) 防 q 含 % 的注入扩展.

    SQL injection 本身由 bound param 防 (不拼字符串), 但用户传 'a%' 期望
    精确匹配字面量 '%', 必须先转义.
    """
    return q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


async def search_ingredients_by_name(
    db: AsyncSession,
    tenant_id: str,
    *,
    q: str,
    limit: int = 20,
) -> list[dict]:
    """按名称模糊查 ingredients (autocomplete).

    - q 必填, 最小 1 字符, 最大 100 字符 (防大 q 性能问题)
    - ILIKE %q% 模糊匹配 (中间匹配, 不只前缀)
    - DISTINCT ON (ingredient_name) 跨 store 同名 ingredient 仅返回 1 条 (id arbitrary)
    - limit ∈ (0, 50] (autocomplete 不应超过 50 个候选)
    - 转义 q 中的 % / _ / \\ 防字面量绕过

    Returns:
        list[{id, ingredient_name, unit, category}] (id arbitrary, 同 name 取最先 id)
    """
    if not q or not q.strip():
        raise ValueError("q 不能为空 (autocomplete 至少 1 字符)")
    if len(q) > 100:
        raise ValueError(f"q 长度 {len(q)} 超过上限 100 字符")
    if limit <= 0 or limit > 50:
        raise ValueError(f"limit 必须 in (0, 50], 实际 {limit}")

    escaped = _escape_like_pattern(q.strip())
    pattern = f"%{escaped}%"

    await _set_tenant(db, tenant_id)
    result = await db.execute(
        text(_SEARCH_INGREDIENTS_BY_NAME_SQL),
        {
            "tenant_id": _uuid_str(tenant_id),
            "pattern": pattern,
            "limit": limit,
        },
    )
    return [dict(r) for r in result.mappings().all()]


__all__ = [
    # 主表
    "create_survey",
    "get_survey",
    "list_surveys",
    "update_survey",
    "transition_status",
    "delete_survey",
    # 明细
    "add_item",
    "get_item",
    "list_items_by_survey",
    "update_item",
    "delete_item",
    # 照片
    "add_photo",
    "get_photo",
    "list_photos_by_survey",
    "update_photo",
    "delete_photo",
    # 聚合
    "get_survey_detail",
    # sub-B: 上传 + autocomplete
    "upload_photo_for_survey",
    "search_ingredients_by_name",
]
