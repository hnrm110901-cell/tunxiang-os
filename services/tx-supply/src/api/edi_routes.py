"""
供应商EDI（电子数据交换）对接路由（v217表）

端点清单：
  POST /api/v1/supply/edi/order-push       — 电子采购订单推送给供应商
  POST /api/v1/supply/edi/delivery-confirm  — 供应商确认发货
  POST /api/v1/supply/edi/receive-confirm   — 门店确认收货
  GET  /api/v1/supply/edi/order-status      — EDI订单状态追踪

统一响应格式: {"ok": bool, "data": {}, "error": {}}
所有接口需 X-Tenant-ID header。
金额单位：分（int）。
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Optional

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from fastapi import status as http_status
from pydantic import BaseModel, Field
from sqlalchemy.exc import OperationalError, ProgrammingError, InterfaceError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import text

from shared.ontology.src.database import get_db_with_tenant

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/supply/edi", tags=["edi"])


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Pydantic 模型
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class EDIOrderItem(BaseModel):
    ingredient_id: str
    name: str
    qty: float = Field(gt=0)
    unit: str
    unit_price_fen: int = Field(ge=0)


class EDIOrderPushRequest(BaseModel):
    supplier_id: str
    supplier_name: Optional[str] = None
    store_id: str
    store_name: Optional[str] = None
    po_id: Optional[str] = None
    items: list[EDIOrderItem] = Field(..., min_length=1)
    notes: Optional[str] = None


class EDIDeliveryConfirmRequest(BaseModel):
    edi_order_id: str
    tracking_no: Optional[str] = None
    delivery_notes: Optional[str] = None


class EDIReceiveConfirmRequest(BaseModel):
    edi_order_id: str
    receive_notes: Optional[str] = None


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  辅助
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def _generate_edi_no() -> str:
    ym = datetime.now(timezone.utc).strftime("%Y%m")
    suffix = uuid.uuid4().hex[:6].upper()
    return f"EDI-{ym}-{suffix}"


def _db_unavailable_response() -> dict:
    return {
        "ok": False,
        "error": {
            "code": "DB_UNAVAILABLE",
            "message": "EDI服务暂时不可用，请稍后重试",
        },
    }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  端点
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.post("/order-push")
async def edi_order_push(
    body: EDIOrderPushRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db_with_tenant),
) -> dict[str, Any]:
    """电子采购订单推送给供应商。"""
    try:
        edi_no = _generate_edi_no()
        edi_id = str(uuid.uuid4())

        items_json = [item.model_dump() for item in body.items]
        total_amount_fen = sum(
            int(item.qty * item.unit_price_fen) for item in body.items
        )

        await db.execute(
            text("""
                INSERT INTO edi_orders
                    (id, tenant_id, edi_no, po_id, supplier_id, supplier_name,
                     store_id, store_name, items, total_amount_fen,
                     status, pushed_at, notes)
                VALUES
                    (:id, :tenant_id, :edi_no, :po_id, :supplier_id, :supplier_name,
                     :store_id, :store_name, :items::jsonb, :total_amount_fen,
                     'pushed', NOW(), :notes)
            """),
            {
                "id": edi_id,
                "tenant_id": x_tenant_id,
                "edi_no": edi_no,
                "po_id": body.po_id,
                "supplier_id": body.supplier_id,
                "supplier_name": body.supplier_name or "",
                "store_id": body.store_id,
                "store_name": body.store_name or "",
                "items": str(items_json).replace("'", '"'),
                "total_amount_fen": total_amount_fen,
                "notes": body.notes,
            },
        )
        await db.commit()

        # 回读
        result = await db.execute(
            text("""
                SELECT id, edi_no, po_id, supplier_id, supplier_name,
                       store_id, store_name, items, total_amount_fen,
                       status, pushed_at, notes, created_at
                FROM edi_orders WHERE id = :id
            """),
            {"id": edi_id},
        )
        row = dict(result.mappings().first())

        logger.info("edi_order_pushed", tenant_id=x_tenant_id, edi_id=edi_id,
                     edi_no=edi_no, supplier_id=body.supplier_id,
                     store_id=body.store_id, total_amount_fen=total_amount_fen)
        return {"ok": True, "data": row}

    except HTTPException:
        raise
    except (OperationalError, InterfaceError, ProgrammingError) as exc:
        await db.rollback()
        logger.error("edi_order_push_db_error", error=str(exc), tenant_id=x_tenant_id)
        raise HTTPException(status_code=http_status.HTTP_503_SERVICE_UNAVAILABLE,
                            detail=_db_unavailable_response())


@router.post("/delivery-confirm")
async def edi_delivery_confirm(
    body: EDIDeliveryConfirmRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db_with_tenant),
) -> dict[str, Any]:
    """供应商确认发货。"""
    try:
        result = await db.execute(
            text("""
                SELECT id, edi_no, status, supplier_id
                FROM edi_orders
                WHERE id = :edi_order_id AND is_deleted = FALSE
            """),
            {"edi_order_id": body.edi_order_id},
        )
        order = result.mappings().first()

        if order is None:
            raise HTTPException(
                status_code=404,
                detail={"ok": False, "error": {"code": "NOT_FOUND", "message": "EDI订单不存在"}},
            )

        if order["status"] not in ("pushed", "supplier_confirmed"):
            raise HTTPException(
                status_code=400,
                detail={
                    "ok": False,
                    "error": {
                        "code": "INVALID_STATUS",
                        "message": f"当前状态 '{order['status']}' 不可确认发货（需 pushed 或 supplier_confirmed）",
                    },
                },
            )

        update_params: dict[str, Any] = {
            "edi_order_id": body.edi_order_id,
        }
        set_parts = ["status = 'shipped'", "shipped_at = NOW()", "updated_at = NOW()"]

        if body.tracking_no:
            set_parts.append("tracking_no = :tracking_no")
            update_params["tracking_no"] = body.tracking_no
        if body.delivery_notes:
            set_parts.append("delivery_notes = :delivery_notes")
            update_params["delivery_notes"] = body.delivery_notes

        await db.execute(
            text(f"UPDATE edi_orders SET {', '.join(set_parts)} WHERE id = :edi_order_id"),
            update_params,
        )
        await db.commit()

        updated = await db.execute(
            text("""
                SELECT id, edi_no, supplier_id, supplier_name, store_id, store_name,
                       items, total_amount_fen, status, pushed_at, shipped_at,
                       tracking_no, delivery_notes, updated_at
                FROM edi_orders WHERE id = :edi_order_id
            """),
            {"edi_order_id": body.edi_order_id},
        )
        row = dict(updated.mappings().first())

        logger.info("edi_delivery_confirmed", tenant_id=x_tenant_id,
                     edi_order_id=body.edi_order_id, edi_no=order["edi_no"],
                     tracking_no=body.tracking_no)
        return {"ok": True, "data": row}

    except HTTPException:
        raise
    except (OperationalError, InterfaceError, ProgrammingError) as exc:
        await db.rollback()
        logger.error("edi_delivery_confirm_db_error", error=str(exc),
                     edi_order_id=body.edi_order_id)
        raise HTTPException(status_code=http_status.HTTP_503_SERVICE_UNAVAILABLE,
                            detail=_db_unavailable_response())


@router.post("/receive-confirm")
async def edi_receive_confirm(
    body: EDIReceiveConfirmRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db_with_tenant),
) -> dict[str, Any]:
    """门店确认收货。"""
    try:
        result = await db.execute(
            text("""
                SELECT id, edi_no, status, store_id
                FROM edi_orders
                WHERE id = :edi_order_id AND is_deleted = FALSE
            """),
            {"edi_order_id": body.edi_order_id},
        )
        order = result.mappings().first()

        if order is None:
            raise HTTPException(
                status_code=404,
                detail={"ok": False, "error": {"code": "NOT_FOUND", "message": "EDI订单不存在"}},
            )

        if order["status"] != "shipped":
            raise HTTPException(
                status_code=400,
                detail={
                    "ok": False,
                    "error": {
                        "code": "INVALID_STATUS",
                        "message": f"当前状态 '{order['status']}' 不可确认收货（需 shipped）",
                    },
                },
            )

        update_params: dict[str, Any] = {"edi_order_id": body.edi_order_id}
        set_parts = ["status = 'received'", "received_at = NOW()", "updated_at = NOW()"]

        if body.receive_notes:
            set_parts.append("receive_notes = :receive_notes")
            update_params["receive_notes"] = body.receive_notes

        await db.execute(
            text(f"UPDATE edi_orders SET {', '.join(set_parts)} WHERE id = :edi_order_id"),
            update_params,
        )
        await db.commit()

        updated = await db.execute(
            text("""
                SELECT id, edi_no, supplier_id, supplier_name, store_id, store_name,
                       items, total_amount_fen, status, pushed_at, shipped_at,
                       received_at, tracking_no, receive_notes, updated_at
                FROM edi_orders WHERE id = :edi_order_id
            """),
            {"edi_order_id": body.edi_order_id},
        )
        row = dict(updated.mappings().first())

        logger.info("edi_receive_confirmed", tenant_id=x_tenant_id,
                     edi_order_id=body.edi_order_id, edi_no=order["edi_no"])
        return {"ok": True, "data": row}

    except HTTPException:
        raise
    except (OperationalError, InterfaceError, ProgrammingError) as exc:
        await db.rollback()
        logger.error("edi_receive_confirm_db_error", error=str(exc),
                     edi_order_id=body.edi_order_id)
        raise HTTPException(status_code=http_status.HTTP_503_SERVICE_UNAVAILABLE,
                            detail=_db_unavailable_response())


@router.get("/order-status")
async def edi_order_status(
    supplier_id: Optional[str] = Query(default=None),
    store_id: Optional[str] = Query(default=None),
    status: Optional[str] = Query(default=None,
                                   description="pushed/supplier_confirmed/shipped/received/cancelled"),
    edi_no: Optional[str] = Query(default=None),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db_with_tenant),
) -> dict[str, Any]:
    """EDI订单状态追踪。"""
    try:
        where_clauses = ["is_deleted = FALSE"]
        params: dict[str, Any] = {"limit": size, "offset": (page - 1) * size}

        if supplier_id:
            where_clauses.append("supplier_id = :supplier_id")
            params["supplier_id"] = supplier_id
        if store_id:
            where_clauses.append("store_id = :store_id")
            params["store_id"] = store_id
        if status:
            where_clauses.append("status = :status")
            params["status"] = status
        if edi_no:
            where_clauses.append("edi_no = :edi_no")
            params["edi_no"] = edi_no

        where_sql = " AND ".join(where_clauses)

        result = await db.execute(
            text(f"""
                SELECT id, edi_no, po_id, supplier_id, supplier_name,
                       store_id, store_name, items, total_amount_fen,
                       status, pushed_at, supplier_confirmed_at, shipped_at,
                       received_at, tracking_no, delivery_notes, receive_notes,
                       notes, created_at, updated_at
                FROM edi_orders
                WHERE {where_sql}
                ORDER BY created_at DESC
                LIMIT :limit OFFSET :offset
            """),
            params,
        )
        rows = [dict(r) for r in result.mappings().all()]

        count_result = await db.execute(
            text(f"SELECT COUNT(*) FROM edi_orders WHERE {where_sql}"),
            {k: v for k, v in params.items() if k not in ("limit", "offset")},
        )
        total = count_result.scalar_one()

        # 状态汇总
        summary_result = await db.execute(
            text(f"""
                SELECT status, COUNT(*) AS cnt,
                       COALESCE(SUM(total_amount_fen), 0) AS amount_fen
                FROM edi_orders
                WHERE {where_sql}
                GROUP BY status
            """),
            {k: v for k, v in params.items() if k not in ("limit", "offset")},
        )
        status_summary = [dict(r) for r in summary_result.mappings().all()]

        logger.info("edi_order_status_queried", tenant_id=x_tenant_id,
                     total=total, filters={"supplier_id": supplier_id, "store_id": store_id,
                                           "status": status})
        return {
            "ok": True,
            "data": {
                "items": rows,
                "total": total,
                "page": page,
                "size": size,
                "status_summary": status_summary,
            },
        }

    except (OperationalError, InterfaceError, ProgrammingError) as exc:
        logger.error("edi_order_status_db_error", error=str(exc), tenant_id=x_tenant_id)
        raise HTTPException(status_code=http_status.HTTP_503_SERVICE_UNAVAILABLE,
                            detail=_db_unavailable_response())
