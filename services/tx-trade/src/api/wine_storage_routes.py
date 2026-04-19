"""存酒管理 API — 台位/会员维度存酒全生命周期管理

端点：
  POST /api/v1/wine-storage                          — 存酒入库
  GET  /api/v1/wine-storage                          — 存酒列表（分页+过滤）
  GET  /api/v1/wine-storage/{record_id}              — 存酒详情 + 历史流水
  POST /api/v1/wine-storage/{record_id}/take         — 取酒
  POST /api/v1/wine-storage/{record_id}/extend       — 续存
  POST /api/v1/wine-storage/{record_id}/transfer     — 转台
  POST /api/v1/wine-storage/{record_id}/write-off    — 核销
  GET  /api/v1/wine-storage/by-table/{table_id}      — 台位存酒快查（POS开台使用）
  GET  /api/v1/wine-storage/by-member/{member_id}    — 会员存酒列表
  GET  /api/v1/wine-storage/stats/summary            — 存酒台账统计

业务规则：
  - 取酒数量不能超过 remaining_quantity
  - 续存时更新 expiry_date
  - days_until_expiry < 7 时响应中标记 expiry_warning: true
  - 所有写操作同时创建 WineStorageTransaction 记录
  - 所有查询强制包含 tenant_id 过滤（RLS 安全）
"""

import uuid
from datetime import date, datetime, timezone
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db_with_tenant

from ..models.wine_storage import (
    WineExtendRequest,
    WineStoreRequest,
    WineTakeRequest,
    WineTransferRequest,
    WineWriteOffRequest,
)

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/api/v1/wine-storage", tags=["存酒管理"])


# ─── 依赖注入 ────────────────────────────────────────────────────────────────


async def _get_tenant_db(x_tenant_id: str = Header(..., alias="X-Tenant-ID")):
    async for session in get_db_with_tenant(x_tenant_id):
        yield session


def _tid(x_tenant_id: str = Header(..., alias="X-Tenant-ID")) -> str:
    return x_tenant_id


# ─── 工具函数 ─────────────────────────────────────────────────────────────────


def _calc_expiry_fields(expiry_date: Optional[date]) -> tuple[Optional[int], bool]:
    """计算距到期天数和到期预警标志。返回 (days_until_expiry, expiry_warning)"""
    if expiry_date is None:
        return None, False
    today = datetime.now(timezone.utc).date()
    days = (expiry_date - today).days
    return days, days < 7


def _serialize_record(row: dict, transactions: Optional[list] = None) -> dict:
    """将数据库行序列化为 API 响应字典"""
    expiry_date = row.get("expiry_date")
    days_until_expiry, expiry_warning = _calc_expiry_fields(expiry_date)

    out = {
        "id": str(row["id"]),
        "tenant_id": str(row["tenant_id"]),
        "store_id": row["store_id"],
        "table_id": row.get("table_id"),
        "member_id": str(row["member_id"]) if row.get("member_id") else None,
        "bottle_code": row["bottle_code"],
        "wine_name": row["wine_name"],
        "wine_brand": row.get("wine_brand"),
        "wine_spec": row.get("wine_spec"),
        "quantity": row["quantity"],
        "remaining_quantity": row["remaining_quantity"],
        "unit": row["unit"],
        "storage_date": row["storage_date"].isoformat()
        if isinstance(row["storage_date"], date)
        else row["storage_date"],
        "expiry_date": expiry_date.isoformat() if isinstance(expiry_date, date) else expiry_date,
        "status": row["status"],
        "storage_price": str(row["storage_price"]) if row.get("storage_price") is not None else None,
        "notes": row.get("notes"),
        "created_by": row.get("created_by"),
        "created_at": row["created_at"].isoformat()
        if isinstance(row.get("created_at"), datetime)
        else row.get("created_at"),
        "updated_at": row["updated_at"].isoformat()
        if isinstance(row.get("updated_at"), datetime)
        else row.get("updated_at"),
        "days_until_expiry": days_until_expiry,
        "expiry_warning": expiry_warning,
    }
    if transactions is not None:
        out["transactions"] = transactions
    return out


def _serialize_transaction(row: dict) -> dict:
    return {
        "id": str(row["id"]),
        "record_id": str(row["record_id"]),
        "trans_type": row["trans_type"],
        "quantity": row["quantity"],
        "price_at_trans": str(row["price_at_trans"]) if row.get("price_at_trans") is not None else None,
        "table_id": row.get("table_id"),
        "order_id": row.get("order_id"),
        "operated_by": row.get("operated_by"),
        "operated_at": row["operated_at"].isoformat()
        if isinstance(row.get("operated_at"), datetime)
        else row.get("operated_at"),
        "approved_by": row.get("approved_by"),
        "notes": row.get("notes"),
        "created_at": row["created_at"].isoformat()
        if isinstance(row.get("created_at"), datetime)
        else row.get("created_at"),
    }


# ─── 存酒入库 ─────────────────────────────────────────────────────────────────


@router.post("", summary="存酒入库")
async def store_wine(
    body: WineStoreRequest,
    db: AsyncSession = Depends(_get_tenant_db),
    tenant_id: str = Depends(_tid),
):
    """客人存酒入库：创建主记录并记录 store_in 流水。"""
    now = datetime.now(timezone.utc)
    record_id = uuid.uuid4()

    await db.execute(
        text("""
            INSERT INTO wine_storage_records
                (id, tenant_id, store_id, table_id, member_id,
                 bottle_code, wine_name, wine_brand, wine_spec,
                 quantity, remaining_quantity, unit,
                 storage_date, expiry_date, status,
                 storage_price, notes, created_by,
                 created_at, updated_at)
            VALUES
                (:id::UUID, :tid::UUID, :store_id, :table_id,
                 :member_id::UUID, :bottle_code, :wine_name, :wine_brand, :wine_spec,
                 :quantity, :quantity, :unit,
                 :storage_date, :expiry_date, 'stored',
                 :storage_price, :notes, :created_by,
                 :now, :now)
        """),
        {
            "id": str(record_id),
            "tid": tenant_id,
            "store_id": body.store_id,
            "table_id": body.table_id,
            "member_id": body.member_id,
            "bottle_code": body.bottle_code,
            "wine_name": body.wine_name,
            "wine_brand": body.wine_brand,
            "wine_spec": body.wine_spec,
            "quantity": body.quantity,
            "unit": body.unit,
            "storage_date": body.storage_date,
            "expiry_date": body.expiry_date,
            "storage_price": str(body.storage_price) if body.storage_price is not None else None,
            "notes": body.notes,
            "created_by": body.created_by,
            "now": now,
        },
    )

    # 记录 store_in 流水
    await db.execute(
        text("""
            INSERT INTO wine_storage_transactions
                (id, tenant_id, record_id, store_id, trans_type,
                 quantity, price_at_trans, table_id, order_id,
                 operated_by, operated_at, approved_by, notes,
                 created_at, updated_at)
            VALUES
                (gen_random_uuid(), :tid::UUID, :record_id::UUID, :store_id, 'store_in',
                 :quantity, :price_at_trans, :table_id, NULL,
                 :operated_by, :now, NULL, :notes,
                 :now, :now)
        """),
        {
            "tid": tenant_id,
            "record_id": str(record_id),
            "store_id": body.store_id,
            "quantity": body.quantity,
            "price_at_trans": str(body.storage_price) if body.storage_price is not None else None,
            "table_id": body.table_id,
            "operated_by": body.created_by,
            "now": now,
            "notes": body.notes,
        },
    )

    await db.commit()

    logger.info(
        "wine_storage.stored",
        record_id=str(record_id),
        wine_name=body.wine_name,
        quantity=body.quantity,
        tenant_id=tenant_id,
    )

    days_until_expiry, expiry_warning = _calc_expiry_fields(body.expiry_date)
    return {
        "ok": True,
        "data": {
            "id": str(record_id),
            "bottle_code": body.bottle_code,
            "wine_name": body.wine_name,
            "quantity": body.quantity,
            "remaining_quantity": body.quantity,
            "status": "stored",
            "days_until_expiry": days_until_expiry,
            "expiry_warning": expiry_warning,
        },
    }


# ─── 存酒列表 ─────────────────────────────────────────────────────────────────


@router.get("", summary="存酒列表（分页+多维过滤）")
async def list_wine_storage(
    store_id: Optional[str] = Query(None, description="按门店过滤"),
    member_id: Optional[str] = Query(None, description="按会员过滤"),
    status: Optional[str] = Query(None, description="按状态过滤，多个用逗号分隔"),
    bottle_code: Optional[str] = Query(None, description="按酒水编号精确匹配"),
    wine_name: Optional[str] = Query(None, description="按酒水名称模糊搜索"),
    storage_date_from: Optional[date] = Query(None),
    storage_date_to: Optional[date] = Query(None),
    expiry_warning_only: bool = Query(False, description="仅返回 7 天内到期记录"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(_get_tenant_db),
    tenant_id: str = Depends(_tid),
):
    """查询存酒列表，强制按 tenant_id 隔离，支持多维过滤和分页。"""
    conditions = ["tenant_id = :tid::UUID", "is_deleted = FALSE"]
    params: dict = {"tid": tenant_id}

    if store_id:
        conditions.append("store_id = :store_id")
        params["store_id"] = store_id

    if member_id:
        conditions.append("member_id = :member_id::UUID")
        params["member_id"] = member_id

    if status:
        status_list = [s.strip() for s in status.split(",") if s.strip()]
        if status_list:
            conditions.append("status = ANY(:status_list)")
            params["status_list"] = status_list

    if bottle_code:
        conditions.append("bottle_code = :bottle_code")
        params["bottle_code"] = bottle_code

    if wine_name:
        conditions.append("wine_name ILIKE :wine_name")
        params["wine_name"] = f"%{wine_name}%"

    if storage_date_from:
        conditions.append("storage_date >= :storage_date_from")
        params["storage_date_from"] = storage_date_from

    if storage_date_to:
        conditions.append("storage_date <= :storage_date_to")
        params["storage_date_to"] = storage_date_to

    if expiry_warning_only:
        today = datetime.now(timezone.utc).date()
        conditions.append("expiry_date IS NOT NULL AND expiry_date <= :warning_date")
        params["warning_date"] = (
            today.replace(day=today.day + 7)
            if today.day <= 24
            else (
                date(today.year, today.month + 1 if today.month < 12 else 1, today.day + 7 - 28)
                if today.month < 12
                else date(today.year + 1, 1, today.day + 7 - 28)
            )
        )
        # 使用更简洁的方式计算 7 天后
        from datetime import timedelta

        params["warning_date"] = today + timedelta(days=7)

    where_clause = " AND ".join(conditions)
    offset = (page - 1) * size

    count_r = await db.execute(
        text(f"SELECT COUNT(*) FROM wine_storage_records WHERE {where_clause}"),
        params,
    )
    total = count_r.scalar()

    rows_r = await db.execute(
        text(f"""
            SELECT id, tenant_id, store_id, table_id, member_id,
                   bottle_code, wine_name, wine_brand, wine_spec,
                   quantity, remaining_quantity, unit,
                   storage_date, expiry_date, status,
                   storage_price, notes, created_by,
                   created_at, updated_at
            FROM wine_storage_records
            WHERE {where_clause}
            ORDER BY created_at DESC
            LIMIT :size OFFSET :offset
        """),
        {**params, "size": size, "offset": offset},
    )
    items = [_serialize_record(dict(r)) for r in rows_r.mappings().all()]

    return {
        "ok": True,
        "data": {
            "items": items,
            "total": total,
            "page": page,
            "size": size,
        },
    }


# ─── 存酒详情 ─────────────────────────────────────────────────────────────────


@router.get("/stats/summary", summary="存酒台账统计（总量/总价值/即将过期数量）")
async def wine_storage_stats(
    store_id: Optional[str] = Query(None, description="按门店过滤"),
    db: AsyncSession = Depends(_get_tenant_db),
    tenant_id: str = Depends(_tid),
):
    """返回存酒台账汇总：总存量、总价值、活跃记录数、即将过期数量（7天内）。"""
    from datetime import timedelta

    params: dict = {"tid": tenant_id}
    store_filter = ""
    if store_id:
        store_filter = "AND store_id = :store_id"
        params["store_id"] = store_id

    warning_date = datetime.now(timezone.utc).date() + timedelta(days=7)
    params["warning_date"] = warning_date

    r = await db.execute(
        text(f"""
            SELECT
                COUNT(*) FILTER (WHERE status IN ('stored', 'partial_taken'))
                    AS active_count,
                COALESCE(SUM(remaining_quantity) FILTER (WHERE status IN ('stored', 'partial_taken')), 0)
                    AS total_remaining_quantity,
                COALESCE(SUM(storage_price) FILTER (WHERE status IN ('stored', 'partial_taken')), 0)
                    AS total_storage_value,
                COUNT(*) FILTER (
                    WHERE status IN ('stored', 'partial_taken')
                    AND expiry_date IS NOT NULL
                    AND expiry_date <= :warning_date
                ) AS expiring_soon_count,
                COUNT(*) FILTER (WHERE status = 'expired')
                    AS expired_count,
                COUNT(*) FILTER (WHERE status = 'written_off')
                    AS written_off_count
            FROM wine_storage_records
            WHERE tenant_id = :tid::UUID AND is_deleted = FALSE
            {store_filter}
        """),
        params,
    )
    row = dict(r.mappings().first())

    return {
        "ok": True,
        "data": {
            "active_count": row["active_count"],
            "total_remaining_quantity": row["total_remaining_quantity"],
            "total_storage_value": str(row["total_storage_value"]),
            "expiring_soon_count": row["expiring_soon_count"],
            "expired_count": row["expired_count"],
            "written_off_count": row["written_off_count"],
        },
    }


@router.get("/by-table/{table_id}", summary="台位存酒快查（POS 开台使用）")
async def list_wine_by_table(
    table_id: str,
    db: AsyncSession = Depends(_get_tenant_db),
    tenant_id: str = Depends(_tid),
):
    """查询指定台位的有效存酒记录，POS 开台时快速显示该台存酒。"""
    r = await db.execute(
        text("""
            SELECT id, tenant_id, store_id, table_id, member_id,
                   bottle_code, wine_name, wine_brand, wine_spec,
                   quantity, remaining_quantity, unit,
                   storage_date, expiry_date, status,
                   storage_price, notes, created_by,
                   created_at, updated_at
            FROM wine_storage_records
            WHERE tenant_id = :tid::UUID
              AND table_id = :table_id
              AND status IN ('stored', 'partial_taken')
              AND is_deleted = FALSE
            ORDER BY created_at DESC
        """),
        {"tid": tenant_id, "table_id": table_id},
    )
    items = [_serialize_record(dict(row)) for row in r.mappings().all()]
    return {"ok": True, "data": {"table_id": table_id, "items": items, "total": len(items)}}


@router.get("/by-member/{member_id}", summary="会员存酒列表")
async def list_wine_by_member(
    member_id: str,
    status: Optional[str] = Query(None, description="状态过滤，默认返回活跃记录"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(_get_tenant_db),
    tenant_id: str = Depends(_tid),
):
    """查询指定会员名下所有存酒记录，支持状态过滤和分页。"""
    conditions = [
        "tenant_id = :tid::UUID",
        "member_id = :member_id::UUID",
        "is_deleted = FALSE",
    ]
    params: dict = {"tid": tenant_id, "member_id": member_id}

    if status:
        status_list = [s.strip() for s in status.split(",") if s.strip()]
        if status_list:
            conditions.append("status = ANY(:status_list)")
            params["status_list"] = status_list
    else:
        conditions.append("status IN ('stored', 'partial_taken')")

    where_clause = " AND ".join(conditions)
    offset = (page - 1) * size

    count_r = await db.execute(
        text(f"SELECT COUNT(*) FROM wine_storage_records WHERE {where_clause}"),
        params,
    )
    total = count_r.scalar()

    rows_r = await db.execute(
        text(f"""
            SELECT id, tenant_id, store_id, table_id, member_id,
                   bottle_code, wine_name, wine_brand, wine_spec,
                   quantity, remaining_quantity, unit,
                   storage_date, expiry_date, status,
                   storage_price, notes, created_by,
                   created_at, updated_at
            FROM wine_storage_records
            WHERE {where_clause}
            ORDER BY created_at DESC
            LIMIT :size OFFSET :offset
        """),
        {**params, "size": size, "offset": offset},
    )
    items = [_serialize_record(dict(r)) for r in rows_r.mappings().all()]

    return {
        "ok": True,
        "data": {
            "member_id": member_id,
            "items": items,
            "total": total,
            "page": page,
            "size": size,
        },
    }


@router.get("/{record_id}", summary="存酒详情 + 历史操作流水")
async def get_wine_storage_detail(
    record_id: str,
    db: AsyncSession = Depends(_get_tenant_db),
    tenant_id: str = Depends(_tid),
):
    """获取存酒主记录详情及全部操作流水（取酒/续存/转台/核销历史）。"""
    row_r = await db.execute(
        text("""
            SELECT id, tenant_id, store_id, table_id, member_id,
                   bottle_code, wine_name, wine_brand, wine_spec,
                   quantity, remaining_quantity, unit,
                   storage_date, expiry_date, status,
                   storage_price, notes, created_by,
                   created_at, updated_at
            FROM wine_storage_records
            WHERE id = :rid::UUID AND tenant_id = :tid::UUID AND is_deleted = FALSE
        """),
        {"rid": record_id, "tid": tenant_id},
    )
    row = row_r.mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail="存酒记录不存在")

    trans_r = await db.execute(
        text("""
            SELECT id, record_id, trans_type, quantity, price_at_trans,
                   table_id, order_id, operated_by, operated_at,
                   approved_by, notes, created_at
            FROM wine_storage_transactions
            WHERE record_id = :rid::UUID AND tenant_id = :tid::UUID
            ORDER BY created_at DESC
        """),
        {"rid": record_id, "tid": tenant_id},
    )
    transactions = [_serialize_transaction(dict(t)) for t in trans_r.mappings().all()]

    return {"ok": True, "data": _serialize_record(dict(row), transactions=transactions)}


# ─── 取酒 ─────────────────────────────────────────────────────────────────────


@router.post("/{record_id}/take", summary="取酒")
async def take_wine(
    record_id: str,
    body: WineTakeRequest,
    db: AsyncSession = Depends(_get_tenant_db),
    tenant_id: str = Depends(_tid),
):
    """从指定存酒记录中取出酒水，更新剩余数量和状态，记录 take_out 流水。"""
    # 加 FOR UPDATE 锁防止并发超取
    row_r = await db.execute(
        text("""
            SELECT id, remaining_quantity, status, store_id, wine_name
            FROM wine_storage_records
            WHERE id = :rid::UUID AND tenant_id = :tid::UUID AND is_deleted = FALSE
            FOR UPDATE
        """),
        {"rid": record_id, "tid": tenant_id},
    )
    row = row_r.mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail="存酒记录不存在")

    if row["status"] in ("fully_taken", "expired", "written_off"):
        raise HTTPException(status_code=400, detail=f"存酒状态 {row['status']} 不允许取酒")

    if body.quantity > row["remaining_quantity"]:
        raise HTTPException(
            status_code=400,
            detail=f"取酒数量 {body.quantity} 超过剩余数量 {row['remaining_quantity']}",
        )

    new_remaining = row["remaining_quantity"] - body.quantity
    new_status = "fully_taken" if new_remaining == 0 else "partial_taken"
    now = datetime.now(timezone.utc)

    await db.execute(
        text("""
            UPDATE wine_storage_records
            SET remaining_quantity = :remaining,
                status = :status,
                updated_at = :now
            WHERE id = :rid::UUID
        """),
        {"remaining": new_remaining, "status": new_status, "now": now, "rid": record_id},
    )

    await db.execute(
        text("""
            INSERT INTO wine_storage_transactions
                (id, tenant_id, record_id, store_id, trans_type,
                 quantity, price_at_trans, table_id, order_id,
                 operated_by, operated_at, approved_by, notes,
                 created_at, updated_at)
            VALUES
                (gen_random_uuid(), :tid::UUID, :record_id::UUID, :store_id, 'take_out',
                 :quantity, NULL, :table_id, :order_id,
                 :operated_by, :now, NULL, :notes,
                 :now, :now)
        """),
        {
            "tid": tenant_id,
            "record_id": record_id,
            "store_id": row["store_id"],
            "quantity": body.quantity,
            "table_id": body.table_id,
            "order_id": body.order_id,
            "operated_by": body.operated_by,
            "now": now,
            "notes": body.notes,
        },
    )

    await db.commit()

    logger.info(
        "wine_storage.taken",
        record_id=record_id,
        quantity=body.quantity,
        remaining=new_remaining,
        tenant_id=tenant_id,
    )
    return {
        "ok": True,
        "data": {
            "record_id": record_id,
            "wine_name": row["wine_name"],
            "taken_quantity": body.quantity,
            "remaining_quantity": new_remaining,
            "status": new_status,
        },
    }


# ─── 续存 ─────────────────────────────────────────────────────────────────────


@router.post("/{record_id}/extend", summary="续存（延长到期日）")
async def extend_wine_storage(
    record_id: str,
    body: WineExtendRequest,
    db: AsyncSession = Depends(_get_tenant_db),
    tenant_id: str = Depends(_tid),
):
    """延长存酒到期日，可选收取续存费用，记录 extend 流水。"""
    row_r = await db.execute(
        text("""
            SELECT id, status, store_id, wine_name, expiry_date
            FROM wine_storage_records
            WHERE id = :rid::UUID AND tenant_id = :tid::UUID AND is_deleted = FALSE
        """),
        {"rid": record_id, "tid": tenant_id},
    )
    row = row_r.mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail="存酒记录不存在")

    if row["status"] in ("fully_taken", "written_off"):
        raise HTTPException(status_code=400, detail=f"存酒状态 {row['status']} 不允许续存")

    now = datetime.now(timezone.utc)

    # 续存时重置状态（expired → stored）
    new_status = row["status"] if row["status"] != "expired" else "stored"

    await db.execute(
        text("""
            UPDATE wine_storage_records
            SET expiry_date = :new_expiry_date,
                status = :status,
                updated_at = :now
            WHERE id = :rid::UUID
        """),
        {
            "new_expiry_date": body.new_expiry_date,
            "status": new_status,
            "now": now,
            "rid": record_id,
        },
    )

    await db.execute(
        text("""
            INSERT INTO wine_storage_transactions
                (id, tenant_id, record_id, store_id, trans_type,
                 quantity, price_at_trans, table_id, order_id,
                 operated_by, operated_at, approved_by, notes,
                 created_at, updated_at)
            VALUES
                (gen_random_uuid(), :tid::UUID, :record_id::UUID, :store_id, 'extend',
                 0, :fee, NULL, NULL,
                 :operated_by, :now, NULL, :notes,
                 :now, :now)
        """),
        {
            "tid": tenant_id,
            "record_id": record_id,
            "store_id": row["store_id"],
            "fee": str(body.fee) if body.fee is not None else None,
            "operated_by": body.operated_by,
            "now": now,
            "notes": body.notes or f"续存至 {body.new_expiry_date}",
        },
    )

    await db.commit()

    days_until_expiry, expiry_warning = _calc_expiry_fields(body.new_expiry_date)
    logger.info(
        "wine_storage.extended",
        record_id=record_id,
        new_expiry_date=str(body.new_expiry_date),
        tenant_id=tenant_id,
    )
    return {
        "ok": True,
        "data": {
            "record_id": record_id,
            "wine_name": row["wine_name"],
            "old_expiry_date": row["expiry_date"].isoformat()
            if isinstance(row.get("expiry_date"), date)
            else row.get("expiry_date"),
            "new_expiry_date": body.new_expiry_date.isoformat(),
            "days_until_expiry": days_until_expiry,
            "expiry_warning": expiry_warning,
            "status": new_status,
        },
    }


# ─── 转台 ─────────────────────────────────────────────────────────────────────


@router.post("/{record_id}/transfer", summary="转台（变更关联台位）")
async def transfer_wine(
    record_id: str,
    body: WineTransferRequest,
    db: AsyncSession = Depends(_get_tenant_db),
    tenant_id: str = Depends(_tid),
):
    """将存酒记录关联台位从当前台位变更为目标台位，记录 transfer_out + transfer_in 流水。"""
    row_r = await db.execute(
        text("""
            SELECT id, status, store_id, wine_name, table_id, remaining_quantity
            FROM wine_storage_records
            WHERE id = :rid::UUID AND tenant_id = :tid::UUID AND is_deleted = FALSE
        """),
        {"rid": record_id, "tid": tenant_id},
    )
    row = row_r.mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail="存酒记录不存在")

    if row["status"] in ("fully_taken", "written_off"):
        raise HTTPException(status_code=400, detail=f"存酒状态 {row['status']} 不允许转台")

    from_table_id = row["table_id"]
    if from_table_id == body.to_table_id:
        raise HTTPException(status_code=400, detail="目标台位与当前台位相同")

    now = datetime.now(timezone.utc)

    await db.execute(
        text("""
            UPDATE wine_storage_records
            SET table_id = :to_table_id,
                updated_at = :now
            WHERE id = :rid::UUID
        """),
        {"to_table_id": body.to_table_id, "now": now, "rid": record_id},
    )

    # 记录 transfer_out 流水（原台位）
    await db.execute(
        text("""
            INSERT INTO wine_storage_transactions
                (id, tenant_id, record_id, store_id, trans_type,
                 quantity, price_at_trans, table_id, order_id,
                 operated_by, operated_at, approved_by, notes,
                 created_at, updated_at)
            VALUES
                (gen_random_uuid(), :tid::UUID, :record_id::UUID, :store_id, 'transfer_out',
                 :quantity, NULL, :from_table_id, NULL,
                 :operated_by, :now, NULL, :notes,
                 :now, :now)
        """),
        {
            "tid": tenant_id,
            "record_id": record_id,
            "store_id": row["store_id"],
            "quantity": row["remaining_quantity"],
            "from_table_id": from_table_id,
            "operated_by": body.operated_by,
            "now": now,
            "notes": body.notes or f"转台至 {body.to_table_id}",
        },
    )

    # 记录 transfer_in 流水（目标台位）
    await db.execute(
        text("""
            INSERT INTO wine_storage_transactions
                (id, tenant_id, record_id, store_id, trans_type,
                 quantity, price_at_trans, table_id, order_id,
                 operated_by, operated_at, approved_by, notes,
                 created_at, updated_at)
            VALUES
                (gen_random_uuid(), :tid::UUID, :record_id::UUID, :store_id, 'transfer_in',
                 :quantity, NULL, :to_table_id, NULL,
                 :operated_by, :now, NULL, :notes,
                 :now, :now)
        """),
        {
            "tid": tenant_id,
            "record_id": record_id,
            "store_id": row["store_id"],
            "quantity": row["remaining_quantity"],
            "to_table_id": body.to_table_id,
            "operated_by": body.operated_by,
            "now": now,
            "notes": body.notes or f"从 {from_table_id} 转入",
        },
    )

    await db.commit()

    logger.info(
        "wine_storage.transferred",
        record_id=record_id,
        from_table=from_table_id,
        to_table=body.to_table_id,
        tenant_id=tenant_id,
    )
    return {
        "ok": True,
        "data": {
            "record_id": record_id,
            "wine_name": row["wine_name"],
            "from_table_id": from_table_id,
            "to_table_id": body.to_table_id,
        },
    }


# ─── 核销 ─────────────────────────────────────────────────────────────────────


@router.post("/{record_id}/write-off", summary="核销存酒（管理员操作）")
async def write_off_wine(
    record_id: str,
    body: WineWriteOffRequest,
    db: AsyncSession = Depends(_get_tenant_db),
    tenant_id: str = Depends(_tid),
):
    """核销存酒记录（过期处理/损耗/特殊情况），需要审批人确认，记录 write_off 流水。"""
    row_r = await db.execute(
        text("""
            SELECT id, status, store_id, wine_name, remaining_quantity
            FROM wine_storage_records
            WHERE id = :rid::UUID AND tenant_id = :tid::UUID AND is_deleted = FALSE
        """),
        {"rid": record_id, "tid": tenant_id},
    )
    row = row_r.mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail="存酒记录不存在")

    if row["status"] in ("fully_taken", "written_off"):
        raise HTTPException(status_code=400, detail=f"存酒状态 {row['status']} 不允许核销")

    now = datetime.now(timezone.utc)

    await db.execute(
        text("""
            UPDATE wine_storage_records
            SET status = 'written_off',
                updated_at = :now
            WHERE id = :rid::UUID
        """),
        {"now": now, "rid": record_id},
    )

    await db.execute(
        text("""
            INSERT INTO wine_storage_transactions
                (id, tenant_id, record_id, store_id, trans_type,
                 quantity, price_at_trans, table_id, order_id,
                 operated_by, operated_at, approved_by, notes,
                 created_at, updated_at)
            VALUES
                (gen_random_uuid(), :tid::UUID, :record_id::UUID, :store_id, 'write_off',
                 :quantity, NULL, NULL, :order_id,
                 :operated_by, :now, :approved_by, :notes,
                 :now, :now)
        """),
        {
            "tid": tenant_id,
            "record_id": record_id,
            "store_id": row["store_id"],
            "quantity": row["remaining_quantity"],
            "order_id": body.order_id,
            "operated_by": body.operated_by,
            "now": now,
            "approved_by": body.approved_by,
            "notes": body.reason,
        },
    )

    await db.commit()

    logger.info(
        "wine_storage.written_off",
        record_id=record_id,
        reason=body.reason,
        approved_by=body.approved_by,
        tenant_id=tenant_id,
    )
    return {
        "ok": True,
        "data": {
            "record_id": record_id,
            "wine_name": row["wine_name"],
            "written_off_quantity": row["remaining_quantity"],
            "reason": body.reason,
            "status": "written_off",
        },
    }
