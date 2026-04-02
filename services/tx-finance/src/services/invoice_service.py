"""电子发票业务服务层

职责：
  - 申请发票：写入 invoices 记录 → 调用诺诺 → 更新状态
  - 重试失败发票
  - 查询状态（本地 + 诺诺实时查询）
  - 重打发票（重新获取 PDF 链接）
  - 红冲（作废发票）
"""
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Optional

import structlog
from models.invoice import Invoice
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.adapters.nuonuo.src.invoice_client import NuonuoInvoiceClient

logger = structlog.get_logger()

# 发票金额允许的最大偏差（元），防止金额异常
_AMOUNT_TOLERANCE = Decimal("0.01")


class InvoiceAmountMismatchError(ValueError):
    """发票金额与订单金额不匹配"""


class InvoiceNotFoundError(LookupError):
    """发票记录不存在或不属于该租户"""


class InvoiceStatusError(RuntimeError):
    """当前状态不允许执行此操作"""


class InvoiceService:
    """电子发票核心服务"""

    def __init__(self, nuonuo_client: Optional[NuonuoInvoiceClient] = None) -> None:
        self._client = nuonuo_client or NuonuoInvoiceClient()

    # ── 内部工具 ──────────────────────────────────────────────────────────────

    async def _get_invoice(
        self, invoice_id: uuid.UUID, tenant_id: uuid.UUID, db: AsyncSession
    ) -> Invoice:
        result = await db.execute(
            select(Invoice).where(
                Invoice.id == invoice_id,
                Invoice.tenant_id == tenant_id,
            )
        )
        invoice = result.scalar_one_or_none()
        if invoice is None:
            raise InvoiceNotFoundError(
                f"发票 {invoice_id} 不存在或不属于租户 {tenant_id}"
            )
        return invoice

    def _validate_amount(
        self, invoice_amount: Decimal, order_amount: Decimal
    ) -> None:
        """校验发票金额与订单金额，防止异常开票。"""
        diff = abs(invoice_amount - order_amount)
        if diff > _AMOUNT_TOLERANCE:
            raise InvoiceAmountMismatchError(
                f"发票金额 {invoice_amount} 与订单金额 {order_amount} 相差 {diff}，超出允许偏差"
            )

    def _build_nuonuo_payload(
        self,
        invoice: Invoice,
        extra: dict[str, Any],
    ) -> dict[str, Any]:
        """构建诺诺 API 申请发票所需 payload。"""
        goods_list = extra.get("goods_list", [])
        if not goods_list:
            # 无商品明细时生成简单单行明细
            goods_list = [
                {
                    "goodsName": extra.get("goods_name", "餐饮消费"),
                    "num": "1",
                    "unit": "次",
                    "specType": "",
                    "price": str(invoice.amount),
                    "amount": str(invoice.amount),
                    "taxRate": extra.get("tax_rate", "0.06"),
                    "taxAmount": str(invoice.tax_amount or Decimal("0")),
                    "invoiceLineProperty": "0",  # 0=正常行
                }
            ]
        return {
            "orderNo": str(invoice.platform_request_id),
            "invoiceDate": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
            "buyerName": invoice.invoice_title or "",
            "buyerTaxNum": invoice.tax_number or "",
            "buyerAddress": extra.get("buyer_address", ""),
            "buyerPhone": extra.get("buyer_phone", ""),
            "buyerBankName": extra.get("buyer_bank_name", ""),
            "buyerBankAccount": extra.get("buyer_bank_account", ""),
            "invoiceKind": _invoice_kind(invoice.invoice_type),
            "goodsWithTaxFlag": "1",  # 含税
            "invoiceDetailList": goods_list,
            "clerk": extra.get("clerk", "系统"),
            "remark": extra.get("remark", ""),
        }

    # ── 公开方法 ──────────────────────────────────────────────────────────────

    async def request_invoice(
        self,
        order_id: uuid.UUID,
        invoice_info: dict[str, Any],
        tenant_id: uuid.UUID,
        db: AsyncSession,
        order_amount: Optional[Decimal] = None,
    ) -> Invoice:
        """申请发票（订单完成后调用）。

        Args:
            order_id: 关联订单 ID
            invoice_info: 抬头信息，需含 invoice_type、invoice_title、amount 等
            tenant_id: 租户 ID（显式传入，RLS 双保险）
            db: 已绑定 tenant_id 的 DB session
            order_amount: 订单实付金额，用于金额校验（可选）

        Returns:
            已持久化的 Invoice 实例
        """
        amount = Decimal(str(invoice_info["amount"]))
        if order_amount is not None:
            self._validate_amount(amount, order_amount)

        request_id = f"TX-{uuid.uuid4().hex[:16].upper()}"
        invoice = Invoice(
            tenant_id=tenant_id,
            order_id=order_id,
            invoice_type=invoice_info.get("invoice_type", "electronic"),
            invoice_title=invoice_info.get("invoice_title"),
            tax_number=invoice_info.get("tax_number"),
            amount=amount,
            tax_amount=(
                Decimal(str(invoice_info["tax_amount"]))
                if invoice_info.get("tax_amount") is not None
                else None
            ),
            platform_request_id=request_id,
            status="pending",
        )
        db.add(invoice)
        await db.flush()  # 获取 id，仍在事务中

        log = logger.bind(
            invoice_id=str(invoice.id),
            order_id=str(order_id),
            tenant_id=str(tenant_id),
            request_id=request_id,
        )
        log.info("invoice.requesting")

        payload = self._build_nuonuo_payload(invoice, invoice_info)
        resp = await self._client.apply_invoice(payload)

        if resp.success:
            # 诺诺为异步开票，成功仅表示受理，invoice_no 由 query 回填
            serial_no = resp.data.get("serialNo", "")
            invoice.status = "pending"  # 等待诺诺异步结果
            if serial_no:
                # serialNo 可以视作平台确认号，更新 platform_request_id 以便后续查询
                invoice.platform_request_id = serial_no
            log.info("invoice.accepted_by_nuonuo", serial_no=serial_no)
        else:
            invoice.status = "failed"
            invoice.failed_reason = resp.error_msg
            log.warning("invoice.apply_failed", reason=resp.error_msg)

        await db.commit()
        await db.refresh(invoice)
        return invoice

    async def retry_failed(
        self,
        invoice_id: uuid.UUID,
        tenant_id: uuid.UUID,
        db: AsyncSession,
    ) -> Invoice:
        """重试失败的发票申请。

        仅允许 status='failed' 的发票重试。
        """
        invoice = await self._get_invoice(invoice_id, tenant_id, db)
        if invoice.status != "failed":
            raise InvoiceStatusError(
                f"发票 {invoice_id} 状态为 {invoice.status}，只有 failed 状态可重试"
            )

        log = logger.bind(invoice_id=str(invoice_id), tenant_id=str(tenant_id))
        log.info("invoice.retry_start")

        # 重置状态，生成新请求号防止诺诺幂等校验拒绝
        invoice.status = "pending"
        invoice.failed_reason = None
        invoice.platform_request_id = f"TX-{uuid.uuid4().hex[:16].upper()}"
        await db.flush()

        # 重新构建 payload（简化：仅含金额和抬头，无商品明细）
        payload = {
            "orderNo": invoice.platform_request_id,
            "invoiceDate": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
            "buyerName": invoice.invoice_title or "",
            "buyerTaxNum": invoice.tax_number or "",
            "invoiceKind": _invoice_kind(invoice.invoice_type),
            "goodsWithTaxFlag": "1",
            "invoiceDetailList": [
                {
                    "goodsName": "餐饮消费",
                    "num": "1",
                    "unit": "次",
                    "price": str(invoice.amount),
                    "amount": str(invoice.amount),
                    "taxRate": "0.06",
                    "taxAmount": str(invoice.tax_amount or Decimal("0")),
                    "invoiceLineProperty": "0",
                }
            ],
            "clerk": "系统",
        }
        resp = await self._client.apply_invoice(payload)

        if resp.success:
            serial_no = resp.data.get("serialNo", "")
            if serial_no:
                invoice.platform_request_id = serial_no
            log.info("invoice.retry_accepted", serial_no=serial_no)
        else:
            invoice.status = "failed"
            invoice.failed_reason = resp.error_msg
            log.warning("invoice.retry_failed", reason=resp.error_msg)

        await db.commit()
        await db.refresh(invoice)
        return invoice

    async def get_invoice_status(
        self,
        invoice_id: uuid.UUID,
        tenant_id: uuid.UUID,
        db: AsyncSession,
    ) -> dict[str, Any]:
        """查询发票状态。

        若本地状态为 pending 且存在 platform_request_id，则实时查询诺诺更新状态。
        """
        invoice = await self._get_invoice(invoice_id, tenant_id, db)

        if invoice.status == "pending" and invoice.platform_request_id:
            resp = await self._client.query_invoice(invoice.platform_request_id)
            if resp.success:
                items = resp.data.get("invoiceQueryResultList", [])
                if items:
                    item = items[0]
                    nuonuo_status = item.get("status")  # 0=开票中 1=成功 2=失败
                    if nuonuo_status == "1":
                        invoice.status = "issued"
                        invoice.invoice_no = item.get("invoiceNo", "")
                        invoice.invoice_code = item.get("invoiceCode", "")
                        invoice.pdf_url = item.get("pdfUrl", "")
                        invoice.issued_at = datetime.now(timezone.utc)
                        await db.commit()
                        await db.refresh(invoice)
                    elif nuonuo_status == "2":
                        invoice.status = "failed"
                        invoice.failed_reason = item.get("failCause", "诺诺开票失败")
                        await db.commit()
                        await db.refresh(invoice)

        return _invoice_to_dict(invoice)

    async def reprint(
        self,
        invoice_id: uuid.UUID,
        tenant_id: uuid.UUID,
        db: AsyncSession,
    ) -> dict[str, Any]:
        """重打发票（重新获取 PDF 链接并返回）。

        仅 issued 状态的发票可重打。
        """
        invoice = await self._get_invoice(invoice_id, tenant_id, db)
        if invoice.status != "issued":
            raise InvoiceStatusError(
                f"发票 {invoice_id} 状态为 {invoice.status}，只有 issued 状态可重打"
            )

        log = logger.bind(invoice_id=str(invoice_id), tenant_id=str(tenant_id))

        if invoice.invoice_code and invoice.invoice_no:
            resp = await self._client.get_pdf_url(invoice.invoice_code, invoice.invoice_no)
            if resp.success:
                new_url = resp.data.get("pdf_url", "")
                if new_url:
                    invoice.pdf_url = new_url
                    await db.commit()
                    await db.refresh(invoice)
                    log.info("invoice.reprint_ok", pdf_url=new_url)
            else:
                log.warning("invoice.reprint_pdf_failed", reason=resp.error_msg)

        return _invoice_to_dict(invoice)

    async def cancel_invoice(
        self,
        invoice_id: uuid.UUID,
        tenant_id: uuid.UUID,
        db: AsyncSession,
        reason: str = "顾客申请作废",
        red_invoice_data: Optional[dict[str, Any]] = None,
    ) -> Invoice:
        """红冲作废发票。

        issued 状态方可作废：调用诺诺红冲接口，状态更新为 cancelled。
        """
        invoice = await self._get_invoice(invoice_id, tenant_id, db)
        if invoice.status != "issued":
            raise InvoiceStatusError(
                f"发票 {invoice_id} 状态为 {invoice.status}，只有 issued 状态可作废"
            )
        if not invoice.invoice_no or not invoice.invoice_code:
            raise InvoiceStatusError("发票号码或发票代码缺失，无法红冲")

        log = logger.bind(
            invoice_id=str(invoice_id),
            invoice_no=invoice.invoice_no,
            tenant_id=str(tenant_id),
        )
        log.info("invoice.cancelling")

        # 构建红字发票负数明细
        red_data = red_invoice_data or {
            "orderNo": f"TX-RED-{uuid.uuid4().hex[:12].upper()}",
            "invoiceDate": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
            "buyerName": invoice.invoice_title or "",
            "buyerTaxNum": invoice.tax_number or "",
            "invoiceKind": _invoice_kind(invoice.invoice_type),
            "goodsWithTaxFlag": "1",
            "invoiceDetailList": [
                {
                    "goodsName": "餐饮消费（红冲）",
                    "num": "-1",
                    "unit": "次",
                    "price": str(invoice.amount),
                    "amount": str(-invoice.amount),
                    "taxRate": "0.06",
                    "taxAmount": str(-(invoice.tax_amount or Decimal("0"))),
                    "invoiceLineProperty": "2",  # 2=折扣行
                }
            ],
            "clerk": "系统",
        }

        resp = await self._client.red_flush_invoice(
            invoice_no=invoice.invoice_no,
            invoice_code=invoice.invoice_code,
            reason=reason,
            invoice_data=red_data,
        )

        if resp.success:
            invoice.status = "cancelled"
            log.info("invoice.cancelled_ok")
        else:
            # 红冲失败不改变状态，仅记录日志，由人工介入
            log.error("invoice.cancel_failed", reason=resp.error_msg)
            raise RuntimeError(f"红冲失败：{resp.error_msg}")

        await db.commit()
        await db.refresh(invoice)
        return invoice


# ── 工具函数 ──────────────────────────────────────────────────────────────────

def _invoice_kind(invoice_type: str) -> str:
    """将内部发票类型映射到诺诺 invoiceKind 值。"""
    mapping = {
        "vat_special": "2",    # 增值税专用发票
        "vat_normal": "1",     # 增值税普通发票
        "electronic": "3",     # 全电发票/电子普票
    }
    return mapping.get(invoice_type, "3")


def _invoice_to_dict(invoice: Invoice) -> dict[str, Any]:
    """将 Invoice ORM 对象序列化为响应字典。"""
    return {
        "id": str(invoice.id),
        "tenant_id": str(invoice.tenant_id),
        "order_id": str(invoice.order_id),
        "invoice_type": invoice.invoice_type,
        "invoice_title": invoice.invoice_title,
        "tax_number": invoice.tax_number,
        "amount": str(invoice.amount),
        "tax_amount": str(invoice.tax_amount) if invoice.tax_amount is not None else None,
        "invoice_no": invoice.invoice_no,
        "invoice_code": invoice.invoice_code,
        "platform": invoice.platform,
        "platform_request_id": invoice.platform_request_id,
        "status": invoice.status,
        "pdf_url": invoice.pdf_url,
        "issued_at": invoice.issued_at.isoformat() if invoice.issued_at else None,
        "failed_reason": invoice.failed_reason,
        "created_at": invoice.created_at.isoformat() if invoice.created_at else None,
    }
