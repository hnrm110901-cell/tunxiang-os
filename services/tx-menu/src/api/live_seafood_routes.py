"""活鲜海鲜 API — 徐记海鲜核心业务模块

涵盖：
  - 活鲜菜品管理（称重/条头计价）
  - 鱼缸区域管理
  - 活鲜库存更新
  - 称重记录（称重→确认→加入订单）
  - 活鲜厨打单打印触发
"""
import uuid as _uuid
from decimal import Decimal
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

log = structlog.get_logger(__name__)
router = APIRouter(prefix="/api/v1/menu", tags=["live-seafood"])


# ─── 工具 ─────────────────────────────────────────────────────────────────────

def _tenant(request: Request) -> str:
    tid = getattr(request.state, "tenant_id", None) or request.headers.get("X-Tenant-ID", "")
    if not tid:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header required")
    return tid


def _ok(data) -> dict:
    return {"ok": True, "data": data, "error": None}


async def _set_rls(db: AsyncSession, tenant_id: str) -> None:
    await db.execute(text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": tenant_id})


# ─── 请求/响应模型 ─────────────────────────────────────────────────────────────

class TankZoneReq(BaseModel):
    store_id: str
    zone_code: str = Field(..., max_length=20, description="区域编码，如：A1/海鲜池-1")
    zone_name: str = Field(..., max_length=50, description="展示名，如：海鲜区A缸1号")
    capacity_kg: Optional[float] = Field(None, ge=0)
    water_temp_celsius: Optional[float] = Field(None, ge=0, le=40)
    notes: Optional[str] = None
    sort_order: int = 0


class UpdateLiveSeafoodReq(BaseModel):
    """更新菜品的活鲜计价方式（补充到已有菜品上）"""
    pricing_method: str = Field(..., pattern="^(weight|count)$",
                                description="weight=称重计价 / count=条头计价")
    weight_unit: Optional[str] = Field(None, pattern="^(jin|liang|kg|g)$",
                                       description="称重单位（pricing_method=weight时必填）")
    price_per_unit_fen: int = Field(..., ge=0, description="单位价格（分/斤 或 分/条）")
    min_order_qty: Optional[float] = Field(None, ge=0.1, description="最小点单量")
    display_unit: str = Field(..., max_length=10, description="展示单位，如：斤/条/头/位")
    tank_zone_id: Optional[str] = None
    alive_rate_pct: Optional[int] = Field(None, ge=0, le=100)

    @model_validator(mode="after")
    def _check_weight_unit(self) -> "UpdateLiveSeafoodReq":
        if self.pricing_method == "weight" and not self.weight_unit:
            raise ValueError("pricing_method=weight 时 weight_unit 为必填")
        return self


class WeighRecordReq(BaseModel):
    """创建活鲜称重记录（称重→等待顾客确认）"""
    store_id: str
    dish_id: str
    weighed_qty: float = Field(..., gt=0, description="称重数量，如：1.35（斤）")
    weight_unit: str = Field(..., pattern="^(jin|liang|kg|g)$")
    price_per_unit_fen: int = Field(..., ge=0, description="称重时单价（快照，防止价格变动影响）")
    tank_zone_id: Optional[str] = None
    zone_code: Optional[str] = Field(None, description="鱼缸区域编码，如：A1（可选，用于校验鱼缸归属）")
    weighed_by: Optional[str] = Field(None, description="称重员工ID")
    notes: Optional[str] = None

    @field_validator("weighed_qty", mode="after")
    @classmethod
    def _validate_weight_range(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("重量必须大于0")
        if v > 50:
            raise ValueError("单次称重超过50kg，请检查秤是否异常")
        return v


class ConfirmWeighReq(BaseModel):
    """确认称重记录并绑定到订单"""
    order_id: str
    confirmed_by: Optional[str] = None
    adjusted_qty: Optional[float] = Field(None, gt=0,
                                           description="顾客要求调整后的重量（如不同则重新计算金额）")


class UpdateStockReq(BaseModel):
    """更新活鲜库存（收货/销售/死亡损耗）"""
    delta_count: Optional[int] = Field(None, description="库存条数变化（正=增加，负=减少）")
    delta_weight_g: Optional[int] = Field(None, description="库存重量变化（克），正=增加")
    reason: str = Field(..., description="变更原因：purchase=采购入库/sold=售出/death=死亡损耗/adjust=盘点调整")
    notes: Optional[str] = None


# ─── Mock 数据（接入数据库前使用）────────────────────────────────────────────────

# 有效 dish_id 集合（mock 阶段），key=dish_id, value=菜品名
# TODO: 替换为真实DB查询 SELECT id FROM dishes WHERE id=$dish_id AND tenant_id=$tenant_id AND is_deleted=FALSE
_MOCK_DISH_IDS: dict[str, str] = {
    "d-sf-001": "石斑鱼",
    "d-sf-002": "对虾",
    "d-sf-003": "波士顿龙虾",
    "d-sf-004": "澳洲龙虾",
    "d-sf-005": "花蟹",
}

# 有效鱼缸 zone_code 集合（mock 阶段）
# TODO: 替换为真实DB查询 SELECT zone_code FROM fish_tank_zones WHERE store_id=$store_id AND tenant_id=$tenant_id AND is_deleted=FALSE
_MOCK_VALID_ZONE_CODES: set[str] = {"A1", "B2", "C1", "D1"}


# ─── 鱼缸区域管理 ─────────────────────────────────────────────────────────────

@router.get("/tank-zones", summary="查询门店鱼缸区域列表")
async def list_tank_zones(
    store_id: str = Query(...),
    request: Request = None,
    db: AsyncSession = Depends(get_db),
) -> dict:
    tid = _tenant(request)
    await _set_rls(db, tid)
    result = await db.execute(text("""
        SELECT id, zone_code, zone_name, capacity_kg, water_temp_celsius,
               is_active, sort_order, notes
        FROM fish_tank_zones
        WHERE store_id = :sid
          AND tenant_id = :tid
          AND is_deleted = false
        ORDER BY sort_order, zone_code
    """), {"sid": _uuid.UUID(store_id), "tid": _uuid.UUID(tid)})
    rows = result.fetchall()
    return _ok({"items": [
        {
            "id": str(r[0]), "zone_code": r[1], "zone_name": r[2],
            "capacity_kg": float(r[3]) if r[3] else None,
            "water_temp_celsius": float(r[4]) if r[4] else None,
            "is_active": r[5], "sort_order": r[6], "notes": r[7],
        }
        for r in rows
    ], "total": len(rows)})


@router.post("/tank-zones", summary="创建鱼缸区域", status_code=201)
async def create_tank_zone(
    req: TankZoneReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    tid = _tenant(request)
    await _set_rls(db, tid)
    zone_id = _uuid.uuid4()
    await db.execute(text("""
        INSERT INTO fish_tank_zones
            (id, tenant_id, store_id, zone_code, zone_name,
             capacity_kg, water_temp_celsius, notes, sort_order)
        VALUES
            (:id, :tid, :sid, :code, :name, :cap, :temp, :notes, :sort)
    """), {
        "id": zone_id, "tid": _uuid.UUID(tid), "sid": _uuid.UUID(req.store_id),
        "code": req.zone_code, "name": req.zone_name,
        "cap": req.capacity_kg, "temp": req.water_temp_celsius,
        "notes": req.notes, "sort": req.sort_order,
    })
    await db.commit()
    log.info("tank_zone.created", zone_id=str(zone_id), store_id=req.store_id)
    return _ok({"id": str(zone_id), "zone_code": req.zone_code, "zone_name": req.zone_name})


# ─── 活鲜菜品配置 ──────────────────────────────────────────────────────────────

@router.get("/live-seafood", summary="获取门店活鲜菜品列表（含库存）")
async def list_live_seafood(
    store_id: Optional[str] = Query(None, description="门店ID，不传=集团全部"),
    tank_zone_id: Optional[str] = Query(None),
    in_stock_only: bool = Query(False, description="仅显示有货品种"),
    request: Request = None,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """返回所有活鲜计价菜品及实时库存。"""
    tid = _tenant(request)
    await _set_rls(db, tid)

    conditions = ["d.pricing_method IN ('weight', 'count')",
                  "d.tenant_id = :tid", "d.is_deleted = false"]
    params: dict = {"tid": _uuid.UUID(tid)}

    if store_id:
        conditions.append("(d.store_id = :sid OR d.store_id IS NULL)")
        params["sid"] = _uuid.UUID(store_id)
    if tank_zone_id:
        conditions.append("d.tank_zone_id = :zone_id")
        params["zone_id"] = _uuid.UUID(tank_zone_id)
    if in_stock_only:
        conditions.append("(d.live_stock_count > 0 OR d.live_stock_weight_g > 0)")

    where_clause = " AND ".join(conditions)
    result = await db.execute(text(f"""  # noqa: S608 — mock SQL, not user input
        SELECT
            d.id, d.dish_name, d.pricing_method,
            d.weight_unit, d.price_per_unit_fen, d.min_order_qty, d.display_unit,
            d.tank_zone_id, d.alive_rate_pct,
            d.live_stock_count, d.live_stock_weight_g,
            d.image_url, d.is_available,
            tz.zone_name AS tank_zone_name
        FROM dishes d
        LEFT JOIN fish_tank_zones tz ON tz.id = d.tank_zone_id
        WHERE {where_clause}
        ORDER BY d.dish_name
    """), params)

    rows = result.fetchall()
    return _ok({"items": [
        {
            "id": str(r[0]),
            "dish_name": r[1],
            "pricing_method": r[2],
            "weight_unit": r[3],
            "price_per_unit_fen": r[4],
            "min_order_qty": float(r[5]) if r[5] else 1.0,
            "display_unit": r[6],
            "tank_zone_id": str(r[7]) if r[7] else None,
            "tank_zone_name": r[13],
            "alive_rate_pct": r[8],
            "live_stock_count": r[9],
            "live_stock_weight_g": r[10],
            "image_url": r[11],
            "is_available": r[12],
            # 方便前端展示用：计算展示价格文本
            "price_display": _format_price_display(r[2], r[4], r[6]),
        }
        for r in rows
    ], "total": len(rows)})


@router.patch("/live-seafood/{dish_id}", summary="设置菜品为活鲜计价方式")
async def update_live_seafood_config(
    dish_id: str,
    req: UpdateLiveSeafoodReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """将已有菜品升级为活鲜计价模式（称重/条头），更新相关字段。"""
    tid = _tenant(request)
    await _set_rls(db, tid)
    result = await db.execute(text("""
        UPDATE dishes SET
            pricing_method = :method,
            weight_unit = :wunit,
            price_per_unit_fen = :price,
            min_order_qty = :min_qty,
            display_unit = :dunit,
            tank_zone_id = :zone_id,
            alive_rate_pct = :alive_pct,
            updated_at = now()
        WHERE id = :did AND tenant_id = :tid AND is_deleted = false
        RETURNING id, dish_name, pricing_method, price_per_unit_fen
    """), {
        "did": _uuid.UUID(dish_id), "tid": _uuid.UUID(tid),
        "method": req.pricing_method,
        "wunit": req.weight_unit,
        "price": req.price_per_unit_fen,
        "min_qty": Decimal(str(req.min_order_qty)) if req.min_order_qty else Decimal("1.0"),
        "dunit": req.display_unit,
        "zone_id": _uuid.UUID(req.tank_zone_id) if req.tank_zone_id else None,
        "alive_pct": req.alive_rate_pct,
    })
    row = result.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="菜品不存在")
    await db.commit()
    log.info("live_seafood.config_updated", dish_id=dish_id, method=req.pricing_method)
    return _ok({"dish_id": dish_id, "dish_name": row[1], "pricing_method": row[2]})


@router.post("/live-seafood/{dish_id}/stock", summary="更新活鲜库存")
async def update_live_stock(
    dish_id: str,
    req: UpdateStockReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """更新活鲜库存数量或重量。支持采购入库、销售扣库、死亡损耗记录。"""
    tid = _tenant(request)
    await _set_rls(db, tid)

    set_clauses = ["updated_at = now()"]
    params: dict = {"did": _uuid.UUID(dish_id), "tid": _uuid.UUID(tid)}

    if req.delta_count is not None:
        set_clauses.append("live_stock_count = GREATEST(0, live_stock_count + :dc)")
        params["dc"] = req.delta_count
    if req.delta_weight_g is not None:
        set_clauses.append("live_stock_weight_g = GREATEST(0, live_stock_weight_g + :dw)")
        params["dw"] = req.delta_weight_g

    result = await db.execute(text(f"""  # noqa: S608 — mock SQL, not user input
        UPDATE dishes SET {', '.join(set_clauses)}
        WHERE id = :did AND tenant_id = :tid AND is_deleted = false
        RETURNING id, dish_name, live_stock_count, live_stock_weight_g
    """), params)
    row = result.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="菜品不存在")
    await db.commit()

    log.info("live_stock.updated", dish_id=dish_id, reason=req.reason,
             delta_count=req.delta_count, delta_weight_g=req.delta_weight_g)
    return _ok({
        "dish_id": dish_id,
        "dish_name": row[1],
        "live_stock_count": row[2],
        "live_stock_weight_g": row[3],
        "reason": req.reason,
    })


# ─── 活鲜称重流程 ──────────────────────────────────────────────────────────────

@router.post("/live-seafood/weigh", summary="创建称重记录（称重→等顾客确认）", status_code=201)
async def create_weigh_record(
    req: WeighRecordReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    活鲜称重流程第一步。
    服务员在POS上录入称重数据，系统生成称重记录（status=pending），
    自动计算金额，等待顾客确认后再绑定到订单。
    """
    tid = _tenant(request)
    await _set_rls(db, tid)

    # ── 校验 dish_id 格式（必须为有效UUID格式）
    try:
        _uuid.UUID(req.dish_id)
    except ValueError:
        raise HTTPException(  # noqa: B904
            status_code=422,
            detail={
                "ok": False,
                "error": {
                    "code": "INVALID_DISH_ID",
                    "message": "dish_id 格式无效，必须为UUID格式",
                    "field": "dish_id",
                },
            },
        )

    # ── 校验 dish_id 存在性（真实 DB 查询）
    dish_check = await db.execute(
        text("SELECT id, dish_name FROM dishes WHERE id = :id AND tenant_id = :tid AND is_deleted = false"),
        {"id": _uuid.UUID(req.dish_id), "tid": _uuid.UUID(tid)},
    )
    dish_row = dish_check.fetchone()
    if not dish_row:
        raise HTTPException(
            status_code=404,
            detail={
                "ok": False,
                "error": {
                    "code": "DISH_NOT_FOUND",
                    "message": f"菜品 {req.dish_id} 不存在",
                    "field": "dish_id",
                },
            },
        )
    real_dish_name: str = dish_row[1]

    # ── 校验 zone_code 合法性（如果传入）
    if req.zone_code is not None:
        zone_code_upper = req.zone_code.upper()
        zone_result = await db.execute(
            text("SELECT zone_code FROM fish_tank_zones WHERE store_id = :sid AND tenant_id = :tid AND zone_code = :zc AND is_deleted = false"),
            {"sid": _uuid.UUID(req.store_id), "tid": _uuid.UUID(tid), "zc": zone_code_upper},
        )
        if not zone_result.fetchone():
            raise HTTPException(
                status_code=422,
                detail={
                    "ok": False,
                    "error": {
                        "code": "TANK_NOT_FOUND",
                        "message": "鱼缸区域不存在",
                        "field": "zone_code",
                    },
                },
            )

    # ── 校验称重数量合理性（Pydantic validator 已拦截 <=0，此处补充上限）
    if req.weighed_qty > 50:
        raise HTTPException(
            status_code=422,
            detail={
                "ok": False,
                "error": {
                    "code": "WEIGHT_OUT_OF_RANGE",
                    "message": "单次称重超过50kg，请检查秤是否异常",
                    "field": "weighed_qty",
                },
            },
        )

    # 计算金额
    qty = Decimal(str(req.weighed_qty))
    amount_fen = int(qty * req.price_per_unit_fen)

    record_id = _uuid.uuid4()
    await db.execute(text("""
        INSERT INTO live_seafood_weigh_records
            (id, tenant_id, store_id, dish_id, weighed_qty, weight_unit,
             price_per_unit_fen, amount_fen, tank_zone_id, weighed_by, notes, status)
        VALUES
            (:id, :tid, :sid, :did, :qty, :wunit,
             :price, :amount, :zone, :weighed_by, :notes, 'pending')
    """), {
        "id": record_id, "tid": _uuid.UUID(tid), "sid": _uuid.UUID(req.store_id),
        "did": _uuid.UUID(req.dish_id),
        "qty": qty, "wunit": req.weight_unit,
        "price": req.price_per_unit_fen, "amount": amount_fen,
        "zone": _uuid.UUID(req.tank_zone_id) if req.tank_zone_id else None,
        "weighed_by": _uuid.UUID(req.weighed_by) if req.weighed_by else None,
        "notes": req.notes,
    })

    # 菜品名称已在存在性校验时获取，直接使用
    dish_name = real_dish_name

    # 更新 dish_name 快照
    await db.execute(text("""
        UPDATE live_seafood_weigh_records SET dish_name = :name WHERE id = :id
    """), {"name": dish_name, "id": record_id})

    await db.commit()

    log.info("weigh_record.created",
             record_id=str(record_id), dish_id=req.dish_id,
             qty=float(qty), amount_fen=amount_fen)

    return _ok({
        "weigh_record_id": str(record_id),
        "dish_name": dish_name,
        "weighed_qty": float(qty),
        "weight_unit": req.weight_unit,
        "unit_display": _unit_display(req.weight_unit),
        "price_per_unit_fen": req.price_per_unit_fen,
        "amount_fen": amount_fen,
        "amount_display": f"¥{amount_fen / 100:.2f}",
        "status": "pending",
        # 打印称重小票所需信息
        "print_data": {
            "dish_name": dish_name,
            "qty_display": f"{float(qty):.3f}{_unit_display(req.weight_unit)}",
            "unit_price_display": f"¥{req.price_per_unit_fen / 100:.2f}/{_unit_display(req.weight_unit)}",
            "amount_display": f"¥{amount_fen / 100:.2f}",
        },
    })


@router.post("/live-seafood/weigh/{record_id}/confirm", summary="确认称重并绑定到订单")
async def confirm_weigh_record(
    record_id: str,
    req: ConfirmWeighReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    活鲜称重流程第二步。顾客或服务员确认称重结果后，
    将称重记录绑定到订单，并自动扣减活鲜库存。
    """
    tid = _tenant(request)
    await _set_rls(db, tid)

    # 查称重记录
    rec_result = await db.execute(text("""
        SELECT id, dish_id, dish_name, weighed_qty, weight_unit,
               price_per_unit_fen, amount_fen, status
        FROM live_seafood_weigh_records
        WHERE id = :rid AND tenant_id = :tid
    """), {"rid": _uuid.UUID(record_id), "tid": _uuid.UUID(tid)})
    rec = rec_result.fetchone()
    if not rec:
        raise HTTPException(status_code=404, detail="称重记录不存在")
    if rec[7] != "pending":
        raise HTTPException(status_code=400, detail=f"称重记录状态为 {rec[7]}，无法再次确认")

    # 允许调整重量
    final_qty = Decimal(str(req.adjusted_qty)) if req.adjusted_qty else rec[3]
    final_amount_fen = int(final_qty * rec[5])

    # 更新称重记录
    await db.execute(text("""
        UPDATE live_seafood_weigh_records SET
            order_id = :oid,
            confirmed_by = :confirmed_by,
            confirmed_at = now(),
            weighed_qty = :qty,
            amount_fen = :amount,
            status = 'confirmed'
        WHERE id = :rid AND tenant_id = :tid
    """), {
        "oid": _uuid.UUID(req.order_id), "rid": _uuid.UUID(record_id),
        "tid": _uuid.UUID(tid),
        "confirmed_by": _uuid.UUID(req.confirmed_by) if req.confirmed_by else None,
        "qty": final_qty, "amount": final_amount_fen,
    })

    # 扣减活鲜库存（按克计）
    weight_g = _to_grams(float(final_qty), rec[4])
    await db.execute(text("""
        UPDATE dishes SET
            live_stock_weight_g = GREATEST(0, live_stock_weight_g - :wg),
            updated_at = now()
        WHERE id = :did AND tenant_id = :tid
    """), {"did": rec[1], "tid": _uuid.UUID(tid), "wg": weight_g})

    await db.commit()

    log.info("weigh_record.confirmed",
             record_id=record_id, order_id=req.order_id, amount_fen=final_amount_fen)

    return _ok({
        "weigh_record_id": record_id,
        "order_id": req.order_id,
        "dish_name": rec[2],
        "final_qty": float(final_qty),
        "weight_unit": rec[4],
        "final_amount_fen": final_amount_fen,
        "status": "confirmed",
    })


@router.get("/live-seafood/weigh/{store_id}/pending", summary="查询门店待确认称重记录")
async def list_pending_weigh(
    store_id: str,
    request: Request = None,
    db: AsyncSession = Depends(get_db),
) -> dict:
    tid = _tenant(request)
    await _set_rls(db, tid)
    result = await db.execute(text("""
        SELECT r.id, r.dish_id, r.dish_name, r.weighed_qty, r.weight_unit,
               r.price_per_unit_fen, r.amount_fen, r.created_at,
               tz.zone_name
        FROM live_seafood_weigh_records r
        LEFT JOIN fish_tank_zones tz ON tz.id = r.tank_zone_id
        WHERE r.store_id = :sid AND r.tenant_id = :tid
          AND r.status = 'pending'
        ORDER BY r.created_at DESC
    """), {"sid": _uuid.UUID(store_id), "tid": _uuid.UUID(tid)})
    rows = result.fetchall()
    return _ok({"items": [
        {
            "id": str(r[0]), "dish_id": str(r[1]), "dish_name": r[2],
            "weighed_qty": float(r[3]), "weight_unit": r[4],
            "price_per_unit_fen": r[5], "amount_fen": r[6],
            "amount_display": f"¥{r[6] / 100:.2f}",
            "tank_zone_name": r[8],
            "created_at": r[7].isoformat() if r[7] else None,
        }
        for r in rows
    ], "total": len(rows)})


# ─── 工具函数 ──────────────────────────────────────────────────────────────────

def _format_price_display(pricing_method: str, price_per_unit_fen: int, display_unit: str) -> str:
    """生成价格展示文本，如：68元/斤"""
    if not price_per_unit_fen:
        return "价格待定"
    yuan = price_per_unit_fen / 100
    if yuan == int(yuan):  # noqa: SIM108
        price_str = f"{int(yuan)}"
    else:
        price_str = f"{yuan:.1f}"
    return f"{price_str}元/{display_unit or '份'}"


def _unit_display(weight_unit: str) -> str:
    return {"jin": "斤", "liang": "两", "kg": "千克", "g": "克"}.get(weight_unit, weight_unit)


def _to_grams(qty: float, weight_unit: str) -> int:
    """换算成克，用于库存扣减"""
    multipliers = {"jin": 500, "liang": 50, "kg": 1000, "g": 1}
    return int(qty * multipliers.get(weight_unit, 1))
