"""发票管理 API

数据表：invoice_titles / invoices（v146 迁移）
"""

from typing import Any

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/api/v1/member", tags=["invoice"])


# ── 请求模型 ──────────────────────────────────────────────────


class InvoiceTitleReq(BaseModel):
    customer_id: str
    type: str = "personal"  # personal / company
    title: str = ""
    tax_id: str = ""
    address: str = ""
    phone: str = ""
    bank_name: str = ""
    bank_account: str = ""
    is_default: bool = False


# ── 辅助函数 ──────────────────────────────────────────────────


async def _set_rls(db: AsyncSession, tenant_id: str) -> None:
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": tenant_id},
    )


def _row_to_title(row: Any) -> dict[str, Any]:
    return {
        "id": str(row[0]),
        "customer_id": str(row[1]),
        "type": row[2],
        "title": row[3],
        "tax_id": row[4],
        "address": row[5],
        "phone": row[6],
        "bank_name": row[7],
        "bank_account": row[8],
        "is_default": row[9],
    }


def _row_to_invoice(row: Any) -> dict[str, Any]:
    return {
        "id": str(row[0]),
        "customer_id": str(row[1]) if row[1] else None,
        "order_no": row[2] or "",
        "amount_yuan": f"{(row[3] or 0) / 100:.2f}",
        "status": row[4],
        "title": row[5] or "",
        "type": row[6] or "personal",
        "invoice_no": row[7],
        "issued_at": row[8].isoformat() if row[8] else None,
        "created_at": row[9].isoformat() if row[9] else "",
    }


# ── 端点 ──────────────────────────────────────────────────────


@router.get("/invoice-titles")
async def list_invoice_titles(
    customer_id: str = Query(..., description="顾客ID"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """获取发票抬头列表（默认抬头排在最前）"""
    if not x_tenant_id:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header is required")

    try:
        await _set_rls(db, x_tenant_id)

        rows = await db.execute(
            text("""
                SELECT id, customer_id, type, title, tax_id,
                       address, phone, bank_name, bank_account, is_default
                FROM invoice_titles
                WHERE tenant_id = :tid AND customer_id = :cid AND is_deleted = false
                ORDER BY is_default DESC, created_at DESC
            """),
            {"tid": x_tenant_id, "cid": customer_id},
        )
        items = [_row_to_title(r) for r in rows.all()]

        return {"ok": True, "data": {"items": items, "total": len(items)}}

    except SQLAlchemyError as exc:
        logger.error("invoice_titles.list.db_error", exc_info=True, error=str(exc))
        return {"ok": True, "data": {"items": [], "total": 0}}


@router.post("/invoice-titles")
async def create_invoice_title(
    req: InvoiceTitleReq,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """新增发票抬头"""
    if not x_tenant_id:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header is required")

    try:
        await _set_rls(db, x_tenant_id)

        # 若设为默认，先清除旧默认
        if req.is_default:
            await db.execute(
                text("""
                    UPDATE invoice_titles
                    SET is_default = false, updated_at = NOW()
                    WHERE tenant_id = :tid AND customer_id = :cid AND is_deleted = false
                """),
                {"tid": x_tenant_id, "cid": req.customer_id},
            )

        result = await db.execute(
            text("""
                INSERT INTO invoice_titles
                    (tenant_id, customer_id, type, title, tax_id,
                     address, phone, bank_name, bank_account, is_default)
                VALUES
                    (:tid, :cid, :type, :title, :tax_id,
                     :address, :phone, :bank_name, :bank_account, :is_default)
                RETURNING id, customer_id, type, title, tax_id,
                          address, phone, bank_name, bank_account, is_default
            """),
            {
                "tid": x_tenant_id,
                "cid": req.customer_id,
                "type": req.type,
                "title": req.title,
                "tax_id": req.tax_id,
                "address": req.address,
                "phone": req.phone,
                "bank_name": req.bank_name,
                "bank_account": req.bank_account,
                "is_default": req.is_default,
            },
        )
        title = _row_to_title(result.first())
        await db.commit()

        logger.info(
            "invoice_title_created",
            title_id=title["id"],
            customer_id=req.customer_id,
            tenant_id=x_tenant_id,
        )
        return {"ok": True, "data": title}

    except SQLAlchemyError as exc:
        await db.rollback()
        logger.error("invoice_titles.create.db_error", exc_info=True, error=str(exc))
        raise HTTPException(status_code=500, detail="服务暂时不可用")


@router.delete("/invoice-titles/{title_id}")
async def delete_invoice_title(
    title_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """软删除发票抬头"""
    if not x_tenant_id:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header is required")

    try:
        await _set_rls(db, x_tenant_id)

        await db.execute(
            text("""
                UPDATE invoice_titles
                SET is_deleted = true, updated_at = NOW()
                WHERE id = :tid_id AND tenant_id = :tid
            """),
            {"tid_id": title_id, "tid": x_tenant_id},
        )
        await db.commit()

        logger.info("invoice_title_deleted", title_id=title_id, tenant_id=x_tenant_id)
        return {"ok": True, "data": None}

    except SQLAlchemyError as exc:
        await db.rollback()
        logger.error("invoice_titles.delete.db_error", exc_info=True, error=str(exc))
        raise HTTPException(status_code=500, detail="服务暂时不可用")


@router.get("/invoices")
async def list_invoices(
    customer_id: str = Query(..., description="顾客ID"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """获取历史发票列表（分页）"""
    if not x_tenant_id:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header is required")

    try:
        await _set_rls(db, x_tenant_id)

        cnt_row = await db.execute(
            text("""
                SELECT COUNT(*) FROM invoices
                WHERE tenant_id = :tid AND customer_id = :cid AND is_deleted = false
            """),
            {"tid": x_tenant_id, "cid": customer_id},
        )
        total: int = cnt_row.scalar() or 0

        offset = (page - 1) * size
        rows = await db.execute(
            text("""
                SELECT id, customer_id, order_no, amount_fen,
                       status, title_snapshot, type_snapshot,
                       invoice_no, issued_at, created_at
                FROM invoices
                WHERE tenant_id = :tid AND customer_id = :cid AND is_deleted = false
                ORDER BY created_at DESC
                LIMIT :lim OFFSET :off
            """),
            {"tid": x_tenant_id, "cid": customer_id, "lim": size, "off": offset},
        )
        items = [_row_to_invoice(r) for r in rows.all()]

        return {"ok": True, "data": {"items": items, "total": total}}

    except SQLAlchemyError as exc:
        logger.error("invoices.list.db_error", exc_info=True, error=str(exc))
        return {"ok": True, "data": {"items": [], "total": 0}}
