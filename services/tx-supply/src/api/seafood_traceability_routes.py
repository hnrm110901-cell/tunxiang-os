"""活鲜批次追溯 API — 批次入库/缸位管理/损耗记录/溯源链/损耗报表

端点：
  POST /api/v1/supply/seafood/batch-receive      — 活鲜批次入库
  GET  /api/v1/supply/seafood/batches             — 批次列表
  GET  /api/v1/supply/seafood/batches/{id}/trace  — 批次溯源链
  POST /api/v1/supply/seafood/tank-assignment     — 分配到缸位
  GET  /api/v1/supply/seafood/tanks               — 缸位状态总览
  POST /api/v1/supply/seafood/mortality           — 记录死亡/损耗
  GET  /api/v1/supply/seafood/loss-report         — 损耗报表
"""

import uuid
from datetime import date, datetime
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db_with_tenant

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/api/v1/supply/seafood", tags=["活鲜追溯"])


async def _get_tenant_db(x_tenant_id: str = Header(..., alias="X-Tenant-ID")):
    async for session in get_db_with_tenant(x_tenant_id):
        yield session


def _tid(x_tenant_id: str = Header(..., alias="X-Tenant-ID")) -> str:
    return x_tenant_id


# ─── 请求模型 ──


class BatchReceiveRequest(BaseModel):
    store_id: str
    species: str = Field(..., max_length=80)
    batch_no: str = Field(..., max_length=50)
    quantity: int = Field(..., gt=0)
    weight_g: int = Field(..., gt=0)
    unit_price_fen: int = Field(..., gt=0, description="进货单价(分/斤)")
    supplier_id: Optional[str] = None
    supplier_name: Optional[str] = None
    origin: Optional[str] = None


class TankAssignRequest(BaseModel):
    batch_id: str
    tank_id: str
    quantity: int = Field(..., gt=0)
    weight_g: int = Field(..., gt=0)


class MortalityRequest(BaseModel):
    store_id: str
    batch_id: Optional[str] = None
    tank_id: Optional[str] = None
    species: str
    dead_qty: int = Field(..., gt=0)
    dead_weight_g: int = Field(..., gt=0)
    cause: str = Field("unknown", description="natural/temperature/transport/unknown")
    notes: Optional[str] = None


# ─── 端点 ──


@router.post("/batch-receive", summary="活鲜批次入库")
async def batch_receive(
    body: BatchReceiveRequest,
    db: AsyncSession = Depends(_get_tenant_db),
    tenant_id: str = Depends(_tid),
):
    total_cost = body.weight_g * body.unit_price_fen // 500  # 斤=500g
    result = await db.execute(
        text("""
        INSERT INTO seafood_batches
            (tenant_id, store_id, supplier_id, supplier_name, species, batch_no,
             quantity, weight_g, unit_price_fen, total_cost_fen,
             remaining_qty, remaining_weight_g, origin)
        VALUES (:tid::UUID, :sid::UUID, :sup_id, :sup_name, :species, :batch_no,
                :qty, :wg, :price, :cost, :qty, :wg, :origin)
        RETURNING id, received_at
    """),
        {
            "tid": tenant_id,
            "sid": body.store_id,
            "sup_id": body.supplier_id,
            "sup_name": body.supplier_name,
            "species": body.species,
            "batch_no": body.batch_no,
            "qty": body.quantity,
            "wg": body.weight_g,
            "price": body.unit_price_fen,
            "cost": total_cost,
            "origin": body.origin,
        },
    )
    row = result.mappings().first()
    await db.commit()
    return {"ok": True, "data": {"id": str(row["id"]), "batch_no": body.batch_no, "total_cost_fen": total_cost}}


@router.get("/batches", summary="批次列表")
async def list_batches(
    store_id: Optional[str] = None,
    species: Optional[str] = None,
    status: Optional[str] = None,
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(_get_tenant_db),
    tenant_id: str = Depends(_tid),
):
    wheres = ["is_deleted=FALSE"]
    params: dict = {"lim": size, "off": (page - 1) * size}
    if store_id:
        wheres.append("store_id = :sid::UUID")
        params["sid"] = store_id
    if species:
        wheres.append("species ILIKE :sp")
        params["sp"] = f"%{species}%"
    if status:
        wheres.append("status = :st")
        params["st"] = status
    w = " AND ".join(wheres)

    total = (await db.execute(text(f"SELECT COUNT(*) FROM seafood_batches WHERE {w}"), params)).scalar() or 0
    result = await db.execute(
        text(f"""
        SELECT id, store_id, supplier_name, species, batch_no, quantity, weight_g,
               unit_price_fen, remaining_qty, remaining_weight_g, status, origin, received_at
        FROM seafood_batches WHERE {w}
        ORDER BY received_at DESC LIMIT :lim OFFSET :off
    """),
        params,
    )
    items = []
    for r in result.mappings().all():
        d = dict(r)
        for k, v in d.items():
            if isinstance(v, uuid.UUID):
                d[k] = str(v)
            elif isinstance(v, (datetime, date)):
                d[k] = v.isoformat()
        items.append(d)
    return {"ok": True, "data": {"items": items, "total": total, "page": page, "size": size}}


@router.get("/batches/{batch_id}/trace", summary="批次溯源链")
async def batch_trace(
    batch_id: str,
    db: AsyncSession = Depends(_get_tenant_db),
    tenant_id: str = Depends(_tid),
):
    batch = await db.execute(
        text("""
        SELECT id, supplier_name, species, batch_no, quantity, weight_g,
               origin, received_at, remaining_qty, status
        FROM seafood_batches WHERE id = :bid::UUID AND is_deleted=FALSE
    """),
        {"bid": batch_id},
    )
    b = batch.mappings().first()
    if not b:
        raise HTTPException(status_code=404, detail="批次不存在")

    # 缸位分配记录
    tanks = await db.execute(
        text("""
        SELECT t.tank_no, t.species, t.current_qty, t.current_weight_g, t.temperature_c, t.survival_rate
        FROM seafood_tanks t WHERE t.batch_id = :bid::UUID AND t.is_deleted=FALSE
    """),
        {"bid": batch_id},
    )

    # 损耗记录
    losses = await db.execute(
        text("""
        SELECT dead_qty, dead_weight_g, cause, recorded_at, notes
        FROM seafood_mortality_logs WHERE batch_id = :bid::UUID AND is_deleted=FALSE
        ORDER BY recorded_at
    """),
        {"bid": batch_id},
    )

    return {
        "ok": True,
        "data": {
            "batch": {
                k: (str(v) if isinstance(v, uuid.UUID) else v.isoformat() if isinstance(v, (datetime, date)) else v)
                for k, v in dict(b).items()
            },
            "tanks": [dict(r) for r in tanks.mappings().all()],
            "mortality": [dict(r) for r in losses.mappings().all()],
        },
    }


@router.post("/tank-assignment", summary="分配到缸位")
async def tank_assignment(
    body: TankAssignRequest,
    db: AsyncSession = Depends(_get_tenant_db),
    tenant_id: str = Depends(_tid),
):
    # 更新缸位
    await db.execute(
        text("""
        UPDATE seafood_tanks SET batch_id = :bid::UUID, current_qty = current_qty + :qty,
               current_weight_g = current_weight_g + :wg, updated_at = now()
        WHERE id = :tid::UUID AND is_deleted=FALSE
    """),
        {"bid": body.batch_id, "qty": body.quantity, "wg": body.weight_g, "tid": body.tank_id},
    )

    # 扣减批次剩余
    await db.execute(
        text("""
        UPDATE seafood_batches SET remaining_qty = remaining_qty - :qty,
               remaining_weight_g = remaining_weight_g - :wg
        WHERE id = :bid::UUID
    """),
        {"bid": body.batch_id, "qty": body.quantity, "wg": body.weight_g},
    )
    await db.commit()
    return {"ok": True, "data": {"tank_id": body.tank_id, "assigned_qty": body.quantity}}


@router.get("/tanks", summary="缸位状态总览")
async def list_tanks(
    store_id: str = Query(...),
    db: AsyncSession = Depends(_get_tenant_db),
    tenant_id: str = Depends(_tid),
):
    result = await db.execute(
        text("""
        SELECT id, tank_no, species, current_qty, current_weight_g,
               temperature_c, salinity_ppt, survival_rate, status, batch_id, updated_at
        FROM seafood_tanks WHERE store_id = :sid::UUID AND is_deleted=FALSE
        ORDER BY tank_no
    """),
        {"sid": store_id},
    )
    items = []
    for r in result.mappings().all():
        d = dict(r)
        for k, v in d.items():
            if isinstance(v, uuid.UUID):
                d[k] = str(v)
            elif isinstance(v, (datetime, date)):
                d[k] = v.isoformat()
        items.append(d)
    return {"ok": True, "data": {"store_id": store_id, "tanks": items}}


@router.post("/mortality", summary="记录死亡/损耗")
async def record_mortality(
    body: MortalityRequest,
    db: AsyncSession = Depends(_get_tenant_db),
    tenant_id: str = Depends(_tid),
):
    result = await db.execute(
        text("""
        INSERT INTO seafood_mortality_logs
            (tenant_id, store_id, batch_id, tank_id, species, dead_qty, dead_weight_g, cause, notes)
        VALUES (:tid::UUID, :sid::UUID, :bid, :tkid, :sp, :dq, :dw, :cause, :notes)
        RETURNING id, recorded_at
    """),
        {
            "tid": tenant_id,
            "sid": body.store_id,
            "bid": body.batch_id,
            "tkid": body.tank_id,
            "sp": body.species,
            "dq": body.dead_qty,
            "dw": body.dead_weight_g,
            "cause": body.cause,
            "notes": body.notes,
        },
    )
    row = result.mappings().first()

    # 更新缸位存活率
    if body.tank_id:
        await db.execute(
            text("""
            UPDATE seafood_tanks SET
                current_qty = GREATEST(0, current_qty - :dq),
                current_weight_g = GREATEST(0, current_weight_g - :dw),
                updated_at = now()
            WHERE id = :tid::UUID
        """),
            {"dq": body.dead_qty, "dw": body.dead_weight_g, "tid": body.tank_id},
        )

    await db.commit()
    return {"ok": True, "data": {"id": str(row["id"]), "species": body.species, "dead_qty": body.dead_qty}}


@router.get("/loss-report", summary="损耗报表")
async def loss_report(
    store_id: Optional[str] = None,
    start_date: str = Query(...),
    end_date: str = Query(...),
    db: AsyncSession = Depends(_get_tenant_db),
    tenant_id: str = Depends(_tid),
):
    store_filter = "AND m.store_id = :sid::UUID" if store_id else ""
    params: dict = {"sd": start_date, "ed": end_date}
    if store_id:
        params["sid"] = store_id

    result = await db.execute(
        text(f"""
        SELECT m.species,
               COUNT(*) AS incidents,
               SUM(m.dead_qty) AS total_dead_qty,
               SUM(m.dead_weight_g) AS total_dead_weight_g,
               b.supplier_name
        FROM seafood_mortality_logs m
        LEFT JOIN seafood_batches b ON b.id = m.batch_id
        WHERE m.is_deleted=FALSE
          AND m.recorded_at::date BETWEEN :sd::DATE AND :ed::DATE
          {store_filter}
        GROUP BY m.species, b.supplier_name
        ORDER BY total_dead_qty DESC
    """),
        params,
    )

    items = [dict(r) for r in result.mappings().all()]
    total_dead = sum(i.get("total_dead_qty", 0) or 0 for i in items)
    return {
        "ok": True,
        "data": {"items": items, "total_dead_qty": total_dead, "period": {"start": start_date, "end": end_date}},
    }
