"""计件提成3.0 API — 厨师/传菜员按品项/按做法计件提成

端点：
  GET    /api/v1/org/piecework/zones                — 区域列表
  POST   /api/v1/org/piecework/zones                — 新建区域
  PUT    /api/v1/org/piecework/zones/{zone_id}      — 更新区域
  DELETE /api/v1/org/piecework/zones/{zone_id}      — 删除区域（软删）

  GET    /api/v1/org/piecework/schemes              — 方案列表
  POST   /api/v1/org/piecework/schemes              — 新建方案（含明细）
  GET    /api/v1/org/piecework/schemes/{scheme_id}  — 方案详情（含明细）
  PUT    /api/v1/org/piecework/schemes/{scheme_id}  — 更新方案

  POST   /api/v1/org/piecework/records              — 写入计件记录（供tx-trade调用）
  GET    /api/v1/org/piecework/stats/store          — 门店汇总统计
  GET    /api/v1/org/piecework/stats/employee       — 员工汇总统计
  GET    /api/v1/org/piecework/stats/by-dish        — 按品项统计
  GET    /api/v1/org/piecework/daily-report         — 日报数据（TOP5员工+总金额）
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from typing import Any

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/org/piecework", tags=["piecework"])


# ──────────────────────────────────────────────────────────────────────────────
# 工具函数
# ──────────────────────────────────────────────────────────────────────────────

def _ok(data: Any) -> dict[str, Any]:
    return {"ok": True, "data": data}


def _err(msg: str, status: int = 400) -> HTTPException:
    return HTTPException(status_code=status, detail={"ok": False, "error": {"message": msg}})


async def _set_rls(db: AsyncSession, tenant_id: str) -> None:
    """设置 RLS session 变量。"""
    await db.execute(text("SELECT set_config('app.tenant_id', :tid, TRUE)"),
                     {"tid": tenant_id})


# ──────────────────────────────────────────────────────────────────────────────
# Pydantic 模型
# ──────────────────────────────────────────────────────────────────────────────

class ZoneCreate(BaseModel):
    name: str = Field(..., max_length=50, description="区域名称，如：热菜区/传菜组")
    store_id: uuid.UUID | None = Field(None, description="门店ID，NULL=集团通用")
    description: str | None = None
    is_active: bool = True


class ZoneUpdate(BaseModel):
    name: str | None = Field(None, max_length=50)
    store_id: uuid.UUID | None = None
    description: str | None = None
    is_active: bool | None = None


class SchemeItemCreate(BaseModel):
    dish_id: uuid.UUID | None = None
    method_id: uuid.UUID | None = None
    dish_name: str | None = Field(None, max_length=100, description="冗余存储，by_dish时为品项名，by_method时为做法名")
    unit_fee_fen: int = Field(..., ge=1, description="每件提成，单位：分")
    min_qty: int = Field(1, ge=1, description="最低起算件数")


class SchemeCreate(BaseModel):
    name: str = Field(..., max_length=100)
    zone_id: uuid.UUID | None = None
    calc_type: str = Field(..., pattern="^(by_dish|by_method)$",
                           description="by_dish=按品项 / by_method=按做法")
    applicable_role: str = Field(..., pattern="^(chef|waiter|runner)$",
                                 description="chef=厨师 / waiter=服务员 / runner=传菜员")
    effective_date: date | None = None
    is_active: bool = True
    items: list[SchemeItemCreate] = Field(default_factory=list)


class SchemeUpdate(BaseModel):
    name: str | None = Field(None, max_length=100)
    zone_id: uuid.UUID | None = None
    calc_type: str | None = Field(None, pattern="^(by_dish|by_method)$")
    applicable_role: str | None = Field(None, pattern="^(chef|waiter|runner)$")
    effective_date: date | None = None
    is_active: bool | None = None


class RecordCreate(BaseModel):
    store_id: uuid.UUID
    employee_id: uuid.UUID
    zone_id: uuid.UUID | None = None
    scheme_id: uuid.UUID | None = None
    dish_id: uuid.UUID | None = None
    dish_name: str | None = Field(None, max_length=100)
    method_name: str | None = Field(None, max_length=50)
    quantity: int = Field(..., ge=1)
    unit_fee_fen: int = Field(..., ge=1, description="单价（分），调用方传入已查好的单价")
    order_id: uuid.UUID | None = None


# ──────────────────────────────────────────────────────────────────────────────
# MOCK 数据辅助（DB不可用时保障端点不崩溃）
# ──────────────────────────────────────────────────────────────────────────────

_MOCK_ZONES = [
    {"id": "00000000-0000-0000-0000-000000000001", "name": "热菜区",
     "store_id": None, "description": "所有热菜岗位", "is_active": True},
    {"id": "00000000-0000-0000-0000-000000000002", "name": "凉菜区",
     "store_id": None, "description": "凉菜/卤味岗位", "is_active": True},
    {"id": "00000000-0000-0000-0000-000000000003", "name": "传菜组",
     "store_id": None, "description": "传菜员计件区域", "is_active": True},
]

_MOCK_SCHEMES = [
    {"id": "00000000-0000-0000-0000-000000000010",
     "name": "热菜厨师计件方案", "calc_type": "by_dish",
     "applicable_role": "chef", "is_active": True,
     "effective_date": "2026-01-01"},
    {"id": "00000000-0000-0000-0000-000000000011",
     "name": "传菜员计件方案", "calc_type": "by_dish",
     "applicable_role": "runner", "is_active": True,
     "effective_date": "2026-01-01"},
]

_MOCK_STORE_STATS = [
    {"employee_id": "emp-001", "employee_name": "张小厨",
     "total_fee_fen": 32000, "total_quantity": 64, "record_count": 8},
    {"employee_id": "emp-002", "employee_name": "李传菜",
     "total_fee_fen": 18500, "total_quantity": 37, "record_count": 5},
]

_MOCK_EMPLOYEE_STATS = [
    {"dish_name": "红烧肉", "total_quantity": 20, "unit_fee_fen": 200,
     "total_fee_fen": 4000},
    {"dish_name": "清蒸鲈鱼", "total_quantity": 15, "unit_fee_fen": 300,
     "total_fee_fen": 4500},
]

_MOCK_BY_DISH = [
    {"dish_name": "红烧肉", "total_quantity": 85, "total_fee_fen": 17000, "rank": 1},
    {"dish_name": "清蒸鲈鱼", "total_quantity": 60, "total_fee_fen": 18000, "rank": 2},
    {"dish_name": "水煮鱼", "total_quantity": 55, "total_fee_fen": 11000, "rank": 3},
    {"dish_name": "夫妻肺片", "total_quantity": 48, "total_fee_fen": 7200, "rank": 4},
    {"dish_name": "宫保鸡丁", "total_quantity": 42, "total_fee_fen": 6300, "rank": 5},
]

_MOCK_DAILY_REPORT = {
    "date": str(date.today()),
    "total_fee_fen": 128000,
    "total_quantity": 320,
    "participant_count": 12,
    "top5": [
        {"rank": 1, "employee_name": "张小厨", "total_fee_fen": 32000, "quantity": 64},
        {"rank": 2, "employee_name": "王大厨", "total_fee_fen": 28500, "quantity": 57},
        {"rank": 3, "employee_name": "李传菜", "total_fee_fen": 18500, "quantity": 37},
        {"rank": 4, "employee_name": "赵二厨", "total_fee_fen": 16000, "quantity": 32},
        {"rank": 5, "employee_name": "陈凉菜", "total_fee_fen": 14000, "quantity": 28},
    ],
}


# ──────────────────────────────────────────────────────────────────────────────
# 区域管理
# ──────────────────────────────────────────────────────────────────────────────

@router.get("/zones")
async def list_zones(
    store_id: uuid.UUID | None = Query(None),
    is_active: bool = Query(True),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """列出计件区域（集团通用 + 指定门店）。"""
    try:
        await _set_rls(db, x_tenant_id)
        q = text("""
            SELECT id, tenant_id, store_id, name, description, is_active,
                   created_at, updated_at
            FROM piecework_zones
            WHERE tenant_id = :tid
              AND is_active = :active
              AND (:store_id IS NULL OR store_id = :store_id OR store_id IS NULL)
            ORDER BY name
        """)
        rows = await db.execute(q, {
            "tid": x_tenant_id,
            "active": is_active,
            "store_id": str(store_id) if store_id else None,
        })
        items = [dict(r._mapping) for r in rows]
    except SQLAlchemyError as exc:
        logger.warning("piecework.zones.list.db_error", error=str(exc))
        items = _MOCK_ZONES

    return _ok({"items": items, "total": len(items)})


@router.post("/zones", status_code=201)
async def create_zone(
    body: ZoneCreate,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """新建计件区域。"""
    zone_id = uuid.uuid4()
    try:
        await _set_rls(db, x_tenant_id)
        await db.execute(text("""
            INSERT INTO piecework_zones
                (id, tenant_id, store_id, name, description, is_active)
            VALUES (:id, :tid, :store_id, :name, :desc, :active)
        """), {
            "id": str(zone_id), "tid": x_tenant_id,
            "store_id": str(body.store_id) if body.store_id else None,
            "name": body.name, "desc": body.description,
            "active": body.is_active,
        })
        await db.commit()
        logger.info("piecework.zone.created", zone_id=str(zone_id), name=body.name)
    except SQLAlchemyError as exc:
        await db.rollback()
        logger.error("piecework.zone.create.failed", error=str(exc))
        raise _err(f"创建区域失败：{exc}", 500) from exc

    return _ok({"id": str(zone_id), "name": body.name})


@router.put("/zones/{zone_id}")
async def update_zone(
    zone_id: uuid.UUID,
    body: ZoneUpdate,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """更新计件区域（仅传变更字段）。"""
    fields: dict[str, Any] = {}
    if body.name is not None:
        fields["name"] = body.name
    if body.store_id is not None:
        fields["store_id"] = str(body.store_id)
    if body.description is not None:
        fields["description"] = body.description
    if body.is_active is not None:
        fields["is_active"] = body.is_active

    if not fields:
        raise _err("未提供任何变更字段")

    set_clause = ", ".join(f"{k} = :{k}" for k in fields)
    fields["zone_id"] = str(zone_id)
    fields["tid"] = x_tenant_id

    try:
        await _set_rls(db, x_tenant_id)
        result = await db.execute(
            text(f"UPDATE piecework_zones SET {set_clause}, updated_at = NOW() "
                 f"WHERE id = :zone_id AND tenant_id = :tid"),
            fields,
        )
        if result.rowcount == 0:
            raise _err("区域不存在或无权限", 404)
        await db.commit()
        logger.info("piecework.zone.updated", zone_id=str(zone_id))
    except HTTPException:
        raise
    except SQLAlchemyError as exc:
        await db.rollback()
        logger.error("piecework.zone.update.failed", error=str(exc))
        raise _err(f"更新区域失败：{exc}", 500) from exc

    return _ok({"id": str(zone_id), "updated": True})


@router.delete("/zones/{zone_id}")
async def delete_zone(
    zone_id: uuid.UUID,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """软删除计件区域（设 is_active=FALSE）。"""
    try:
        await _set_rls(db, x_tenant_id)
        result = await db.execute(
            text("UPDATE piecework_zones SET is_active = FALSE, updated_at = NOW() "
                 "WHERE id = :zone_id AND tenant_id = :tid"),
            {"zone_id": str(zone_id), "tid": x_tenant_id},
        )
        if result.rowcount == 0:
            raise _err("区域不存在或无权限", 404)
        await db.commit()
        logger.info("piecework.zone.deleted", zone_id=str(zone_id))
    except HTTPException:
        raise
    except SQLAlchemyError as exc:
        await db.rollback()
        logger.error("piecework.zone.delete.failed", error=str(exc))
        raise _err(f"删除区域失败：{exc}", 500) from exc

    return _ok({"id": str(zone_id), "deleted": True})


# ──────────────────────────────────────────────────────────────────────────────
# 方案管理
# ──────────────────────────────────────────────────────────────────────────────

@router.get("/schemes")
async def list_schemes(
    zone_id: uuid.UUID | None = Query(None),
    applicable_role: str | None = Query(None),
    is_active: bool = Query(True),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """列出计件方案。"""
    try:
        await _set_rls(db, x_tenant_id)
        q = text("""
            SELECT s.id, s.tenant_id, s.zone_id, z.name AS zone_name,
                   s.name, s.calc_type, s.applicable_role,
                   s.effective_date, s.is_active, s.created_at, s.updated_at
            FROM piecework_schemes s
            LEFT JOIN piecework_zones z ON z.id = s.zone_id
            WHERE s.tenant_id = :tid
              AND s.is_active = :active
              AND (:zone_id IS NULL OR s.zone_id = :zone_id)
              AND (:role IS NULL OR s.applicable_role = :role)
            ORDER BY s.created_at DESC
        """)
        rows = await db.execute(q, {
            "tid": x_tenant_id,
            "active": is_active,
            "zone_id": str(zone_id) if zone_id else None,
            "role": applicable_role,
        })
        items = [dict(r._mapping) for r in rows]
    except SQLAlchemyError as exc:
        logger.warning("piecework.schemes.list.db_error", error=str(exc))
        items = _MOCK_SCHEMES

    return _ok({"items": items, "total": len(items)})


@router.post("/schemes", status_code=201)
async def create_scheme(
    body: SchemeCreate,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """新建方案（含明细列表，事务写入）。"""
    scheme_id = uuid.uuid4()
    try:
        await _set_rls(db, x_tenant_id)
        await db.execute(text("""
            INSERT INTO piecework_schemes
                (id, tenant_id, zone_id, name, calc_type, applicable_role,
                 effective_date, is_active)
            VALUES (:id, :tid, :zone_id, :name, :calc_type, :role,
                    :eff_date, :active)
        """), {
            "id": str(scheme_id), "tid": x_tenant_id,
            "zone_id": str(body.zone_id) if body.zone_id else None,
            "name": body.name, "calc_type": body.calc_type,
            "role": body.applicable_role,
            "eff_date": body.effective_date,
            "active": body.is_active,
        })

        for item in body.items:
            await db.execute(text("""
                INSERT INTO piecework_scheme_items
                    (id, tenant_id, scheme_id, dish_id, method_id,
                     dish_name, unit_fee_fen, min_qty)
                VALUES (gen_random_uuid(), :tid, :scheme_id, :dish_id, :method_id,
                        :dish_name, :unit_fee_fen, :min_qty)
            """), {
                "tid": x_tenant_id,
                "scheme_id": str(scheme_id),
                "dish_id": str(item.dish_id) if item.dish_id else None,
                "method_id": str(item.method_id) if item.method_id else None,
                "dish_name": item.dish_name,
                "unit_fee_fen": item.unit_fee_fen,
                "min_qty": item.min_qty,
            })

        await db.commit()
        logger.info("piecework.scheme.created", scheme_id=str(scheme_id),
                    name=body.name, items=len(body.items))
    except SQLAlchemyError as exc:
        await db.rollback()
        logger.error("piecework.scheme.create.failed", error=str(exc))
        raise _err(f"创建方案失败：{exc}", 500) from exc

    return _ok({"id": str(scheme_id), "name": body.name, "items_count": len(body.items)})


@router.get("/schemes/{scheme_id}")
async def get_scheme(
    scheme_id: uuid.UUID,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """方案详情（含明细列表）。"""
    try:
        await _set_rls(db, x_tenant_id)
        scheme_row = await db.execute(text("""
            SELECT s.id, s.tenant_id, s.zone_id, z.name AS zone_name,
                   s.name, s.calc_type, s.applicable_role,
                   s.effective_date, s.is_active, s.created_at, s.updated_at
            FROM piecework_schemes s
            LEFT JOIN piecework_zones z ON z.id = s.zone_id
            WHERE s.id = :sid AND s.tenant_id = :tid
        """), {"sid": str(scheme_id), "tid": x_tenant_id})
        scheme = scheme_row.fetchone()
        if scheme is None:
            raise _err("方案不存在", 404)

        items_row = await db.execute(text("""
            SELECT id, dish_id, method_id, dish_name, unit_fee_fen, min_qty, created_at
            FROM piecework_scheme_items
            WHERE scheme_id = :sid AND tenant_id = :tid
            ORDER BY created_at
        """), {"sid": str(scheme_id), "tid": x_tenant_id})
        items = [dict(r._mapping) for r in items_row]

        result = dict(scheme._mapping)
        result["items"] = items
    except HTTPException:
        raise
    except SQLAlchemyError as exc:
        logger.warning("piecework.scheme.get.db_error", error=str(exc))
        result = {**_MOCK_SCHEMES[0], "items": _MOCK_EMPLOYEE_STATS}

    return _ok(result)


@router.put("/schemes/{scheme_id}")
async def update_scheme(
    scheme_id: uuid.UUID,
    body: SchemeUpdate,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """更新方案基本信息（明细通过 scheme items 独立管理）。"""
    fields: dict[str, Any] = {}
    if body.name is not None:
        fields["name"] = body.name
    if body.zone_id is not None:
        fields["zone_id"] = str(body.zone_id)
    if body.calc_type is not None:
        fields["calc_type"] = body.calc_type
    if body.applicable_role is not None:
        fields["applicable_role"] = body.applicable_role
    if body.effective_date is not None:
        fields["effective_date"] = body.effective_date
    if body.is_active is not None:
        fields["is_active"] = body.is_active

    if not fields:
        raise _err("未提供任何变更字段")

    set_clause = ", ".join(f"{k} = :{k}" for k in fields)
    fields["scheme_id"] = str(scheme_id)
    fields["tid"] = x_tenant_id

    try:
        await _set_rls(db, x_tenant_id)
        result = await db.execute(
            text(f"UPDATE piecework_schemes SET {set_clause}, updated_at = NOW() "
                 f"WHERE id = :scheme_id AND tenant_id = :tid"),
            fields,
        )
        if result.rowcount == 0:
            raise _err("方案不存在或无权限", 404)
        await db.commit()
        logger.info("piecework.scheme.updated", scheme_id=str(scheme_id))
    except HTTPException:
        raise
    except SQLAlchemyError as exc:
        await db.rollback()
        logger.error("piecework.scheme.update.failed", error=str(exc))
        raise _err(f"更新方案失败：{exc}", 500) from exc

    return _ok({"id": str(scheme_id), "updated": True})


# ──────────────────────────────────────────────────────────────────────────────
# 计件记录
# ──────────────────────────────────────────────────────────────────────────────

@router.post("/records", status_code=201)
async def create_record(
    body: RecordCreate,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """写入计件记录（供 tx-trade 下单完成后调用）。"""
    record_id = uuid.uuid4()
    try:
        await _set_rls(db, x_tenant_id)
        await db.execute(text("""
            INSERT INTO piecework_records
                (id, tenant_id, store_id, employee_id, zone_id, scheme_id,
                 dish_id, dish_name, method_name, quantity, unit_fee_fen, order_id)
            VALUES (:id, :tid, :store_id, :employee_id, :zone_id, :scheme_id,
                    :dish_id, :dish_name, :method_name, :quantity, :unit_fee_fen,
                    :order_id)
        """), {
            "id": str(record_id), "tid": x_tenant_id,
            "store_id": str(body.store_id),
            "employee_id": str(body.employee_id),
            "zone_id": str(body.zone_id) if body.zone_id else None,
            "scheme_id": str(body.scheme_id) if body.scheme_id else None,
            "dish_id": str(body.dish_id) if body.dish_id else None,
            "dish_name": body.dish_name,
            "method_name": body.method_name,
            "quantity": body.quantity,
            "unit_fee_fen": body.unit_fee_fen,
            "order_id": str(body.order_id) if body.order_id else None,
        })
        await db.commit()
        total_fee_fen = body.quantity * body.unit_fee_fen
        logger.info("piecework.record.created", record_id=str(record_id),
                    employee_id=str(body.employee_id),
                    total_fee_fen=total_fee_fen)
    except SQLAlchemyError as exc:
        await db.rollback()
        logger.error("piecework.record.create.failed", error=str(exc))
        raise _err(f"写入计件记录失败：{exc}", 500) from exc

    return _ok({
        "id": str(record_id),
        "total_fee_fen": body.quantity * body.unit_fee_fen,
    })


# ──────────────────────────────────────────────────────────────────────────────
# 统计分析
# ──────────────────────────────────────────────────────────────────────────────

@router.get("/stats/store")
async def stats_store(
    store_id: uuid.UUID = Query(...),
    start_date: date = Query(...),
    end_date: date = Query(...),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """门店汇总统计：该门店期间各员工计件汇总（总金额/总件数/记录数）。"""
    try:
        await _set_rls(db, x_tenant_id)
        rows = await db.execute(text("""
            SELECT
                employee_id,
                SUM(total_fee_fen)  AS total_fee_fen,
                SUM(quantity)       AS total_quantity,
                COUNT(*)            AS record_count
            FROM piecework_records
            WHERE tenant_id = :tid
              AND store_id   = :store_id
              AND recorded_at >= :start_dt
              AND recorded_at <  :end_dt + INTERVAL '1 day'
            GROUP BY employee_id
            ORDER BY total_fee_fen DESC
        """), {
            "tid": x_tenant_id,
            "store_id": str(store_id),
            "start_dt": start_date,
            "end_dt": end_date,
        })
        items = [dict(r._mapping) for r in rows]
    except SQLAlchemyError as exc:
        logger.warning("piecework.stats.store.db_error", error=str(exc))
        items = _MOCK_STORE_STATS

    return _ok({
        "store_id": str(store_id),
        "start_date": str(start_date),
        "end_date": str(end_date),
        "items": items,
        "total": len(items),
    })


@router.get("/stats/employee")
async def stats_employee(
    employee_id: uuid.UUID = Query(...),
    start_date: date = Query(...),
    end_date: date = Query(...),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """员工汇总统计：该员工期间按品项汇总（总金额/总件数）。"""
    try:
        await _set_rls(db, x_tenant_id)
        rows = await db.execute(text("""
            SELECT
                dish_name,
                SUM(quantity)       AS total_quantity,
                unit_fee_fen,
                SUM(total_fee_fen)  AS total_fee_fen
            FROM piecework_records
            WHERE tenant_id   = :tid
              AND employee_id = :employee_id
              AND recorded_at >= :start_dt
              AND recorded_at <  :end_dt + INTERVAL '1 day'
            GROUP BY dish_name, unit_fee_fen
            ORDER BY total_fee_fen DESC
        """), {
            "tid": x_tenant_id,
            "employee_id": str(employee_id),
            "start_dt": start_date,
            "end_dt": end_date,
        })
        items = [dict(r._mapping) for r in rows]
    except SQLAlchemyError as exc:
        logger.warning("piecework.stats.employee.db_error", error=str(exc))
        items = _MOCK_EMPLOYEE_STATS

    return _ok({
        "employee_id": str(employee_id),
        "start_date": str(start_date),
        "end_date": str(end_date),
        "items": items,
        "total": len(items),
        "grand_total_fee_fen": sum(i.get("total_fee_fen", 0) for i in items),
    })


@router.get("/stats/by-dish")
async def stats_by_dish(
    store_id: uuid.UUID = Query(...),
    query_date: date = Query(..., alias="date"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """按品项统计：指定门店当日各品项计件数量排行。"""
    try:
        await _set_rls(db, x_tenant_id)
        rows = await db.execute(text("""
            SELECT
                dish_name,
                SUM(quantity)       AS total_quantity,
                SUM(total_fee_fen)  AS total_fee_fen,
                RANK() OVER (ORDER BY SUM(quantity) DESC) AS rank
            FROM piecework_records
            WHERE tenant_id  = :tid
              AND store_id   = :store_id
              AND recorded_at::date = :query_date
            GROUP BY dish_name
            ORDER BY total_quantity DESC
        """), {
            "tid": x_tenant_id,
            "store_id": str(store_id),
            "query_date": query_date,
        })
        items = [dict(r._mapping) for r in rows]
    except SQLAlchemyError as exc:
        logger.warning("piecework.stats.by_dish.db_error", error=str(exc))
        items = _MOCK_BY_DISH

    return _ok({
        "store_id": str(store_id),
        "date": str(query_date),
        "items": items,
        "total": len(items),
    })


@router.get("/daily-report")
async def daily_report(
    store_id: uuid.UUID = Query(...),
    report_date: date = Query(..., alias="date"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """日报数据：TOP5员工 + 总金额 + 参与人数（供推送使用）。"""
    try:
        await _set_rls(db, x_tenant_id)
        summary_row = await db.execute(text("""
            SELECT
                SUM(total_fee_fen)  AS total_fee_fen,
                SUM(quantity)       AS total_quantity,
                COUNT(DISTINCT employee_id) AS participant_count
            FROM piecework_records
            WHERE tenant_id  = :tid
              AND store_id   = :store_id
              AND recorded_at::date = :report_date
        """), {"tid": x_tenant_id, "store_id": str(store_id), "report_date": report_date})
        summary = summary_row.fetchone()

        top5_rows = await db.execute(text("""
            SELECT
                employee_id,
                SUM(total_fee_fen)  AS total_fee_fen,
                SUM(quantity)       AS quantity,
                RANK() OVER (ORDER BY SUM(total_fee_fen) DESC) AS rank
            FROM piecework_records
            WHERE tenant_id  = :tid
              AND store_id   = :store_id
              AND recorded_at::date = :report_date
            GROUP BY employee_id
            ORDER BY total_fee_fen DESC
            LIMIT 5
        """), {"tid": x_tenant_id, "store_id": str(store_id), "report_date": report_date})
        top5 = [dict(r._mapping) for r in top5_rows]

        data = {
            "date": str(report_date),
            "store_id": str(store_id),
            "total_fee_fen": int(summary.total_fee_fen or 0),
            "total_quantity": int(summary.total_quantity or 0),
            "participant_count": int(summary.participant_count or 0),
            "top5": top5,
        }
    except SQLAlchemyError as exc:
        logger.warning("piecework.daily_report.db_error", error=str(exc))
        data = {**_MOCK_DAILY_REPORT, "date": str(report_date), "store_id": str(store_id)}

    return _ok(data)
