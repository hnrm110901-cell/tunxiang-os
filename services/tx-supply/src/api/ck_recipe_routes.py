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

import uuid
from datetime import date, datetime
from typing import Any, Dict, List, Optional

import structlog
from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel, Field

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
    "draft":       {"confirmed"},
    "confirmed":   {"in_progress"},
    "in_progress": {"done"},
    "done":        set(),
}

_DISPATCH_STATUS_TRANSITIONS: dict[str, set[str]] = {
    "pending":    {"dispatched"},
    "dispatched": {"received", "rejected"},
    "received":   set(),
    "rejected":   set(),
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


# ─── Mock 数据仓库（开发阶段）─────────────────────────────────────────────────
# TODO: 替换为真实DB查询（共享 AsyncSession，参考 ck_production_routes.py）

_RECIPES: dict[str, dict] = {}
_RECIPE_INGREDIENTS: dict[str, list[dict]] = {}
_PLANS: dict[str, dict] = {}
_PLAN_ITEMS: dict[str, list[dict]] = {}
_DISPATCH_ORDERS: dict[str, dict] = {}
_DISPATCH_ITEMS: dict[str, list[dict]] = {}


# ═══════════════════════════════════════════════════════════════════════════════
# 配方管理 — /api/v1/supply/recipes
# ═══════════════════════════════════════════════════════════════════════════════


@router.get("/api/v1/supply/recipes", summary="配方列表")
async def list_recipes(
    dish_id: Optional[str] = Query(None, description="按菜品ID过滤"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> Dict[str, Any]:
    """返回当前租户的配方列表，支持按 dish_id 过滤。

    TODO: 替换为真实DB查询
        SELECT r.*, COUNT(ri.id) AS ingredient_count
        FROM dish_recipes r
        LEFT JOIN recipe_ingredients ri ON ri.recipe_id = r.id AND ri.is_deleted = false
        WHERE r.tenant_id = :tenant_id AND r.is_deleted = false
        [AND r.dish_id = :dish_id]
        GROUP BY r.id
        ORDER BY r.created_at DESC
    """
    items = [r for r in _RECIPES.values() if r["tenant_id"] == x_tenant_id]
    if dish_id:
        items = [r for r in items if r["dish_id"] == dish_id]

    # 为每条配方附加原料数量
    result = []
    for recipe in items:
        rec = dict(recipe)
        rec["ingredient_count"] = len(_RECIPE_INGREDIENTS.get(recipe["id"], []))
        result.append(rec)

    return {"ok": True, "data": {"items": result, "total": len(result)}}


@router.post("/api/v1/supply/recipes", summary="创建配方", status_code=201)
async def create_recipe(
    body: RecipeIn,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> Dict[str, Any]:
    """创建标准配方，含原料明细列表。

    TODO: 替换为真实DB写入
        INSERT INTO dish_recipes (tenant_id, dish_id, version, yield_qty, yield_unit, notes)
        VALUES (:tenant_id, :dish_id, :version, :yield_qty, :yield_unit, :notes)
        RETURNING id;
        -- 版本号 = MAX(version)+1 WHERE tenant_id=:tid AND dish_id=:dish_id
        INSERT INTO recipe_ingredients (...) VALUES ...
    """
    recipe_id = _new_id()
    now = _now_iso()

    # 计算下一个版本号
    existing = [r for r in _RECIPES.values()
                if r["tenant_id"] == x_tenant_id and r["dish_id"] == body.dish_id]
    version = max((r["version"] for r in existing), default=0) + 1

    recipe = {
        "id": recipe_id,
        "tenant_id": x_tenant_id,
        "dish_id": body.dish_id,
        "version": version,
        "is_active": True,
        "yield_qty": body.yield_qty,
        "yield_unit": body.yield_unit,
        "notes": body.notes,
        "created_at": now,
        "updated_at": now,
        "is_deleted": False,
    }
    _RECIPES[recipe_id] = recipe

    ingredients = []
    for ing in body.ingredients:
        ing_row = {
            "id": _new_id(),
            "tenant_id": x_tenant_id,
            "recipe_id": recipe_id,
            "ingredient_name": ing.ingredient_name,
            "ingredient_id": ing.ingredient_id,
            "qty": ing.qty,
            "unit": ing.unit,
            "loss_rate": ing.loss_rate,
            "is_deleted": False,
        }
        ingredients.append(ing_row)
    _RECIPE_INGREDIENTS[recipe_id] = ingredients

    log.info("recipe.created", recipe_id=recipe_id, tenant_id=x_tenant_id)
    result = dict(recipe)
    result["ingredients"] = ingredients
    return {"ok": True, "data": result}


@router.get("/api/v1/supply/recipes/{recipe_id}", summary="配方详情（含原料）")
async def get_recipe(
    recipe_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> Dict[str, Any]:
    """查询单条配方详情，含原料明细列表。

    TODO: 替换为真实DB查询
        SELECT * FROM dish_recipes WHERE id=:id AND tenant_id=:tid AND is_deleted=false;
        SELECT * FROM recipe_ingredients WHERE recipe_id=:id AND is_deleted=false;
    """
    recipe = _RECIPES.get(recipe_id)
    if not recipe or recipe["tenant_id"] != x_tenant_id or recipe["is_deleted"]:
        raise HTTPException(status_code=404, detail="配方不存在")

    result = dict(recipe)
    result["ingredients"] = _RECIPE_INGREDIENTS.get(recipe_id, [])
    return {"ok": True, "data": result}


@router.put("/api/v1/supply/recipes/{recipe_id}", summary="更新配方")
async def update_recipe(
    recipe_id: str,
    body: RecipeUpdateIn,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> Dict[str, Any]:
    """更新配方基本信息及原料明细。

    TODO: 替换为真实DB更新
        UPDATE dish_recipes SET yield_qty=:yq, ... WHERE id=:id AND tenant_id=:tid;
        -- 若 ingredients 非 None：先软删除旧明细，再批量插入新明细
    """
    recipe = _RECIPES.get(recipe_id)
    if not recipe or recipe["tenant_id"] != x_tenant_id or recipe["is_deleted"]:
        raise HTTPException(status_code=404, detail="配方不存在")

    if body.yield_qty is not None:
        recipe["yield_qty"] = body.yield_qty
    if body.yield_unit is not None:
        recipe["yield_unit"] = body.yield_unit
    if body.notes is not None:
        recipe["notes"] = body.notes
    if body.is_active is not None:
        recipe["is_active"] = body.is_active
    recipe["updated_at"] = _now_iso()

    if body.ingredients is not None:
        # 替换原料明细
        ingredients = []
        for ing in body.ingredients:
            ing_row = {
                "id": _new_id(),
                "tenant_id": x_tenant_id,
                "recipe_id": recipe_id,
                "ingredient_name": ing.ingredient_name,
                "ingredient_id": ing.ingredient_id,
                "qty": ing.qty,
                "unit": ing.unit,
                "loss_rate": ing.loss_rate,
                "is_deleted": False,
            }
            ingredients.append(ing_row)
        _RECIPE_INGREDIENTS[recipe_id] = ingredients

    result = dict(recipe)
    result["ingredients"] = _RECIPE_INGREDIENTS.get(recipe_id, [])
    return {"ok": True, "data": result}


@router.post("/api/v1/supply/recipes/{recipe_id}/calculate", summary="按产量计算原料用量")
async def calculate_recipe(
    recipe_id: str,
    body: RecipeCalculateIn,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> Dict[str, Any]:
    """按目标产量计算各原料实际需求量。

    公式：actual_qty = (target_qty / yield_qty) × ing.qty × (1 + loss_rate)

    TODO: 替换为真实DB查询配方和原料明细
    """
    recipe = _RECIPES.get(recipe_id)
    if not recipe or recipe["tenant_id"] != x_tenant_id or recipe["is_deleted"]:
        raise HTTPException(status_code=404, detail="配方不存在")

    ingredients = _RECIPE_INGREDIENTS.get(recipe_id, [])
    yield_qty: float = recipe["yield_qty"]
    if yield_qty <= 0:
        raise HTTPException(status_code=400, detail="配方 yield_qty 无效（必须>0）")

    scale = body.target_qty / yield_qty
    calculated = []
    for ing in ingredients:
        if ing.get("is_deleted"):
            continue
        actual_qty = round(scale * ing["qty"] * (1.0 + ing["loss_rate"]), 4)
        calculated.append({
            "ingredient_name": ing["ingredient_name"],
            "ingredient_id": ing["ingredient_id"],
            "unit": ing["unit"],
            "standard_qty": ing["qty"],
            "loss_rate": ing["loss_rate"],
            "calculated_qty": actual_qty,
        })

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
) -> Dict[str, Any]:
    """查询生产计划列表，支持按日期/状态过滤。

    TODO: 替换为真实DB查询
        SELECT p.*, COUNT(pi.id) AS item_count
        FROM ck_production_plans p
        LEFT JOIN ck_plan_items pi ON pi.plan_id=p.id AND pi.is_deleted=false
        WHERE p.tenant_id=:tid AND p.is_deleted=false
        [AND p.plan_date=:plan_date] [AND p.status=:status]
        GROUP BY p.id
        ORDER BY p.plan_date DESC, p.created_at DESC
    """
    plans = [p for p in _PLANS.values() if p["tenant_id"] == x_tenant_id]
    if plan_date:
        plans = [p for p in plans if p["plan_date"] == plan_date]
    if status:
        plans = [p for p in plans if p["status"] == status]

    result = []
    for plan in plans:
        rec = dict(plan)
        rec["item_count"] = len(_PLAN_ITEMS.get(plan["id"], []))
        result.append(rec)

    return {"ok": True, "data": {"items": result, "total": len(result)}}


@router.post("/api/v1/supply/ck/plans", summary="创建生产计划", status_code=201)
async def create_production_plan(
    body: ProductionPlanIn,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> Dict[str, Any]:
    """创建生产计划，并从配方自动展开原料需求（写入计划明细）。

    TODO: 替换为真实DB写入
        INSERT INTO ck_production_plans (...) RETURNING id;
        -- 对每个 item.dish_id 查询激活配方：
        SELECT * FROM dish_recipes WHERE tenant_id=:tid AND dish_id=:dish_id
          AND is_active=true AND is_deleted=false LIMIT 1;
        INSERT INTO ck_plan_items (tenant_id, plan_id, dish_id, recipe_id, planned_qty, unit) ...
    """
    plan_id = _new_id()
    now = _now_iso()

    plan = {
        "id": plan_id,
        "tenant_id": x_tenant_id,
        "plan_date": body.plan_date,
        "status": "draft",
        "store_id": body.store_id,
        "created_by": body.created_by,
        "notes": body.notes,
        "created_at": now,
        "updated_at": now,
        "is_deleted": False,
    }
    _PLANS[plan_id] = plan

    plan_items = []
    for item in body.items:
        # 自动关联激活配方
        # TODO: 真实DB中查询 dish_recipes WHERE dish_id=:dish_id AND is_active=true
        recipe_id = item.recipe_id
        if not recipe_id:
            # 从 mock 数据中查激活配方
            active = next(
                (r for r in _RECIPES.values()
                 if r["tenant_id"] == x_tenant_id
                 and r["dish_id"] == item.dish_id
                 and r["is_active"]),
                None,
            )
            if active:
                recipe_id = active["id"]

        plan_item = {
            "id": _new_id(),
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
        plan_items.append(plan_item)
    _PLAN_ITEMS[plan_id] = plan_items

    log.info("production_plan.created", plan_id=plan_id, tenant_id=x_tenant_id)
    result = dict(plan)
    result["items"] = plan_items
    return {"ok": True, "data": result}


@router.put("/api/v1/supply/ck/plans/{plan_id}/status", summary="推进计划状态")
async def update_plan_status(
    plan_id: str,
    body: PlanStatusIn,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> Dict[str, Any]:
    """推进生产计划状态：draft→confirmed→in_progress→done。

    TODO: 替换为真实DB更新
        SELECT status FROM ck_production_plans WHERE id=:id AND tenant_id=:tid;
        UPDATE ck_production_plans SET status=:status WHERE id=:id AND tenant_id=:tid;
    """
    plan = _PLANS.get(plan_id)
    if not plan or plan["tenant_id"] != x_tenant_id or plan["is_deleted"]:
        raise HTTPException(status_code=404, detail="生产计划不存在")

    current = plan["status"]
    target = body.status
    allowed = _PLAN_STATUS_TRANSITIONS.get(current, set())
    if target not in allowed:
        raise HTTPException(
            status_code=400,
            detail=f"状态不可从 {current} 转移到 {target}（允许：{sorted(allowed)}）",
        )

    plan["status"] = target
    plan["updated_at"] = _now_iso()
    log.info("production_plan.status_updated", plan_id=plan_id, from_=current, to=target)

    result = dict(plan)
    result["items"] = _PLAN_ITEMS.get(plan_id, [])
    return {"ok": True, "data": result}


@router.get("/api/v1/supply/ck/plans/{plan_id}/material-list", summary="原料汇总清单")
async def get_material_list(
    plan_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> Dict[str, Any]:
    """计算当前生产计划所需原料汇总清单（按 ingredient_name+unit 合并同类项）。

    算法：
      对每个 plan_item：
        scale = planned_qty / recipe.yield_qty
        actual_qty_per_ing = scale × ing.qty × (1 + loss_rate)
      按 ingredient_name + unit 分组汇总

    TODO: 替换为真实DB查询
        SELECT ri.ingredient_name, ri.ingredient_id, ri.unit,
               SUM(pi.planned_qty / r.yield_qty * ri.qty * (1 + ri.loss_rate)) AS total_qty
        FROM ck_plan_items pi
        JOIN dish_recipes r ON r.id = pi.recipe_id
        JOIN recipe_ingredients ri ON ri.recipe_id = r.id AND ri.is_deleted=false
        WHERE pi.plan_id=:plan_id AND pi.tenant_id=:tid AND pi.is_deleted=false
        GROUP BY ri.ingredient_name, ri.ingredient_id, ri.unit
        ORDER BY ri.ingredient_name
    """
    plan = _PLANS.get(plan_id)
    if not plan or plan["tenant_id"] != x_tenant_id or plan["is_deleted"]:
        raise HTTPException(status_code=404, detail="生产计划不存在")

    plan_items = _PLAN_ITEMS.get(plan_id, [])
    aggregated: dict[tuple, dict] = {}

    for pi in plan_items:
        if pi.get("is_deleted") or not pi.get("recipe_id"):
            continue
        recipe = _RECIPES.get(pi["recipe_id"])
        if not recipe:
            continue
        yield_qty: float = recipe["yield_qty"]
        if yield_qty <= 0:
            continue
        scale = pi["planned_qty"] / yield_qty

        for ing in _RECIPE_INGREDIENTS.get(pi["recipe_id"], []):
            if ing.get("is_deleted"):
                continue
            key = (ing["ingredient_name"], ing["unit"])
            actual = scale * ing["qty"] * (1.0 + ing["loss_rate"])
            if key not in aggregated:
                aggregated[key] = {
                    "ingredient_name": ing["ingredient_name"],
                    "ingredient_id": ing.get("ingredient_id"),
                    "unit": ing["unit"],
                    "total_qty": 0.0,
                }
            aggregated[key]["total_qty"] = round(aggregated[key]["total_qty"] + actual, 4)

    material_list = sorted(aggregated.values(), key=lambda x: x["ingredient_name"])
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
) -> Dict[str, Any]:
    """查询调拨单列表，支持按日期/目标门店过滤。

    TODO: 替换为真实DB查询
        SELECT * FROM ck_dispatch_orders
        WHERE tenant_id=:tid AND is_deleted=false
        [AND dispatch_date=:date] [AND to_store_id=:to_store_id]
        ORDER BY dispatch_date DESC, created_at DESC
    """
    orders = [o for o in _DISPATCH_ORDERS.values() if o["tenant_id"] == x_tenant_id]
    if dispatch_date:
        orders = [o for o in orders if o["dispatch_date"] == dispatch_date]
    if to_store_id:
        orders = [o for o in orders if o["to_store_id"] == to_store_id]

    return {"ok": True, "data": {"items": orders, "total": len(orders)}}


@router.post("/api/v1/supply/ck/dispatch", summary="创建调拨单", status_code=201)
async def create_dispatch_order(
    body: DispatchOrderIn,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> Dict[str, Any]:
    """创建配送调拨单，自动生成单号 CK-YYYYMMDD-XXXX。

    TODO: 替换为真实DB写入
        INSERT INTO ck_dispatch_orders (tenant_id, dispatch_no, plan_id, to_store_id,
          dispatch_date, driver_name, vehicle_no, status)
        VALUES (...) RETURNING id;
        INSERT INTO ck_dispatch_items (...) VALUES ...
    """
    order_id = _new_id()
    now = _now_iso()
    dispatch_no = _gen_dispatch_no(body.dispatch_date)

    order = {
        "id": order_id,
        "tenant_id": x_tenant_id,
        "dispatch_no": dispatch_no,
        "plan_id": body.plan_id,
        "from_store_id": None,
        "to_store_id": body.to_store_id,
        "dispatch_date": body.dispatch_date,
        "status": "pending",
        "driver_name": body.driver_name,
        "vehicle_no": body.vehicle_no,
        "receiver_name": None,
        "received_at": None,
        "notes": None,
        "created_at": now,
        "updated_at": now,
        "is_deleted": False,
    }
    _DISPATCH_ORDERS[order_id] = order

    dispatch_items = []
    for item in body.items:
        di = {
            "id": _new_id(),
            "tenant_id": x_tenant_id,
            "dispatch_order_id": order_id,
            "dish_id": item.dish_id,
            "planned_qty": item.planned_qty,
            "actual_qty": None,
            "unit": item.unit,
            "is_deleted": False,
        }
        dispatch_items.append(di)
    _DISPATCH_ITEMS[order_id] = dispatch_items

    log.info("dispatch_order.created", order_id=order_id,
             dispatch_no=dispatch_no, tenant_id=x_tenant_id)
    result = dict(order)
    result["items"] = dispatch_items
    return {"ok": True, "data": result}


@router.put("/api/v1/supply/ck/dispatch/{order_id}/receive", summary="门店确认收货")
async def receive_dispatch_order(
    order_id: str,
    body: ReceiveConfirmIn,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> Dict[str, Any]:
    """门店确认收货，录入各菜品实收量，推进调拨单状态到 received。

    差异超过 5% 时自动在 item 添加差异提示。

    TODO: 替换为真实DB更新
        UPDATE ck_dispatch_orders SET status='received', receiver_name=:name,
          received_at=now() WHERE id=:id AND tenant_id=:tid;
        UPDATE ck_dispatch_items SET actual_qty=:qty WHERE dispatch_order_id=:id
          AND dish_id=:dish_id AND tenant_id=:tid;
    """
    order = _DISPATCH_ORDERS.get(order_id)
    if not order or order["tenant_id"] != x_tenant_id or order["is_deleted"]:
        raise HTTPException(status_code=404, detail="调拨单不存在")

    current = order["status"]
    allowed = _DISPATCH_STATUS_TRANSITIONS.get(current, set())
    if "received" not in allowed:
        raise HTTPException(
            status_code=400,
            detail=f"调拨单当前状态 {current} 不可确认收货（需为 dispatched 状态）",
        )

    items = _DISPATCH_ITEMS.get(order_id, [])
    actual_map = {ri.dish_id: ri.actual_qty for ri in body.items}

    for item in items:
        if item.get("is_deleted"):
            continue
        dish_id = item["dish_id"]
        if dish_id not in actual_map:
            continue
        actual = actual_map[dish_id]
        item["actual_qty"] = actual

        # 差异超过 5% 提示（写入 notes 字段）
        planned = item["planned_qty"]
        if planned > 0:
            diff_pct = abs(actual - planned) / planned
            if diff_pct > 0.05:
                item["variance_note"] = (
                    f"[差异提醒] 计划{planned}，实收{actual}，"
                    f"偏差{round(diff_pct * 100, 1)}%"
                )

    order["status"] = "received"
    order["receiver_name"] = body.receiver_name
    order["received_at"] = _now_iso()
    order["updated_at"] = _now_iso()

    log.info("dispatch_order.received", order_id=order_id, tenant_id=x_tenant_id)
    result = dict(order)
    result["items"] = items
    return {"ok": True, "data": result}


@router.get("/api/v1/supply/ck/dispatch/{order_id}/print", summary="调拨单打印数据")
async def print_dispatch_order(
    order_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> Dict[str, Any]:
    """返回调拨单语义标记打印数据，供 TXBridge 渲染小票。

    格式参考 TXBridge 打印协议：
      type='title'   — 居中标题
      type='divider' — 分隔线
      type='kv'      — 键值对行（key/value）
      type='table'   — 明细表格（headers/rows）
      type='barcode' — 条码（value=单号）

    TODO: 替换为真实DB查询，并关联菜品名称
    """
    order = _DISPATCH_ORDERS.get(order_id)
    if not order or order["tenant_id"] != x_tenant_id or order["is_deleted"]:
        raise HTTPException(status_code=404, detail="调拨单不存在")

    items = _DISPATCH_ITEMS.get(order_id, [])

    print_blocks: List[Dict[str, Any]] = [
        {"type": "title",   "value": "屯象OS — 调拨单"},
        {"type": "divider"},
        {"type": "kv",      "key": "单号",   "value": order["dispatch_no"]},
        {"type": "kv",      "key": "日期",   "value": order["dispatch_date"]},
        {"type": "kv",      "key": "状态",   "value": order["status"]},
        {"type": "kv",      "key": "目标门店", "value": order["to_store_id"]},
        {"type": "kv",      "key": "司机",   "value": order.get("driver_name") or "-"},
        {"type": "kv",      "key": "车牌号", "value": order.get("vehicle_no") or "-"},
        {"type": "divider"},
        {
            "type": "table",
            "headers": ["菜品ID", "计划数量", "实收数量", "单位"],
            "rows": [
                [
                    item["dish_id"][:8] + "…",  # TODO: 替换为菜品名称
                    str(item["planned_qty"]),
                    str(item.get("actual_qty") or "-"),
                    item["unit"],
                ]
                for item in items if not item.get("is_deleted")
            ],
        },
        {"type": "divider"},
        {"type": "barcode", "value": order["dispatch_no"]},
        {"type": "kv",      "key": "收货签名", "value": "_____________"},
    ]

    return {
        "ok": True,
        "data": {
            "dispatch_no": order["dispatch_no"],
            "print_blocks": print_blocks,
        },
    }
