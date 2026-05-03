"""
GoPay adapter — wraps GoPayClient for PaymentGateway interface.

Provides a consistent interface for the tx-trade PaymentGateway
to interact with GoPay payment operations, following the same pattern
as GrabPayAdapter used for Malaysia.
"""

from __future__ import annotations

from typing import Any, Optional

import structlog

from shared.adapters.gopay.src.client import (
    GoPayClient,
    GoPayError,
)

logger = structlog.get_logger()

# Module-level re-export for convenience
GoPayError = GoPayError


class GoPayAdapter:
    """GoPay adapter — bridges GoPayClient to PaymentGateway interface.

    Provides create_qr / query / refund operations with consistent error handling,
    structured logging, and amount conversion. Designed to be injected into
    PaymentGateway alongside ID payment routing.
    """

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        production: bool = False,
        base_url: str = "",
    ):
        """
        Args:
            client_id:     GoPay 分配的 Client ID
            client_secret: GoPay 分配的 Client Secret
            production:    是否生产环境（False = 沙箱环境）
            base_url:      自定义 API 基础 URL
        """
        self._client = GoPayClient(
            client_id=client_id,
            client_secret=client_secret,
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
        """创建 GoPay 二维码支付

        Args:
            payment_no:    商户支付流水号
            amount_fen:    支付金额（分）
            callback_url:  异步通知地址
            extra_params:  额外参数（可选，可传入 order_id, redirect_url, description）

        Returns:
            {
                "gopay_txn_id": "...",
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
            "gopay_adapter.create_qr_success",
            payment_no=payment_no,
            gopay_txn_id=result["gopay_txn_id"],
        )

        return {
            "gopay_txn_id": result["gopay_txn_id"],
            "qr_code": result.get("qr_code", ""),
            "payment_url": result.get("payment_url", ""),
            "status": result["status"],
        }

    async def query_payment(self, gopay_txn_id: str) -> dict:
        """查询 GoPay 支付状态

        Args:
            gopay_txn_id: GoPay 侧交易号

        Returns:
            {
                "gopay_txn_id": "...",
                "status": "paid" | "pending" | "failed",
                "amount_fen": 8800,
                "paid_at": "...",
            }
        """
        return await self._client.query_payment(gopay_txn_id=gopay_txn_id)

    async def refund(
        self,
        payment_no: str,
        txn_id: str,
        refund_no: str,
        amount_fen: int,
        reason: str = "",
    ) -> dict:
        """退款到 GoPay Wallet

        Args:
            payment_no:    原商户支付流水号（仅日志）
            txn_id:        GoPay 交易号
            refund_no:     商户退款单号
            amount_fen:    退款金额（分）
            reason:        退款原因

        Returns:
            {"gopay_refund_id": "...", "status": "refunded", "amount_fen": ...}
        """
        result = await self._client.refund(
            gopay_txn_id=txn_id,
            refund_no=refund_no,
            amount_fen=amount_fen,
            reason=reason,
        )
        logger.info(
            "gopay_adapter.refund_success",
            payment_no=payment_no,
            gopay_txn_id=gopay_txn_id,
            refund_no=refund_no,
        )
        return result

    def verify_callback(self, raw_body: str, signature: str) -> dict:
        """验证 GoPay 回调签名

        Args:
            raw_body:   回调请求体原始字符串
            signature:  Header 中的签名字符串

        Returns:
            回调 payload 字典

        Raises:
            GoPaySignatureError: 签名校验失败
        """
        return self._client.verify_callback(raw_body=raw_body, signature=signature)

    async def close(self) -> None:
        """释放 HTTP 客户端连接池"""
        await self._client.aclose()
