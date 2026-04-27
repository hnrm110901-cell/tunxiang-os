"""供应链移动端 + EDI 路由（模块 3.3）

端点清单：
  # 移动采购
  POST /api/v1/supply/mobile/purchase-request              — 扫码采购申请
  GET  /api/v1/supply/mobile/purchase-requests             — 我的采购申请列表
  POST /api/v1/supply/mobile/purchase-requests/{id}/approve — 审批采购申请

  # 移动收货
  POST /api/v1/supply/mobile/receive                       — 扫码确认收货（更新库存）
  GET  /api/v1/supply/mobile/pending-receipts              — 待收货采购单列表

  # 移动盘点
  POST /api/v1/supply/mobile/stocktake/start               — 开始盘点任务
  POST /api/v1/supply/mobile/stocktake/item                — 录入盘点条目
  POST /api/v1/supply/mobile/stocktake/{id}/submit         — 提交盘点

  # 门店间调拨（扩展）
  POST /api/v1/supply/transfers                            — 发起调拨申请（重用transfer_router前置路由）
  GET  /api/v1/supply/transfers                            — 调拨列表
  POST /api/v1/supply/transfers/{id}/approve               — 审批
  POST /api/v1/supply/transfers/{id}/execute               — 执行（库存联动）

  # 供应商EDI门户（扩展）
  GET  /api/v1/supply/edi/orders                           — 供应商查看采购单
  POST /api/v1/supply/edi/orders/{id}/confirm              — 供应商确认发货

统一响应格式: {"ok": bool, "data": {}, "error": {}}
金额单位：分（int）。
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from typing import List, Optional

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.exc import InterfaceError, OperationalError, ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import text

from shared.events.src.emitter import emit_event
from shared.events.src.event_types import InventoryEventType
from shared.ontology.src.database import get_db as _get_db

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/supply/mobile", tags=["supply-mobile"])
transfer_ext_router = APIRouter(prefix="/api/v1/supply/transfers", tags=["supply-transfers-ext"])
edi_ext_router = APIRouter(prefix="/api/v1/supply/edi", tags=["supply-edi-ext"])


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Pydantic 模型
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


# ── 采购申请 ──────────────────────────────────────────────


class MobilePurchaseRequestIn(BaseModel):
    store_id: str
    barcode: Optional[str] = None  # 条码（扫码或手动）
    ingredient_id: Optional[str] = None  # 食材ID（已知时直传）
    ingredient_name: str
    quantity: float = Field(gt=0)
    unit: str
    unit_price_fen: int = Field(ge=0, description="预估单价（分）")
    supplier_id: Optional[str] = None
    supplier_name: Optional[str] = None
    requested_by: Optional[str] = None
    notes: Optional[str] = None


class ApprovePurchaseRequestIn(BaseModel):
    approved_by: str
    approved_quantity: Optional[float] = None  # None 时按申请数量全量审批
    unit_price_fen: Optional[int] = None
    notes: Optional[str] = None


# ── 移动收货 ──────────────────────────────────────────────


class MobileReceiveItemIn(BaseModel):
    ingredient_id: str
    ingredient_name: str = ""
    barcode: Optional[str] = None
    received_quantity: float = Field(gt=0)
    unit: str
    unit_price_fen: int = Field(ge=0)
    batch_no: Optional[str] = None
    expiry_date: Optional[str] = None  # YYYY-MM-DD


class MobileReceiveIn(BaseModel):
    purchase_request_id: str
    store_id: str
    items: List[MobileReceiveItemIn]
    receiver_id: Optional[str] = None
    notes: Optional[str] = None


# ── 移动盘点 ──────────────────────────────────────────────


class StartStocktakeIn(BaseModel):
    store_id: str
    operator_id: Optional[str] = None
    notes: Optional[str] = None


class StocktakeItemIn(BaseModel):
    stocktake_id: str
    ingredient_id: str
    ingredient_name: str = ""
    barcode: Optional[str] = None
    actual_quantity: float = Field(ge=0)
    unit: str
    unit_cost_fen: int = Field(ge=0, description="单位成本（分），用于差异金额计算")
    notes: Optional[str] = None


class SubmitStocktakeIn(BaseModel):
    operator_id: Optional[str] = None


# ── 调拨（扩展执行端点） ──────────────────────────────────


class ExecuteTransferIn(BaseModel):
    operator_id: Optional[str] = None
    notes: Optional[str] = None


class CreateTransferExtIn(BaseModel):
    from_store_id: str
    to_store_id: str
    items: List[dict]
    transfer_reason: Optional[str] = None
    requested_by: Optional[str] = None
    notes: Optional[str] = None


class ApproveTransferExtIn(BaseModel):
    approved_by: str
    notes: Optional[str] = None


# ── EDI 扩展 ─────────────────────────────────────────────


class EDIOrderConfirmIn(BaseModel):
    supplier_id: str
    tracking_no: Optional[str] = None
    estimated_delivery: Optional[str] = None  # YYYY-MM-DD
    notes: Optional[str] = None


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  工具函数
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _exec(db: AsyncSession, stmt: str, params: dict | None = None) -> None:
    await db.execute(text(stmt), params or {})


async def _fetch_one(db: AsyncSession, stmt: str, params: dict | None = None) -> dict | None:
    result = await db.execute(text(stmt), params or {})
    row = result.mappings().first()
    return dict(row) if row else None


async def _fetch_all(db: AsyncSession, stmt: str, params: dict | None = None) -> list[dict]:
    result = await db.execute(text(stmt), params or {})
    return [dict(r) for r in result.mappings().all()]


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  移动采购
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.post("/purchase-request")
async def create_purchase_request(
    body: MobilePurchaseRequestIn,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
) -> dict:
    """扫码采购申请。支持条码扫描或手动录入食材信息。"""
    req_id = str(uuid.uuid4())
    ingredient_id = body.ingredient_id or str(uuid.uuid4())
    now = _now_iso()
    try:
        await _exec(
            db,
            """
            INSERT INTO mobile_purchase_requests
                (id, tenant_id, store_id, barcode, ingredient_id, ingredient_name,
                 quantity, unit, unit_price_fen, supplier_id, supplier_name,
                 status, requested_by, notes, created_at, updated_at)
            VALUES
                (:id, :tenant_id, :store_id, :barcode, :ingredient_id, :ingredient_name,
                 :quantity, :unit, :unit_price_fen, :supplier_id, :supplier_name,
                 'pending', :requested_by, :notes, :now, :now)
            """,
            {
                "id": req_id,
                "tenant_id": x_tenant_id,
                "store_id": body.store_id,
                "barcode": body.barcode,
                "ingredient_id": ingredient_id,
                "ingredient_name": body.ingredient_name,
                "quantity": body.quantity,
                "unit": body.unit,
                "unit_price_fen": body.unit_price_fen,
                "supplier_id": body.supplier_id,
                "supplier_name": body.supplier_name,
                "requested_by": body.requested_by,
                "notes": body.notes,
                "now": now,
            },
        )
        await db.commit()
    except (OperationalError, ProgrammingError) as e:
        await db.rollback()
        logger.warning("mobile_purchase_request_db_error", error=str(e))
        raise HTTPException(status_code=503, detail="数据库暂不可用，请稍后重试")

    return {
        "ok": True,
        "data": {
            "id": req_id,
            "ingredient_id": ingredient_id,
            "status": "pending",
            "created_at": now,
        },
    }


@router.get("/purchase-requests")
async def list_purchase_requests(
    store_id: Optional[str] = Query(None),
    requested_by: Optional[str] = Query(None),
    status: Optional[str] = Query(None, description="pending|approved|rejected|received"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
) -> dict:
    """我的采购申请列表。"""
    filters = "WHERE tenant_id = :tenant_id AND is_deleted = FALSE"
    params: dict = {"tenant_id": x_tenant_id}
    if store_id:
        filters += " AND store_id = :store_id"
        params["store_id"] = store_id
    if requested_by:
        filters += " AND requested_by = :requested_by"
        params["requested_by"] = requested_by
    if status:
        filters += " AND status = :status"
        params["status"] = status

    try:
        count_row = await _fetch_one(
            db,
            f"SELECT COUNT(*) AS total FROM mobile_purchase_requests {filters}",
            params,
        )
        total = count_row["total"] if count_row else 0
        params["limit"] = size
        params["offset"] = (page - 1) * size
        rows = await _fetch_all(
            db,
            f"SELECT * FROM mobile_purchase_requests {filters} ORDER BY created_at DESC LIMIT :limit OFFSET :offset",
            params,
        )
    except (OperationalError, ProgrammingError) as e:
        logger.warning("list_purchase_requests_db_error", error=str(e))
        return {"ok": True, "data": {"items": [], "total": 0}}

    return {"ok": True, "data": {"items": rows, "total": total}}


@router.post("/purchase-requests/{req_id}/approve")
async def approve_purchase_request(
    req_id: str,
    body: ApprovePurchaseRequestIn,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
) -> dict:
    """审批采购申请（approve / reject）。"""
    try:
        existing = await _fetch_one(
            db,
            "SELECT * FROM mobile_purchase_requests WHERE id = :id AND tenant_id = :tid AND is_deleted = FALSE",
            {"id": req_id, "tid": x_tenant_id},
        )
    except (OperationalError, ProgrammingError) as e:
        logger.warning("approve_purchase_request_db_error", error=str(e))
        raise HTTPException(status_code=503, detail="数据库暂不可用")

    if not existing:
        raise HTTPException(status_code=404, detail="采购申请不存在")
    if existing["status"] != "pending":
        raise HTTPException(status_code=400, detail=f"当前状态 {existing['status']} 不可审批")

    approved_qty = body.approved_quantity if body.approved_quantity is not None else existing["quantity"]
    unit_price = body.unit_price_fen if body.unit_price_fen is not None else existing["unit_price_fen"]
    now = _now_iso()

    try:
        await _exec(
            db,
            """
            UPDATE mobile_purchase_requests
            SET status = 'approved', approved_by = :approved_by,
                approved_quantity = :qty, unit_price_fen = :price,
                approved_at = :now, updated_at = :now, notes = COALESCE(:notes, notes)
            WHERE id = :id AND tenant_id = :tid
            """,
            {
                "id": req_id,
                "tid": x_tenant_id,
                "approved_by": body.approved_by,
                "qty": approved_qty,
                "price": unit_price,
                "now": now,
                "notes": body.notes,
            },
        )
        await db.commit()
    except (OperationalError, ProgrammingError) as e:
        await db.rollback()
        raise HTTPException(status_code=503, detail="数据库写入失败")

    return {
        "ok": True,
        "data": {
            "id": req_id,
            "status": "approved",
            "approved_by": body.approved_by,
            "approved_quantity": approved_qty,
            "approved_at": now,
        },
    }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  移动收货
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.post("/receive")
async def mobile_receive(
    body: MobileReceiveIn,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
) -> dict:
    """扫码确认收货，更新库存并发射 INVENTORY.RECEIVED 事件。"""
    receive_id = str(uuid.uuid4())
    now = _now_iso()

    try:
        # 更新采购申请状态为已收货
        await _exec(
            db,
            """
            UPDATE mobile_purchase_requests
            SET status = 'received', updated_at = :now
            WHERE id = :req_id AND tenant_id = :tid
            """,
            {"req_id": body.purchase_request_id, "tid": x_tenant_id, "now": now},
        )

        received_items = []
        for item in body.items:
            item_id = str(uuid.uuid4())
            # 插入收货记录
            await _exec(
                db,
                """
                INSERT INTO mobile_receive_records
                    (id, tenant_id, receive_id, store_id, purchase_request_id,
                     ingredient_id, ingredient_name, barcode,
                     received_quantity, unit, unit_price_fen, batch_no, expiry_date,
                     receiver_id, notes, created_at)
                VALUES
                    (:id, :tid, :receive_id, :store_id, :req_id,
                     :ingredient_id, :ingredient_name, :barcode,
                     :received_qty, :unit, :unit_price_fen, :batch_no, :expiry_date,
                     :receiver_id, :notes, :now)
                """,
                {
                    "id": item_id,
                    "tid": x_tenant_id,
                    "receive_id": receive_id,
                    "store_id": body.store_id,
                    "req_id": body.purchase_request_id,
                    "ingredient_id": item.ingredient_id,
                    "ingredient_name": item.ingredient_name,
                    "barcode": item.barcode,
                    "received_qty": item.received_quantity,
                    "unit": item.unit,
                    "unit_price_fen": item.unit_price_fen,
                    "batch_no": item.batch_no,
                    "expiry_date": item.expiry_date,
                    "receiver_id": body.receiver_id,
                    "notes": body.notes,
                    "now": now,
                },
            )
            received_items.append(item.ingredient_id)

            # Phase 1 平行事件写入：收货入库
            asyncio.create_task(
                emit_event(
                    event_type=InventoryEventType.RECEIVED,
                    tenant_id=x_tenant_id,
                    stream_id=item.ingredient_id,
                    payload={
                        "ingredient_id": item.ingredient_id,
                        "quantity": item.received_quantity,
                        "unit_price_fen": item.unit_price_fen,
                        "batch_no": item.batch_no,
                        "source": "mobile_receive",
                    },
                    store_id=body.store_id,
                    source_service="tx-supply",
                    metadata={
                        "receive_id": receive_id,
                        "purchase_request_id": body.purchase_request_id,
                        "receiver_id": body.receiver_id,
                    },
                )
            )

        await db.commit()
    except (OperationalError, ProgrammingError, InterfaceError) as e:
        await db.rollback()
        logger.error("mobile_receive_db_error", error=str(e))
        raise HTTPException(status_code=503, detail="收货记录写入失败，请重试")

    return {
        "ok": True,
        "data": {
            "receive_id": receive_id,
            "items_received": len(body.items),
            "created_at": now,
        },
    }


@router.get("/pending-receipts")
async def list_pending_receipts(
    store_id: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
) -> dict:
    """待收货采购单列表（status='approved'）。"""
    filters = "WHERE tenant_id = :tid AND status = 'approved' AND is_deleted = FALSE"
    params: dict = {"tid": x_tenant_id}
    if store_id:
        filters += " AND store_id = :store_id"
        params["store_id"] = store_id

    try:
        count_row = await _fetch_one(
            db,
            f"SELECT COUNT(*) AS total FROM mobile_purchase_requests {filters}",
            params,
        )
        total = count_row["total"] if count_row else 0
        params["limit"] = size
        params["offset"] = (page - 1) * size
        rows = await _fetch_all(
            db,
            f"SELECT * FROM mobile_purchase_requests {filters} ORDER BY approved_at ASC LIMIT :limit OFFSET :offset",
            params,
        )
    except (OperationalError, ProgrammingError) as e:
        logger.warning("pending_receipts_db_error", error=str(e))
        return {"ok": True, "data": {"items": [], "total": 0}}

    return {"ok": True, "data": {"items": rows, "total": total}}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  移动盘点
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.post("/stocktake/start")
async def start_stocktake(
    body: StartStocktakeIn,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
) -> dict:
    """开始盘点任务（创建 open 状态的盘点单）。"""
    session_id = str(uuid.uuid4())
    now = _now_iso()
    try:
        await _exec(
            db,
            """
            INSERT INTO mobile_stocktake_sessions
                (id, tenant_id, store_id, status, operator_id, notes, created_at, updated_at)
            VALUES
                (:id, :tid, :store_id, 'open', :operator_id, :notes, :now, :now)
            """,
            {
                "id": session_id,
                "tid": x_tenant_id,
                "store_id": body.store_id,
                "operator_id": body.operator_id,
                "notes": body.notes,
                "now": now,
            },
        )
        await db.commit()
    except (OperationalError, ProgrammingError) as e:
        await db.rollback()
        logger.error("start_stocktake_db_error", error=str(e))
        raise HTTPException(status_code=503, detail="创建盘点任务失败")

    return {
        "ok": True,
        "data": {"id": session_id, "status": "open", "created_at": now},
    }


@router.post("/stocktake/item")
async def add_stocktake_item(
    body: StocktakeItemIn,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
) -> dict:
    """录入盘点条目（扫码或手动输入）。同一盘点单内同一食材可覆盖更新。"""
    try:
        session = await _fetch_one(
            db,
            "SELECT * FROM mobile_stocktake_sessions WHERE id = :id AND tenant_id = :tid",
            {"id": body.stocktake_id, "tid": x_tenant_id},
        )
    except (OperationalError, ProgrammingError) as e:
        raise HTTPException(status_code=503, detail="数据库暂不可用")

    if not session:
        raise HTTPException(status_code=404, detail="盘点任务不存在")
    if session["status"] != "open":
        raise HTTPException(status_code=400, detail="盘点任务已关闭，不可继续录入")

    item_id = str(uuid.uuid4())
    now = _now_iso()

    try:
        # 同一盘点单内同食材覆盖更新（upsert by stocktake_id + ingredient_id）
        await _exec(
            db,
            """
            INSERT INTO mobile_stocktake_items
                (id, tenant_id, stocktake_id, ingredient_id, ingredient_name, barcode,
                 actual_quantity, unit, unit_cost_fen, notes, created_at, updated_at)
            VALUES
                (:id, :tid, :sid, :ingredient_id, :ingredient_name, :barcode,
                 :actual_qty, :unit, :unit_cost_fen, :notes, :now, :now)
            ON CONFLICT (stocktake_id, ingredient_id)
            DO UPDATE SET
                actual_quantity = EXCLUDED.actual_quantity,
                unit_cost_fen   = EXCLUDED.unit_cost_fen,
                notes           = EXCLUDED.notes,
                updated_at      = EXCLUDED.updated_at
            """,
            {
                "id": item_id,
                "tid": x_tenant_id,
                "sid": body.stocktake_id,
                "ingredient_id": body.ingredient_id,
                "ingredient_name": body.ingredient_name,
                "barcode": body.barcode,
                "actual_qty": body.actual_quantity,
                "unit": body.unit,
                "unit_cost_fen": body.unit_cost_fen,
                "notes": body.notes,
                "now": now,
            },
        )
        await db.commit()
    except (OperationalError, ProgrammingError) as e:
        await db.rollback()
        raise HTTPException(status_code=503, detail="录入失败，请重试")

    return {
        "ok": True,
        "data": {
            "stocktake_id": body.stocktake_id,
            "ingredient_id": body.ingredient_id,
            "actual_quantity": body.actual_quantity,
            "updated_at": now,
        },
    }


@router.post("/stocktake/{session_id}/submit")
async def submit_stocktake(
    session_id: str,
    body: SubmitStocktakeIn,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
) -> dict:
    """提交盘点。汇总差异，发射 INVENTORY.ADJUSTED 事件，关闭盘点单。"""
    try:
        session = await _fetch_one(
            db,
            "SELECT * FROM mobile_stocktake_sessions WHERE id = :id AND tenant_id = :tid",
            {"id": session_id, "tid": x_tenant_id},
        )
        items = await _fetch_all(
            db,
            "SELECT * FROM mobile_stocktake_items WHERE stocktake_id = :sid AND tenant_id = :tid",
            {"sid": session_id, "tid": x_tenant_id},
        )
    except (OperationalError, ProgrammingError) as e:
        raise HTTPException(status_code=503, detail="数据库暂不可用")

    if not session:
        raise HTTPException(status_code=404, detail="盘点任务不存在")
    if session["status"] != "open":
        raise HTTPException(status_code=400, detail="盘点任务已提交")
    if not items:
        raise HTTPException(status_code=400, detail="盘点条目为空，请先录入数据")

    now = _now_iso()

    try:
        await _exec(
            db,
            """
            UPDATE mobile_stocktake_sessions
            SET status = 'completed', submitted_at = :now,
                operator_id = COALESCE(:operator_id, operator_id), updated_at = :now
            WHERE id = :id AND tenant_id = :tid
            """,
            {
                "id": session_id,
                "tid": x_tenant_id,
                "operator_id": body.operator_id,
                "now": now,
            },
        )
        await db.commit()
    except (OperationalError, ProgrammingError) as e:
        await db.rollback()
        raise HTTPException(status_code=503, detail="提交盘点失败")

    # Phase 1 平行事件写入：每个差异条目发射 ADJUSTED 事件
    for item in items:
        asyncio.create_task(
            emit_event(
                event_type=InventoryEventType.ADJUSTED,
                tenant_id=x_tenant_id,
                stream_id=item["ingredient_id"],
                payload={
                    "ingredient_id": item["ingredient_id"],
                    "actual_quantity": float(item["actual_quantity"]),
                    "unit_cost_fen": int(item["unit_cost_fen"]),
                    "reason": "mobile_stocktake",
                    "stocktake_id": session_id,
                },
                store_id=session["store_id"],
                source_service="tx-supply",
                metadata={
                    "operator_id": body.operator_id or session.get("operator_id"),
                    "submitted_at": now,
                },
            )
        )

    return {
        "ok": True,
        "data": {
            "id": session_id,
            "status": "completed",
            "items_count": len(items),
            "submitted_at": now,
        },
    }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  门店调拨扩展：execute 端点（发起/审批已由 transfer_router 处理）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@transfer_ext_router.post("/{transfer_id}/execute")
async def execute_transfer(
    transfer_id: str,
    body: ExecuteTransferIn,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
) -> dict:
    """执行调拨：from_store 扣库存，to_store 加库存，发射 ADJUSTED 事件。"""
    try:
        transfer = await _fetch_one(
            db,
            "SELECT * FROM transfer_orders WHERE id = :id AND tenant_id = :tid AND is_deleted = FALSE",
            {"id": transfer_id, "tid": x_tenant_id},
        )
        items = await _fetch_all(
            db,
            "SELECT * FROM transfer_order_items WHERE transfer_order_id = :id AND tenant_id = :tid",
            {"id": transfer_id, "tid": x_tenant_id},
        )
    except (OperationalError, ProgrammingError) as e:
        raise HTTPException(status_code=503, detail="数据库暂不可用")

    if not transfer:
        raise HTTPException(status_code=404, detail="调拨单不存在")
    if transfer["status"] not in ("approved", "shipped"):
        raise HTTPException(status_code=400, detail=f"当前状态 {transfer['status']} 不可执行")

    now = _now_iso()

    try:
        await _exec(
            db,
            """
            UPDATE transfer_orders
            SET status = 'completed', updated_at = :now
            WHERE id = :id AND tenant_id = :tid
            """,
            {"id": transfer_id, "tid": x_tenant_id, "now": now},
        )
        await db.commit()
    except (OperationalError, ProgrammingError) as e:
        await db.rollback()
        raise HTTPException(status_code=503, detail="执行调拨失败")

    # 发射调拨双边库存事件
    for item in items:
        qty = float(item.get("approved_quantity") or item.get("requested_quantity", 0))
        # 发出方扣减
        asyncio.create_task(
            emit_event(
                event_type=InventoryEventType.CONSUMED,
                tenant_id=x_tenant_id,
                stream_id=item["ingredient_id"],
                payload={"ingredient_id": item["ingredient_id"], "quantity": qty, "reason": "transfer_out"},
                store_id=transfer["from_store_id"],
                source_service="tx-supply",
                metadata={"transfer_id": transfer_id, "operator_id": body.operator_id},
            )
        )
        # 接收方增加
        asyncio.create_task(
            emit_event(
                event_type=InventoryEventType.RECEIVED,
                tenant_id=x_tenant_id,
                stream_id=item["ingredient_id"],
                payload={"ingredient_id": item["ingredient_id"], "quantity": qty, "reason": "transfer_in"},
                store_id=transfer["to_store_id"],
                source_service="tx-supply",
                metadata={"transfer_id": transfer_id, "operator_id": body.operator_id},
            )
        )

    return {
        "ok": True,
        "data": {
            "transfer_id": transfer_id,
            "status": "completed",
            "items_executed": len(items),
            "executed_at": now,
        },
    }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  供应商 EDI 扩展：供应商查看采购单 + 确认发货
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@edi_ext_router.get("/orders")
async def edi_list_orders(
    supplier_id: Optional[str] = Query(None),
    status: Optional[str] = Query(None, description="pending|confirmed|shipped|completed"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
) -> dict:
    """供应商 EDI 门户：查看发给本供应商的采购单列表。"""
    filters = "WHERE tenant_id = :tid"
    params: dict = {"tid": x_tenant_id}
    if supplier_id:
        filters += " AND supplier_id = :supplier_id"
        params["supplier_id"] = supplier_id
    if status:
        filters += " AND status = :status"
        params["status"] = status

    try:
        count_row = await _fetch_one(
            db,
            f"SELECT COUNT(*) AS total FROM edi_orders {filters}",
            params,
        )
        total = count_row["total"] if count_row else 0
        params["limit"] = size
        params["offset"] = (page - 1) * size
        rows = await _fetch_all(
            db,
            f"SELECT * FROM edi_orders {filters} ORDER BY created_at DESC LIMIT :limit OFFSET :offset",
            params,
        )
    except (OperationalError, ProgrammingError) as e:
        logger.warning("edi_list_orders_db_error", error=str(e))
        return {"ok": True, "data": {"items": [], "total": 0}}

    return {"ok": True, "data": {"items": rows, "total": total}}


@edi_ext_router.post("/orders/{order_id}/confirm")
async def edi_confirm_order(
    order_id: str,
    body: EDIOrderConfirmIn,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
) -> dict:
    """供应商通过 EDI 门户确认发货。"""
    try:
        order = await _fetch_one(
            db,
            "SELECT * FROM edi_orders WHERE id = :id AND tenant_id = :tid",
            {"id": order_id, "tid": x_tenant_id},
        )
    except (OperationalError, ProgrammingError) as e:
        raise HTTPException(status_code=503, detail="数据库暂不可用")

    if not order:
        raise HTTPException(status_code=404, detail="EDI 采购单不存在")
    if order["status"] not in ("pending", "confirmed"):
        raise HTTPException(status_code=400, detail=f"当前状态 {order['status']} 不可确认发货")

    now = _now_iso()
    try:
        await _exec(
            db,
            """
            UPDATE edi_orders
            SET status = 'shipped',
                tracking_no = COALESCE(:tracking_no, tracking_no),
                estimated_delivery = COALESCE(:est_delivery::date, estimated_delivery),
                supplier_confirmed_at = :now,
                updated_at = :now
            WHERE id = :id AND tenant_id = :tid
            """,
            {
                "id": order_id,
                "tid": x_tenant_id,
                "tracking_no": body.tracking_no,
                "est_delivery": body.estimated_delivery,
                "now": now,
            },
        )
        await db.commit()
    except (OperationalError, ProgrammingError) as e:
        await db.rollback()
        raise HTTPException(status_code=503, detail="确认发货失败")

    logger.info(
        "edi_order_confirmed",
        order_id=order_id,
        supplier_id=body.supplier_id,
        tracking_no=body.tracking_no,
    )

    return {
        "ok": True,
        "data": {
            "id": order_id,
            "status": "shipped",
            "tracking_no": body.tracking_no,
            "estimated_delivery": body.estimated_delivery,
            "confirmed_at": now,
        },
    }
