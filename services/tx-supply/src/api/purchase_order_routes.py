"""采购单管理 + 验收入库 API

DDL（如 purchase_orders 表尚未创建，请执行以下迁移）:

    -- purchase_orders
    CREATE TABLE purchase_orders (
        id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        tenant_id            UUID NOT NULL,
        store_id             UUID NOT NULL,
        supplier_id          UUID,
        po_number            TEXT NOT NULL,          -- 采购单编号，格式: PO-YYYYMMDD-XXXXXX
        status               TEXT NOT NULL DEFAULT 'draft',
            -- draft / pending_approval / approved / received / cancelled
        total_amount_fen     BIGINT NOT NULL DEFAULT 0,
        expected_delivery_date DATE,
        actual_delivery_date   DATE,
        approved_by          UUID,
        approved_at          TIMESTAMPTZ,
        received_at          TIMESTAMPTZ,
        notes                TEXT,
        created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
        is_deleted           BOOLEAN NOT NULL DEFAULT FALSE
    );
    CREATE INDEX ON purchase_orders (tenant_id, store_id, status);
    CREATE INDEX ON purchase_orders (tenant_id, supplier_id);

    ALTER TABLE purchase_orders ENABLE ROW LEVEL SECURITY;
    CREATE POLICY po_tenant_isolation ON purchase_orders
        USING (tenant_id = current_setting('app.tenant_id')::uuid);

    -- purchase_order_items
    CREATE TABLE purchase_order_items (
        id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        po_id                UUID NOT NULL REFERENCES purchase_orders(id) ON DELETE CASCADE,
        tenant_id            UUID NOT NULL,
        ingredient_id        UUID NOT NULL,
        ingredient_name      TEXT NOT NULL DEFAULT '',
        quantity             NUMERIC(12, 4) NOT NULL,
        unit                 TEXT NOT NULL DEFAULT '',
        unit_price_fen       BIGINT NOT NULL DEFAULT 0,
        subtotal_fen         BIGINT NOT NULL DEFAULT 0,  -- quantity * unit_price_fen
        received_quantity    NUMERIC(12, 4) NOT NULL DEFAULT 0,
        notes                TEXT
    );
    CREATE INDEX ON purchase_order_items (po_id);
    CREATE INDEX ON purchase_order_items (tenant_id, ingredient_id);

    ALTER TABLE purchase_order_items ENABLE ROW LEVEL SECURITY;
    CREATE POLICY poi_tenant_isolation ON purchase_order_items
        USING (tenant_id = current_setting('app.tenant_id')::uuid);

    -- ingredient_batches（可选，若已存在则忽略）
    CREATE TABLE IF NOT EXISTS ingredient_batches (
        id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        tenant_id            UUID NOT NULL,
        ingredient_id        UUID NOT NULL,
        store_id             UUID NOT NULL,
        po_id                UUID REFERENCES purchase_orders(id),
        batch_no             TEXT,
        quantity             NUMERIC(12, 4) NOT NULL,
        unit_price_fen       BIGINT NOT NULL DEFAULT 0,
        expiry_date          DATE,
        received_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
        notes                TEXT,
        created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
        is_deleted           BOOLEAN NOT NULL DEFAULT FALSE
    );
    ALTER TABLE ingredient_batches ENABLE ROW LEVEL SECURITY;
    CREATE POLICY ib_tenant_isolation ON ingredient_batches
        USING (tenant_id = current_setting('app.tenant_id')::uuid);

统一响应格式: {"ok": bool, "data": {}, "error": {}}
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import List, Optional

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db as _get_db

logger = structlog.get_logger(__name__)

router = APIRouter(
    prefix="/api/v1/supply/purchase-orders",
    tags=["purchase-orders"],
)


# ─── 内部工具 ───────────────────────────────────────────────


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _new_id() -> str:
    return str(uuid.uuid4())


def _po_number() -> str:
    """生成采购单编号，格式: PO-YYYYMMDD-6位随机"""
    today = datetime.now(timezone.utc).strftime("%Y%m%d")
    suffix = uuid.uuid4().hex[:6].upper()
    return f"PO-{today}-{suffix}"


async def _set_tenant(db: AsyncSession, tenant_id: str) -> None:
    """激活 RLS 租户隔离"""
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": str(tenant_id)},
    )


def _table_not_ready_response() -> dict:
    return {"ok": False, "error": {"code": "TABLE_NOT_READY"}}


# ─── 请求模型 ────────────────────────────────────────────────


class POItemIn(BaseModel):
    ingredient_id: str
    ingredient_name: str = ""
    quantity: Decimal = Field(gt=Decimal("0"))
    unit: str = ""
    unit_price_fen: int = Field(ge=0)
    notes: Optional[str] = None


class CreatePurchaseOrderRequest(BaseModel):
    store_id: str
    supplier_id: Optional[str] = None
    expected_delivery_date: Optional[date] = None
    notes: Optional[str] = None
    items: List[POItemIn] = Field(min_length=1)


class ReceivedItemIn(BaseModel):
    ingredient_id: str
    received_quantity: Decimal = Field(gt=Decimal("0"))
    actual_unit_price_fen: int = Field(ge=0)
    batch_no: Optional[str] = None
    expiry_date: Optional[date] = None
    notes: Optional[str] = None


class ReceiveRequest(BaseModel):
    received_items: List[ReceivedItemIn] = Field(min_length=1)


# ─── 1. 采购单列表 ─────────────────────────────────────────


@router.get("")
async def list_purchase_orders(
    status: Optional[str] = Query(None),
    store_id: Optional[str] = Query(None),
    supplier_id: Optional[str] = Query(None),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
) -> dict:
    """采购单列表（分页，支持状态/门店/供应商/日期过滤）"""
    try:
        await _set_tenant(db, x_tenant_id)

        where_clauses = [
            "tenant_id = :tenant_id",
            "is_deleted = FALSE",
        ]
        params: dict = {"tenant_id": x_tenant_id}

        if status:
            where_clauses.append("status = :status")
            params["status"] = status
        if store_id:
            where_clauses.append("store_id = :store_id::uuid")
            params["store_id"] = store_id
        if supplier_id:
            where_clauses.append("supplier_id = :supplier_id::uuid")
            params["supplier_id"] = supplier_id
        if start_date:
            where_clauses.append("created_at::date >= :start_date")
            params["start_date"] = start_date
        if end_date:
            where_clauses.append("created_at::date <= :end_date")
            params["end_date"] = end_date

        where_sql = " AND ".join(where_clauses)
        offset = (page - 1) * size

        count_sql = text(f"SELECT COUNT(*) FROM purchase_orders WHERE {where_sql}")
        total_result = await db.execute(count_sql, params)
        total = total_result.scalar_one()

        list_sql = text(
            f"""
            SELECT id, store_id, supplier_id, po_number, status,
                   total_amount_fen, expected_delivery_date, actual_delivery_date,
                   approved_by, approved_at, received_at, notes,
                   created_at, updated_at
            FROM purchase_orders
            WHERE {where_sql}
            ORDER BY created_at DESC
            LIMIT :limit OFFSET :offset
            """
        )
        params["limit"] = size
        params["offset"] = offset
        rows = await db.execute(list_sql, params)
        items = [dict(row._mapping) for row in rows]

        return {
            "ok": True,
            "data": {
                "items": items,
                "total": total,
                "page": page,
                "size": size,
            },
        }
    except ProgrammingError as exc:
        if "does not exist" in str(exc).lower():
            logger.warning("purchase_orders table not ready", error=str(exc))
            return _table_not_ready_response()
        raise


# ─── 2. 创建采购单 ─────────────────────────────────────────


@router.post("")
async def create_purchase_order(
    body: CreatePurchaseOrderRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
) -> dict:
    """创建采购单（draft 状态），自动计算 total_amount_fen"""
    try:
        await _set_tenant(db, x_tenant_id)

        po_id = _new_id()
        po_number = _po_number()
        now = _now()

        # 计算总金额（分）
        total_amount_fen = sum(int(item.quantity * item.unit_price_fen) for item in body.items)

        # 插入采购单主记录
        await db.execute(
            text(
                """
                INSERT INTO purchase_orders (
                    id, tenant_id, store_id, supplier_id, po_number, status,
                    total_amount_fen, expected_delivery_date, notes,
                    created_at, updated_at
                ) VALUES (
                    :id::uuid, :tenant_id::uuid, :store_id::uuid,
                    :supplier_id::uuid,
                    :po_number, 'draft',
                    :total_amount_fen, :expected_delivery_date, :notes,
                    :now, :now
                )
                """
            ),
            {
                "id": po_id,
                "tenant_id": x_tenant_id,
                "store_id": body.store_id,
                "supplier_id": body.supplier_id,
                "po_number": po_number,
                "total_amount_fen": total_amount_fen,
                "expected_delivery_date": body.expected_delivery_date,
                "notes": body.notes,
                "now": now,
            },
        )

        # 插入明细行
        for item in body.items:
            subtotal_fen = int(item.quantity * item.unit_price_fen)
            await db.execute(
                text(
                    """
                    INSERT INTO purchase_order_items (
                        id, po_id, tenant_id, ingredient_id, ingredient_name,
                        quantity, unit, unit_price_fen, subtotal_fen, notes
                    ) VALUES (
                        :id::uuid, :po_id::uuid, :tenant_id::uuid,
                        :ingredient_id::uuid, :ingredient_name,
                        :quantity, :unit, :unit_price_fen, :subtotal_fen, :notes
                    )
                    """
                ),
                {
                    "id": _new_id(),
                    "po_id": po_id,
                    "tenant_id": x_tenant_id,
                    "ingredient_id": item.ingredient_id,
                    "ingredient_name": item.ingredient_name,
                    "quantity": item.quantity,
                    "unit": item.unit,
                    "unit_price_fen": item.unit_price_fen,
                    "subtotal_fen": subtotal_fen,
                    "notes": item.notes,
                },
            )

        await db.commit()

        logger.info(
            "purchase_order_created",
            po_id=po_id,
            po_number=po_number,
            tenant_id=x_tenant_id,
            store_id=body.store_id,
            total_amount_fen=total_amount_fen,
        )

        return {
            "ok": True,
            "data": {
                "po_id": po_id,
                "po_number": po_number,
                "status": "draft",
                "total_amount_fen": total_amount_fen,
            },
        }
    except ProgrammingError as exc:
        await db.rollback()
        if "does not exist" in str(exc).lower():
            logger.warning("purchase_orders table not ready", error=str(exc))
            return _table_not_ready_response()
        raise
    except ValueError as exc:
        await db.rollback()
        raise HTTPException(status_code=400, detail=str(exc))


# ─── 3. 采购单详情 ─────────────────────────────────────────


@router.get("/{po_id}")
async def get_purchase_order(
    po_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
) -> dict:
    """采购单详情（含明细行）"""
    try:
        await _set_tenant(db, x_tenant_id)

        po_row = await db.execute(
            text(
                """
                SELECT id, store_id, supplier_id, po_number, status,
                       total_amount_fen, expected_delivery_date, actual_delivery_date,
                       approved_by, approved_at, received_at, notes,
                       created_at, updated_at
                FROM purchase_orders
                WHERE id = :po_id::uuid
                  AND tenant_id = :tenant_id::uuid
                  AND is_deleted = FALSE
                """
            ),
            {"po_id": po_id, "tenant_id": x_tenant_id},
        )
        po = po_row.fetchone()
        if po is None:
            raise HTTPException(status_code=404, detail="采购单不存在")

        items_row = await db.execute(
            text(
                """
                SELECT id, ingredient_id, ingredient_name,
                       quantity, unit, unit_price_fen, subtotal_fen,
                       received_quantity, notes
                FROM purchase_order_items
                WHERE po_id = :po_id::uuid
                  AND tenant_id = :tenant_id::uuid
                ORDER BY ingredient_name
                """
            ),
            {"po_id": po_id, "tenant_id": x_tenant_id},
        )
        items = [dict(row._mapping) for row in items_row]

        data = dict(po._mapping)
        data["items"] = items
        return {"ok": True, "data": data}
    except HTTPException:
        raise
    except ProgrammingError as exc:
        if "does not exist" in str(exc).lower():
            logger.warning("purchase_orders table not ready", error=str(exc))
            return _table_not_ready_response()
        raise


# ─── 4. 提交审批 ──────────────────────────────────────────


@router.post("/{po_id}/submit")
async def submit_purchase_order(
    po_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
) -> dict:
    """提交审批：draft → pending_approval"""
    try:
        await _set_tenant(db, x_tenant_id)

        result = await db.execute(
            text(
                """
                UPDATE purchase_orders
                SET status = 'pending_approval', updated_at = :now
                WHERE id = :po_id::uuid
                  AND tenant_id = :tenant_id::uuid
                  AND status = 'draft'
                  AND is_deleted = FALSE
                RETURNING id, po_number, status
                """
            ),
            {"po_id": po_id, "tenant_id": x_tenant_id, "now": _now()},
        )
        row = result.fetchone()
        if row is None:
            raise HTTPException(
                status_code=400,
                detail="采购单不存在或当前状态不允许提交审批（仅 draft 状态可提交）",
            )

        await db.commit()
        logger.info(
            "purchase_order_submitted",
            po_id=po_id,
            tenant_id=x_tenant_id,
        )
        return {"ok": True, "data": dict(row._mapping)}
    except HTTPException:
        raise
    except ProgrammingError as exc:
        await db.rollback()
        if "does not exist" in str(exc).lower():
            return _table_not_ready_response()
        raise


# ─── 5. 审批通过 ──────────────────────────────────────────


class ApproveRequest(BaseModel):
    approved_by: str  # 审批人 user_id


@router.post("/{po_id}/approve")
async def approve_purchase_order(
    po_id: str,
    body: ApproveRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
) -> dict:
    """审批通过：pending_approval → approved，记录审批人和审批时间"""
    try:
        await _set_tenant(db, x_tenant_id)

        now = _now()
        result = await db.execute(
            text(
                """
                UPDATE purchase_orders
                SET status = 'approved',
                    approved_by = :approved_by::uuid,
                    approved_at = :now,
                    updated_at  = :now
                WHERE id = :po_id::uuid
                  AND tenant_id = :tenant_id::uuid
                  AND status = 'pending_approval'
                  AND is_deleted = FALSE
                RETURNING id, po_number, status, approved_by, approved_at
                """
            ),
            {
                "po_id": po_id,
                "tenant_id": x_tenant_id,
                "approved_by": body.approved_by,
                "now": now,
            },
        )
        row = result.fetchone()
        if row is None:
            raise HTTPException(
                status_code=400,
                detail="采购单不存在或当前状态不允许审批（仅 pending_approval 状态可审批）",
            )

        await db.commit()
        logger.info(
            "purchase_order_approved",
            po_id=po_id,
            approved_by=body.approved_by,
            tenant_id=x_tenant_id,
        )
        return {"ok": True, "data": dict(row._mapping)}
    except HTTPException:
        raise
    except ProgrammingError as exc:
        await db.rollback()
        if "does not exist" in str(exc).lower():
            return _table_not_ready_response()
        raise


# ─── 6. 验收入库 ──────────────────────────────────────────


@router.post("/{po_id}/receive")
async def receive_purchase_order(
    po_id: str,
    body: ReceiveRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
) -> dict:
    """验收入库：approved → received

    执行步骤：
    1. 校验采购单状态为 approved
    2. 更新库存：ingredients.stock_quantity += received_quantity
    3. 尝试插入 ingredient_batches（表不存在时跳过，仅更新库存）
    4. 更新 purchase_order_items.received_quantity
    5. 更新采购单状态为 received，记录 received_at
    """
    try:
        await _set_tenant(db, x_tenant_id)

        # 校验采购单状态
        po_result = await db.execute(
            text(
                """
                SELECT id, store_id, status
                FROM purchase_orders
                WHERE id = :po_id::uuid
                  AND tenant_id = :tenant_id::uuid
                  AND is_deleted = FALSE
                """
            ),
            {"po_id": po_id, "tenant_id": x_tenant_id},
        )
        po = po_result.fetchone()
        if po is None:
            raise HTTPException(status_code=404, detail="采购单不存在")
        if po.status != "approved":
            raise HTTPException(
                status_code=400,
                detail=f"采购单当前状态为 '{po.status}'，仅 approved 状态可验收入库",
            )

        store_id = str(po.store_id)
        now = _now()

        # 检测 ingredient_batches 表是否存在
        has_batches_table = await _check_table_exists(db, "ingredient_batches")

        for item in body.received_items:
            # 更新食材库存
            inv_result = await db.execute(
                text(
                    """
                    UPDATE ingredients
                    SET stock_quantity = stock_quantity + :qty,
                        updated_at = :now
                    WHERE id = :ingredient_id::uuid
                      AND tenant_id = :tenant_id::uuid
                    RETURNING id
                    """
                ),
                {
                    "qty": item.received_quantity,
                    "ingredient_id": item.ingredient_id,
                    "tenant_id": x_tenant_id,
                    "now": now,
                },
            )
            updated = inv_result.fetchone()
            if updated is None:
                logger.warning(
                    "ingredient_not_found_during_receive",
                    ingredient_id=item.ingredient_id,
                    po_id=po_id,
                    tenant_id=x_tenant_id,
                )

            # 记录入库批次（表存在时）
            if has_batches_table:
                await db.execute(
                    text(
                        """
                        INSERT INTO ingredient_batches (
                            id, tenant_id, ingredient_id, store_id, po_id,
                            batch_no, quantity, unit_price_fen, expiry_date,
                            received_at, notes, created_at
                        ) VALUES (
                            :id::uuid, :tenant_id::uuid, :ingredient_id::uuid,
                            :store_id::uuid, :po_id::uuid,
                            :batch_no, :quantity, :unit_price_fen, :expiry_date,
                            :now, :notes, :now
                        )
                        """
                    ),
                    {
                        "id": _new_id(),
                        "tenant_id": x_tenant_id,
                        "ingredient_id": item.ingredient_id,
                        "store_id": store_id,
                        "po_id": po_id,
                        "batch_no": item.batch_no,
                        "quantity": item.received_quantity,
                        "unit_price_fen": item.actual_unit_price_fen,
                        "expiry_date": item.expiry_date,
                        "now": now,
                        "notes": item.notes,
                    },
                )

            # 更新采购单明细的已收数量
            await db.execute(
                text(
                    """
                    UPDATE purchase_order_items
                    SET received_quantity = received_quantity + :qty
                    WHERE po_id = :po_id::uuid
                      AND ingredient_id = :ingredient_id::uuid
                      AND tenant_id = :tenant_id::uuid
                    """
                ),
                {
                    "qty": item.received_quantity,
                    "po_id": po_id,
                    "ingredient_id": item.ingredient_id,
                    "tenant_id": x_tenant_id,
                },
            )

        # 更新采购单状态
        await db.execute(
            text(
                """
                UPDATE purchase_orders
                SET status = 'received',
                    received_at = :now,
                    actual_delivery_date = :today,
                    updated_at = :now
                WHERE id = :po_id::uuid
                  AND tenant_id = :tenant_id::uuid
                """
            ),
            {
                "po_id": po_id,
                "tenant_id": x_tenant_id,
                "now": now,
                "today": now.date(),
            },
        )

        await db.commit()

        logger.info(
            "purchase_order_received",
            po_id=po_id,
            tenant_id=x_tenant_id,
            store_id=store_id,
            item_count=len(body.received_items),
            batches_recorded=has_batches_table,
        )

        return {
            "ok": True,
            "data": {
                "po_id": po_id,
                "status": "received",
                "received_at": now.isoformat(),
                "item_count": len(body.received_items),
            },
        }
    except HTTPException:
        raise
    except ProgrammingError as exc:
        await db.rollback()
        if "does not exist" in str(exc).lower():
            logger.warning("table not ready during receive", error=str(exc))
            return _table_not_ready_response()
        raise
    except ValueError as exc:
        await db.rollback()
        raise HTTPException(status_code=400, detail=str(exc))


# ─── 7. 取消采购单 ─────────────────────────────────────────


class CancelRequest(BaseModel):
    reason: Optional[str] = None


@router.post("/{po_id}/cancel")
async def cancel_purchase_order(
    po_id: str,
    body: CancelRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
) -> dict:
    """取消采购单：draft/pending_approval → cancelled（已 approved 状态不可取消）"""
    try:
        await _set_tenant(db, x_tenant_id)

        result = await db.execute(
            text(
                """
                UPDATE purchase_orders
                SET status = 'cancelled',
                    notes  = CASE
                                 WHEN :reason IS NOT NULL
                                 THEN COALESCE(notes || ' | ', '') || '取消原因: ' || :reason
                                 ELSE notes
                             END,
                    updated_at = :now
                WHERE id = :po_id::uuid
                  AND tenant_id = :tenant_id::uuid
                  AND status IN ('draft', 'pending_approval')
                  AND is_deleted = FALSE
                RETURNING id, po_number, status
                """
            ),
            {
                "po_id": po_id,
                "tenant_id": x_tenant_id,
                "reason": body.reason,
                "now": _now(),
            },
        )
        row = result.fetchone()
        if row is None:
            # 区分"不存在"和"已 approved 不可取消"
            check_result = await db.execute(
                text(
                    """
                    SELECT status FROM purchase_orders
                    WHERE id = :po_id::uuid
                      AND tenant_id = :tenant_id::uuid
                      AND is_deleted = FALSE
                    """
                ),
                {"po_id": po_id, "tenant_id": x_tenant_id},
            )
            existing = check_result.fetchone()
            if existing is None:
                raise HTTPException(status_code=404, detail="采购单不存在")
            raise HTTPException(
                status_code=400,
                detail=f"采购单当前状态为 '{existing.status}'，已审批通过的采购单不可取消",
            )

        await db.commit()
        logger.info(
            "purchase_order_cancelled",
            po_id=po_id,
            tenant_id=x_tenant_id,
            reason=body.reason,
        )
        return {"ok": True, "data": dict(row._mapping)}
    except HTTPException:
        raise
    except ProgrammingError as exc:
        await db.rollback()
        if "does not exist" in str(exc).lower():
            return _table_not_ready_response()
        raise


# ─── 内部工具：检测表是否存在 ──────────────────────────────


async def _check_table_exists(db: AsyncSession, table_name: str) -> bool:
    """查询 information_schema 确认表是否存在"""
    result = await db.execute(
        text(
            """
            SELECT 1 FROM information_schema.tables
            WHERE table_schema = 'public'
              AND table_name = :table_name
            LIMIT 1
            """
        ),
        {"table_name": table_name},
    )
    return result.fetchone() is not None
