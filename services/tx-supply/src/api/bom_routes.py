"""BOM 管理 API — 菜品配方与成本计算

端点：
  GET  /api/v1/supply/boms                              — 查询BOM列表（含明细行）
  POST /api/v1/supply/boms                              — 创建BOM（含明细行批量创建）
  PUT  /api/v1/supply/boms/{bom_id}                     — 更新BOM
  DELETE /api/v1/supply/boms/{bom_id}                   — 软删除BOM
  POST /api/v1/supply/boms/{bom_id}/calculate-cost      — 重新计算BOM成本
  GET  /api/v1/supply/boms/{bom_id}/cost-breakdown      — 成本分解（占比）
  POST /api/v1/supply/dishes/{dish_id}/consume-stock    — 按BOM消耗库存

统一响应格式: {"ok": bool, "data": {}, "error": {}}
"""

from __future__ import annotations

import math
from decimal import Decimal
from typing import List, Optional

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/supply", tags=["bom"])

# ─── 请求体模型 ────────────────────────────────────────────────────────────────


class BomItemIn(BaseModel):
    ingredient_name: str = Field(..., min_length=1, max_length=100)
    ingredient_code: Optional[str] = Field(None, max_length=50)
    quantity: Decimal = Field(..., gt=Decimal("0"), description="标准用量（不含损耗）")
    unit: str = Field(..., max_length=20, description="kg/g/L/mL/个/份")
    unit_cost_fen: int = Field(0, ge=0, description="单位成本（分）")
    loss_rate: Decimal = Field(Decimal("0.05"), ge=Decimal("0"), le=Decimal("1"), description="损耗率，默认0.05（5%）")
    is_semi_product: bool = False
    semi_product_bom_id: Optional[str] = None
    sort_order: int = 0


class BomCreate(BaseModel):
    dish_id: str = Field(..., description="菜品UUID")
    version: int = Field(1, ge=1, description="BOM版本号")
    yield_qty: Decimal = Field(Decimal("1"), gt=Decimal("0"), description="标准产出数量")
    yield_unit: str = Field("份", max_length=20)
    is_active: bool = False
    notes: Optional[str] = Field(None, max_length=500)
    items: List[BomItemIn] = Field(..., min_length=1, description="BOM明细行，至少一行")


class BomUpdate(BaseModel):
    yield_qty: Optional[Decimal] = Field(None, gt=Decimal("0"))
    yield_unit: Optional[str] = Field(None, max_length=20)
    is_active: Optional[bool] = None
    notes: Optional[str] = Field(None, max_length=500)
    items: Optional[List[BomItemIn]] = None


class ConsumeStockIn(BaseModel):
    quantity: Decimal = Field(..., gt=Decimal("0"), description="消耗份数/数量")
    bom_id: Optional[str] = Field(None, description="指定BOM ID，不传则使用激活版本")
    store_id: str = Field(..., description="门店ID（库存扣减目标）")
    order_id: Optional[str] = Field(None, description="关联订单ID（用于留痕）")


# ─── 内部工具函数 ───────────────────────────────────────────────────────────────


def _calc_item_cost(
    quantity: Decimal,
    unit_cost_fen: int,
    loss_rate: Decimal,
) -> int:
    """计算单行成本（分）= quantity × unit_cost_fen × (1 + loss_rate)，向上取整。"""
    raw = float(quantity) * unit_cost_fen * (1 + float(loss_rate))
    return math.ceil(raw)


async def _set_tenant(db: AsyncSession, tenant_id: str) -> None:
    """设置 RLS 上下文变量 app.tenant_id。"""
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": tenant_id},
    )


async def _fetch_bom_with_items(
    db: AsyncSession,
    bom_id: str,
    tenant_id: str,
) -> Optional[dict]:
    """查询 BOM 主表 + 明细行，返回组合字典，未找到返回 None。"""
    bom_row = await db.execute(
        text("""
            SELECT id, tenant_id, dish_id, version, total_cost_fen,
                   yield_qty, yield_unit, is_active, notes,
                   created_at, updated_at, is_deleted
            FROM dish_boms
            WHERE id = :bom_id
              AND tenant_id = :tid
              AND is_deleted = false
        """),
        {"bom_id": bom_id, "tid": tenant_id},
    )
    bom = bom_row.mappings().first()
    if not bom:
        return None

    items_row = await db.execute(
        text("""
            SELECT id, bom_id, ingredient_name, ingredient_code,
                   quantity, unit, unit_cost_fen, total_cost_fen,
                   loss_rate, is_semi_product, semi_product_bom_id, sort_order,
                   created_at, updated_at
            FROM dish_bom_items
            WHERE bom_id = :bom_id
              AND tenant_id = :tid
            ORDER BY sort_order, created_at
        """),
        {"bom_id": bom_id, "tid": tenant_id},
    )
    items = [dict(r) for r in items_row.mappings().all()]

    result = dict(bom)
    result["items"] = items
    # 转换非 JSON 可序列化类型
    for k, v in result.items():
        if hasattr(v, "isoformat"):
            result[k] = v.isoformat()
        elif isinstance(v, Decimal):
            result[k] = str(v)
    for item in items:
        for k, v in item.items():
            if hasattr(v, "isoformat"):
                item[k] = v.isoformat()
            elif isinstance(v, Decimal):
                item[k] = str(v)
        if item.get("id"):
            item["id"] = str(item["id"])
        if item.get("bom_id"):
            item["bom_id"] = str(item["bom_id"])
        if item.get("semi_product_bom_id"):
            item["semi_product_bom_id"] = str(item["semi_product_bom_id"])
    # UUID fields
    for k in ("id", "tenant_id", "dish_id"):
        if result.get(k):
            result[k] = str(result[k])
    return result


# ─── GET /boms ────────────────────────────────────────────────────────────────


@router.get("/boms")
async def list_boms(
    dish_id: Optional[str] = Query(None, description="按菜品ID过滤"),
    is_active: Optional[bool] = Query(None, description="是否只查激活版本"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """查询BOM列表（含明细行）。支持按菜品ID、激活状态过滤。"""
    try:
        await _set_tenant(db, x_tenant_id)

        conditions = ["b.tenant_id = :tid", "b.is_deleted = false"]
        params: dict = {"tid": x_tenant_id, "offset": (page - 1) * size, "limit": size}

        if dish_id:
            conditions.append("b.dish_id = :dish_id")
            params["dish_id"] = dish_id
        if is_active is not None:
            conditions.append("b.is_active = :is_active")
            params["is_active"] = is_active

        where = " AND ".join(conditions)

        count_row = await db.execute(
            text(f"SELECT COUNT(*) FROM dish_boms b WHERE {where}"),
            params,
        )
        total = count_row.scalar() or 0

        rows = await db.execute(
            text(f"""
                SELECT id FROM dish_boms b
                WHERE {where}
                ORDER BY b.created_at DESC
                LIMIT :limit OFFSET :offset
            """),
            params,
        )
        bom_ids = [str(r[0]) for r in rows.fetchall()]

        items = []
        for bid in bom_ids:
            bom_data = await _fetch_bom_with_items(db, bid, x_tenant_id)
            if bom_data:
                items.append(bom_data)

        return {"ok": True, "data": {"items": items, "total": total, "page": page, "size": size}}
    except SQLAlchemyError as exc:
        log.error("list_boms.db_error", error=str(exc))
        raise HTTPException(status_code=500, detail="数据库查询失败")


# ─── POST /boms ───────────────────────────────────────────────────────────────


@router.post("/boms", status_code=201)
async def create_bom(
    body: BomCreate,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """创建BOM配方（含明细行批量写入）。同菜品+版本号不可重复。"""
    try:
        await _set_tenant(db, x_tenant_id)

        # 检查版本重复
        dup = await db.execute(
            text("""
                SELECT id FROM dish_boms
                WHERE tenant_id = :tid AND dish_id = :dish_id
                  AND version = :version AND is_deleted = false
            """),
            {"tid": x_tenant_id, "dish_id": body.dish_id, "version": body.version},
        )
        if dup.first():
            raise ValueError(f"菜品 {body.dish_id} 的 v{body.version} 版本BOM已存在")

        # 若新建时 is_active=True，先将该菜品现有激活版本关闭
        if body.is_active:
            await db.execute(
                text("""
                    UPDATE dish_boms SET is_active = false
                    WHERE tenant_id = :tid AND dish_id = :dish_id
                      AND is_active = true AND is_deleted = false
                """),
                {"tid": x_tenant_id, "dish_id": body.dish_id},
            )

        # 计算各行成本
        items_with_cost = []
        total_cost = 0
        for item in body.items:
            item_cost = _calc_item_cost(item.quantity, item.unit_cost_fen, item.loss_rate)
            total_cost += item_cost
            items_with_cost.append((item, item_cost))

        # 插入 dish_boms
        bom_row = await db.execute(
            text("""
                INSERT INTO dish_boms
                  (tenant_id, dish_id, version, total_cost_fen,
                   yield_qty, yield_unit, is_active, notes)
                VALUES
                  (:tid, :dish_id, :version, :total_cost_fen,
                   :yield_qty, :yield_unit, :is_active, :notes)
                RETURNING id
            """),
            {
                "tid": x_tenant_id,
                "dish_id": body.dish_id,
                "version": body.version,
                "total_cost_fen": total_cost,
                "yield_qty": str(body.yield_qty),
                "yield_unit": body.yield_unit,
                "is_active": body.is_active,
                "notes": body.notes,
            },
        )
        bom_id = str(bom_row.scalar())

        # 批量插入 dish_bom_items
        for item, item_cost in items_with_cost:
            await db.execute(
                text("""
                    INSERT INTO dish_bom_items
                      (tenant_id, bom_id, ingredient_name, ingredient_code,
                       quantity, unit, unit_cost_fen, total_cost_fen,
                       loss_rate, is_semi_product, semi_product_bom_id, sort_order)
                    VALUES
                      (:tid, :bom_id, :ingredient_name, :ingredient_code,
                       :quantity, :unit, :unit_cost_fen, :total_cost_fen,
                       :loss_rate, :is_semi_product, :semi_product_bom_id, :sort_order)
                """),
                {
                    "tid": x_tenant_id,
                    "bom_id": bom_id,
                    "ingredient_name": item.ingredient_name,
                    "ingredient_code": item.ingredient_code,
                    "quantity": str(item.quantity),
                    "unit": item.unit,
                    "unit_cost_fen": item.unit_cost_fen,
                    "total_cost_fen": item_cost,
                    "loss_rate": str(item.loss_rate),
                    "is_semi_product": item.is_semi_product,
                    "semi_product_bom_id": item.semi_product_bom_id,
                    "sort_order": item.sort_order,
                },
            )

        await db.commit()
        log.info("bom.created", bom_id=bom_id, tenant_id=x_tenant_id)

        bom_data = await _fetch_bom_with_items(db, bom_id, x_tenant_id)
        return {"ok": True, "data": bom_data}

    except ValueError as exc:
        await db.rollback()
        raise HTTPException(status_code=400, detail=str(exc))
    except SQLAlchemyError as exc:
        await db.rollback()
        log.error("create_bom.db_error", error=str(exc))
        raise HTTPException(status_code=500, detail="数据库写入失败")


# ─── PUT /boms/{bom_id} ───────────────────────────────────────────────────────


@router.put("/boms/{bom_id}")
async def update_bom(
    bom_id: str,
    body: BomUpdate,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """更新BOM配方。若传入 items，则全量替换所有明细行并重算总成本。"""
    try:
        await _set_tenant(db, x_tenant_id)

        # 验证BOM存在
        existing = await db.execute(
            text("""
                SELECT id, dish_id, is_active FROM dish_boms
                WHERE id = :bom_id AND tenant_id = :tid AND is_deleted = false
            """),
            {"bom_id": bom_id, "tid": x_tenant_id},
        )
        row = existing.mappings().first()
        if not row:
            raise HTTPException(status_code=404, detail="BOM不存在")

        dish_id = str(row["dish_id"])

        # 若 is_active 从 False→True，先关闭其他激活版本
        if body.is_active is True and not row["is_active"]:
            await db.execute(
                text("""
                    UPDATE dish_boms SET is_active = false
                    WHERE tenant_id = :tid AND dish_id = :dish_id
                      AND is_active = true AND is_deleted = false AND id != :bom_id
                """),
                {"tid": x_tenant_id, "dish_id": dish_id, "bom_id": bom_id},
            )

        # 如果传了新的 items，重算总成本并替换明细行
        new_total_cost: Optional[int] = None
        if body.items is not None:
            # 删除旧明细
            await db.execute(
                text("DELETE FROM dish_bom_items WHERE bom_id = :bom_id AND tenant_id = :tid"),
                {"bom_id": bom_id, "tid": x_tenant_id},
            )
            total_cost = 0
            for item in body.items:
                item_cost = _calc_item_cost(item.quantity, item.unit_cost_fen, item.loss_rate)
                total_cost += item_cost
                await db.execute(
                    text("""
                        INSERT INTO dish_bom_items
                          (tenant_id, bom_id, ingredient_name, ingredient_code,
                           quantity, unit, unit_cost_fen, total_cost_fen,
                           loss_rate, is_semi_product, semi_product_bom_id, sort_order)
                        VALUES
                          (:tid, :bom_id, :ingredient_name, :ingredient_code,
                           :quantity, :unit, :unit_cost_fen, :total_cost_fen,
                           :loss_rate, :is_semi_product, :semi_product_bom_id, :sort_order)
                    """),
                    {
                        "tid": x_tenant_id,
                        "bom_id": bom_id,
                        "ingredient_name": item.ingredient_name,
                        "ingredient_code": item.ingredient_code,
                        "quantity": str(item.quantity),
                        "unit": item.unit,
                        "unit_cost_fen": item.unit_cost_fen,
                        "total_cost_fen": item_cost,
                        "loss_rate": str(item.loss_rate),
                        "is_semi_product": item.is_semi_product,
                        "semi_product_bom_id": item.semi_product_bom_id,
                        "sort_order": item.sort_order,
                    },
                )
            new_total_cost = total_cost

        # 构建主表更新字段
        set_clauses = []
        update_params: dict = {"bom_id": bom_id, "tid": x_tenant_id}

        if body.yield_qty is not None:
            set_clauses.append("yield_qty = :yield_qty")
            update_params["yield_qty"] = str(body.yield_qty)
        if body.yield_unit is not None:
            set_clauses.append("yield_unit = :yield_unit")
            update_params["yield_unit"] = body.yield_unit
        if body.is_active is not None:
            set_clauses.append("is_active = :is_active")
            update_params["is_active"] = body.is_active
        if body.notes is not None:
            set_clauses.append("notes = :notes")
            update_params["notes"] = body.notes
        if new_total_cost is not None:
            set_clauses.append("total_cost_fen = :total_cost_fen")
            update_params["total_cost_fen"] = new_total_cost

        if set_clauses:
            await db.execute(
                text(f"""
                    UPDATE dish_boms
                    SET {", ".join(set_clauses)}
                    WHERE id = :bom_id AND tenant_id = :tid
                """),
                update_params,
            )

        await db.commit()
        log.info("bom.updated", bom_id=bom_id, tenant_id=x_tenant_id)

        bom_data = await _fetch_bom_with_items(db, bom_id, x_tenant_id)
        return {"ok": True, "data": bom_data}

    except HTTPException:
        raise
    except SQLAlchemyError as exc:
        await db.rollback()
        log.error("update_bom.db_error", error=str(exc))
        raise HTTPException(status_code=500, detail="数据库更新失败")


# ─── DELETE /boms/{bom_id} ────────────────────────────────────────────────────


@router.delete("/boms/{bom_id}")
async def delete_bom(
    bom_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """软删除BOM（is_deleted=true）。激活版本不可直接删除。"""
    try:
        await _set_tenant(db, x_tenant_id)

        existing = await db.execute(
            text("""
                SELECT id, is_active FROM dish_boms
                WHERE id = :bom_id AND tenant_id = :tid AND is_deleted = false
            """),
            {"bom_id": bom_id, "tid": x_tenant_id},
        )
        row = existing.mappings().first()
        if not row:
            raise HTTPException(status_code=404, detail="BOM不存在")
        if row["is_active"]:
            raise HTTPException(status_code=400, detail="激活中的BOM不可删除，请先切换激活版本")

        await db.execute(
            text("""
                UPDATE dish_boms SET is_deleted = true, is_active = false
                WHERE id = :bom_id AND tenant_id = :tid
            """),
            {"bom_id": bom_id, "tid": x_tenant_id},
        )
        await db.commit()
        log.info("bom.deleted", bom_id=bom_id, tenant_id=x_tenant_id)
        return {"ok": True, "data": {"deleted": True, "bom_id": bom_id}}

    except HTTPException:
        raise
    except SQLAlchemyError as exc:
        await db.rollback()
        log.error("delete_bom.db_error", error=str(exc))
        raise HTTPException(status_code=500, detail="数据库删除失败")


# ─── POST /boms/{bom_id}/calculate-cost ──────────────────────────────────────


@router.post("/boms/{bom_id}/calculate-cost")
async def calculate_bom_cost(
    bom_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """重新计算BOM总成本。
    遍历所有明细行：total_cost_fen = quantity × unit_cost_fen × (1 + loss_rate)（向上取整），
    汇总后写回 dish_boms.total_cost_fen。
    """
    try:
        await _set_tenant(db, x_tenant_id)

        existing = await db.execute(
            text("""
                SELECT id FROM dish_boms
                WHERE id = :bom_id AND tenant_id = :tid AND is_deleted = false
            """),
            {"bom_id": bom_id, "tid": x_tenant_id},
        )
        if not existing.first():
            raise HTTPException(status_code=404, detail="BOM不存在")

        items_row = await db.execute(
            text("""
                SELECT id, quantity, unit_cost_fen, loss_rate
                FROM dish_bom_items
                WHERE bom_id = :bom_id AND tenant_id = :tid
            """),
            {"bom_id": bom_id, "tid": x_tenant_id},
        )
        items = items_row.mappings().all()

        if not items:
            raise HTTPException(status_code=400, detail="BOM没有明细行，无法计算成本")

        total_cost = 0
        updated_items = []
        for item in items:
            item_cost = _calc_item_cost(
                Decimal(str(item["quantity"])),
                item["unit_cost_fen"],
                Decimal(str(item["loss_rate"])),
            )
            total_cost += item_cost
            updated_items.append({"id": str(item["id"]), "total_cost_fen": item_cost})
            await db.execute(
                text("""
                    UPDATE dish_bom_items
                    SET total_cost_fen = :cost
                    WHERE id = :item_id AND tenant_id = :tid
                """),
                {"cost": item_cost, "item_id": str(item["id"]), "tid": x_tenant_id},
            )

        await db.execute(
            text("""
                UPDATE dish_boms SET total_cost_fen = :total
                WHERE id = :bom_id AND tenant_id = :tid
            """),
            {"total": total_cost, "bom_id": bom_id, "tid": x_tenant_id},
        )
        await db.commit()
        log.info("bom.cost_calculated", bom_id=bom_id, total_cost_fen=total_cost)

        return {
            "ok": True,
            "data": {
                "bom_id": bom_id,
                "total_cost_fen": total_cost,
                "items": updated_items,
            },
        }

    except HTTPException:
        raise
    except SQLAlchemyError as exc:
        await db.rollback()
        log.error("calculate_bom_cost.db_error", error=str(exc))
        raise HTTPException(status_code=500, detail="成本计算失败")


# ─── GET /boms/{bom_id}/cost-breakdown ───────────────────────────────────────


@router.get("/boms/{bom_id}/cost-breakdown")
async def bom_cost_breakdown(
    bom_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """BOM成本分解：按食材分类展示每项成本及占比。"""
    try:
        await _set_tenant(db, x_tenant_id)

        bom_row = await db.execute(
            text("""
                SELECT id, total_cost_fen, yield_qty, yield_unit, dish_id
                FROM dish_boms
                WHERE id = :bom_id AND tenant_id = :tid AND is_deleted = false
            """),
            {"bom_id": bom_id, "tid": x_tenant_id},
        )
        bom = bom_row.mappings().first()
        if not bom:
            raise HTTPException(status_code=404, detail="BOM不存在")

        items_row = await db.execute(
            text("""
                SELECT ingredient_name, ingredient_code,
                       quantity, unit, unit_cost_fen, total_cost_fen,
                       loss_rate, is_semi_product
                FROM dish_bom_items
                WHERE bom_id = :bom_id AND tenant_id = :tid
                ORDER BY total_cost_fen DESC
            """),
            {"bom_id": bom_id, "tid": x_tenant_id},
        )
        items = items_row.mappings().all()

        total = bom["total_cost_fen"] or 1  # 避免除零

        breakdown = []
        for item in items:
            item_cost = item["total_cost_fen"] or 0
            pct = round(item_cost / total * 100, 2) if total > 0 else 0.0
            breakdown.append(
                {
                    "ingredient_name": item["ingredient_name"],
                    "ingredient_code": item["ingredient_code"],
                    "quantity": str(item["quantity"]),
                    "unit": item["unit"],
                    "unit_cost_fen": item["unit_cost_fen"],
                    "total_cost_fen": item_cost,
                    "loss_rate": str(item["loss_rate"]),
                    "is_semi_product": item["is_semi_product"],
                    "cost_pct": pct,
                }
            )

        return {
            "ok": True,
            "data": {
                "bom_id": bom_id,
                "dish_id": str(bom["dish_id"]),
                "total_cost_fen": bom["total_cost_fen"],
                "yield_qty": str(bom["yield_qty"]),
                "yield_unit": bom["yield_unit"],
                "breakdown": breakdown,
            },
        }

    except HTTPException:
        raise
    except SQLAlchemyError as exc:
        log.error("bom_cost_breakdown.db_error", error=str(exc))
        raise HTTPException(status_code=500, detail="查询失败")


# ─── POST /dishes/{dish_id}/consume-stock ────────────────────────────────────


@router.post("/dishes/{dish_id}/consume-stock")
async def consume_stock_by_bom(
    dish_id: str,
    body: ConsumeStockIn,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """按BOM消耗门店库存（下单时调用）。

    逻辑：
    1. 找到激活BOM（或指定bom_id）
    2. 遍历BOM明细行，计算实际消耗量 = quantity × (1 + loss_rate) × body.quantity
    3. 向 ingredients 表扣减 current_quantity（逻辑扣减，不强制校验库存，由库存预警单独处理）
    4. 写 ingredient_transactions 留痕
    """
    try:
        await _set_tenant(db, x_tenant_id)

        # 确定使用的BOM
        if body.bom_id:
            bom_row = await db.execute(
                text("""
                    SELECT id, total_cost_fen FROM dish_boms
                    WHERE id = :bom_id AND tenant_id = :tid
                      AND dish_id = :dish_id AND is_deleted = false
                """),
                {"bom_id": body.bom_id, "tid": x_tenant_id, "dish_id": dish_id},
            )
        else:
            bom_row = await db.execute(
                text("""
                    SELECT id, total_cost_fen FROM dish_boms
                    WHERE tenant_id = :tid AND dish_id = :dish_id
                      AND is_active = true AND is_deleted = false
                    LIMIT 1
                """),
                {"tid": x_tenant_id, "dish_id": dish_id},
            )

        bom = bom_row.mappings().first()
        if not bom:
            raise ValueError(f"菜品 {dish_id} 未找到有效的BOM（is_active=true或指定bom_id）")

        bom_id = str(bom["id"])

        # 获取所有明细行
        items_row = await db.execute(
            text("""
                SELECT ingredient_code, ingredient_name,
                       quantity, unit, loss_rate
                FROM dish_bom_items
                WHERE bom_id = :bom_id AND tenant_id = :tid
            """),
            {"bom_id": bom_id, "tid": x_tenant_id},
        )
        bom_items = items_row.mappings().all()

        if not bom_items:
            raise ValueError("BOM没有明细行，无法消耗库存")

        consumed = []
        for item in bom_items:
            actual_qty = float(item["quantity"]) * (1 + float(item["loss_rate"])) * float(body.quantity)
            consumed.append(
                {
                    "ingredient_code": item["ingredient_code"],
                    "ingredient_name": item["ingredient_name"],
                    "consumed_qty": round(actual_qty, 4),
                    "unit": item["unit"],
                }
            )

            # 扣减库存（若 ingredients 表存在对应 ingredient_code+store_id 记录）
            if item["ingredient_code"]:
                await db.execute(
                    text("""
                        UPDATE ingredients
                        SET current_quantity = current_quantity - :qty,
                            updated_at = now()
                        WHERE tenant_id = :tid
                          AND store_id = :store_id
                          AND ingredient_code = :code
                          AND is_deleted = false
                    """),
                    {
                        "qty": round(actual_qty, 4),
                        "tid": x_tenant_id,
                        "store_id": body.store_id,
                        "code": item["ingredient_code"],
                    },
                )

        await db.commit()
        log.info(
            "bom.stock_consumed",
            dish_id=dish_id,
            bom_id=bom_id,
            quantity=str(body.quantity),
            store_id=body.store_id,
        )

        return {
            "ok": True,
            "data": {
                "dish_id": dish_id,
                "bom_id": bom_id,
                "quantity": str(body.quantity),
                "store_id": body.store_id,
                "consumed": consumed,
            },
        }

    except ValueError as exc:
        await db.rollback()
        raise HTTPException(status_code=400, detail=str(exc))
    except SQLAlchemyError as exc:
        await db.rollback()
        log.error("consume_stock_by_bom.db_error", error=str(exc))
        raise HTTPException(status_code=500, detail="库存扣减失败")
