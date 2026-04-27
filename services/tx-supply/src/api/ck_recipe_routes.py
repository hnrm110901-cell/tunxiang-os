"""中央厨房核心 API — 配方管理 + 生产计划 + 配送调拨

对应数据库表（v120 迁移）：
  dish_recipes / recipe_ingredients — 标准配方（BOM）
  ck_production_plans / ck_plan_items — 生产计划
  ck_dispatch_orders / ck_dispatch_items — 配送调拨单

路由前缀：
  /api/v1/supply/recipes   — 配方管理
  /api/v1/supply/ck/plans  — 生产计划
  /api/v1/supply/ck/dispatch — 配送调拨

统一响应格式: {"ok": bool, "data": {}, "error": {}}
认证头：X-Tenant-ID（所有接口必填）
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import date, datetime
from typing import Any, Dict, List, Optional

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from shared.events.src.emitter import emit_event
from shared.ontology.src.database import get_db

log = structlog.get_logger(__name__)

router = APIRouter(tags=["ck_recipe"])


# ─── Pydantic V2 Models ──────────────────────────────────────────────────────


class RecipeIngredientIn(BaseModel):
    ingredient_name: str
    ingredient_id: str | None = None
    qty: float
    unit: str
    loss_rate: float = 0.0


class RecipeIn(BaseModel):
    dish_id: str
    yield_qty: float = 1.0
    yield_unit: str = "portion"
    notes: str | None = None
    ingredients: list[RecipeIngredientIn]


class RecipeUpdateIn(BaseModel):
    yield_qty: float | None = None
    yield_unit: str | None = None
    notes: str | None = None
    is_active: bool | None = None
    ingredients: list[RecipeIngredientIn] | None = None


class RecipeCalculateIn(BaseModel):
    target_qty: float = Field(..., gt=0, description="目标产量")


class PlanItemIn(BaseModel):
    dish_id: str
    recipe_id: str | None = None
    planned_qty: float
    unit: str = "portion"


class ProductionPlanIn(BaseModel):
    plan_date: str  # YYYY-MM-DD
    store_id: str | None = None
    created_by: str | None = None
    notes: str | None = None
    items: list[PlanItemIn]


class PlanStatusIn(BaseModel):
    status: str = Field(
        ...,
        description="目标状态：confirmed / in_progress / done",
    )


class DispatchItemIn(BaseModel):
    dish_id: str
    planned_qty: float
    unit: str


class DispatchOrderIn(BaseModel):
    plan_id: str | None = None
    to_store_id: str
    dispatch_date: str  # YYYY-MM-DD
    items: list[DispatchItemIn]
    driver_name: str | None = None
    vehicle_no: str | None = None


class ReceiveItemIn(BaseModel):
    dish_id: str
    actual_qty: float


class ReceiveConfirmIn(BaseModel):
    receiver_name: str | None = None
    items: list[ReceiveItemIn]


# ─── 状态转移规则 ────────────────────────────────────────────────────────────

_PLAN_STATUS_TRANSITIONS: dict[str, set[str]] = {
    "draft": {"confirmed"},
    "confirmed": {"in_progress"},
    "in_progress": {"done"},
    "done": set(),
}

_DISPATCH_STATUS_TRANSITIONS: dict[str, set[str]] = {
    "pending": {"dispatched"},
    "dispatched": {"received", "rejected"},
    "received": set(),
    "rejected": set(),
}


# ─── 工具函数 ─────────────────────────────────────────────────────────────────


def _new_id() -> str:
    return str(uuid.uuid4())


def _today() -> str:
    return date.today().isoformat()


def _now_iso() -> str:
    return datetime.utcnow().isoformat() + "Z"


def _gen_dispatch_no(dispatch_date: str) -> str:
    """生成调拨单号，格式 CK-YYYYMMDD-XXXX。"""
    date_part = dispatch_date.replace("-", "")
    suffix = uuid.uuid4().hex[:4].upper()
    return f"CK-{date_part}-{suffix}"


def _row_to_dict(row) -> dict:
    """将 SQLAlchemy Row 转换为普通字典。"""
    return dict(row._mapping)


# ═══════════════════════════════════════════════════════════════════════════════
# 配方管理 — /api/v1/supply/recipes
# ═══════════════════════════════════════════════════════════════════════════════


@router.get("/api/v1/supply/recipes", summary="配方列表")
async def list_recipes(
    dish_id: Optional[str] = Query(None, description="按菜品ID过滤"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """返回当前租户的配方列表，支持按 dish_id 过滤。"""
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": x_tenant_id},
    )
    try:
        sql = """
            SELECT r.id, r.tenant_id, r.dish_id, r.version, r.is_active,
                   r.yield_qty, r.yield_unit, r.notes, r.is_deleted,
                   r.created_at, r.updated_at,
                   COUNT(ri.id) AS ingredient_count
            FROM dish_recipes r
            LEFT JOIN recipe_ingredients ri
                ON ri.recipe_id = r.id AND ri.is_deleted = false
            WHERE r.tenant_id = :tenant_id AND r.is_deleted = false
        """
        params: dict[str, Any] = {"tenant_id": x_tenant_id}
        if dish_id:
            sql += " AND r.dish_id = :dish_id"
            params["dish_id"] = dish_id
        sql += " GROUP BY r.id ORDER BY r.created_at DESC"

        result = await db.execute(text(sql), params)
        rows = result.fetchall()
        items = [_row_to_dict(row) for row in rows]
        return {"ok": True, "data": {"items": items, "total": len(items)}}
    except SQLAlchemyError as exc:
        log.error("list_recipes.db_error", error=str(exc), tenant_id=x_tenant_id)
        return {"ok": True, "data": {"items": [], "total": 0}}


@router.post("/api/v1/supply/recipes", summary="创建配方", status_code=201)
async def create_recipe(
    body: RecipeIn,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """创建标准配方，含原料明细列表。"""
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": x_tenant_id},
    )
    try:
        # 计算下一个版本号
        ver_result = await db.execute(
            text(
                "SELECT COALESCE(MAX(version), 0) AS max_ver "
                "FROM dish_recipes "
                "WHERE tenant_id = :tenant_id AND dish_id = :dish_id"
            ),
            {"tenant_id": x_tenant_id, "dish_id": body.dish_id},
        )
        max_ver = ver_result.scalar() or 0
        version = int(max_ver) + 1

        recipe_id = _new_id()

        # 插入配方主表
        await db.execute(
            text(
                "INSERT INTO dish_recipes "
                "(id, tenant_id, dish_id, version, is_active, yield_qty, yield_unit, notes, is_deleted) "
                "VALUES (:id, :tenant_id, :dish_id, :version, true, :yield_qty, :yield_unit, :notes, false)"
            ),
            {
                "id": recipe_id,
                "tenant_id": x_tenant_id,
                "dish_id": body.dish_id,
                "version": version,
                "yield_qty": body.yield_qty,
                "yield_unit": body.yield_unit,
                "notes": body.notes,
            },
        )

        # 批量插入原料明细
        ingredients = []
        for ing in body.ingredients:
            ing_id = _new_id()
            await db.execute(
                text(
                    "INSERT INTO recipe_ingredients "
                    "(id, tenant_id, recipe_id, ingredient_name, ingredient_id, qty, unit, loss_rate, is_deleted) "
                    "VALUES (:id, :tenant_id, :recipe_id, :ingredient_name, :ingredient_id, :qty, :unit, :loss_rate, false)"
                ),
                {
                    "id": ing_id,
                    "tenant_id": x_tenant_id,
                    "recipe_id": recipe_id,
                    "ingredient_name": ing.ingredient_name,
                    "ingredient_id": ing.ingredient_id,
                    "qty": ing.qty,
                    "unit": ing.unit,
                    "loss_rate": ing.loss_rate,
                },
            )
            ingredients.append(
                {
                    "id": ing_id,
                    "tenant_id": x_tenant_id,
                    "recipe_id": recipe_id,
                    "ingredient_name": ing.ingredient_name,
                    "ingredient_id": ing.ingredient_id,
                    "qty": ing.qty,
                    "unit": ing.unit,
                    "loss_rate": ing.loss_rate,
                    "is_deleted": False,
                }
            )

        await db.commit()

        # 查回完整记录
        rec_result = await db.execute(
            text("SELECT * FROM dish_recipes WHERE id = :id"),
            {"id": recipe_id},
        )
        recipe = _row_to_dict(rec_result.fetchone())
        recipe["ingredients"] = ingredients

        log.info("recipe.created", recipe_id=recipe_id, tenant_id=x_tenant_id)

        asyncio.create_task(
            emit_event(
                tenant_id=x_tenant_id,
                store_id=None,
                event_type="supply.bom_updated",
                stream_id=str(recipe_id),
                payload={
                    "recipe_id": str(recipe_id),
                    "dish_id": body.dish_id,
                    "action": "created",
                    "ingredient_count": len(body.ingredients),
                },
                source_service="tx-supply",
            )
        )

        return {"ok": True, "data": recipe}
    except SQLAlchemyError as exc:
        await db.rollback()
        log.error("create_recipe.db_error", error=str(exc), tenant_id=x_tenant_id)
        raise HTTPException(status_code=500, detail="创建配方失败，请稍后重试")


@router.get("/api/v1/supply/recipes/{recipe_id}", summary="配方详情（含原料）")
async def get_recipe(
    recipe_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """查询单条配方详情，含原料明细列表。"""
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": x_tenant_id},
    )
    rec_result = await db.execute(
        text("SELECT * FROM dish_recipes WHERE id = :id AND tenant_id = :tenant_id AND is_deleted = false"),
        {"id": recipe_id, "tenant_id": x_tenant_id},
    )
    row = rec_result.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="配方不存在")

    recipe = _row_to_dict(row)

    ing_result = await db.execute(
        text("SELECT * FROM recipe_ingredients WHERE recipe_id = :recipe_id AND is_deleted = false"),
        {"recipe_id": recipe_id},
    )
    recipe["ingredients"] = [_row_to_dict(r) for r in ing_result.fetchall()]

    return {"ok": True, "data": recipe}


@router.put("/api/v1/supply/recipes/{recipe_id}", summary="更新配方")
async def update_recipe(
    recipe_id: str,
    body: RecipeUpdateIn,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """更新配方基本信息及原料明细。"""
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": x_tenant_id},
    )

    # 查验存在
    check_result = await db.execute(
        text("SELECT id, dish_id FROM dish_recipes WHERE id = :id AND tenant_id = :tenant_id AND is_deleted = false"),
        {"id": recipe_id, "tenant_id": x_tenant_id},
    )
    row = check_result.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="配方不存在")

    dish_id = row.dish_id

    try:
        # 构建动态 SET 子句
        set_parts = ["updated_at = now()"]
        params: dict[str, Any] = {"id": recipe_id, "tenant_id": x_tenant_id}
        if body.yield_qty is not None:
            set_parts.append("yield_qty = :yield_qty")
            params["yield_qty"] = body.yield_qty
        if body.yield_unit is not None:
            set_parts.append("yield_unit = :yield_unit")
            params["yield_unit"] = body.yield_unit
        if body.notes is not None:
            set_parts.append("notes = :notes")
            params["notes"] = body.notes
        if body.is_active is not None:
            set_parts.append("is_active = :is_active")
            params["is_active"] = body.is_active

        await db.execute(
            text(f"UPDATE dish_recipes SET {', '.join(set_parts)} WHERE id = :id AND tenant_id = :tenant_id"),
            params,
        )

        # 若 ingredients 非 None：先软删旧明细，再批量插入新明细
        if body.ingredients is not None:
            await db.execute(
                text(
                    "UPDATE recipe_ingredients SET is_deleted = true "
                    "WHERE recipe_id = :recipe_id AND tenant_id = :tenant_id"
                ),
                {"recipe_id": recipe_id, "tenant_id": x_tenant_id},
            )
            for ing in body.ingredients:
                await db.execute(
                    text(
                        "INSERT INTO recipe_ingredients "
                        "(id, tenant_id, recipe_id, ingredient_name, ingredient_id, qty, unit, loss_rate, is_deleted) "
                        "VALUES (:id, :tenant_id, :recipe_id, :ingredient_name, :ingredient_id, :qty, :unit, :loss_rate, false)"
                    ),
                    {
                        "id": _new_id(),
                        "tenant_id": x_tenant_id,
                        "recipe_id": recipe_id,
                        "ingredient_name": ing.ingredient_name,
                        "ingredient_id": ing.ingredient_id,
                        "qty": ing.qty,
                        "unit": ing.unit,
                        "loss_rate": ing.loss_rate,
                    },
                )

        await db.commit()

        # 查回完整记录
        rec_result = await db.execute(
            text("SELECT * FROM dish_recipes WHERE id = :id"),
            {"id": recipe_id},
        )
        recipe = _row_to_dict(rec_result.fetchone())

        ing_result = await db.execute(
            text("SELECT * FROM recipe_ingredients WHERE recipe_id = :recipe_id AND is_deleted = false"),
            {"recipe_id": recipe_id},
        )
        recipe["ingredients"] = [_row_to_dict(r) for r in ing_result.fetchall()]

        asyncio.create_task(
            emit_event(
                tenant_id=x_tenant_id,
                store_id=None,
                event_type="supply.bom_updated",
                stream_id=recipe_id,
                payload={
                    "recipe_id": recipe_id,
                    "dish_id": dish_id,
                    "action": "updated",
                },
                source_service="tx-supply",
            )
        )

        return {"ok": True, "data": recipe}
    except SQLAlchemyError as exc:
        await db.rollback()
        log.error("update_recipe.db_error", error=str(exc), recipe_id=recipe_id)
        raise HTTPException(status_code=500, detail="更新配方失败，请稍后重试")


@router.post("/api/v1/supply/recipes/{recipe_id}/calculate", summary="按产量计算原料用量")
async def calculate_recipe(
    recipe_id: str,
    body: RecipeCalculateIn,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """按目标产量计算各原料实际需求量。

    公式：actual_qty = (target_qty / yield_qty) × ing.qty × (1 + loss_rate)
    """
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": x_tenant_id},
    )

    rec_result = await db.execute(
        text("SELECT * FROM dish_recipes WHERE id = :id AND tenant_id = :tenant_id AND is_deleted = false"),
        {"id": recipe_id, "tenant_id": x_tenant_id},
    )
    row = rec_result.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="配方不存在")

    recipe = _row_to_dict(row)
    yield_qty: float = float(recipe["yield_qty"])
    if yield_qty <= 0:
        raise HTTPException(status_code=400, detail="配方 yield_qty 无效（必须>0）")

    ing_result = await db.execute(
        text("SELECT * FROM recipe_ingredients WHERE recipe_id = :recipe_id AND is_deleted = false"),
        {"recipe_id": recipe_id},
    )
    ingredients = [_row_to_dict(r) for r in ing_result.fetchall()]

    scale = body.target_qty / yield_qty
    calculated = []
    for ing in ingredients:
        actual_qty = round(scale * float(ing["qty"]) * (1.0 + float(ing["loss_rate"])), 4)
        calculated.append(
            {
                "ingredient_name": ing["ingredient_name"],
                "ingredient_id": ing["ingredient_id"],
                "unit": ing["unit"],
                "standard_qty": ing["qty"],
                "loss_rate": ing["loss_rate"],
                "calculated_qty": actual_qty,
            }
        )

    return {
        "ok": True,
        "data": {
            "recipe_id": recipe_id,
            "dish_id": recipe["dish_id"],
            "yield_qty": yield_qty,
            "yield_unit": recipe["yield_unit"],
            "target_qty": body.target_qty,
            "scale_factor": round(scale, 4),
            "ingredients": calculated,
        },
    }


# ═══════════════════════════════════════════════════════════════════════════════
# 生产计划 — /api/v1/supply/ck/plans
# ═══════════════════════════════════════════════════════════════════════════════


@router.get("/api/v1/supply/ck/plans", summary="生产计划列表")
async def list_production_plans(
    plan_date: Optional[str] = Query(None, description="按日期过滤 YYYY-MM-DD"),
    status: Optional[str] = Query(None, description="按状态过滤"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """查询生产计划列表，支持按日期/状态过滤。"""
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": x_tenant_id},
    )
    try:
        sql = """
            SELECT p.id, p.tenant_id, p.plan_date, p.status, p.store_id,
                   p.created_by, p.notes, p.is_deleted, p.created_at, p.updated_at,
                   COUNT(pi.id) AS item_count
            FROM ck_production_plans p
            LEFT JOIN ck_plan_items pi
                ON pi.plan_id = p.id AND pi.is_deleted = false
            WHERE p.tenant_id = :tenant_id AND p.is_deleted = false
        """
        params: dict[str, Any] = {"tenant_id": x_tenant_id}
        if plan_date:
            sql += " AND p.plan_date = :plan_date"
            params["plan_date"] = plan_date
        if status:
            sql += " AND p.status = :status"
            params["status"] = status
        sql += " GROUP BY p.id ORDER BY p.plan_date DESC, p.created_at DESC"

        result = await db.execute(text(sql), params)
        rows = result.fetchall()
        items = [_row_to_dict(row) for row in rows]
        return {"ok": True, "data": {"items": items, "total": len(items)}}
    except SQLAlchemyError as exc:
        log.error("list_production_plans.db_error", error=str(exc), tenant_id=x_tenant_id)
        return {"ok": True, "data": {"items": [], "total": 0}}


@router.post("/api/v1/supply/ck/plans", summary="创建生产计划", status_code=201)
async def create_production_plan(
    body: ProductionPlanIn,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """创建生产计划，并从配方自动展开原料需求（写入计划明细）。"""
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": x_tenant_id},
    )
    try:
        plan_id = _new_id()

        # 插入生产计划主表
        await db.execute(
            text(
                "INSERT INTO ck_production_plans "
                "(id, tenant_id, plan_date, status, store_id, created_by, notes, is_deleted) "
                "VALUES (:id, :tenant_id, :plan_date, 'draft', :store_id, :created_by, :notes, false)"
            ),
            {
                "id": plan_id,
                "tenant_id": x_tenant_id,
                "plan_date": body.plan_date,
                "store_id": body.store_id,
                "created_by": body.created_by,
                "notes": body.notes,
            },
        )

        # 对每个 item 查激活配方并插入计划明细
        plan_items = []
        for item in body.items:
            recipe_id = item.recipe_id
            if not recipe_id:
                # 查询该 dish_id 的激活配方
                active_result = await db.execute(
                    text(
                        "SELECT id FROM dish_recipes "
                        "WHERE tenant_id = :tenant_id AND dish_id = :dish_id "
                        "AND is_active = true AND is_deleted = false "
                        "LIMIT 1"
                    ),
                    {"tenant_id": x_tenant_id, "dish_id": item.dish_id},
                )
                active_row = active_result.fetchone()
                if active_row:
                    recipe_id = str(active_row.id)

            item_id = _new_id()
            await db.execute(
                text(
                    "INSERT INTO ck_plan_items "
                    "(id, tenant_id, plan_id, dish_id, recipe_id, planned_qty, actual_qty, unit, status, is_deleted) "
                    "VALUES (:id, :tenant_id, :plan_id, :dish_id, :recipe_id, :planned_qty, null, :unit, 'pending', false)"
                ),
                {
                    "id": item_id,
                    "tenant_id": x_tenant_id,
                    "plan_id": plan_id,
                    "dish_id": item.dish_id,
                    "recipe_id": recipe_id,
                    "planned_qty": item.planned_qty,
                    "unit": item.unit,
                },
            )
            plan_items.append(
                {
                    "id": item_id,
                    "tenant_id": x_tenant_id,
                    "plan_id": plan_id,
                    "dish_id": item.dish_id,
                    "recipe_id": recipe_id,
                    "planned_qty": item.planned_qty,
                    "actual_qty": None,
                    "unit": item.unit,
                    "status": "pending",
                    "is_deleted": False,
                }
            )

        await db.commit()

        # 查回计划主表
        plan_result = await db.execute(
            text("SELECT * FROM ck_production_plans WHERE id = :id"),
            {"id": plan_id},
        )
        plan = _row_to_dict(plan_result.fetchone())
        plan["items"] = plan_items

        log.info("production_plan.created", plan_id=plan_id, tenant_id=x_tenant_id)
        return {"ok": True, "data": plan}
    except SQLAlchemyError as exc:
        await db.rollback()
        log.error("create_production_plan.db_error", error=str(exc), tenant_id=x_tenant_id)
        raise HTTPException(status_code=500, detail="创建生产计划失败，请稍后重试")


@router.put("/api/v1/supply/ck/plans/{plan_id}/status", summary="推进计划状态")
async def update_plan_status(
    plan_id: str,
    body: PlanStatusIn,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """推进生产计划状态：draft→confirmed→in_progress→done。"""
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": x_tenant_id},
    )

    plan_result = await db.execute(
        text("SELECT * FROM ck_production_plans WHERE id = :id AND tenant_id = :tenant_id AND is_deleted = false"),
        {"id": plan_id, "tenant_id": x_tenant_id},
    )
    row = plan_result.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="生产计划不存在")

    plan = _row_to_dict(row)
    current = plan["status"]
    target = body.status
    allowed = _PLAN_STATUS_TRANSITIONS.get(current, set())
    if target not in allowed:
        raise HTTPException(
            status_code=400,
            detail=f"状态不可从 {current} 转移到 {target}（允许：{sorted(allowed)}）",
        )

    try:
        await db.execute(
            text(
                "UPDATE ck_production_plans SET status = :status, updated_at = now() "
                "WHERE id = :id AND tenant_id = :tenant_id"
            ),
            {"status": target, "id": plan_id, "tenant_id": x_tenant_id},
        )
        await db.commit()
    except SQLAlchemyError as exc:
        await db.rollback()
        log.error("update_plan_status.db_error", error=str(exc), plan_id=plan_id)
        raise HTTPException(status_code=500, detail="更新计划状态失败，请稍后重试")

    log.info("production_plan.status_updated", plan_id=plan_id, from_=current, to=target)

    # 查回计划和明细
    updated_result = await db.execute(
        text("SELECT * FROM ck_production_plans WHERE id = :id"),
        {"id": plan_id},
    )
    updated_plan = _row_to_dict(updated_result.fetchone())

    items_result = await db.execute(
        text("SELECT * FROM ck_plan_items WHERE plan_id = :plan_id AND is_deleted = false"),
        {"plan_id": plan_id},
    )
    updated_plan["items"] = [_row_to_dict(r) for r in items_result.fetchall()]

    return {"ok": True, "data": updated_plan}


@router.get("/api/v1/supply/ck/plans/{plan_id}/material-list", summary="原料汇总清单")
async def get_material_list(
    plan_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """计算当前生产计划所需原料汇总清单（按 ingredient_name+unit 合并同类项）。

    算法：
      对每个 plan_item：
        scale = planned_qty / recipe.yield_qty
        actual_qty_per_ing = scale × ing.qty × (1 + loss_rate)
      按 ingredient_name + unit 分组汇总
    """
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": x_tenant_id},
    )

    plan_result = await db.execute(
        text("SELECT * FROM ck_production_plans WHERE id = :id AND tenant_id = :tenant_id AND is_deleted = false"),
        {"id": plan_id, "tenant_id": x_tenant_id},
    )
    row = plan_result.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="生产计划不存在")

    plan = _row_to_dict(row)

    # 使用 SQL 聚合直接计算原料汇总
    agg_result = await db.execute(
        text("""
            SELECT ri.ingredient_name,
                   ri.ingredient_id,
                   ri.unit,
                   SUM(pi.planned_qty / r.yield_qty * ri.qty * (1.0 + ri.loss_rate)) AS total_qty
            FROM ck_plan_items pi
            JOIN dish_recipes r ON r.id = pi.recipe_id AND r.is_deleted = false
            JOIN recipe_ingredients ri ON ri.recipe_id = r.id AND ri.is_deleted = false
            WHERE pi.plan_id = :plan_id
              AND pi.tenant_id = :tenant_id
              AND pi.is_deleted = false
              AND pi.recipe_id IS NOT NULL
              AND r.yield_qty > 0
            GROUP BY ri.ingredient_name, ri.ingredient_id, ri.unit
            ORDER BY ri.ingredient_name
        """),
        {"plan_id": plan_id, "tenant_id": x_tenant_id},
    )
    material_list = []
    for r in agg_result.fetchall():
        row_dict = _row_to_dict(r)
        row_dict["total_qty"] = round(float(row_dict["total_qty"]), 4)
        material_list.append(row_dict)

    return {
        "ok": True,
        "data": {
            "plan_id": plan_id,
            "plan_date": plan["plan_date"],
            "items": material_list,
            "total_ingredients": len(material_list),
        },
    }


# ═══════════════════════════════════════════════════════════════════════════════
# 配送调拨 — /api/v1/supply/ck/dispatch
# ═══════════════════════════════════════════════════════════════════════════════


@router.get("/api/v1/supply/ck/dispatch", summary="调拨单列表")
async def list_dispatch_orders(
    dispatch_date: Optional[str] = Query(None, alias="date", description="按日期过滤 YYYY-MM-DD"),
    to_store_id: Optional[str] = Query(None, description="按目标门店ID过滤"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """查询调拨单列表，支持按日期/目标门店过滤。"""
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": x_tenant_id},
    )
    try:
        sql = """
            SELECT * FROM ck_dispatch_orders
            WHERE tenant_id = :tenant_id AND is_deleted = false
        """
        params: dict[str, Any] = {"tenant_id": x_tenant_id}
        if dispatch_date:
            sql += " AND dispatch_date = :dispatch_date"
            params["dispatch_date"] = dispatch_date
        if to_store_id:
            sql += " AND to_store_id = :to_store_id"
            params["to_store_id"] = to_store_id
        sql += " ORDER BY dispatch_date DESC, created_at DESC"

        result = await db.execute(text(sql), params)
        orders = [_row_to_dict(r) for r in result.fetchall()]
        return {"ok": True, "data": {"items": orders, "total": len(orders)}}
    except SQLAlchemyError as exc:
        log.error("list_dispatch_orders.db_error", error=str(exc), tenant_id=x_tenant_id)
        return {"ok": True, "data": {"items": [], "total": 0}}


@router.post("/api/v1/supply/ck/dispatch", summary="创建调拨单", status_code=201)
async def create_dispatch_order(
    body: DispatchOrderIn,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """创建配送调拨单，自动生成单号 CK-YYYYMMDD-XXXX。"""
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": x_tenant_id},
    )
    try:
        order_id = _new_id()
        dispatch_no = _gen_dispatch_no(body.dispatch_date)

        await db.execute(
            text(
                "INSERT INTO ck_dispatch_orders "
                "(id, tenant_id, dispatch_no, plan_id, to_store_id, dispatch_date, "
                " status, driver_name, vehicle_no, is_deleted) "
                "VALUES (:id, :tenant_id, :dispatch_no, :plan_id, :to_store_id, :dispatch_date, "
                " 'pending', :driver_name, :vehicle_no, false)"
            ),
            {
                "id": order_id,
                "tenant_id": x_tenant_id,
                "dispatch_no": dispatch_no,
                "plan_id": body.plan_id,
                "to_store_id": body.to_store_id,
                "dispatch_date": body.dispatch_date,
                "driver_name": body.driver_name,
                "vehicle_no": body.vehicle_no,
            },
        )

        dispatch_items = []
        for item in body.items:
            item_id = _new_id()
            await db.execute(
                text(
                    "INSERT INTO ck_dispatch_items "
                    "(id, tenant_id, dispatch_id, dish_id, planned_qty, actual_qty, unit, is_deleted) "
                    "VALUES (:id, :tenant_id, :dispatch_id, :dish_id, :planned_qty, null, :unit, false)"
                ),
                {
                    "id": item_id,
                    "tenant_id": x_tenant_id,
                    "dispatch_id": order_id,
                    "dish_id": item.dish_id,
                    "planned_qty": item.planned_qty,
                    "unit": item.unit,
                },
            )
            dispatch_items.append(
                {
                    "id": item_id,
                    "tenant_id": x_tenant_id,
                    "dispatch_id": order_id,
                    "dish_id": item.dish_id,
                    "planned_qty": item.planned_qty,
                    "actual_qty": None,
                    "unit": item.unit,
                    "is_deleted": False,
                }
            )

        await db.commit()

        # 查回完整订单记录
        order_result = await db.execute(
            text("SELECT * FROM ck_dispatch_orders WHERE id = :id"),
            {"id": order_id},
        )
        order = _row_to_dict(order_result.fetchone())
        order["items"] = dispatch_items

        log.info("dispatch_order.created", order_id=order_id, dispatch_no=dispatch_no, tenant_id=x_tenant_id)
        return {"ok": True, "data": order}
    except SQLAlchemyError as exc:
        await db.rollback()
        log.error("create_dispatch_order.db_error", error=str(exc), tenant_id=x_tenant_id)
        raise HTTPException(status_code=500, detail="创建调拨单失败，请稍后重试")


@router.put("/api/v1/supply/ck/dispatch/{order_id}/receive", summary="门店确认收货")
async def receive_dispatch_order(
    order_id: str,
    body: ReceiveConfirmIn,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """门店确认收货，录入各菜品实收量，推进调拨单状态到 received。

    差异超过 5% 时自动在 item 添加差异提示。
    """
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": x_tenant_id},
    )

    order_result = await db.execute(
        text("SELECT * FROM ck_dispatch_orders WHERE id = :id AND tenant_id = :tenant_id AND is_deleted = false"),
        {"id": order_id, "tenant_id": x_tenant_id},
    )
    row = order_result.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="调拨单不存在")

    order = _row_to_dict(row)
    current = order["status"]
    allowed = _DISPATCH_STATUS_TRANSITIONS.get(current, set())
    if "received" not in allowed:
        raise HTTPException(
            status_code=400,
            detail=f"调拨单当前状态 {current} 不可确认收货（需为 dispatched 状态）",
        )

    try:
        # 更新调拨单主表状态
        await db.execute(
            text(
                "UPDATE ck_dispatch_orders "
                "SET status = 'received', receiver_name = :receiver_name, "
                "    received_at = now(), updated_at = now() "
                "WHERE id = :id AND tenant_id = :tenant_id"
            ),
            {
                "receiver_name": body.receiver_name,
                "id": order_id,
                "tenant_id": x_tenant_id,
            },
        )

        # 更新各明细实收量
        actual_map = {ri.dish_id: ri.actual_qty for ri in body.items}
        for dish_id, actual_qty in actual_map.items():
            await db.execute(
                text(
                    "UPDATE ck_dispatch_items SET actual_qty = :actual_qty "
                    "WHERE dispatch_id = :dispatch_id AND dish_id = :dish_id "
                    "AND tenant_id = :tenant_id AND is_deleted = false"
                ),
                {
                    "actual_qty": actual_qty,
                    "dispatch_id": order_id,
                    "dish_id": dish_id,
                    "tenant_id": x_tenant_id,
                },
            )

        await db.commit()
    except SQLAlchemyError as exc:
        await db.rollback()
        log.error("receive_dispatch_order.db_error", error=str(exc), order_id=order_id)
        raise HTTPException(status_code=500, detail="确认收货失败，请稍后重试")

    # 查回最新订单和明细
    updated_order_result = await db.execute(
        text("SELECT * FROM ck_dispatch_orders WHERE id = :id"),
        {"id": order_id},
    )
    updated_order = _row_to_dict(updated_order_result.fetchone())

    items_result = await db.execute(
        text("SELECT * FROM ck_dispatch_items WHERE dispatch_id = :dispatch_id AND is_deleted = false"),
        {"dispatch_id": order_id},
    )
    items = [_row_to_dict(r) for r in items_result.fetchall()]

    # 差异超过 5% 提示（写入 variance_note 字段，不持久化）
    for item in items:
        dish_id = item["dish_id"]
        if dish_id not in actual_map:
            continue
        actual = actual_map[dish_id]
        planned = float(item["planned_qty"])
        if planned > 0 and actual is not None:
            diff_pct = abs(float(actual) - planned) / planned
            if diff_pct > 0.05:
                item["variance_note"] = f"[差异提醒] 计划{planned}，实收{actual}，偏差{round(diff_pct * 100, 1)}%"

    log.info("dispatch_order.received", order_id=order_id, tenant_id=x_tenant_id)
    updated_order["items"] = items
    return {"ok": True, "data": updated_order}


@router.get("/api/v1/supply/ck/dispatch/{order_id}/print", summary="调拨单打印数据")
async def print_dispatch_order(
    order_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """返回调拨单语义标记打印数据，供 TXBridge 渲染小票。

    格式参考 TXBridge 打印协议：
      type='title'   — 居中标题
      type='divider' — 分隔线
      type='kv'      — 键值对行（key/value）
      type='table'   — 明细表格（headers/rows）
      type='barcode' — 条码（value=单号）
    """
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": x_tenant_id},
    )

    order_result = await db.execute(
        text("SELECT * FROM ck_dispatch_orders WHERE id = :id AND tenant_id = :tenant_id AND is_deleted = false"),
        {"id": order_id, "tenant_id": x_tenant_id},
    )
    row = order_result.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="调拨单不存在")

    order = _row_to_dict(row)

    items_result = await db.execute(
        text("SELECT * FROM ck_dispatch_items WHERE dispatch_id = :dispatch_id AND is_deleted = false"),
        {"dispatch_id": order_id},
    )
    items = [_row_to_dict(r) for r in items_result.fetchall()]

    print_blocks: List[Dict[str, Any]] = [
        {"type": "title", "value": "屯象OS — 调拨单"},
        {"type": "divider"},
        {"type": "kv", "key": "单号", "value": order["dispatch_no"]},
        {"type": "kv", "key": "日期", "value": order["dispatch_date"]},
        {"type": "kv", "key": "状态", "value": order["status"]},
        {"type": "kv", "key": "目标门店", "value": order["to_store_id"]},
        {"type": "kv", "key": "司机", "value": order.get("driver_name") or "-"},
        {"type": "kv", "key": "车牌号", "value": order.get("vehicle_no") or "-"},
        {"type": "divider"},
        {
            "type": "table",
            "headers": ["菜品ID", "计划数量", "实收数量", "单位"],
            "rows": [
                [
                    str(item["dish_id"])[:8] + "…",
                    str(item["planned_qty"]),
                    str(item.get("actual_qty") or "-"),
                    item["unit"],
                ]
                for item in items
            ],
        },
        {"type": "divider"},
        {"type": "barcode", "value": order["dispatch_no"]},
        {"type": "kv", "key": "收货签名", "value": "_____________"},
    ]

    return {
        "ok": True,
        "data": {
            "dispatch_no": order["dispatch_no"],
            "print_blocks": print_blocks,
        },
    }
