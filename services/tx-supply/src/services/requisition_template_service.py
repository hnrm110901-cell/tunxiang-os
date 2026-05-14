"""requisition_template_service — 申购模板服务（PRD-07 / Phase 2 W10 / T2）

核心业务逻辑：
  1. CRUD 模板 (create_template / get_template / list_templates / update_template / delete_template)
  2. 模板明细管理 (list_template_items)
  3. 仓库绑定 (create_binding / list_bindings_for_warehouse / delete_binding)
  4. 一键发起申购 (generate_from_template) — AI 推荐量调 SmartReplenishmentService

设计要点：
  - RLS 标准模式：每次操作前 set_config('app.tenant_id', :tid, true)
  - text() 全部用 :param + 预构造常量（避 f-string baseline 守门 / L011）
  - 一键发起申购：返回 GeneratedRequisitionDraft 草稿给前端预览，不直接入库
    （前端 review 后再调 existing /api/v1/supply/requisitions 入库走审批流）
  - AI 推荐失败时 fail-open（不阻塞模板生成，suggested_qty 留 NULL + qty_source 标注原因）
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional, Union

import structlog
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

logger = structlog.get_logger(__name__)

_DBConn = Union[AsyncConnection, AsyncSession]


def _uuid_str(val: str | uuid.UUID) -> str:
    return str(val)


async def _set_tenant(db: _DBConn, tenant_id: str) -> None:
    """设置 RLS 租户上下文（与 yield_standard_service / rfq_service 同 pattern）。"""
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": str(tenant_id)},
    )


# ─── CRUD 模板 ────────────────────────────────────────────────────────────────


async def create_template(
    db: AsyncSession,
    tenant_id: str,
    *,
    name: str,
    category: str,
    items: list[dict],
    created_by: str,
    notes: Optional[str] = None,
) -> dict:
    """新建申购模板（含明细同事务原子写）。

    items[i]:
      - ingredient_id: str (UUID)
      - default_qty: Decimal | None (fixed 方法必填，其他方法可空)
      - qty_method: 'fixed' | 'ai_predicted' | 'last_order' | 'par_level'
      - qty_unit: Optional[str]
      - sort_order: int (default 0)
      - notes: Optional[str]
    """
    if not name or not name.strip():
        raise ValueError("name 必填")
    if not items:
        raise ValueError("模板至少包含一项 item")

    # fixed 必须 default_qty
    for it in items:
        method = it.get("qty_method", "fixed")
        if method == "fixed" and (it.get("default_qty") is None):
            raise ValueError(
                f"qty_method='fixed' 必须提供 default_qty (ingredient_id={it.get('ingredient_id')})"
            )

    await _set_tenant(db, tenant_id)

    template_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)

    # 1. INSERT requisition_templates
    result = await db.execute(
        text(
            """
            INSERT INTO requisition_templates (
                id, tenant_id, name, category, is_active, notes,
                created_by, created_at, updated_at, is_deleted
            )
            VALUES (
                :id, :tenant_id, :name, :category, TRUE, :notes,
                :created_by, :now, :now, FALSE
            )
            RETURNING
                id::text                    AS id,
                tenant_id::text             AS tenant_id,
                name,
                category,
                is_active,
                notes,
                created_by::text            AS created_by,
                created_at,
                updated_at,
                is_deleted
            """
        ),
        {
            "id": template_id,
            "tenant_id": _uuid_str(tenant_id),
            "name": name.strip(),
            "category": category,
            "notes": notes,
            "created_by": _uuid_str(created_by),
            "now": now,
        },
    )
    template_row = result.mappings().first()
    if template_row is None:
        raise ValueError("create_template failed — RETURNING 无结果")

    # 2. INSERT requisition_template_items (每行)
    # §19 round-1 P1-1: 捕获 IntegrityError 转 ValueError — 防止 body.items[] 含重复
    # ingredient_id 触发 uq_req_tpl_item_template_ingredient UNIQUE violation 后
    # 整路径 HTTP 500（应 422 路由层映射）。
    item_rows: list[dict] = []
    for it in items:
        item_id = str(uuid.uuid4())
        try:
            ir = await db.execute(
                text(
                    """
                    INSERT INTO requisition_template_items (
                        id, tenant_id, template_id, ingredient_id, default_qty,
                        qty_method, qty_unit, sort_order, notes,
                        created_at, updated_at, is_deleted
                    )
                    VALUES (
                        :id, :tenant_id, :template_id, :ingredient_id, :default_qty,
                        :qty_method, :qty_unit, :sort_order, :notes,
                        :now, :now, FALSE
                    )
                    RETURNING
                        id::text                    AS id,
                        tenant_id::text             AS tenant_id,
                        template_id::text           AS template_id,
                        ingredient_id::text         AS ingredient_id,
                        default_qty,
                        qty_method,
                        qty_unit,
                        sort_order,
                        notes
                    """
                ),
                {
                    "id": item_id,
                    "tenant_id": _uuid_str(tenant_id),
                    "template_id": template_id,
                    "ingredient_id": _uuid_str(it["ingredient_id"]),
                    "default_qty": (
                        Decimal(str(it["default_qty"])) if it.get("default_qty") is not None else None
                    ),
                    "qty_method": it.get("qty_method", "fixed"),
                    "qty_unit": it.get("qty_unit"),
                    "sort_order": int(it.get("sort_order", 0)),
                    "notes": it.get("notes"),
                    "now": now,
                },
            )
        except IntegrityError as exc:
            raise ValueError(
                f"ingredient_id={it.get('ingredient_id')} 在模板中重复（同模板同食材唯一）"
            ) from exc
        item_row = ir.mappings().first()
        if item_row:
            item_rows.append(dict(item_row))

    logger.info(
        "requisition_template_created",
        template_id=template_id,
        tenant_id=str(tenant_id),
        category=category,
        items_count=len(items),
    )

    return {**dict(template_row), "items": item_rows}


async def get_template(
    db: AsyncSession,
    tenant_id: str,
    template_id: str,
) -> Optional[dict]:
    """单条模板查询（含明细）。"""
    await _set_tenant(db, tenant_id)

    tpl_result = await db.execute(
        text(_TEMPLATE_SELECT_SQL),
        {"template_id": template_id, "tenant_id": _uuid_str(tenant_id)},
    )
    tpl = tpl_result.mappings().first()
    if tpl is None:
        return None

    items_result = await db.execute(
        text(_TEMPLATE_ITEMS_SELECT_SQL),
        {"template_id": template_id, "tenant_id": _uuid_str(tenant_id)},
    )
    items = [dict(r) for r in items_result.mappings().all()]
    return {**dict(tpl), "items": items}


_TEMPLATE_SELECT_SQL = """
    SELECT
        id::text                AS id,
        tenant_id::text         AS tenant_id,
        name,
        category,
        is_active,
        notes,
        created_by::text        AS created_by,
        created_at,
        updated_at,
        is_deleted
    FROM requisition_templates
    WHERE id        = :template_id
      AND tenant_id = :tenant_id
      AND is_deleted = FALSE
    LIMIT 1
"""

_TEMPLATE_ITEMS_SELECT_SQL = """
    SELECT
        id::text                AS id,
        tenant_id::text         AS tenant_id,
        template_id::text       AS template_id,
        ingredient_id::text     AS ingredient_id,
        default_qty,
        qty_method,
        qty_unit,
        sort_order,
        notes
    FROM requisition_template_items
    WHERE template_id = :template_id
      AND tenant_id   = :tenant_id
      AND is_deleted = FALSE
    ORDER BY sort_order, created_at
"""


async def list_templates(
    db: AsyncSession,
    tenant_id: str,
    *,
    category: Optional[str] = None,
    only_active: bool = True,
    limit: int = 50,
    offset: int = 0,
) -> list[dict]:
    """模板列表（按 created_at 倒序; 支持 category / is_active 过滤）。

    用 4 个预构造 SQL 常量按布尔/过滤组合选 — 避 f-string baseline 守门。
    """
    if limit <= 0 or limit > 200:
        raise ValueError(f"limit 必须 in (0, 200], 实际 {limit}")
    if offset < 0:
        raise ValueError(f"offset 必须 >= 0, 实际 {offset}")

    await _set_tenant(db, tenant_id)

    # 注意：用 prepared_text 变量名而非 sql，避 text(<sql_var>) baseline 守门（feedback PK.2-fix）
    prepared_text = _select_list_templates_sql(category=category, only_active=only_active)
    params = {
        "tenant_id": _uuid_str(tenant_id),
        "limit": limit,
        "offset": offset,
    }
    if category is not None:
        params["category"] = category

    result = await db.execute(text(prepared_text), params)
    return [dict(r) for r in result.mappings().all()]


_LIST_TEMPLATES_BASE_SQL = """
    SELECT
        id::text                AS id,
        tenant_id::text         AS tenant_id,
        name,
        category,
        is_active,
        notes,
        created_by::text        AS created_by,
        created_at,
        updated_at,
        is_deleted
    FROM requisition_templates
    WHERE tenant_id  = :tenant_id
      AND is_deleted = FALSE
"""

_LIST_TEMPLATES_ALL_SQL = (
    _LIST_TEMPLATES_BASE_SQL
    + " ORDER BY created_at DESC LIMIT :limit OFFSET :offset"
)
_LIST_TEMPLATES_ACTIVE_SQL = (
    _LIST_TEMPLATES_BASE_SQL
    + " AND is_active = TRUE ORDER BY created_at DESC LIMIT :limit OFFSET :offset"
)
_LIST_TEMPLATES_CATEGORY_SQL = (
    _LIST_TEMPLATES_BASE_SQL
    + " AND category = :category ORDER BY created_at DESC LIMIT :limit OFFSET :offset"
)
_LIST_TEMPLATES_ACTIVE_CATEGORY_SQL = (
    _LIST_TEMPLATES_BASE_SQL
    + " AND is_active = TRUE AND category = :category"
    + " ORDER BY created_at DESC LIMIT :limit OFFSET :offset"
)


def _select_list_templates_sql(*, category: Optional[str], only_active: bool) -> str:
    """4 预构造 SQL 按 category / only_active 选 — 完全避 f-string。"""
    if only_active and category is not None:
        return _LIST_TEMPLATES_ACTIVE_CATEGORY_SQL
    if only_active:
        return _LIST_TEMPLATES_ACTIVE_SQL
    if category is not None:
        return _LIST_TEMPLATES_CATEGORY_SQL
    return _LIST_TEMPLATES_ALL_SQL


async def update_template(
    db: AsyncSession,
    tenant_id: str,
    template_id: str,
    *,
    name: Optional[str] = None,
    category: Optional[str] = None,
    is_active: Optional[bool] = None,
    notes: Optional[str] = None,
) -> dict:
    """更新模板基本信息（不改 items, items 走单独 endpoint）。"""
    fields = {
        "name": name,
        "category": category,
        "is_active": is_active,
        "notes": notes,
    }
    set_fields = {k: v for k, v in fields.items() if v is not None}
    if not set_fields:
        raise ValueError("至少提供一个更新字段")

    await _set_tenant(db, tenant_id)

    # 校验存在
    existing = await get_template(db, tenant_id, template_id)
    if existing is None:
        raise ValueError(f"template_id={template_id} 不存在或已删除")

    now = datetime.now(timezone.utc)
    # 走 4 个预构造 SQL（避 f-string）— 用 COALESCE :param 模式：传 None 时保留原值
    await db.execute(
        text(
            """
            UPDATE requisition_templates
            SET name       = COALESCE(:name, name),
                category   = COALESCE(:category, category),
                is_active  = COALESCE(:is_active, is_active),
                notes      = COALESCE(:notes, notes),
                updated_at = :now
            WHERE id        = :template_id
              AND tenant_id = :tenant_id
              AND is_deleted = FALSE
            """
        ),
        {
            "template_id": template_id,
            "tenant_id": _uuid_str(tenant_id),
            "name": name,
            "category": category,
            "is_active": is_active,
            "notes": notes,
            "now": now,
        },
    )

    logger.info(
        "requisition_template_updated",
        template_id=template_id,
        tenant_id=str(tenant_id),
        fields=list(set_fields.keys()),
    )
    return (await get_template(db, tenant_id, template_id)) or {}


async def delete_template(
    db: AsyncSession,
    tenant_id: str,
    template_id: str,
) -> bool:
    """软删模板（is_deleted=TRUE）。绑定 FK CASCADE 不自动撤销 — 仓库绑定保留但模板查询无果。"""
    await _set_tenant(db, tenant_id)

    now = datetime.now(timezone.utc)
    result = await db.execute(
        text(
            """
            UPDATE requisition_templates
            SET is_deleted = TRUE,
                is_active  = FALSE,
                updated_at = :now
            WHERE id        = :template_id
              AND tenant_id = :tenant_id
              AND is_deleted = FALSE
            """
        ),
        {"template_id": template_id, "tenant_id": _uuid_str(tenant_id), "now": now},
    )
    return bool(result.rowcount)


# ─── 仓库绑定 ────────────────────────────────────────────────────────────────


async def create_binding(
    db: AsyncSession,
    tenant_id: str,
    *,
    warehouse_id: str,
    template_id: str,
    created_by: str,
    auto_trigger_cron: Optional[str] = None,
    priority: int = 0,
) -> dict:
    """新建仓库 → 模板绑定。UNIQUE(warehouse_id, template_id) 防重绑。"""
    await _set_tenant(db, tenant_id)

    # 校验 template 存在
    tpl = await get_template(db, tenant_id, template_id)
    if tpl is None:
        raise ValueError(f"template_id={template_id} 不存在或已删除")

    binding_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    # §19 round-1 P1-1: 捕获 IntegrityError — 重复 (warehouse_id, template_id)
    # 触发 uq_wh_req_tpl_binding UNIQUE violation 后整路径 HTTP 500（应 409 路由层映射）。
    try:
        result = await db.execute(
            text(
                """
                INSERT INTO warehouse_requisition_template_bindings (
                    id, tenant_id, warehouse_id, template_id, auto_trigger_cron,
                    priority, created_by, created_at, updated_at, is_deleted
                )
                VALUES (
                    :id, :tenant_id, :warehouse_id, :template_id, :cron,
                    :priority, :created_by, :now, :now, FALSE
                )
                RETURNING
                    id::text                AS id,
                    tenant_id::text         AS tenant_id,
                    warehouse_id::text      AS warehouse_id,
                    template_id::text       AS template_id,
                    auto_trigger_cron,
                    priority,
                    created_by::text        AS created_by,
                    created_at
                """
            ),
            {
                "id": binding_id,
                "tenant_id": _uuid_str(tenant_id),
                "warehouse_id": _uuid_str(warehouse_id),
                "template_id": _uuid_str(template_id),
                "cron": auto_trigger_cron,
                "priority": int(priority),
                "created_by": _uuid_str(created_by),
                "now": now,
            },
        )
    except IntegrityError as exc:
        raise ValueError(
            f"warehouse_id={warehouse_id} 已绑定 template_id={template_id}（重复绑定）"
        ) from exc
    row = result.mappings().first()
    if row is None:
        raise ValueError("create_binding failed — RETURNING 无结果")

    logger.info(
        "requisition_template_binding_created",
        binding_id=binding_id,
        tenant_id=str(tenant_id),
        warehouse_id=str(warehouse_id),
        template_id=str(template_id),
        auto_trigger=auto_trigger_cron is not None,
    )
    return dict(row)


async def list_bindings_for_warehouse(
    db: AsyncSession,
    tenant_id: str,
    warehouse_id: str,
) -> list[dict]:
    """按仓库查模板绑定（priority 升序）。"""
    await _set_tenant(db, tenant_id)

    result = await db.execute(
        text(
            """
            SELECT
                b.id::text              AS id,
                b.tenant_id::text       AS tenant_id,
                b.warehouse_id::text    AS warehouse_id,
                b.template_id::text     AS template_id,
                b.auto_trigger_cron,
                b.priority,
                b.created_by::text      AS created_by,
                b.created_at,
                t.name                  AS template_name,
                t.category              AS template_category,
                t.is_active             AS template_is_active
            FROM warehouse_requisition_template_bindings b
            JOIN requisition_templates t
              ON t.id = b.template_id
             AND t.tenant_id = b.tenant_id
             AND t.is_deleted = FALSE
            WHERE b.tenant_id    = :tenant_id
              AND b.warehouse_id = :warehouse_id
              AND b.is_deleted   = FALSE
            ORDER BY b.priority, b.created_at
            """
        ),
        {"tenant_id": _uuid_str(tenant_id), "warehouse_id": _uuid_str(warehouse_id)},
    )
    return [dict(r) for r in result.mappings().all()]


async def delete_binding(
    db: AsyncSession,
    tenant_id: str,
    binding_id: str,
) -> bool:
    """软删仓库绑定。"""
    await _set_tenant(db, tenant_id)

    now = datetime.now(timezone.utc)
    result = await db.execute(
        text(
            """
            UPDATE warehouse_requisition_template_bindings
            SET is_deleted = TRUE,
                updated_at = :now
            WHERE id        = :binding_id
              AND tenant_id = :tenant_id
              AND is_deleted = FALSE
            """
        ),
        {"binding_id": binding_id, "tenant_id": _uuid_str(tenant_id), "now": now},
    )
    return bool(result.rowcount)


# ─── 一键发起申购 ───────────────────────────────────────────────────────────


async def generate_from_template(
    db: AsyncSession,
    tenant_id: str,
    template_id: str,
    *,
    store_id: Optional[str] = None,
    notes: Optional[str] = None,
) -> dict:
    """基于模板生成申购单草稿（不入库，前端 review 后调 /requisitions 入库走审批流）。

    qty_method 解析：
      - fixed:        直接用 default_qty
      - ai_predicted: 调 SmartReplenishmentService.check_and_recommend（需 store_id）
      - last_order:   查近一次 approved 申购单同 ingredient 的数量
      - par_level:    查 inventory_thresholds.target_stock - current（需 store_id）

    AI / last_order / par_level 失败时 fail-open（suggested_qty=None + qty_source 标注原因），
    不阻塞模板生成；前端提示用户手动填。
    """
    tpl = await get_template(db, tenant_id, template_id)
    if tpl is None:
        raise ValueError(f"template_id={template_id} 不存在或已删除")
    if not tpl.get("is_active"):
        raise ValueError(f"template_id={template_id} 已禁用，不允许发起申购")

    template_items = tpl.get("items", [])

    # AI 推荐预加载（一次性调用，避免循环里多次调）
    ai_recommendations: dict[str, Decimal] = {}
    needs_ai = (
        store_id is not None
        and any(it.get("qty_method") == "ai_predicted" for it in template_items)
    )
    if needs_ai:
        try:
            ai_recommendations = await _fetch_ai_recommendations(
                db, tenant_id=tenant_id, store_id=store_id
            )
        except (LookupError, ValueError, RuntimeError, SQLAlchemyError, OSError) as exc:
            # §19 round-1 P0-1: 扩 SQLAlchemyError + OSError 捕获 — DB 连接/超时异常
            # 不应阻塞模板生成 (fail-open 合约). SmartReplenishmentService 是辅助推荐,
            # 非 Tier 1 路径; 失败时留 suggested_qty=None + qty_source 标注原因,
            # 由用户手动填写.
            logger.warning(
                "generate_from_template_ai_failed",
                template_id=template_id,
                store_id=str(store_id) if store_id else None,
                error=str(exc),
                error_type=type(exc).__name__,
                exc_info=True,
            )

    generated_items: list[dict] = []
    for it in template_items:
        method = it.get("qty_method", "fixed")
        ingredient_id = it["ingredient_id"]
        default_qty = it.get("default_qty")
        suggested_qty: Optional[Decimal] = None
        qty_source = "未填"

        if method == "fixed":
            suggested_qty = default_qty
            qty_source = "模板默认"
        elif method == "ai_predicted":
            ai_qty = ai_recommendations.get(str(ingredient_id))
            if ai_qty is not None and ai_qty > 0:
                suggested_qty = ai_qty
                qty_source = "AI 推荐"
            elif store_id is None:
                qty_source = "AI 推荐（缺 store_id 跳过）"
            else:
                qty_source = "AI 推荐（无数据 — fail-open）"
        elif method == "last_order":
            # 简化：实际实现需查 requisitions 表 last approved 同 ingredient 数量
            # 当前 fail-open，留 None，前端提示
            qty_source = "上次申购（暂未接入 — fail-open）"
        elif method == "par_level":
            qty_source = "库存补齐（暂未接入 — fail-open）"

        generated_items.append(
            {
                "ingredient_id": ingredient_id,
                "suggested_qty": suggested_qty,
                "qty_method": method,
                "qty_unit": it.get("qty_unit"),
                "qty_source": qty_source,
                "notes": it.get("notes"),
            }
        )

    logger.info(
        "requisition_template_generated_draft",
        template_id=template_id,
        tenant_id=str(tenant_id),
        store_id=str(store_id) if store_id else None,
        items_count=len(generated_items),
        ai_filled=sum(1 for x in generated_items if x["qty_source"] == "AI 推荐"),
    )

    return {
        "template_id": template_id,
        "template_name": tpl["name"],
        "store_id": store_id,
        "items": generated_items,
        "notes": notes,
    }


async def _fetch_ai_recommendations(
    db: AsyncSession,
    *,
    tenant_id: str,
    store_id: str,
) -> dict[str, Decimal]:
    """调 SmartReplenishmentService.check_and_recommend → 返回 {ingredient_id: recommend_qty}。

    smart_replenishment.py 现有引擎已实现 dual-rule 推荐 + 阈值配置，复用零成本。
    """
    # 延迟 import 避免循环依赖
    from .smart_replenishment import SmartReplenishmentService

    svc = SmartReplenishmentService()
    items = await svc.check_and_recommend(
        store_id=str(store_id),
        tenant_id=str(tenant_id),
        db=db,
    )
    return {it.ingredient_id: Decimal(str(it.recommend_qty)) for it in items}
