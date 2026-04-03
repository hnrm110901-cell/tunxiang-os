"""诺诺开放平台 — 电子发票客户端

封装发票申请、查询、红冲等核心操作。
所有密钥从环境变量读取，禁止硬编码。
"""
import os
from dataclasses import dataclass, field
from typing import Any

import structlog

from .adapter import NuonuoAdapter

logger = structlog.get_logger()


@dataclass
class NuonuoResponse:
    success: bool
    data: dict[str, Any] = field(default_factory=dict)
    error_code: str = ""
    error_msg: str = ""


def _build_adapter() -> NuonuoAdapter:
    """从环境变量构建 NuonuoAdapter 实例。"""
    app_key = os.environ["NUONUO_APP_KEY"]
    app_secret = os.environ["NUONUO_APP_SECRET"]
    merchant_no = os.environ["NUONUO_MERCHANT_NO"]  # 销方税号
    sandbox = os.environ.get("NUONUO_SANDBOX", "false").lower() == "true"
    return NuonuoAdapter(
        config={
            "app_key": app_key,
            "app_secret": app_secret,
            "tax_number": merchant_no,
            "sandbox": sandbox,
        }
    )


class NuonuoInvoiceClient:
    """诺诺电子发票客户端

    所有公开方法均为 async，调用诺诺开放平台 API 并返回 NuonuoResponse。
    异常不向上抛出，改为在 NuonuoResponse.success=False + error_msg 中记录，
    便于调用方在不影响主业务的情况下处理失败。
    """

    def __init__(self) -> None:
        # 延迟创建 adapter，避免进程启动时环境变量尚未注入
        self._adapter: NuonuoAdapter | None = None

    def _get_adapter(self) -> NuonuoAdapter:
        if self._adapter is None:
            self._adapter = _build_adapter()
        return self._adapter

    async def apply_invoice(self, invoice_data: dict[str, Any]) -> NuonuoResponse:
        """申请开具电子发票。

        invoice_data 应包含诺诺 requestBillingNew 所需字段，例如：
            buyerName, buyerTaxNum, buyerAddress, buyerPhone,
            buyerBankName, buyerBankAccount,
            orderNo (平台侧请求单号), invoiceDate, clerk,
            goodsWithTaxFlag (含税标志), invoiceDetailList (商品明细)
        """
        adapter = self._get_adapter()
        try:
            result = await adapter.issue_invoice(invoice_data)
            serial_no = result.get("serialNo", "")
            logger.info("nuonuo.apply_invoice.ok", serial_no=serial_no)
            return NuonuoResponse(success=True, data=result)
        except Exception as exc:  # noqa: BLE001 — 顶层兜底，记录完整错误
            logger.error(
                "nuonuo.apply_invoice.failed",
                error=str(exc),
                invoice_data_keys=list(invoice_data.keys()),
                exc_info=True,
            )
            return NuonuoResponse(success=False, error_msg=str(exc))

    async def query_invoice(self, request_id: str) -> NuonuoResponse:
        """查询发票开票结果（通过平台请求单号）。"""
        adapter = self._get_adapter()
        try:
            result = await adapter.query_invoice([request_id])
            logger.info("nuonuo.query_invoice.ok", request_id=request_id)
            return NuonuoResponse(success=True, data=result)
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "nuonuo.query_invoice.failed",
                request_id=request_id,
                error=str(exc),
                exc_info=True,
            )
            return NuonuoResponse(success=False, error_msg=str(exc))

    async def red_flush_invoice(
        self,
        invoice_no: str,
        invoice_code: str,
        reason: str,
        invoice_data: dict[str, Any],
    ) -> NuonuoResponse:
        """红冲（开具负数红字发票）。

        Args:
            invoice_no: 原蓝字发票号码
            invoice_code: 原蓝字发票代码
            reason: 红冲原因
            invoice_data: 红字发票商品明细（金额取负值）
        """
        adapter = self._get_adapter()
        try:
            result = await adapter.issue_red_invoice(
                original_invoice_code=invoice_code,
                original_invoice_number=invoice_no,
                reason=reason,
                invoice_data=invoice_data,
            )
            logger.info(
                "nuonuo.red_flush.ok",
                invoice_no=invoice_no,
                invoice_code=invoice_code,
            )
            return NuonuoResponse(success=True, data=result)
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "nuonuo.red_flush.failed",
                invoice_no=invoice_no,
                invoice_code=invoice_code,
                error=str(exc),
                exc_info=True,
            )
            return NuonuoResponse(success=False, error_msg=str(exc))

    async def void_invoice(
        self,
        invoice_id: str,
        invoice_no: str,
        invoice_code: str,
    ) -> NuonuoResponse:
        """作废发票（当日发票）。"""
        adapter = self._get_adapter()
        try:
            result = await adapter.void_invoice(invoice_id, invoice_code, invoice_no)
            logger.info("nuonuo.void_invoice.ok", invoice_no=invoice_no)
            return NuonuoResponse(success=True, data=result)
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "nuonuo.void_invoice.failed",
                invoice_no=invoice_no,
                error=str(exc),
                exc_info=True,
            )
            return NuonuoResponse(success=False, error_msg=str(exc))

    async def get_pdf_url(self, invoice_code: str, invoice_no: str) -> NuonuoResponse:
        """获取发票 PDF 下载链接。"""
        adapter = self._get_adapter()
        try:
            pdf_url = await adapter.download_pdf(invoice_code, invoice_no)
            return NuonuoResponse(success=True, data={"pdf_url": pdf_url})
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "nuonuo.get_pdf_url.failed",
                invoice_no=invoice_no,
                error=str(exc),
                exc_info=True,
            )
            return NuonuoResponse(success=False, error_msg=str(exc))

    async def close(self) -> None:
        """释放底层 HTTP 连接。"""
        if self._adapter is not None:
            await self._adapter.close()
            self._adapter = None
