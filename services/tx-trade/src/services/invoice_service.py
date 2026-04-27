"""发票服务 — 顾客餐后开票申请系统（电子发票/纸质发票/增值税专票）

顾客扫码填写抬头信息，后端向税控平台提交开票申请并写回状态。
数据持久化到 invoice_requests 表（v254 迁移创建）。

注意：此文件与 v238 的费控报销 invoices 表无关，场景不同：
  - invoice_requests：顾客餐后申请开票，关联餐饮订单
  - invoices（v238）：员工上传发票图片，用于费控报销
"""

import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

import structlog
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger()


class InvoiceType:
    ELECTRONIC = "electronic"
    PAPER = "paper"
    VAT_SPECIAL = "vat_special"


class InvoiceStatus:
    PENDING = "pending"
    SUBMITTED = "submitted"
    ISSUED = "issued"
    FAILED = "failed"
    CANCELLED = "cancelled"


async def create_invoice_request(
    order_id: str,
    invoice_type: str,
    buyer_info: dict,
    tenant_id: str,
    db: AsyncSession,
    *,
    amount_fen: int = 0,
    items: Optional[list[dict]] = None,
) -> dict:
    """创建开票申请，写入 invoice_requests 表。

    buyer_info 示例:
    {
        "name": "某某公司",
        "tax_no": "91110000...",
        "address": "北京市...",
        "phone": "010-1234",
        "bank_name": "工商银行",
        "bank_account": "1234567890",
        "email": "invoice@example.com"  # 电子发票接收邮箱
    }
    """
    if invoice_type not in (InvoiceType.ELECTRONIC, InvoiceType.PAPER, InvoiceType.VAT_SPECIAL):
        raise ValueError(f"Invalid invoice_type: {invoice_type}")

    if invoice_type == InvoiceType.VAT_SPECIAL:
        required_fields = ["name", "tax_no", "address", "phone", "bank_name", "bank_account"]
        missing = [f for f in required_fields if not buyer_info.get(f)]
        if missing:
            raise ValueError(f"VAT special invoice requires: {', '.join(missing)}")

    invoice_no = f"INV{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}{uuid.uuid4().hex[:6].upper()}"

    try:
        await db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": str(tenant_id)},
        )

        result = await db.execute(
            text("""
                INSERT INTO invoice_requests (
                    tenant_id,
                    order_id,
                    invoice_no,
                    invoice_type,
                    buyer_name,
                    buyer_tax_no,
                    buyer_address,
                    buyer_phone,
                    buyer_bank_name,
                    buyer_bank_account,
                    buyer_email,
                    amount_fen,
                    items,
                    status
                ) VALUES (
                    :tenant_id,
                    :order_id,
                    :invoice_no,
                    :invoice_type,
                    :buyer_name,
                    :buyer_tax_no,
                    :buyer_address,
                    :buyer_phone,
                    :buyer_bank_name,
                    :buyer_bank_account,
                    :buyer_email,
                    :amount_fen,
                    :items,
                    'pending'
                )
                RETURNING id, invoice_no, status, created_at
            """),
            {
                "tenant_id": str(tenant_id),
                "order_id": order_id,
                "invoice_no": invoice_no,
                "invoice_type": invoice_type,
                "buyer_name": buyer_info.get("name"),
                "buyer_tax_no": buyer_info.get("tax_no"),
                "buyer_address": buyer_info.get("address"),
                "buyer_phone": buyer_info.get("phone"),
                "buyer_bank_name": buyer_info.get("bank_name"),
                "buyer_bank_account": buyer_info.get("bank_account"),
                "buyer_email": buyer_info.get("email"),
                "amount_fen": amount_fen,
                "items": json.dumps(items or [], ensure_ascii=False),
            },
        )
        row = result.mappings().first()
        await db.commit()

    except SQLAlchemyError as exc:
        await db.rollback()
        logger.error(
            "invoice_request_create_failed",
            order_id=order_id,
            tenant_id=tenant_id,
            exc_info=True,
        )
        raise ValueError(f"Failed to create invoice request: {exc}") from exc

    invoice_id = str(row["id"])
    logger.info(
        "invoice_request_created",
        invoice_id=invoice_id,
        order_id=order_id,
        invoice_type=invoice_type,
        tenant_id=tenant_id,
        amount_fen=amount_fen,
    )
    return {
        "id": invoice_id,
        "invoice_no": row["invoice_no"],
        "order_id": order_id,
        "tenant_id": str(tenant_id),
        "invoice_type": invoice_type,
        "buyer_info": buyer_info,
        "amount_fen": amount_fen,
        "items": items or [],
        "status": row["status"],
        "created_at": row["created_at"].isoformat() if row["created_at"] else None,
        "submitted_at": None,
        "issued_at": None,
        "tax_platform_code": None,
        "pdf_url": None,
        "error_message": None,
    }


async def submit_to_tax_platform(
    invoice_id: str,
    tenant_id: str,
    db: AsyncSession,
) -> dict:
    """提交到税控平台。

    # 税控平台 mock — 生产环境需替换为真实 API 调用（金税四期接口）
    mock 逻辑：直接标记为 issued，生成模拟税控编码和 PDF 链接。
    """
    try:
        await db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": str(tenant_id)},
        )

        result = await db.execute(
            text("""
                SELECT id, tenant_id, status, invoice_type
                FROM invoice_requests
                WHERE id = :bid AND tenant_id = :tid AND is_deleted = FALSE
            """),
            {"bid": invoice_id, "tid": str(tenant_id)},
        )
        row = result.mappings().first()

    except SQLAlchemyError as exc:
        await db.rollback()
        logger.error(
            "invoice_submit_query_failed",
            invoice_id=invoice_id,
            tenant_id=tenant_id,
            exc_info=True,
        )
        raise ValueError(f"Failed to query invoice: {exc}") from exc

    if not row:
        raise ValueError(f"Invoice not found: {invoice_id}")
    if str(row["tenant_id"]) != str(tenant_id):
        raise PermissionError("Invoice does not belong to this tenant")
    if row["status"] not in (InvoiceStatus.PENDING, InvoiceStatus.FAILED):
        raise ValueError(f"Invoice status '{row['status']}' cannot be submitted")

    # 税控平台 mock — 生产环境需替换为真实 API 调用（金税四期接口）
    now = datetime.now(timezone.utc)
    tax_code = f"TAX{now.strftime('%Y%m%d')}{uuid.uuid4().hex[:8].upper()}"
    pdf_url = (
        f"https://tax-mock.tunxiang.com/invoices/{invoice_id}.pdf"
        if row["invoice_type"] == InvoiceType.ELECTRONIC
        else None
    )

    try:
        await db.execute(
            text("""
                UPDATE invoice_requests
                SET status = 'issued',
                    submitted_at = :now,
                    issued_at = :now,
                    tax_platform_code = :tax_code,
                    pdf_url = :pdf_url,
                    updated_at = :now
                WHERE id = :bid AND tenant_id = :tid
            """),
            {
                "now": now,
                "tax_code": tax_code,
                "pdf_url": pdf_url,
                "bid": invoice_id,
                "tid": str(tenant_id),
            },
        )
        await db.commit()

    except SQLAlchemyError as exc:
        await db.rollback()
        logger.error(
            "invoice_submit_update_failed",
            invoice_id=invoice_id,
            tenant_id=tenant_id,
            exc_info=True,
        )
        raise ValueError(f"Failed to update invoice status: {exc}") from exc

    logger.info(
        "invoice_submitted_to_tax",
        invoice_id=invoice_id,
        tenant_id=tenant_id,
        tax_code=tax_code,
        status=InvoiceStatus.ISSUED,
    )
    return {
        "invoice_id": invoice_id,
        "status": InvoiceStatus.ISSUED,
        "tax_platform_code": tax_code,
        "pdf_url": pdf_url,
    }


async def get_invoice_status(
    invoice_id: str,
    tenant_id: str,
    db: AsyncSession,
) -> dict:
    """查询发票状态"""
    try:
        await db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": str(tenant_id)},
        )

        result = await db.execute(
            text("""
                SELECT id, invoice_no, status, invoice_type, amount_fen,
                       tax_platform_code, pdf_url, issued_at, error_message,
                       tenant_id
                FROM invoice_requests
                WHERE id = :bid AND tenant_id = :tid AND is_deleted = FALSE
            """),
            {"bid": invoice_id, "tid": str(tenant_id)},
        )
        row = result.mappings().first()

    except SQLAlchemyError as exc:
        await db.rollback()
        logger.error(
            "invoice_status_query_failed",
            invoice_id=invoice_id,
            tenant_id=tenant_id,
            exc_info=True,
        )
        raise ValueError(f"Failed to query invoice status: {exc}") from exc

    if not row:
        raise ValueError(f"Invoice not found: {invoice_id}")
    if str(row["tenant_id"]) != str(tenant_id):
        raise PermissionError("Invoice does not belong to this tenant")

    logger.info(
        "invoice_status_queried",
        invoice_id=invoice_id,
        tenant_id=tenant_id,
        status=row["status"],
    )
    return {
        "invoice_id": str(row["id"]),
        "invoice_no": row["invoice_no"],
        "status": row["status"],
        "invoice_type": row["invoice_type"],
        "amount_fen": row["amount_fen"],
        "tax_platform_code": row["tax_platform_code"],
        "pdf_url": row["pdf_url"],
        "issued_at": row["issued_at"].isoformat() if row["issued_at"] else None,
        "error_message": row["error_message"],
    }


async def generate_qrcode_data(
    order_id: str,
    tenant_id: str,
    db: AsyncSession,
    *,
    amount_fen: int = 0,
    store_name: str = "",
) -> dict:
    """生成开票二维码数据

    顾客扫码后跳转到开票页面，填写抬头信息提交。
    token 无需持久化，TTL 30 天。
    """
    qr_token = uuid.uuid4().hex
    expires_at = datetime.now(timezone.utc) + timedelta(days=30)
    qr_data = {
        "url": f"https://invoice.tunxiang.com/apply?token={qr_token}",
        "token": qr_token,
        "order_id": order_id,
        "tenant_id": tenant_id,
        "amount_fen": amount_fen,
        "store_name": store_name,
        "expires_at": expires_at.isoformat(),
    }

    logger.info(
        "invoice_qrcode_generated",
        order_id=order_id,
        tenant_id=tenant_id,
        token=qr_token,
    )
    return qr_data


async def get_invoice_ledger(
    store_id: str,
    date_range: tuple[str, str],
    tenant_id: str,
    db: AsyncSession,
) -> dict:
    """发票台账 — 查询指定租户、日期范围内的发票汇总

    date_range: ("2026-03-01", "2026-03-31")

    注意：invoice_requests 表无 store_id 字段，按 tenant_id + 日期范围查询。
    store_id 保留在返回值中供调用方参考。
    """
    start_str, end_str = date_range
    start_date = datetime.fromisoformat(start_str).replace(tzinfo=timezone.utc)
    end_date = datetime.fromisoformat(end_str).replace(tzinfo=timezone.utc)

    try:
        await db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": str(tenant_id)},
        )

        result = await db.execute(
            text("""
                SELECT id, invoice_no, invoice_type, amount_fen, status, created_at
                FROM invoice_requests
                WHERE tenant_id = :tid
                  AND is_deleted = FALSE
                  AND created_at BETWEEN :start_date AND :end_date
                ORDER BY created_at DESC
            """),
            {
                "tid": str(tenant_id),
                "start_date": start_date,
                "end_date": end_date,
            },
        )
        rows = result.mappings().all()

    except SQLAlchemyError as exc:
        await db.rollback()
        logger.error(
            "invoice_ledger_query_failed",
            store_id=store_id,
            tenant_id=tenant_id,
            date_range=date_range,
            exc_info=True,
        )
        raise ValueError(f"Failed to query invoice ledger: {exc}") from exc

    matched = []
    total_amount_fen = 0
    type_counts: dict[str, int] = {}

    for row in rows:
        matched.append(
            {
                "invoice_id": str(row["id"]),
                "invoice_no": row["invoice_no"],
                "invoice_type": row["invoice_type"],
                "amount_fen": row["amount_fen"],
                "status": row["status"],
                "created_at": row["created_at"].isoformat() if row["created_at"] else None,
            }
        )
        total_amount_fen += row["amount_fen"] or 0
        t = row["invoice_type"]
        type_counts[t] = type_counts.get(t, 0) + 1

    logger.info(
        "invoice_ledger_queried",
        store_id=store_id,
        tenant_id=tenant_id,
        date_range=date_range,
        count=len(matched),
    )
    return {
        "store_id": store_id,
        "date_range": list(date_range),
        "total_count": len(matched),
        "total_amount_fen": total_amount_fen,
        "type_counts": type_counts,
        "items": matched,
    }
