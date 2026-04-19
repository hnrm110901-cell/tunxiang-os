"""套餐组合 API — 8个端点

基础端点（原有）：
- GET  /api/v1/menu/combos                              列出套餐
- POST /api/v1/menu/combos                              创建套餐
- POST /api/v1/menu/combos/{combo_id}/order             点套餐→自动展开为多条 OrderItem

N选M分组管理（新增）：
- GET  /api/v1/menu/combos/{combo_id}/groups                        获取套餐分组列表（含菜品）
- POST /api/v1/menu/combos/{combo_id}/groups                        创建分组
- POST /api/v1/menu/combos/{combo_id}/groups/{group_id}/items       添加菜品到分组
- DELETE /api/v1/menu/combos/{combo_id}/groups/{group_id}/items/{item_id}  从分组移除菜品
- POST /api/v1/menu/combos/{combo_id}/validate-selection            验证顾客选择是否满足规则
"""

import uuid
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db
from shared.ontology.src.entities import Dish, Order, OrderItem
from shared.ontology.src.enums import OrderStatus

from ..models.dish_combo import DishCombo

logger = structlog.get_logger()
router = APIRouter(prefix="/api/v1/menu", tags=["combo"])


def _get_tenant_id(request: Request) -> str:
    tid = getattr(request.state, "tenant_id", None) or request.headers.get("X-Tenant-ID", "")
    if not tid:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header required")
    return tid


def _ok(data: dict | list) -> dict:
    return {"ok": True, "data": data, "error": None}


# ─── 请求模型 ───


class ComboItemReq(BaseModel):
    dish_id: str
    dish_name: str
    qty: int = Field(default=1, ge=1)
    price_fen: int = Field(ge=0, description="子项售价(分)")


class CreateComboReq(BaseModel):
    store_id: Optional[str] = None
    combo_name: str
    combo_price_fen: int = Field(ge=0)
    original_price_fen: int = Field(ge=0)
    items: list[ComboItemReq]
    description: Optional[str] = None
    image_url: Optional[str] = None
    is_active: bool = True


class OrderComboReq(BaseModel):
    order_id: str
    qty: int = Field(default=1, ge=1, description="套餐份数")
    notes: Optional[str] = None


# ─── 端点 ───


@router.get("/combos")
async def list_combos(
    request: Request,
    store_id: Optional[str] = Query(default=None),
    is_active: bool = Query(default=True),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """列出套餐 — 支持按门店和上架状态过滤"""
    tenant_id = _get_tenant_id(request)
    tenant_uuid = uuid.UUID(tenant_id)

    conditions = [
        DishCombo.tenant_id == tenant_uuid,
        DishCombo.is_deleted == False,  # noqa: E712
        DishCombo.is_active == is_active,
    ]
    if store_id:
        conditions.append(DishCombo.store_id == uuid.UUID(store_id))

    result = await db.execute(
        select(DishCombo).where(*conditions).order_by(DishCombo.created_at.desc()).offset((page - 1) * size).limit(size)
    )
    combos = result.scalars().all()

    items = [
        {
            "id": str(c.id),
            "store_id": str(c.store_id) if c.store_id else None,
            "combo_name": c.combo_name,
            "combo_price_fen": c.combo_price_fen,
            "original_price_fen": c.original_price_fen,
            "items": c.items_json,
            "description": c.description,
            "image_url": c.image_url,
            "is_active": c.is_active,
            "saving_fen": c.original_price_fen - c.combo_price_fen,
        }
        for c in combos
    ]

    return _ok({"items": items, "total": len(items), "page": page, "size": size})


@router.post("/combos")
async def create_combo(
    req: CreateComboReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """创建套餐"""
    tenant_id = _get_tenant_id(request)
    tenant_uuid = uuid.UUID(tenant_id)

    items_json = [
        {
            "dish_id": item.dish_id,
            "dish_name": item.dish_name,
            "qty": item.qty,
            "price_fen": item.price_fen,
        }
        for item in req.items
    ]

    combo = DishCombo(
        id=uuid.uuid4(),
        tenant_id=tenant_uuid,
        store_id=uuid.UUID(req.store_id) if req.store_id else None,
        combo_name=req.combo_name,
        combo_price_fen=req.combo_price_fen,
        original_price_fen=req.original_price_fen,
        items_json=items_json,
        description=req.description,
        image_url=req.image_url,
        is_active=req.is_active,
    )
    db.add(combo)
    await db.commit()

    logger.info(
        "combo_created",
        combo_id=str(combo.id),
        combo_name=req.combo_name,
        items_count=len(items_json),
    )

    return _ok(
        {
            "combo_id": str(combo.id),
            "combo_name": req.combo_name,
            "combo_price_fen": req.combo_price_fen,
            "original_price_fen": req.original_price_fen,
            "saving_fen": req.original_price_fen - req.combo_price_fen,
            "items_count": len(items_json),
        }
    )


@router.get("/combos/{combo_id}/detail")
async def get_combo_detail(
    combo_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """获取套餐N选M完整结构（含分组和可选菜品）

    查询 combo_groups + combo_group_items 表，graceful 降级：
    若表不存在或查询失败，返回空分组列表并记录 warning。
    """
    tenant_id = _get_tenant_id(request)
    tenant_uuid = uuid.UUID(tenant_id)

    # 查套餐基本信息
    result = await db.execute(
        select(DishCombo).where(
            DishCombo.id == uuid.UUID(combo_id),
            DishCombo.tenant_id == tenant_uuid,
            DishCombo.is_deleted == False,  # noqa: E712
        )
    )
    combo = result.scalar_one_or_none()
    if not combo:
        raise HTTPException(status_code=404, detail="套餐不存在")

    # 查询 combo_groups + combo_group_items（v113 已建表）
    # graceful 降级：若表不存在则返回空分组列表并记录 warning
    try:
        groups_result = await db.execute(
            text("""
                SELECT
                    cg.id::TEXT         AS group_id,
                    cg.group_name,
                    cg.min_select,
                    cg.max_select,
                    cg.is_required,
                    cg.sort_order       AS group_sort_order,
                    cgi.id::TEXT        AS item_id,
                    cgi.dish_id::TEXT   AS dish_id,
                    cgi.dish_name,
                    cgi.extra_price_fen,
                    cgi.is_default,
                    cgi.sort_order      AS item_sort_order
                FROM combo_groups cg
                LEFT JOIN combo_group_items cgi
                    ON cgi.group_id = cg.id
                    AND cgi.is_deleted = false
                WHERE cg.combo_id = :combo_id
                  AND cg.tenant_id = :tenant_id
                  AND cg.is_deleted = false
                ORDER BY cg.sort_order ASC, cgi.sort_order ASC
            """),
            {"combo_id": uuid.UUID(combo_id), "tenant_id": tenant_uuid},
        )
        rows = list(groups_result.mappings())

        # 合并分组行 → {group_id: {meta, items: []}}
        groups_map: dict = {}
        for row in rows:
            gid = row["group_id"]
            if gid not in groups_map:
                groups_map[gid] = {
                    "group_id": gid,
                    "group_name": row["group_name"],
                    "min_select": row["min_select"],
                    "max_select": row["max_select"],
                    "is_required": row["is_required"],
                    "items": [],
                }
            if row["item_id"]:
                groups_map[gid]["items"].append(
                    {
                        "item_id": row["item_id"],
                        "dish_id": row["dish_id"],
                        "dish_name": row["dish_name"],
                        "extra_price_fen": row["extra_price_fen"] or 0,
                        "is_default": row["is_default"] or False,
                        "image_url": None,
                        "sold_out": False,
                    }
                )
        groups = list(groups_map.values())
    except SQLAlchemyError as exc:
        logger.warning(
            "combo_groups_db_error_graceful_fallback",
            combo_id=combo_id,
            error=str(exc),
        )
        groups = []

    return _ok(
        {
            "combo_id": str(combo.id),
            "combo_name": combo.combo_name,
            "price_fen": combo.combo_price_fen,
            "description": getattr(combo, "description", None) or "",
            "min_person": getattr(combo, "min_person", None),
            "image_url": getattr(combo, "image_url", None),
            "groups": groups,
        }
    )


@router.post("/combos/{combo_id}/order")
async def order_combo(
    combo_id: str,
    req: OrderComboReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """点套餐 → 自动展开为多条 OrderItem

    每个子菜品按比例分摊套餐价，保留 combo_id 关联。
    """
    tenant_id = _get_tenant_id(request)
    tenant_uuid = uuid.UUID(tenant_id)
    combo_uuid = uuid.UUID(combo_id)
    order_uuid = uuid.UUID(req.order_id)

    # 查套餐
    result = await db.execute(
        select(DishCombo).where(
            DishCombo.id == combo_uuid,
            DishCombo.tenant_id == tenant_uuid,
            DishCombo.is_active == True,  # noqa: E712
        )
    )
    combo = result.scalar_one_or_none()
    if not combo:
        raise HTTPException(status_code=404, detail="套餐不存在或已下架")

    # 查订单
    order_result = await db.execute(
        select(Order).where(
            Order.id == order_uuid,
            Order.tenant_id == tenant_uuid,
        )
    )
    order = order_result.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="订单不存在")
    if order.status in (OrderStatus.completed.value, OrderStatus.cancelled.value):
        raise HTTPException(status_code=400, detail=f"订单状态 {order.status}，无法加菜")

    # 按比例分摊套餐价到各子项
    combo_items: list[dict] = combo.items_json or []
    original_total = combo.original_price_fen
    combo_total = combo.combo_price_fen

    created_items = []
    total_subtotal = 0

    for idx, ci in enumerate(combo_items):
        ci_price = ci.get("price_fen", 0)
        ci_qty = ci.get("qty", 1) * req.qty

        # 按原价占比分摊套餐价；最后一项用减法兜底，避免分钱误差
        if idx < len(combo_items) - 1 and original_total > 0:
            allocated_unit = round(combo_total * ci_price / original_total)
        elif idx == len(combo_items) - 1:
            # 最后一项 = 套餐总价 - 已分配
            allocated_unit = combo_total * req.qty - total_subtotal
            # 修正为单价
            allocated_unit = allocated_unit // ci_qty if ci_qty > 0 else allocated_unit
        else:
            allocated_unit = ci_price

        subtotal = allocated_unit * ci_qty
        total_subtotal += subtotal

        dish_uuid = uuid.UUID(ci["dish_id"]) if ci.get("dish_id") else None

        # 查菜品获取 BOM 成本
        food_cost_fen = None
        gross_margin = None
        if dish_uuid:
            dish_result = await db.execute(select(Dish).where(Dish.id == dish_uuid))
            dish = dish_result.scalar_one_or_none()
            if dish and dish.cost_fen:
                food_cost_fen = dish.cost_fen * ci_qty
                if subtotal > 0:
                    gross_margin = round((subtotal - food_cost_fen) / subtotal, 4)

        item = OrderItem(
            id=uuid.uuid4(),
            tenant_id=tenant_uuid,
            order_id=order_uuid,
            dish_id=dish_uuid,
            item_name=ci.get("dish_name", "套餐子项"),
            quantity=ci_qty,
            unit_price_fen=allocated_unit,
            subtotal_fen=subtotal,
            food_cost_fen=food_cost_fen,
            gross_margin=gross_margin,
            notes=req.notes or f"套餐[{combo.combo_name}]",
            customizations={"combo_id": combo_id, "combo_name": combo.combo_name},
            pricing_mode="fixed",
        )
        db.add(item)
        created_items.append(
            {
                "item_id": str(item.id),
                "dish_name": ci.get("dish_name"),
                "qty": ci_qty,
                "unit_price_fen": allocated_unit,
                "subtotal_fen": subtotal,
            }
        )

    # 更新订单总额
    combo_subtotal = combo.combo_price_fen * req.qty
    order.total_amount_fen += combo_subtotal
    order.final_amount_fen = order.total_amount_fen - order.discount_amount_fen
    if order.status == OrderStatus.pending.value:
        order.status = OrderStatus.confirmed.value

    await db.commit()

    logger.info(
        "combo_ordered",
        combo_id=combo_id,
        order_id=req.order_id,
        qty=req.qty,
        items_expanded=len(created_items),
        combo_subtotal_fen=combo_subtotal,
    )

    return _ok(
        {
            "combo_id": combo_id,
            "combo_name": combo.combo_name,
            "qty": req.qty,
            "combo_subtotal_fen": combo_subtotal,
            "items_expanded": created_items,
            "order_total_fen": order.total_amount_fen,
            "order_final_fen": order.final_amount_fen,
        }
    )


# ═══════════════════════════════════════════════════════════════════════════════
# 套餐N选M分组管理 — combo_groups / combo_group_items（v113 创建）
# ═══════════════════════════════════════════════════════════════════════════════

# combo_groups 表：
#   id, tenant_id, combo_id, group_name, min_select, max_select,
#   is_required, sort_order, created_at, updated_at, is_deleted
#
# combo_group_items 表：
#   id, tenant_id, group_id, dish_id, dish_name(冗余), quantity,
#   extra_price_fen, is_default, sort_order, created_at, updated_at, is_deleted


async def _rls_menu(db: AsyncSession, tid: str) -> None:
    await db.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": tid})


def _row_to_group(row) -> dict:
    return {
        "id": str(row.id),
        "combo_id": str(row.combo_id),
        "group_name": row.group_name,
        "min_select": row.min_select,
        "max_select": row.max_select,
        "is_required": row.is_required,
        "sort_order": row.sort_order,
    }


def _row_to_group_item(row) -> dict:
    return {
        "id": str(row.id),
        "group_id": str(row.group_id),
        "dish_id": str(row.dish_id) if row.dish_id else None,
        "dish_name": row.dish_name,
        "quantity": row.quantity,
        "extra_price_fen": row.extra_price_fen,
        "is_default": row.is_default,
        "sort_order": row.sort_order,
    }


# ─── 请求模型（N选M） ──────────────────────────────────────────────────────────


class CreateGroupReq(BaseModel):
    group_name: str = Field(..., description="分组名称，如「主食选一款」")
    min_select: int = Field(default=1, ge=0, description="最少选N个")
    max_select: int = Field(default=1, ge=1, description="最多选M个")
    is_required: bool = Field(default=True, description="是否必选")
    sort_order: int = Field(default=0, description="显示排序")


class AddGroupItemReq(BaseModel):
    dish_id: str = Field(..., description="菜品ID")
    dish_name: str = Field(..., description="菜品名称（冗余，避免联表）")
    quantity: int = Field(default=1, ge=1, description="该选项的菜品数量")
    extra_price_fen: int = Field(default=0, ge=0, description="额外加价（分），0=不加价")
    is_default: bool = Field(default=False, description="是否默认选中")
    sort_order: int = Field(default=0, description="显示排序")


class SelectionGroupReq(BaseModel):
    group_id: str
    item_ids: list[str] = Field(..., description="用户选择的 combo_group_items.id 列表")


class ValidateSelectionReq(BaseModel):
    selections: list[SelectionGroupReq]


# ─── GET /combos/{combo_id}/groups ────────────────────────────────────────────


@router.get("/combos/{combo_id}/groups", summary="获取套餐N选M分组列表（含每组可选菜品）")
async def list_combo_groups(
    combo_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """返回该套餐的所有分组，每个分组内嵌可选菜品列表。"""
    tenant_id = _get_tenant_id(request)
    await _rls_menu(db, tenant_id)

    # 校验套餐存在
    combo_check = await db.execute(
        select(DishCombo).where(
            DishCombo.id == uuid.UUID(combo_id),
            DishCombo.tenant_id == uuid.UUID(tenant_id),
            DishCombo.is_deleted == False,  # noqa: E712
        )
    )
    combo = combo_check.scalar_one_or_none()
    if not combo:
        raise HTTPException(status_code=404, detail="套餐不存在")

    # 查分组
    groups_sql = text("""
        SELECT id, combo_id, group_name, min_select, max_select,
               is_required, sort_order
        FROM combo_groups
        WHERE combo_id   = :combo_id
          AND tenant_id  = :tenant_id
          AND is_deleted = false
        ORDER BY sort_order ASC, created_at ASC
    """)
    groups_result = await db.execute(
        groups_sql,
        {
            "combo_id": combo_id,
            "tenant_id": tenant_id,
        },
    )
    group_rows = groups_result.fetchall()

    if not group_rows:
        return _ok({"combo_id": combo_id, "groups": []})

    group_ids = [str(r.id) for r in group_rows]
    gid_params = {f"gid_{i}": gid for i, gid in enumerate(group_ids)}
    id_placeholders = ", ".join([f":gid_{i}" for i in range(len(group_ids))])

    # 查所有分组的菜品（一次查询）
    items_sql = text(f"""
        SELECT id, group_id, dish_id, dish_name, quantity,
               extra_price_fen, is_default, sort_order
        FROM combo_group_items
        WHERE group_id   IN ({id_placeholders})
          AND tenant_id  = :tenant_id
          AND is_deleted = false
        ORDER BY sort_order ASC, created_at ASC
    """)
    items_result = await db.execute(items_sql, {"tenant_id": tenant_id, **gid_params})
    item_rows = items_result.fetchall()

    # 按 group_id 分组
    items_by_group: dict[str, list] = {}
    for item_row in item_rows:
        gid = str(item_row.group_id)
        items_by_group.setdefault(gid, []).append(_row_to_group_item(item_row))

    groups_out = []
    for g in group_rows:
        g_dict = _row_to_group(g)
        g_dict["items"] = items_by_group.get(str(g.id), [])
        groups_out.append(g_dict)

    return _ok(
        {
            "combo_id": combo_id,
            "combo_name": combo.combo_name,
            "groups": groups_out,
            "total_groups": len(groups_out),
        }
    )


# ─── POST /combos/{combo_id}/groups ───────────────────────────────────────────


@router.post("/combos/{combo_id}/groups", summary="创建套餐N选M分组")
async def create_combo_group(
    combo_id: str,
    req: CreateGroupReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    tenant_id = _get_tenant_id(request)
    await _rls_menu(db, tenant_id)

    # 校验套餐存在
    combo_check = await db.execute(
        select(DishCombo).where(
            DishCombo.id == uuid.UUID(combo_id),
            DishCombo.tenant_id == uuid.UUID(tenant_id),
            DishCombo.is_deleted == False,  # noqa: E712
        )
    )
    if not combo_check.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="套餐不存在")

    if req.max_select < req.min_select:
        raise HTTPException(status_code=422, detail="max_select 不能小于 min_select")

    new_id = str(uuid.uuid4())
    insert_sql = text("""
        INSERT INTO combo_groups
          (id, tenant_id, combo_id, group_name, min_select, max_select,
           is_required, sort_order, created_at, updated_at, is_deleted)
        VALUES
          (:id, :tenant_id, :combo_id, :group_name, :min_select, :max_select,
           :is_required, :sort_order, NOW(), NOW(), false)
        RETURNING id, combo_id, group_name, min_select, max_select,
                  is_required, sort_order
    """)
    result = await db.execute(
        insert_sql,
        {
            "id": new_id,
            "tenant_id": tenant_id,
            "combo_id": combo_id,
            "group_name": req.group_name,
            "min_select": req.min_select,
            "max_select": req.max_select,
            "is_required": req.is_required,
            "sort_order": req.sort_order,
        },
    )
    row = result.fetchone()
    await db.commit()

    logger.info("combo_group_created", combo_id=combo_id, group_id=new_id, group_name=req.group_name)
    group_dict = _row_to_group(row)
    group_dict["items"] = []
    return _ok({"group": group_dict})


# ─── POST /combos/{combo_id}/groups/{group_id}/items ──────────────────────────


@router.post("/combos/{combo_id}/groups/{group_id}/items", summary="添加菜品到套餐分组")
async def add_item_to_combo_group(
    combo_id: str,
    group_id: str,
    req: AddGroupItemReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    tenant_id = _get_tenant_id(request)
    await _rls_menu(db, tenant_id)

    # 校验分组存在且属于该套餐
    check_sql = text("""
        SELECT id FROM combo_groups
        WHERE id        = :group_id
          AND combo_id  = :combo_id
          AND tenant_id = :tenant_id
          AND is_deleted = false
    """)
    check_result = await db.execute(
        check_sql,
        {
            "group_id": group_id,
            "combo_id": combo_id,
            "tenant_id": tenant_id,
        },
    )
    if not check_result.fetchone():
        raise HTTPException(status_code=404, detail="分组不存在或不属于该套餐")

    new_id = str(uuid.uuid4())
    insert_sql = text("""
        INSERT INTO combo_group_items
          (id, tenant_id, group_id, dish_id, dish_name, quantity,
           extra_price_fen, is_default, sort_order, created_at, updated_at, is_deleted)
        VALUES
          (:id, :tenant_id, :group_id, :dish_id, :dish_name, :quantity,
           :extra_price_fen, :is_default, :sort_order, NOW(), NOW(), false)
        RETURNING id, group_id, dish_id, dish_name, quantity,
                  extra_price_fen, is_default, sort_order
    """)
    result = await db.execute(
        insert_sql,
        {
            "id": new_id,
            "tenant_id": tenant_id,
            "group_id": group_id,
            "dish_id": req.dish_id,
            "dish_name": req.dish_name,
            "quantity": req.quantity,
            "extra_price_fen": req.extra_price_fen,
            "is_default": req.is_default,
            "sort_order": req.sort_order,
        },
    )
    row = result.fetchone()
    await db.commit()

    logger.info(
        "combo_group_item_added",
        combo_id=combo_id,
        group_id=group_id,
        item_id=new_id,
        dish_name=req.dish_name,
    )
    return _ok({"item": _row_to_group_item(row)})


# ─── DELETE /combos/{combo_id}/groups/{group_id}/items/{item_id} ──────────────


@router.delete(
    "/combos/{combo_id}/groups/{group_id}/items/{item_id}",
    summary="从套餐分组移除菜品（软删除）",
)
async def remove_item_from_combo_group(
    combo_id: str,
    group_id: str,
    item_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    tenant_id = _get_tenant_id(request)
    await _rls_menu(db, tenant_id)

    # 校验 item 存在且属于该分组
    check_sql = text("""
        SELECT i.id FROM combo_group_items i
        JOIN combo_groups g ON g.id = i.group_id
        WHERE i.id        = :item_id
          AND i.group_id  = :group_id
          AND g.combo_id  = :combo_id
          AND i.tenant_id = :tenant_id
          AND i.is_deleted = false
    """)
    check_result = await db.execute(
        check_sql,
        {
            "item_id": item_id,
            "group_id": group_id,
            "combo_id": combo_id,
            "tenant_id": tenant_id,
        },
    )
    if not check_result.fetchone():
        raise HTTPException(status_code=404, detail="菜品不存在于该分组")

    del_sql = text("""
        UPDATE combo_group_items
        SET is_deleted = true, updated_at = NOW()
        WHERE id = :item_id AND tenant_id = :tenant_id
    """)
    await db.execute(del_sql, {"item_id": item_id, "tenant_id": tenant_id})
    await db.commit()

    logger.info("combo_group_item_removed", combo_id=combo_id, group_id=group_id, item_id=item_id)
    return _ok({"item_id": item_id, "removed": True})


# ─── POST /combos/{combo_id}/validate-selection ───────────────────────────────


@router.post("/combos/{combo_id}/validate-selection", summary="验证顾客套餐N选M选择是否合规")
async def validate_combo_selection(
    combo_id: str,
    req: ValidateSelectionReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """验证顾客对该套餐各分组的选择是否满足 min_select/max_select/is_required 规则。

    返回：
      valid  — True=全部合规，False=有违规
      errors — 违规分组列表，每项含 group_id + group_name + message
    """
    tenant_id = _get_tenant_id(request)
    await _rls_menu(db, tenant_id)

    # 查套餐所有分组
    groups_sql = text("""
        SELECT id, group_name, min_select, max_select, is_required
        FROM combo_groups
        WHERE combo_id   = :combo_id
          AND tenant_id  = :tenant_id
          AND is_deleted = false
    """)
    groups_result = await db.execute(
        groups_sql,
        {
            "combo_id": combo_id,
            "tenant_id": tenant_id,
        },
    )
    groups = {str(r.id): r for r in groups_result.fetchall()}

    if not groups:
        raise HTTPException(status_code=404, detail="套餐不存在或无分组")

    # 构建顾客选择 map: group_id -> [item_id, ...]
    selection_map: dict[str, list[str]] = {}
    for sel in req.selections:
        selection_map[sel.group_id] = sel.item_ids

    # 校验选择的 item_id 是否都有效（属于该套餐且未删除）
    all_selected_ids: list[str] = []
    for item_ids in selection_map.values():
        all_selected_ids.extend(item_ids)

    valid_item_ids: set[str] = set()
    if all_selected_ids:
        id_params = {f"iid_{i}": iid for i, iid in enumerate(all_selected_ids)}
        id_placeholders = ", ".join([f":iid_{i}" for i in range(len(all_selected_ids))])
        valid_sql = text(f"""
            SELECT i.id, i.group_id FROM combo_group_items i
            JOIN combo_groups g ON g.id = i.group_id
            WHERE i.id       IN ({id_placeholders})
              AND g.combo_id  = :combo_id
              AND i.tenant_id = :tenant_id
              AND i.is_deleted = false
        """)
        valid_result = await db.execute(
            valid_sql,
            {
                "combo_id": combo_id,
                "tenant_id": tenant_id,
                **id_params,
            },
        )
        for vr in valid_result.fetchall():
            valid_item_ids.add(str(vr.id))

    # 查各 item_id 所属分组（用于"菜品不在该分组"校验）
    item_group_map: dict[str, str] = {}  # item_id -> group_id
    if all_selected_ids:
        id_params_2 = {f"iid2_{i}": iid for i, iid in enumerate(all_selected_ids)}
        id_placeholders_2 = ", ".join([f":iid2_{i}" for i in range(len(all_selected_ids))])
        item_group_sql = text(f"""
            SELECT i.id, i.group_id FROM combo_group_items i
            JOIN combo_groups g ON g.id = i.group_id
            WHERE i.id       IN ({id_placeholders_2})
              AND g.combo_id  = :combo_id
              AND i.tenant_id = :tenant_id
              AND i.is_deleted = false
        """)
        item_group_result = await db.execute(
            item_group_sql,
            {
                "combo_id": combo_id,
                "tenant_id": tenant_id,
                **id_params_2,
            },
        )
        for igr in item_group_result.fetchall():
            item_group_map[str(igr.id)] = str(igr.group_id)

    def _combo_error(code_message: str, group_id: str) -> None:
        raise HTTPException(
            status_code=422,
            detail={
                "ok": False,
                "data": None,
                "error": {
                    "code": "COMBO_VALIDATION_ERROR",
                    "message": code_message,
                    "field": group_id,
                },
            },
        )

    errors: list[dict] = []

    for group_id, group in groups.items():
        selected_ids = selection_map.get(group_id, [])

        # 防御4: 重复选择 — 同一个 item_id 在同一组出现两次
        if len(selected_ids) != len(set(selected_ids)):
            _combo_error("不可重复选择同一菜品", group_id)

        # 防御3: 无效 dish_id — 选择了不属于该分组的菜品
        for iid in selected_ids:
            actual_group = item_group_map.get(iid)
            if actual_group is None:
                # item_id 在整个套餐中都不存在
                _combo_error("菜品不在该套餐分组中", group_id)
            elif actual_group != group_id:
                # item_id 属于该套餐，但不在此分组
                _combo_error("菜品不在该套餐分组中", group_id)

        # 只统计已通过有效性校验的 item
        valid_selected = [iid for iid in selected_ids if iid in valid_item_ids]
        count = len(valid_selected)

        # 防御3 兜底: 仍有无效 id（上面按分组校验后还剩余的）
        invalid_ids = [iid for iid in selected_ids if iid not in valid_item_ids]
        if invalid_ids:
            errors.append(
                {
                    "group_id": group_id,
                    "group_name": group.group_name,
                    "message": f"「{group.group_name}」包含无效菜品选项：{invalid_ids}",
                    "code": "COMBO_VALIDATION_ERROR",
                }
            )
            continue

        # 防御1: 超选 — selected_count > group.max_select
        if count > group.max_select:
            _combo_error("超出最大选择数量", group_id)

        # 防御2: 未选必选项 — is_required=True 且 selected_count < group.min_select
        if group.is_required and count < group.min_select:
            _combo_error("请完成必选项", group_id)

        # 非必选但选了又不够 min_select（理论上 min_select>0 且 is_required=False 很少见）
        if not group.is_required and count > 0 and count < group.min_select:
            errors.append(
                {
                    "group_id": group_id,
                    "group_name": group.group_name,
                    "message": f"「{group.group_name}」至少需要选 {group.min_select} 个，当前选了 {count} 个",
                    "code": "COMBO_VALIDATION_ERROR",
                }
            )

    valid = len(errors) == 0
    logger.info(
        "combo_selection_validated",
        combo_id=combo_id,
        valid=valid,
        errors_count=len(errors),
    )
    return _ok({"valid": valid, "errors": errors})
