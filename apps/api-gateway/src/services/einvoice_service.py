"""
电子发票服务 — D7-P0 Must-Fix Task 3

职责：
  - issue_invoice_for_bill(bill_id, buyer_info): 为账单开票（走 einvoice_adapters）
  - generate_self_service_code(bill_id): 未提供抬头时生成短码 + 自助填写链接
  - self_service_submit(code, buyer_info): 顾客通过短码补录抬头并触发开票
  - post_settle_hook(bill_id, extras): 结算后钩子，根据 meta 决定开票还是生成短码

失败容错：开票失败写 EInvoiceLog.status=FAILED + error_message，不阻塞结算主流程。
"""

import secrets
import string
import uuid
from datetime import datetime
from typing import Any, Dict, Optional

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import settings
from src.core.exceptions import NotFoundError, ValidationError
from src.models.einvoice_log import EInvoiceLog, EInvoiceLogStatus
from src.models.pos_core import Bill

logger = structlog.get_logger()


def _fen_to_yuan(fen: Optional[int]) -> float:
    return round((fen or 0) / 100, 2) if fen is not None else 0.0


class EInvoiceService:
    """电子发票开票服务"""

    def __init__(self, db: AsyncSession):
        self.db = db

    # ══════════════════════════════════════════════════════════════
    # 1. 结算后钩子入口
    # ══════════════════════════════════════════════════════════════

    async def post_settle_hook(
        self,
        bill_id: uuid.UUID,
        bill_extras: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        结算后钩子：

        - 如果 bill.extras.invoice_requested == True 或 企业会员 → 触发开票
          · 提供了 buyer_info 完整抬头 → 直接调 adapter
          · 未提供或缺少 → 生成短码 + 自助链接
        - 其他情况返回 None（不开票）
        """
        bill_extras = bill_extras or {}
        requested = bool(bill_extras.get("invoice_requested")) or bill_extras.get("member_type") == "enterprise"
        if not requested:
            return None

        buyer_info = bill_extras.get("invoice_buyer") or {}
        buyer_name = buyer_info.get("name") or buyer_info.get("buyer_name")
        tax_no = buyer_info.get("tax_no") or buyer_info.get("buyer_tax_number")

        # 抬头完整 → 直接开票
        if buyer_name and tax_no:
            return await self.issue_invoice_for_bill(bill_id, buyer_info)

        # 抬头不全 → 生成短码 + 自助链接
        return await self.generate_self_service_code(bill_id)

    # ══════════════════════════════════════════════════════════════
    # 2. 直接开票
    # ══════════════════════════════════════════════════════════════

    async def issue_invoice_for_bill(
        self,
        bill_id: uuid.UUID,
        buyer_info: Dict[str, Any],
    ) -> Dict[str, Any]:
        """为账单开票（同步调 adapter）"""
        bill = await self._get_bill_or_raise(bill_id)
        amount_fen = bill.actual_amount or bill.payable_amount or 0

        # 创建日志（ISSUING）
        log = EInvoiceLog(
            brand_id=getattr(bill, "brand_id", None),
            store_id=getattr(bill, "store_id", None),
            bill_id=bill.id,
            buyer_name=buyer_info.get("name") or buyer_info.get("buyer_name"),
            buyer_tax_number=buyer_info.get("tax_no") or buyer_info.get("buyer_tax_number"),
            buyer_phone=buyer_info.get("phone"),
            buyer_email=buyer_info.get("email"),
            amount_fen=amount_fen,
            status=EInvoiceLogStatus.ISSUING,
            platform=getattr(settings, "EINVOICE_PLATFORM", "baiwang"),
        )
        self.db.add(log)
        await self.db.commit()
        await self.db.refresh(log)

        # 调 adapter（失败容错）
        try:
            from src.services.einvoice_adapters.factory import get_adapter
            adapter = get_adapter()
            result = await adapter.issue_invoice(
                bill_id=str(bill.id),
                invoice_type="electronic_general",
                title=log.buyer_name,
                tax_no=log.buyer_tax_number,
                total_amount_fen=amount_fen,
                items=[{
                    "name": "餐饮服务",
                    "quantity": 1,
                    "unit_price_yuan": _fen_to_yuan(amount_fen),
                    "tax_rate": 0.06,
                }],
                buyer_name=log.buyer_name,
                buyer_phone=log.buyer_phone,
                buyer_email=log.buyer_email,
            )
            log.status = EInvoiceLogStatus.ISSUED
            log.invoice_no = result.get("invoice_no")
            log.invoice_code = result.get("code")
            log.pdf_url = result.get("pdf_url")
            log.issued_at = datetime.utcnow()
            log.extras = {"adapter_result": result}
            logger.info(
                "einvoice_issued",
                bill_id=str(bill_id),
                invoice_no=log.invoice_no,
                amount_yuan=_fen_to_yuan(amount_fen),
            )
        except Exception as e:
            log.status = EInvoiceLogStatus.FAILED
            log.error_message = str(e)[:2000]
            log.retry_count = (log.retry_count or 0) + 1
            logger.warning("einvoice_failed", bill_id=str(bill_id), error=str(e))

        await self.db.commit()
        await self.db.refresh(log)
        return self._log_to_dict(log)

    # ══════════════════════════════════════════════════════════════
    # 3. 短码自助链接
    # ══════════════════════════════════════════════════════════════

    async def generate_self_service_code(self, bill_id: uuid.UUID) -> Dict[str, Any]:
        """未提供抬头时生成短码 + 自助填写链接"""
        bill = await self._get_bill_or_raise(bill_id)

        # 若已有未完成日志，复用
        stmt = select(EInvoiceLog).where(
            EInvoiceLog.bill_id == bill_id,
            EInvoiceLog.status == EInvoiceLogStatus.PENDING,
        )
        existing = (await self.db.execute(stmt)).scalar_one_or_none()
        if existing:
            return self._log_to_dict(existing)

        short_code = await self._generate_unique_code()
        base_url = getattr(settings, "H5_BASE_URL", "https://h5.zlsjos.cn")
        self_service_url = f"{base_url}/einvoice/self-service/{short_code}"

        amount_fen = bill.actual_amount or bill.payable_amount or 0
        log = EInvoiceLog(
            brand_id=getattr(bill, "brand_id", None),
            store_id=getattr(bill, "store_id", None),
            bill_id=bill.id,
            short_code=short_code,
            self_service_url=self_service_url,
            amount_fen=amount_fen,
            status=EInvoiceLogStatus.PENDING,
            platform=getattr(settings, "EINVOICE_PLATFORM", "baiwang"),
        )
        self.db.add(log)
        await self.db.commit()
        await self.db.refresh(log)

        logger.info(
            "einvoice_self_service_code_generated",
            bill_id=str(bill_id),
            short_code=short_code,
        )
        return self._log_to_dict(log)

    async def self_service_submit(
        self,
        short_code: str,
        buyer_info: Dict[str, Any],
    ) -> Dict[str, Any]:
        """顾客通过短码提交抬头 → 触发开票"""
        stmt = select(EInvoiceLog).where(EInvoiceLog.short_code == short_code)
        log = (await self.db.execute(stmt)).scalar_one_or_none()
        if not log:
            raise NotFoundError(f"短码 {short_code} 不存在或已失效")
        if log.status not in (EInvoiceLogStatus.PENDING, EInvoiceLogStatus.FAILED):
            raise ValidationError(f"开票日志状态为 {log.status.value}，无法再次提交")

        return await self.issue_invoice_for_bill(log.bill_id, buyer_info)

    # ══════════════════════════════════════════════════════════════
    # 4. 查询
    # ══════════════════════════════════════════════════════════════

    async def get_log_by_bill(self, bill_id: uuid.UUID) -> Optional[Dict[str, Any]]:
        stmt = select(EInvoiceLog).where(EInvoiceLog.bill_id == bill_id).order_by(EInvoiceLog.created_at.desc())
        log = (await self.db.execute(stmt)).scalar_one_or_none()
        return self._log_to_dict(log) if log else None

    # ══════════════════════════════════════════════════════════════
    # 私有
    # ══════════════════════════════════════════════════════════════

    async def _get_bill_or_raise(self, bill_id: uuid.UUID) -> Bill:
        stmt = select(Bill).where(Bill.id == bill_id)
        bill = (await self.db.execute(stmt)).scalar_one_or_none()
        if not bill:
            raise NotFoundError(f"账单 {bill_id} 不存在")
        return bill

    async def _generate_unique_code(self, max_retry: int = 10) -> str:
        alphabet = string.ascii_uppercase + string.digits
        # 排除易混淆字符
        alphabet = alphabet.replace("0", "").replace("O", "").replace("1", "").replace("I", "")
        for _ in range(max_retry):
            code = "INV" + "".join(secrets.choice(alphabet) for _ in range(7))
            stmt = select(EInvoiceLog.id).where(EInvoiceLog.short_code == code)
            if not (await self.db.execute(stmt)).scalar_one_or_none():
                return code
        raise RuntimeError("短码生成失败（重试次数已用尽）")

    @staticmethod
    def _log_to_dict(log: EInvoiceLog) -> Dict[str, Any]:
        return {
            "id": str(log.id),
            "bill_id": str(log.bill_id),
            "short_code": log.short_code,
            "self_service_url": log.self_service_url,
            "buyer_name": log.buyer_name,
            "buyer_tax_number": log.buyer_tax_number,
            "amount_fen": log.amount_fen,
            "amount_yuan": _fen_to_yuan(log.amount_fen),
            "status": log.status.value if log.status else None,
            "invoice_no": log.invoice_no,
            "invoice_code": log.invoice_code,
            "pdf_url": log.pdf_url,
            "platform": log.platform,
            "error_message": log.error_message,
            "retry_count": log.retry_count,
            "issued_at": log.issued_at.isoformat() if log.issued_at else None,
            "created_at": log.created_at.isoformat() if log.created_at else None,
        }


def get_einvoice_service(db: AsyncSession) -> EInvoiceService:
    return EInvoiceService(db)
