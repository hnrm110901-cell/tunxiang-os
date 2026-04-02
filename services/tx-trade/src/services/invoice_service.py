"""发票服务 — 电子发票/纸质发票/增值税专票 + 税控对接(mock)

接口完整，税控平台为 mock 实现。
"""
import uuid
from datetime import datetime, timezone
from typing import Optional

import structlog

logger = structlog.get_logger()

# ─── 内存存储（mock） ───

_invoices: dict[str, dict] = {}  # key: invoice_id
_invoice_queue: list[dict] = []  # 待开票队列


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
    db=None,
    *,
    amount_fen: int = 0,
    items: Optional[list[dict]] = None,
) -> dict:
    """创建开票申请

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

    invoice_id = str(uuid.uuid4())
    invoice_no = f"INV{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}{uuid.uuid4().hex[:6].upper()}"

    invoice = {
        "id": invoice_id,
        "invoice_no": invoice_no,
        "order_id": order_id,
        "tenant_id": tenant_id,
        "invoice_type": invoice_type,
        "buyer_info": buyer_info,
        "amount_fen": amount_fen,
        "items": items or [],
        "status": InvoiceStatus.PENDING,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "submitted_at": None,
        "issued_at": None,
        "tax_platform_code": None,
        "pdf_url": None,
        "error_message": None,
    }
    _invoices[invoice_id] = invoice

    logger.info(
        "invoice_request_created",
        invoice_id=invoice_id,
        order_id=order_id,
        invoice_type=invoice_type,
        tenant_id=tenant_id,
        amount_fen=amount_fen,
    )
    return invoice


async def submit_to_tax_platform(
    invoice_id: str,
    tenant_id: str,
    db=None,
) -> dict:
    """提交到税控平台（mock实现）

    mock 逻辑：直接返回成功，生成模拟税控编码
    """
    invoice = _invoices.get(invoice_id)
    if not invoice:
        raise ValueError(f"Invoice not found: {invoice_id}")
    if invoice["tenant_id"] != tenant_id:
        raise PermissionError("Invoice does not belong to this tenant")
    if invoice["status"] not in (InvoiceStatus.PENDING, InvoiceStatus.FAILED):
        raise ValueError(f"Invoice status {invoice['status']} cannot be submitted")

    # Mock 税控平台响应
    tax_code = f"TAX{datetime.now(timezone.utc).strftime('%Y%m%d')}{uuid.uuid4().hex[:8].upper()}"
    invoice["status"] = InvoiceStatus.ISSUED
    invoice["submitted_at"] = datetime.now(timezone.utc).isoformat()
    invoice["issued_at"] = datetime.now(timezone.utc).isoformat()
    invoice["tax_platform_code"] = tax_code
    if invoice["invoice_type"] == InvoiceType.ELECTRONIC:
        invoice["pdf_url"] = f"https://tax-mock.tunxiang.com/invoices/{invoice_id}.pdf"

    logger.info(
        "invoice_submitted_to_tax",
        invoice_id=invoice_id,
        tenant_id=tenant_id,
        tax_code=tax_code,
        status=invoice["status"],
    )
    return {
        "invoice_id": invoice_id,
        "status": invoice["status"],
        "tax_platform_code": tax_code,
        "pdf_url": invoice.get("pdf_url"),
    }


async def get_invoice_status(
    invoice_id: str,
    tenant_id: str,
    db=None,
) -> dict:
    """查询发票状态"""
    invoice = _invoices.get(invoice_id)
    if not invoice:
        raise ValueError(f"Invoice not found: {invoice_id}")
    if invoice["tenant_id"] != tenant_id:
        raise PermissionError("Invoice does not belong to this tenant")

    logger.info(
        "invoice_status_queried",
        invoice_id=invoice_id,
        tenant_id=tenant_id,
        status=invoice["status"],
    )
    return {
        "invoice_id": invoice_id,
        "invoice_no": invoice["invoice_no"],
        "status": invoice["status"],
        "invoice_type": invoice["invoice_type"],
        "amount_fen": invoice["amount_fen"],
        "tax_platform_code": invoice.get("tax_platform_code"),
        "pdf_url": invoice.get("pdf_url"),
        "issued_at": invoice.get("issued_at"),
        "error_message": invoice.get("error_message"),
    }


async def generate_qrcode_data(
    order_id: str,
    tenant_id: str,
    db=None,
    *,
    amount_fen: int = 0,
    store_name: str = "",
) -> dict:
    """生成开票二维码数据

    顾客扫码后跳转到开票页面，填写抬头信息提交。
    """
    qr_token = uuid.uuid4().hex
    qr_data = {
        "url": f"https://invoice.tunxiang.com/apply?token={qr_token}",
        "token": qr_token,
        "order_id": order_id,
        "tenant_id": tenant_id,
        "amount_fen": amount_fen,
        "store_name": store_name,
        "expires_at": datetime(2099, 12, 31, tzinfo=timezone.utc).isoformat(),
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
    db=None,
) -> dict:
    """发票台账 — 查询指定门店、日期范围内的发票汇总

    date_range: ("2026-03-01", "2026-03-31")
    """
    start_str, end_str = date_range
    start_date = datetime.fromisoformat(start_str).replace(tzinfo=timezone.utc)
    end_date = datetime.fromisoformat(end_str).replace(tzinfo=timezone.utc)

    matched: list[dict] = []
    total_amount_fen = 0
    type_counts: dict[str, int] = {}

    for inv in _invoices.values():
        if inv["tenant_id"] != tenant_id:
            continue
        created = datetime.fromisoformat(inv["created_at"])
        if start_date <= created <= end_date:
            matched.append({
                "invoice_id": inv["id"],
                "invoice_no": inv["invoice_no"],
                "invoice_type": inv["invoice_type"],
                "amount_fen": inv["amount_fen"],
                "status": inv["status"],
                "created_at": inv["created_at"],
            })
            total_amount_fen += inv["amount_fen"]
            t = inv["invoice_type"]
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
