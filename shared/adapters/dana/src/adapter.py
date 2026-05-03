"""
DANA adapter — wraps DanaClient for PaymentGateway interface.

Provides a consistent interface for the tx-trade PaymentGateway
to interact with DANA payment operations, following the same pattern
as BoostAdapter used for Malaysia.
"""

from __future__ import annotations

from typing import Any, Optional

import structlog

from shared.adapters.dana.src.client import (
    DanaClient,
    DanaError,
)

logger = structlog.get_logger()

# Module-level re-export for convenience
DanaError = DanaError


class DanaAdapter:
    """DANA adapter — bridges DanaClient to PaymentGateway interface.

    Provides create_qr / query / refund operations with consistent error handling,
    structured logging, and amount conversion.
    """

    def __init__(
        self,
        api_key: str,
        api_secret: str,
        merchant_code: str = "",
        production: bool = False,
        base_url: str = "",
    ):
        """
        Args:
            api_key:       DANA API Key
            api_secret:    DANA API Secret
            merchant_code: 商户编码（可选）
            production:    是否生产环境（False = 沙箱环境）
            base_url:      自定义 API 基础 URL
        """
        self._client = DanaClient(
            api_key=api_key,
            api_secret=api_secret,
            merchant_code=merchant_code,
            production=production,
            base_url=base_url,
        )

    # ─── 主接口 ──────────────────────────────────────────────────────────────────

    async def create_qr_payment(
        self,
        payment_no: str,
        amount_fen: int,
        callback_url: str,
        extra_params: Optional[dict] = None,
    ) -> dict:
        """创建 DANA 二维码支付

        Args:
            payment_no:    商户支付流水号
            amount_fen:    支付金额（分）
            callback_url:  异步通知地址
            extra_params:  额外参数（可选，可传入 order_id, redirect_url, description）

        Returns:
            {
                "dana_txn_id": "...",
                "qr_code": "...",
                "payment_url": "...",
                "status": "pending",
            }
        """
        extra = extra_params or {}
        result = await self._client.create_payment(
            order_id=extra.get("order_id", payment_no),
            payment_no=payment_no,
            amount_fen=amount_fen,
            callback_url=callback_url,
            redirect_url=extra.get("redirect_url", ""),
            description=extra.get("description", ""),
        )

        logger.info(
            "dana_adapter.create_qr_success",
            payment_no=payment_no,
            dana_txn_id=result["dana_txn_id"],
        )

        return {
            "dana_txn_id": result["dana_txn_id"],
            "qr_code": result.get("qr_code", ""),
            "payment_url": result.get("payment_url", ""),
            "status": result["status"],
        }

    async def query_payment(self, dana_txn_id: str) -> dict:
        """查询 DANA 支付状态

        Args:
            dana_txn_id: DANA 侧交易号

        Returns:
            {
                "dana_txn_id": "...",
                "status": "paid" | "pending" | "failed",
                "amount_fen": 8800,
                "paid_at": "...",
            }
        """
        return await self._client.query_payment(dana_txn_id=dana_txn_id)

    async def refund(
        self,
        payment_no: str,
        txn_id: str,
        refund_no: str,
        amount_fen: int,
        reason: str = "",
    ) -> dict:
        """退款到 DANA Wallet

        Args:
            payment_no:    原商户支付流水号（仅日志）
            txn_id:        DANA 交易号
            refund_no:     商户退款单号
            amount_fen:    退款金额（分）
            reason:        退款原因

        Returns:
            {"dana_refund_id": "...", "status": "refunded", "amount_fen": ...}
        """
        result = await self._client.refund(
            dana_txn_id=txn_id,
            refund_no=refund_no,
            amount_fen=amount_fen,
            reason=reason,
        )
        logger.info(
            "dana_adapter.refund_success",
            payment_no=payment_no,
            dana_txn_id=dana_txn_id,
            refund_no=refund_no,
        )
        return result

    def verify_callback(self, raw_body: str, signature: str) -> dict:
        """验证 DANA 回调签名

        Args:
            raw_body:   回调请求体原始字符串
            signature:  Header 中的签名字符串

        Returns:
            回调 payload 字典

        Raises:
            DanaSignatureError: 签名校验失败
        """
        return self._client.verify_callback(raw_body=raw_body, signature=signature)

    async def close(self) -> None:
        """释放 HTTP 客户端连接池"""
        await self._client.aclose()
