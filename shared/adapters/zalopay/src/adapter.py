"""
ZaloPay PaymentAdapter implementation.

Wraps ZaloPayClient to implement the unified PaymentAdapter
interface for the Vietnam market.
"""

from __future__ import annotations

import json
import os
from typing import Any, Optional

import structlog

from shared.adapters.zalopay.src.client import (
    ZaloPayClient,
    ZaloPayError,
    ZaloPayTimeoutError,
)

logger = structlog.get_logger()

# Generate app_trans_id in ZaloPay format: yymmdd_xxxxx
def _generate_app_trans_id(order_id: str) -> str:
    """Generate ZaloPay-compatible transaction ID."""
    import time as time_module

    now = time_module.localtime()
    date_str = time_module.strftime("%y%m%d", now)
    # Use order_id suffix or timestamp as unique counter
    suffix = order_id[-8:] if len(order_id) >= 8 else f"{int(time_module.time() * 1000) % 100000:05d}"
    return f"{date_str}_{suffix}"


class ZaloPayPaymentAdapter:
    """ZaloPay payment adapter for the Vietnam market.

    Wraps ZaloPayClient for payment operations.

    Configuration (environment variables):
      ZALOPAY_APP_ID   — ZaloPay App ID
      ZALOPAY_KEY1     — Key1 for API request signing
      ZALOPAY_KEY2     — Key2 for callback verification
      ZALOPAY_SANDBOX  — set to "true" for sandbox (default: production)
    """

    def __init__(
        self,
        app_id: Optional[str] = None,
        key1: Optional[str] = None,
        key2: Optional[str] = None,
        sandbox: Optional[bool] = None,
    ):
        self.app_id = app_id or os.environ.get("ZALOPAY_APP_ID", "")
        self.key1 = key1 or os.environ.get("ZALOPAY_KEY1", "")
        self.key2 = key2 or os.environ.get("ZALOPAY_KEY2", "")
        sandbox_env = os.environ.get("ZALOPAY_SANDBOX", "true").lower()
        self.sandbox = sandbox if sandbox is not None else (sandbox_env == "true")

        self._client: Optional[ZaloPayClient] = None
        self._mock_mode = not (self.app_id and self.key1 and self.key2)

        logger.info(
            "zalopay_payment_adapter_init",
            mock_mode=self._mock_mode,
            sandbox=self.sandbox,
        )

    def _get_client(self) -> ZaloPayClient:
        """Lazy-init ZaloPayClient."""
        if self._client is None and not self._mock_mode:
            self._client = ZaloPayClient(
                app_id=self.app_id,
                key1=self.key1,
                key2=self.key2,
                production=not self.sandbox,
            )
        return self._client  # type: ignore[return-value]

    async def create_payment(
        self,
        order_id: str,
        amount_fen: int,
        description: str = "",
        callback_url: str = "",
    ) -> dict:
        """Create a ZaloPay payment order.

        Args:
            order_id:     Merchant order ID.
            amount_fen:   Amount in VND.
            description:  Payment description.
            callback_url: Post-payment callback URL.

        Returns:
            dict with order_url, qr_code, etc.
        """
        app_trans_id = _generate_app_trans_id(order_id)

        logger.info(
            "zalopay_adapter.create_payment",
            order_id=order_id,
            app_trans_id=app_trans_id,
            amount_fen=amount_fen,
        )

        embed_data = {
            "merchant_id": "tunxiang",
            "merchant_name": "Tunxiang OS",
            "order_id": order_id,
        }

        if self._mock_mode:
            return {
                "app_trans_id": app_trans_id,
                "order_url": f"https://mock.zalopay.vn/order/{app_trans_id}",
                "qr_code": f"https://mock.zalopay.vn/qr/{app_trans_id}",
                "amount_fen": amount_fen,
                "return_code": 1,
                "message": "Mock order created",
            }

        try:
            client = self._get_client()
            result = await client.create_order(
                app_trans_id=app_trans_id,
                amount_fen=amount_fen,
                description=description,
                embed_data=embed_data,
                callback_url=callback_url,
            )
            return {
                "app_trans_id": app_trans_id,
                "order_url": result.get("order_url", ""),
                "qr_code": result.get("qr_code", ""),
                "zp_trans_id": result.get("zp_trans_id", ""),
                "amount_fen": amount_fen,
                "return_code": result.get("return_code", -1),
                "message": result.get("return_message", ""),
            }
        except (ZaloPayError, ZaloPayTimeoutError) as exc:
            logger.error(
                "zalopay_adapter.create_payment_failed",
                order_id=order_id,
                error=str(exc),
            )
            return {
                "error": str(exc),
                "return_code": -1,
                "app_trans_id": app_trans_id,
            }

    async def query_payment(self, app_trans_id: str) -> dict:
        """Query payment status."""
        if self._mock_mode:
            return {
                "app_trans_id": app_trans_id,
                "status": "success",
                "return_code": 1,
            }

        try:
            client = self._get_client()
            result = await client.query_order(app_trans_id)
            return_code = result.get("return_code", -1)
            return {
                "app_trans_id": app_trans_id,
                "status": "success" if return_code == 1 else "failed",
                "return_code": return_code,
                "zp_trans_id": result.get("zp_trans_id", ""),
                "amount_fen": result.get("amount", 0),
            }
        except (ZaloPayError, ZaloPayTimeoutError) as exc:
            logger.error(
                "zalopay_adapter.query_failed",
                app_trans_id=app_trans_id,
                error=str(exc),
            )
            return {"error": str(exc), "return_code": -1}

    async def refund(self, zp_trans_id: str, amount_fen: int) -> dict:
        """Refund a ZaloPay transaction."""
        if self._mock_mode:
            return {
                "zp_trans_id": zp_trans_id,
                "amount_fen": amount_fen,
                "return_code": 1,
                "message": "Mock refund processed",
            }

        try:
            client = self._get_client()
            result = await client.refund(zp_trans_id, amount_fen)
            return {
                "zp_trans_id": zp_trans_id,
                "refund_id": result.get("refund_id", ""),
                "amount_fen": amount_fen,
                "return_code": result.get("return_code", -1),
                "message": result.get("return_message", ""),
            }
        except (ZaloPayError, ZaloPayTimeoutError) as exc:
            logger.error(
                "zalopay_adapter.refund_failed",
                zp_trans_id=zp_trans_id,
                error=str(exc),
            )
            return {"error": str(exc), "return_code": -1}

    async def close(self) -> None:
        """Release HTTP client resources."""
        if self._client is not None:
            await self._client.aclose()
        logger.info("zalopay_payment_adapter_closed")

    async def __aenter__(self) -> "ZaloPayPaymentAdapter":
        return self

    async def __aexit__(self, exc_type: type, exc_val: BaseException, exc_tb: Any) -> None:
        await self.close()
