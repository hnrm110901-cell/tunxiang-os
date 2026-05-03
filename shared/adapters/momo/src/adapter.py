"""
MoMo PaymentAdapter implementation.

Wraps MoMoClient to implement the unified PaymentAdapter
interface for the Vietnam market.
"""

from __future__ import annotations

import json
import os
from typing import Any, Optional

import structlog

from shared.adapters.momo.src.client import MoMoClient, MoMoError, MoMoTimeoutError

logger = structlog.get_logger()

# MoMo transaction result codes
MOMO_RESULT_MAP: dict[int, str] = {
    0: "success",
    1: "pending",
    2: "failed",
    3: "cancelled",
    4: "refunded",
    5: "expired",
    9000: "processing",
}


class MoMoPaymentAdapter:
    """MoMo payment adapter for the Vietnam market.

    Wraps MoMoClient for payment operations.

    Configuration (environment variables):
      MOMO_PARTNER_CODE   — MoMo partner code
      MOMO_ACCESS_KEY     — MoMo access key
      MOMO_SECRET_KEY     — MoMo secret key (HMAC signing)
      MOMO_SANDBOX        — set to "true" for sandbox (default: production)
    """

    def __init__(
        self,
        partner_code: Optional[str] = None,
        access_key: Optional[str] = None,
        secret_key: Optional[str] = None,
        sandbox: Optional[bool] = None,
    ):
        self.partner_code = partner_code or os.environ.get("MOMO_PARTNER_CODE", "")
        self.access_key = access_key or os.environ.get("MOMO_ACCESS_KEY", "")
        self.secret_key = secret_key or os.environ.get("MOMO_SECRET_KEY", "")
        sandbox_env = os.environ.get("MOMO_SANDBOX", "true").lower()
        self.sandbox = sandbox if sandbox is not None else (sandbox_env == "true")

        self._client: Optional[MoMoClient] = None
        self._mock_mode = not (
            self.partner_code and self.access_key and self.secret_key
        )

        logger.info(
            "momo_payment_adapter_init",
            mock_mode=self._mock_mode,
            sandbox=self.sandbox,
        )

    def _get_client(self) -> MoMoClient:
        """Lazy-init MoMoClient."""
        if self._client is None and not self._mock_mode:
            self._client = MoMoClient(
                partner_code=self.partner_code,
                access_key=self.access_key,
                secret_key=self.secret_key,
                production=not self.sandbox,
            )
        return self._client  # type: ignore[return-value]

    async def create_qr_payment(
        self,
        order_id: str,
        amount_fen: int,
        order_info: str,
        ipn_url: str = "",
        redirect_url: str = "",
    ) -> dict:
        """Create a QR payment for customer to scan.

        Args:
            order_id:     Merchant order ID.
            amount_fen:   Amount in VND.
            order_info:   Description.
            ipn_url:      Instant Payment Notification URL.
            redirect_url: Post-payment redirect URL.

        Returns:
            dict with qr_code_url, deeplink, etc.
        """
        logger.info(
            "momo_adapter.create_qr_payment",
            order_id=order_id,
            amount_fen=amount_fen,
        )

        if self._mock_mode:
            import time as time_module

            return {
                "pay_url": f"https://mock.momo.vn/pay/{order_id}",
                "qr_code_url": f"https://mock.momo.vn/qr/{order_id}",
                "deeplink": f"momo://app?orderId={order_id}",
                "order_id": order_id,
                "amount_fen": amount_fen,
                "result_code": 0,
                "message": "Mock payment created successfully",
            }

        try:
            client = self._get_client()
            result = await client.create_qr_payment(
                order_id=order_id,
                amount_fen=amount_fen,
                order_info=order_info,
                ipn_url=ipn_url,
                redirect_url=redirect_url,
            )
            return {
                "pay_url": result.get("payUrl", ""),
                "qr_code_url": result.get("qrCodeUrl", ""),
                "deeplink": result.get("deeplink", ""),
                "order_id": order_id,
                "amount_fen": amount_fen,
                "result_code": result.get("resultCode", -1),
                "message": result.get("message", ""),
            }
        except (MoMoError, MoMoTimeoutError) as exc:
            logger.error(
                "momo_adapter.create_qr_payment_failed",
                order_id=order_id,
                error=str(exc),
            )
            return {
                "error": str(exc),
                "result_code": -1,
                "order_id": order_id,
            }

    async def confirm_payment(self, order_id: str, amount_fen: int) -> dict:
        """Confirm a MoMo payment.

        Args:
            order_id:   Merchant order ID.
            amount_fen: Amount in VND.

        Returns:
            Confirmation result.
        """
        logger.info(
            "momo_adapter.confirm_payment",
            order_id=order_id,
            amount_fen=amount_fen,
        )

        if self._mock_mode:
            return {
                "order_id": order_id,
                "amount_fen": amount_fen,
                "result_code": 0,
                "message": "Mock payment confirmed",
                "trans_id": f"MOCK{order_id[-8:]}",
            }

        try:
            client = self._get_client()
            result = await client.confirm_payment(order_id, amount_fen)
            return {
                "order_id": order_id,
                "amount_fen": amount_fen,
                "result_code": result.get("resultCode", -1),
                "trans_id": result.get("transId", ""),
                "message": result.get("message", ""),
            }
        except (MoMoError, MoMoTimeoutError) as exc:
            logger.error(
                "momo_adapter.confirm_payment_failed",
                order_id=order_id,
                error=str(exc),
            )
            return {"error": str(exc), "result_code": -1, "order_id": order_id}

    async def query_transaction(self, order_id: str) -> dict:
        """Query payment status.

        Returns unified status from MOMO_RESULT_MAP.
        """
        if self._mock_mode:
            return {
                "order_id": order_id,
                "status": "success",
                "result_code": 0,
            }

        try:
            client = self._get_client()
            result = await client.query_transaction(order_id)
            result_code = result.get("resultCode", -1)
            status = MOMO_RESULT_MAP.get(result_code, "unknown")
            return {
                "order_id": order_id,
                "status": status,
                "result_code": result_code,
                "trans_id": result.get("transId", ""),
                "amount_fen": int(result.get("amount", 0)),
            }
        except (MoMoError, MoMoTimeoutError) as exc:
            logger.error(
                "momo_adapter.query_failed",
                order_id=order_id,
                error=str(exc),
            )
            return {"error": str(exc), "result_code": -1, "order_id": order_id}

    async def refund(self, order_id: str, amount_fen: int, trans_id: str) -> dict:
        """Refund a MoMo transaction."""
        if self._mock_mode:
            return {
                "order_id": order_id,
                "trans_id": trans_id,
                "amount_fen": amount_fen,
                "result_code": 0,
                "message": "Mock refund processed",
            }

        try:
            client = self._get_client()
            result = await client.refund(order_id, amount_fen, trans_id)
            return {
                "order_id": order_id,
                "trans_id": result.get("transId", ""),
                "amount_fen": amount_fen,
                "result_code": result.get("resultCode", -1),
                "message": result.get("message", ""),
            }
        except (MoMoError, MoMoTimeoutError) as exc:
            logger.error(
                "momo_adapter.refund_failed",
                order_id=order_id,
                error=str(exc),
            )
            return {"error": str(exc), "result_code": -1, "order_id": order_id}

    async def close(self) -> None:
        """Release HTTP client resources."""
        if self._client is not None:
            await self._client.aclose()
        logger.info("momo_payment_adapter_closed")

    async def __aenter__(self) -> "MoMoPaymentAdapter":
        return self

    async def __aexit__(self, exc_type: type, exc_val: BaseException, exc_tb: Any) -> None:
        await self.close()
