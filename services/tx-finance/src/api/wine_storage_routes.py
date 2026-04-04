"""存酒管理 API 路由

端点：
  POST /api/v1/wine-storage/                          — 存酒
  POST /api/v1/wine-storage/{id}/retrieve             — 取酒（部分或全部）
  POST /api/v1/wine-storage/{id}/extend               — 续存（延长有效期）
  GET  /api/v1/wine-storage/{id}                      — 存酒详情
  GET  /api/v1/wine-storage/customer/{customer_id}    — 查询客户存酒列表
  GET  /api/v1/wine-storage/store/{store_id}          — 门店存酒列表
  GET  /api/v1/wine-storage/report/expiring           — 7天内到期存酒报表
  GET  /api/v1/wine-storage/report/summary            — 存酒汇总报表
"""
import asyncio
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Path, Query
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.events.src.emitter import emit_event
from shared.events.src.event_types import WineStorageEventType
from shared.ontology.src.database import get_db_with_tenant

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/wine-storage", tags=["存酒管理"])


# ─── 工具函数 ──────────────────────────────────────────────────────────────────

def _parse_uuid(val: str, field_name: str) -> uuid.UUID:
    try:
        return uuid.UUID(val)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"无效的 {field_name}: {val}") from exc


def _serialize_row(row: dict) -> dict:
    result = {}
    for k, v in row.items():
        if isinstance(v, uuid.UUID):
            result[k] = str(v)
        elif isinstance(v, datetime):
            result[k] = v.isoformat()
        elif isinstance(v, Decimal):
            result[k] = float(v)
        else:
            result[k] = v
    return result


# ─── 依赖注入 ──────────────────────────────────────────────────────────────────

async def _get_tenant_db(x_tenant_id: str = Header(..., alias="X-Tenant-ID")):
    async for session in get_db_with_tenant(x_tenant_id):
        yield session


# ─── 请求模型 ──────────────────────────────────────────────────────────────────

class WineStoreRequest(BaseModel):
    store_id: uuid.UUID
    customer_id: uuid.UUID                    # 存酒必须绑定会员
    source_order_id: uuid.UUID                # 来源订单
    wine_name: str
    wine_category: str                        # 白酒/红酒/啤酒/洋酒/其他
    quantity: float                           # 存入数量（支持小数瓶）
    unit: str = "瓶"
    estimated_value_fen: Optional[int] = None  # 酒水估值（分），可空
    cabinet_position: Optional[str] = None
    expires_days: int = 180                   # 有效期天数，默认 180 天
    photo_url: Optional[str] = None
    notes: Optional[str] = None


class WineRetrieveRequest(BaseModel):
    quantity: float                           # 取出数量（可部分取出）
    related_order_id: Optional[uuid.UUID] = None  # 关联订单（可空）
    remark: Optional[str] = None


class WineExtendRequest(BaseModel):
    extend_days: int                          # 延长天数
    remark: Optional[str] = None


# ─── POST / — 存酒 ────────────────────────────────────────────────────────────

@router.post("/", summary="存酒")
async def store_wine(
    body: WineStoreRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    x_operator_id: str = Header(..., alias="X-Operator-ID"),
    db: AsyncSession = Depends(_get_tenant_db),
):
    """新建存酒记录，同时写入操作日志。存酒必须绑定会员和来源订单。"""
    tid = _parse_uuid(x_tenant_id, "X-Tenant-ID")
    op_id = _parse_uuid(x_operator_id, "X-Operator-ID")

    valid_categories = {"白酒", "红酒", "啤酒", "洋酒", "其他"}
    if body.wine_category not in valid_categories:
        raise HTTPException(
            status_code=400,
            detail=f"wine_category 必须是: {', '.join(valid_categories)}",
        )

    if body.quantity <= 0:
        raise HTTPException(status_code=400, detail="存酒数量必须大于0")

    expires_at = datetime.now(timezone.utc) + timedelta(days=body.expires_days)

    try:
        result = await db.execute(
            text("""
                INSERT INTO biz_wine_storage (
                    tenant_id, store_id, customer_id, source_order_id,
                    wine_name, wine_category, quantity, original_qty,
                    unit, estimated_value_fen, cabinet_position,
                    status, stored_at, expires_at, operator_id, photo_url, notes
                ) VALUES (
                    :tenant_id::UUID, :store_id::UUID, :customer_id::UUID, :source_order_id::UUID,
                    :wine_name, :wine_category, :quantity, :quantity,
                    :unit, :estimated_value_fen, :cabinet_position,
                    'stored', NOW(), :expires_at, :operator_id::UUID, :photo_url, :notes
                )
                RETURNING id, status, stored_at, expires_at, quantity
            """),
            {
                "tenant_id": str(tid),
                "store_id": str(body.store_id),
                "customer_id": str(body.customer_id),
                "source_order_id": str(body.source_order_id),
                "wine_name": body.wine_name,
                "wine_category": body.wine_category,
                "quantity": body.quantity,
                "unit": body.unit,
                "estimated_value_fen": body.estimated_value_fen,
                "cabinet_position": body.cabinet_position,
                "expires_at": expires_at,
                "operator_id": str(op_id),
                "photo_url": body.photo_url,
                "notes": body.notes,
            },
        )
        row = result.mappings().first()
        storage_id = str(row["id"])

        # 写入操作日志
        await db.execute(
            text("""
                INSERT INTO biz_wine_storage_logs (
                    tenant_id, storage_id, action, quantity_change,
                    related_order_id, operator_id, remark
                ) VALUES (
                    :tenant_id::UUID, :storage_id::UUID, 'store', :quantity_change,
                    :related_order_id::UUID, :operator_id::UUID, :remark
                )
            """),
            {
                "tenant_id": str(tid),
                "storage_id": storage_id,
                "quantity_change": body.quantity,
                "related_order_id": str(body.source_order_id),
                "operator_id": str(op_id),
                "remark": body.notes,
            },
        )
        await db.commit()
    except Exception as exc:
        logger.error("store_wine.failed", customer_id=str(body.customer_id),
                     error=str(exc), exc_info=True)
        raise HTTPException(status_code=500, detail="存酒失败") from exc

    logger.info("wine_stored", storage_id=storage_id, wine_name=body.wine_name,
                quantity=body.quantity, customer_id=str(body.customer_id))

    asyncio.create_task(emit_event(
        event_type=WineStorageEventType.STORED,
        tenant_id=tid,
        stream_id=storage_id,
        payload={
            "storage_id": storage_id,
            "customer_id": str(body.customer_id),
            "wine_name": body.wine_name,
            "wine_category": body.wine_category,
            "quantity": body.quantity,
            "store_id": str(body.store_id),
        },
        store_id=body.store_id,
        source_service="tx-finance",
        metadata={"operator_id": str(op_id)},
    ))

    return {
        "ok": True,
        "data": {
            "storage_id": storage_id,
            "status": row["status"],
            "quantity": float(row["quantity"]) if row["quantity"] else body.quantity,
            "expires_at": row["expires_at"].isoformat() if row["expires_at"] else None,
            "stored_at": row["stored_at"].isoformat() if row["stored_at"] else None,
        },
        "error": None,
    }


# ─── POST /{id}/retrieve — 取酒 ───────────────────────────────────────────────

@router.post("/{storage_id}/retrieve", summary="取酒")
async def retrieve_wine(
    storage_id: str = Path(..., description="存酒记录ID"),
    body: WineRetrieveRequest = ...,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    x_operator_id: str = Header(..., alias="X-Operator-ID"),
    db: AsyncSession = Depends(_get_tenant_db),
):
    """取酒（部分或全部），更新剩余数量，写入操作日志。"""
    tid = _parse_uuid(x_tenant_id, "X-Tenant-ID")
    op_id = _parse_uuid(x_operator_id, "X-Operator-ID")
    sid = _parse_uuid(storage_id, "storage_id")

    if body.quantity <= 0:
        raise HTTPException(status_code=400, detail="取酒数量必须大于0")

    try:
        fetch = await db.execute(
            text("""
                SELECT id, quantity, status, customer_id, wine_name, store_id
                FROM biz_wine_storage
                WHERE id = :id::UUID AND tenant_id = :tenant_id::UUID
            """),
            {"id": str(sid), "tenant_id": str(tid)},
        )
        storage = fetch.mappings().first()
    except Exception as exc:
        logger.error("retrieve_wine.fetch_failed", storage_id=storage_id,
                     error=str(exc), exc_info=True)
        raise HTTPException(status_code=500, detail="查询存酒记录失败") from exc

    if storage is None:
        raise HTTPException(status_code=404, detail=f"存酒记录不存在: {storage_id}")

    if storage["status"] in ("fully_retrieved", "expired", "transferred", "written_off"):
        raise HTTPException(
            status_code=409,
            detail=f"存酒状态 {storage['status']} 不允许取酒",
        )

    current_qty = float(storage["quantity"])
    if body.quantity > current_qty:
        raise HTTPException(
            status_code=400,
            detail=f"取酒数量 {body.quantity} 超过剩余数量 {current_qty}",
        )

    new_qty = current_qty - body.quantity
    new_status = "fully_retrieved" if new_qty == 0 else "partially_retrieved"

    try:
        result = await db.execute(
            text("""
                UPDATE biz_wine_storage
                SET quantity = :new_qty,
                    status = :new_status,
                    updated_at = NOW()
                WHERE id = :id::UUID AND tenant_id = :tenant_id::UUID
                RETURNING id, quantity, status
            """),
            {
                "new_qty": new_qty,
                "new_status": new_status,
                "id": str(sid),
                "tenant_id": str(tid),
            },
        )
        row = result.mappings().first()

        # 写入操作日志（取酒为负数）
        await db.execute(
            text("""
                INSERT INTO biz_wine_storage_logs (
                    tenant_id, storage_id, action, quantity_change,
                    related_order_id, operator_id, remark
                ) VALUES (
                    :tenant_id::UUID, :storage_id::UUID, 'retrieve', :quantity_change,
                    :related_order_id, :operator_id::UUID, :remark
                )
            """),
            {
                "tenant_id": str(tid),
                "storage_id": storage_id,
                "quantity_change": -body.quantity,
                "related_order_id": (
                    str(body.related_order_id) if body.related_order_id else None
                ),
                "operator_id": str(op_id),
                "remark": body.remark,
            },
        )
        await db.commit()
    except Exception as exc:
        logger.error("retrieve_wine.update_failed", storage_id=storage_id,
                     error=str(exc), exc_info=True)
        raise HTTPException(status_code=500, detail="取酒失败") from exc

    logger.info("wine_retrieved", storage_id=storage_id, quantity_retrieved=body.quantity,
                quantity_remaining=new_qty)

    asyncio.create_task(emit_event(
        event_type=WineStorageEventType.RETRIEVED,
        tenant_id=tid,
        stream_id=storage_id,
        payload={
            "storage_id": storage_id,
            "customer_id": str(storage["customer_id"]),
            "quantity_retrieved": body.quantity,
            "quantity_remaining": new_qty,
            "new_status": new_status,
        },
        store_id=storage["store_id"],
        source_service="tx-finance",
        metadata={"operator_id": str(op_id)},
    ))

    return {
        "ok": True,
        "data": {
            "storage_id": storage_id,
            "status": row["status"],
            "quantity_retrieved": body.quantity,
            "quantity_remaining": float(row["quantity"]) if row["quantity"] else new_qty,
        },
        "error": None,
    }


# ─── POST /{id}/extend — 续存 ─────────────────────────────────────────────────

@router.post("/{storage_id}/extend", summary="续存（延长有效期）")
async def extend_storage(
    storage_id: str = Path(..., description="存酒记录ID"),
    body: WineExtendRequest = ...,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    x_operator_id: str = Header(..., alias="X-Operator-ID"),
    db: AsyncSession = Depends(_get_tenant_db),
):
    """延长存酒有效期，并写入续存操作日志。"""
    tid = _parse_uuid(x_tenant_id, "X-Tenant-ID")
    op_id = _parse_uuid(x_operator_id, "X-Operator-ID")
    sid = _parse_uuid(storage_id, "storage_id")

    if body.extend_days <= 0:
        raise HTTPException(status_code=400, detail="延长天数必须大于0")

    try:
        fetch = await db.execute(
            text("""
                SELECT id, expires_at, status
                FROM biz_wine_storage
                WHERE id = :id::UUID AND tenant_id = :tenant_id::UUID
            """),
            {"id": str(sid), "tenant_id": str(tid)},
        )
        storage = fetch.mappings().first()
    except Exception as exc:
        logger.error("extend_storage.fetch_failed", storage_id=storage_id,
                     error=str(exc), exc_info=True)
        raise HTTPException(status_code=500, detail="查询存酒记录失败") from exc

    if storage is None:
        raise HTTPException(status_code=404, detail=f"存酒记录不存在: {storage_id}")

    if storage["status"] in ("fully_retrieved", "transferred", "written_off"):
        raise HTTPException(
            status_code=409,
            detail=f"存酒状态 {storage['status']} 不允许续存",
        )

    old_expires = storage["expires_at"]
    new_expires = old_expires + timedelta(days=body.extend_days)

    try:
        result = await db.execute(
            text("""
                UPDATE biz_wine_storage
                SET expires_at = :new_expires,
                    status = CASE WHEN status = 'expired' THEN 'stored' ELSE status END,
                    updated_at = NOW()
                WHERE id = :id::UUID AND tenant_id = :tenant_id::UUID
                RETURNING id, expires_at, status
            """),
            {"new_expires": new_expires, "id": str(sid), "tenant_id": str(tid)},
        )
        row = result.mappings().first()

        # 写入操作日志
        await db.execute(
            text("""
                INSERT INTO biz_wine_storage_logs (
                    tenant_id, storage_id, action, quantity_change,
                    operator_id, remark
                ) VALUES (
                    :tenant_id::UUID, :storage_id::UUID, 'extend', 0,
                    :operator_id::UUID, :remark
                )
            """),
            {
                "tenant_id": str(tid),
                "storage_id": storage_id,
                "operator_id": str(op_id),
                "remark": body.remark or f"延长 {body.extend_days} 天",
            },
        )
        await db.commit()
    except Exception as exc:
        logger.error("extend_storage.update_failed", storage_id=storage_id,
                     error=str(exc), exc_info=True)
        raise HTTPException(status_code=500, detail="续存失败") from exc

    logger.info("wine_storage_extended", storage_id=storage_id,
                extend_days=body.extend_days,
                new_expires=new_expires.isoformat())

    return {
        "ok": True,
        "data": {
            "storage_id": storage_id,
            "status": row["status"],
            "old_expires_at": old_expires.isoformat() if old_expires else None,
            "new_expires_at": row["expires_at"].isoformat() if row["expires_at"] else None,
            "extended_days": body.extend_days,
        },
        "error": None,
    }


# ─── GET /{id} — 存酒详情 ─────────────────────────────────────────────────────

@router.get("/{storage_id}", summary="存酒详情")
async def get_storage(
    storage_id: str = Path(..., description="存酒记录ID"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_tenant_db),
):
    """获取单条存酒记录的完整详情，含操作日志。"""
    tid = _parse_uuid(x_tenant_id, "X-Tenant-ID")
    sid = _parse_uuid(storage_id, "storage_id")

    try:
        result = await db.execute(
            text("""
                SELECT id, store_id, customer_id, source_order_id,
                       wine_name, wine_category, quantity, original_qty, unit,
                       estimated_value_fen, cabinet_position, status,
                       stored_at, expires_at, operator_id, photo_url, notes,
                       created_at, updated_at
                FROM biz_wine_storage
                WHERE id = :id::UUID AND tenant_id = :tenant_id::UUID
            """),
            {"id": str(sid), "tenant_id": str(tid)},
        )
        row = result.mappings().first()
    except Exception as exc:
        logger.error("get_storage.failed", storage_id=storage_id,
                     error=str(exc), exc_info=True)
        raise HTTPException(status_code=500, detail="查询存酒记录失败") from exc

    if row is None:
        raise HTTPException(status_code=404, detail=f"存酒记录不存在: {storage_id}")

    try:
        logs_result = await db.execute(
            text("""
                SELECT id, action, quantity_change, related_order_id,
                       operator_id, remark, created_at
                FROM biz_wine_storage_logs
                WHERE storage_id = :storage_id::UUID AND tenant_id = :tenant_id::UUID
                ORDER BY created_at DESC
                LIMIT 20
            """),
            {"storage_id": storage_id, "tenant_id": str(tid)},
        )
        logs = [_serialize_row(dict(r)) for r in logs_result.mappings().all()]
    except Exception as exc:
        logger.warning("get_storage.logs_failed", storage_id=storage_id, error=str(exc))
        logs = []

    data = _serialize_row(dict(row))
    data["logs"] = logs
    return {"ok": True, "data": data, "error": None}


# ─── GET /customer/{customer_id} — 客户存酒列表 ──────────────────────────────

@router.get("/customer/{customer_id}", summary="客户存酒列表")
async def list_by_customer(
    customer_id: str = Path(..., description="会员ID"),
    status: Optional[str] = Query(None, description="状态筛选"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_tenant_db),
):
    """查询指定客户的所有存酒，默认返回所有状态。"""
    tid = _parse_uuid(x_tenant_id, "X-Tenant-ID")
    cid = _parse_uuid(customer_id, "customer_id")

    where_clauses = ["tenant_id = :tenant_id::UUID", "customer_id = :customer_id::UUID"]
    params: dict = {"tenant_id": str(tid), "customer_id": str(cid)}

    if status:
        where_clauses.append("status = :status")
        params["status"] = status

    where_sql = " AND ".join(where_clauses)
    offset = (page - 1) * size
    params["limit"] = size
    params["offset"] = offset

    try:
        count_result = await db.execute(
            text(f"SELECT COUNT(*) FROM biz_wine_storage WHERE {where_sql}"),
            params,
        )
        total = count_result.scalar()

        items_result = await db.execute(
            text(f"""
                SELECT id, store_id, wine_name, wine_category, quantity, original_qty,
                       unit, cabinet_position, status, stored_at, expires_at
                FROM biz_wine_storage
                WHERE {where_sql}
                ORDER BY stored_at DESC
                LIMIT :limit OFFSET :offset
            """),
            params,
        )
        items = [_serialize_row(dict(row)) for row in items_result.mappings().all()]
    except Exception as exc:
        logger.error("list_wine_by_customer.failed", customer_id=customer_id,
                     error=str(exc), exc_info=True)
        raise HTTPException(status_code=500, detail="查询客户存酒列表失败") from exc

    return {
        "ok": True,
        "data": {"items": items, "total": total, "page": page, "size": size},
        "error": None,
    }


# ─── GET /store/{store_id} — 门店存酒列表 ────────────────────────────────────

@router.get("/store/{store_id}", summary="门店存酒列表")
async def list_by_store(
    store_id: str = Path(..., description="门店ID"),
    status: Optional[str] = Query(None, description="状态筛选"),
    wine_category: Optional[str] = Query(None, description="酒类筛选"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_tenant_db),
):
    """查询指定门店的存酒列表。"""
    tid = _parse_uuid(x_tenant_id, "X-Tenant-ID")
    sid = _parse_uuid(store_id, "store_id")

    where_clauses = ["tenant_id = :tenant_id::UUID", "store_id = :store_id::UUID"]
    params: dict = {"tenant_id": str(tid), "store_id": str(sid)}

    if status:
        where_clauses.append("status = :status")
        params["status"] = status

    if wine_category:
        where_clauses.append("wine_category = :wine_category")
        params["wine_category"] = wine_category

    where_sql = " AND ".join(where_clauses)
    offset = (page - 1) * size
    params["limit"] = size
    params["offset"] = offset

    try:
        count_result = await db.execute(
            text(f"SELECT COUNT(*) FROM biz_wine_storage WHERE {where_sql}"),
            params,
        )
        total = count_result.scalar()

        items_result = await db.execute(
            text(f"""
                SELECT id, customer_id, wine_name, wine_category, quantity,
                       unit, cabinet_position, status, stored_at, expires_at
                FROM biz_wine_storage
                WHERE {where_sql}
                ORDER BY stored_at DESC
                LIMIT :limit OFFSET :offset
            """),
            params,
        )
        items = [_serialize_row(dict(row)) for row in items_result.mappings().all()]
    except Exception as exc:
        logger.error("list_wine_by_store.failed", store_id=store_id,
                     error=str(exc), exc_info=True)
        raise HTTPException(status_code=500, detail="查询门店存酒列表失败") from exc

    return {
        "ok": True,
        "data": {"items": items, "total": total, "page": page, "size": size},
        "error": None,
    }


# ─── GET /report/expiring — 7天内到期报表 ────────────────────────────────────

@router.get("/report/expiring", summary="即将到期存酒报表")
async def expiring_report(
    store_id: Optional[str] = Query(None, description="门店ID（不传则查所有门店）"),
    days_ahead: int = Query(7, ge=1, le=30, description="提前N天预警，默认7天"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_tenant_db),
):
    """列出 N 天内即将到期的存酒，用于主动联系客户。"""
    tid = _parse_uuid(x_tenant_id, "X-Tenant-ID")

    where_clauses = [
        "tenant_id = :tenant_id::UUID",
        "status IN ('stored', 'partially_retrieved')",
        "expires_at BETWEEN NOW() AND (NOW() + :days_ahead * INTERVAL '1 day')",
    ]
    params: dict = {"tenant_id": str(tid), "days_ahead": days_ahead}

    if store_id:
        sid = _parse_uuid(store_id, "store_id")
        where_clauses.append("store_id = :store_id::UUID")
        params["store_id"] = str(sid)

    where_sql = " AND ".join(where_clauses)

    try:
        result = await db.execute(
            text(f"""
                SELECT id, store_id, customer_id, wine_name, wine_category,
                       quantity, unit, cabinet_position, expires_at,
                       EXTRACT(DAY FROM expires_at - NOW())::INTEGER AS days_remaining
                FROM biz_wine_storage
                WHERE {where_sql}
                ORDER BY expires_at ASC
            """),
            params,
        )
        items = [_serialize_row(dict(row)) for row in result.mappings().all()]
    except Exception as exc:
        logger.error("wine_expiring_report.failed", error=str(exc), exc_info=True)
        raise HTTPException(status_code=500, detail="即将到期存酒报表生成失败") from exc

    return {
        "ok": True,
        "data": {
            "days_ahead": days_ahead,
            "total": len(items),
            "items": items,
        },
        "error": None,
    }


# ─── GET /report/summary — 存酒汇总报表 ──────────────────────────────────────

@router.get("/report/summary", summary="存酒汇总报表")
async def summary_report(
    store_id: str = Query(..., description="门店ID"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_tenant_db),
):
    """按门店和酒类汇总当前有效存酒数量和估值。"""
    tid = _parse_uuid(x_tenant_id, "X-Tenant-ID")
    sid = _parse_uuid(store_id, "store_id")

    try:
        result = await db.execute(
            text("""
                SELECT
                    wine_category,
                    COUNT(*) AS storage_count,
                    SUM(quantity) AS total_quantity,
                    COALESCE(SUM(estimated_value_fen), 0) AS total_estimated_value_fen
                FROM biz_wine_storage
                WHERE tenant_id = :tenant_id::UUID
                  AND store_id = :store_id::UUID
                  AND status IN ('stored', 'partially_retrieved')
                GROUP BY wine_category
                ORDER BY wine_category
            """),
            {"tenant_id": str(tid), "store_id": str(sid)},
        )
        by_category = [_serialize_row(dict(row)) for row in result.mappings().all()]

        total_result = await db.execute(
            text("""
                SELECT
                    COUNT(*) AS total_count,
                    COALESCE(SUM(quantity), 0) AS total_quantity,
                    COALESCE(SUM(estimated_value_fen), 0) AS total_estimated_value_fen
                FROM biz_wine_storage
                WHERE tenant_id = :tenant_id::UUID
                  AND store_id = :store_id::UUID
                  AND status IN ('stored', 'partially_retrieved')
            """),
            {"tenant_id": str(tid), "store_id": str(sid)},
        )
        totals = _serialize_row(dict(total_result.mappings().first()))
    except Exception as exc:
        logger.error("wine_summary_report.failed", store_id=store_id,
                     error=str(exc), exc_info=True)
        raise HTTPException(status_code=500, detail="存酒汇总报表生成失败") from exc

    return {
        "ok": True,
        "data": {
            "store_id": store_id,
            **totals,
            "by_category": by_category,
        },
        "error": None,
    }
