"""
ZaloPay API client for Vietnamese payment integration.

Reference: ZaloPay Merchant API
           https://docs.zalopay.vn/

Authentication: HMAC-SHA256 with Key1 (for API calls) and Key2 (for callback verification).
All monetary amounts are in VND (integer). VND has no decimal subunit.

Supported flows:
  - Create Order (QR/Gateway payment)
  - Query Order Status
  - Refund
  - Callback verification

Reference:
  - ZaloPay API Docs: https://docs.zalopay.vn/merchant/
  - HMAC signing: https://docs.zalopay.vn/merchant/coding/
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

import httpx
import structlog

logger = structlog.get_logger()

# ZaloPay API base URLs
ZALOPAY_PRODUCTION_BASE_URL = "https://merchant.zalopay.vn"
ZALOPAY_SANDBOX_BASE_URL = "https://sb-merchant.zalopay.vn"

# Timeout config
DEFAULT_TIMEOUT = 15.0


class ZaloPayError(Exception):
    """ZaloPay API call exception."""

    def __init__(self, message: str, return_code: int = -1, http_status: int = 0):
        super().__init__(message)
        self.return_code = return_code
        self.http_status = http_status


class ZaloPayAuthError(ZaloPayError):
    """HMAC signature or auth failure."""
    pass


class ZaloPayTimeoutError(ZaloPayError):
    """Network timeout."""
    pass


class ZaloPayCallbackError(ZaloPayError):
    """Callback verification failure."""
    pass


class ZaloPayClient:
    """ZaloPay API client — HMAC-SHA256 signed requests.

    Uses Key1 for API request signing and Key2 for callback verification.

    Supports:
      - POST /v2/create — Create payment order
      - POST /v2/query  — Query order status
      - POST /v2/refund — Refund
    """

    def __init__(
        self,
        app_id: str,
        key1: str,
        key2: str,
        production: bool = False,
        base_url: str = "",
    ):
        """
        Args:
            app_id:     ZaloPay App ID (provided by ZaloPay).
            key1:       Key1 for API request HMAC signing.
            key2:       Key2 for callback HMAC verification.
            production: False = sandbox environment (default).
            base_url:   Custom API base URL.
        """
        if not app_id:
            raise ValueError("app_id must not be empty")
        if not key1:
            raise ValueError("key1 must not be empty")
        if not key2:
            raise ValueError("key2 must not be empty")

        self.app_id = app_id
        self.key1 = key1
        self.key2 = key2
        self.production = production

        if base_url:
            resolved_base = base_url.rstrip("/")
        elif production:
            resolved_base = ZALOPAY_PRODUCTION_BASE_URL
        else:
            resolved_base = ZALOPAY_SANDBOX_BASE_URL

        self.base_url = resolved_base

        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=httpx.Timeout(DEFAULT_TIMEOUT),
            verify=True,
        )

    # ── Public API methods ──────────────────────────────────────────────────

    async def create_order(
        self,
        app_trans_id: str,
        amount_fen: int,
        description: str,
        embed_data: Optional[dict[str, Any]] = None,
        items: Optional[list[dict[str, Any]]] = None,
        bank_code: str = "",
        callback_url: str = "",
        device_info: Optional[dict[str, str]] = None,
    ) -> dict:
        """Create a ZaloPay payment order.

        POST /v2/create

        Args:
            app_trans_id: Merchant transaction ID (unique, format: yymmdd_xxxx).
            amount_fen:   Payment amount in VND.
            description:  Order description.
            embed_data:   Embedded JSON data (e.g. redirect URLs).
            items:        Line items data.
            bank_code:    Specific bank code (empty = any).
            callback_url: Post-payment callback URL.
            device_info:  Customer device info.

        Returns:
            ZaloPay API response with order_url, qr_code, etc.

        Raises:
            ZaloPayError, ZaloPayAuthError, ZaloPayTimeoutError
        """
        if amount_fen < 0:
            raise ValueError("amount_fen must be non-negative")

        app_time = int(time.time() * 1000)
        embed_data_str = json.dumps(embed_data or {}, ensure_ascii=False)
        items_str = json.dumps(items or [], ensure_ascii=False)

        # Build HMAC input
        mac_input = f"{self.app_id}|{app_trans_id}|{amount_fen}|{description}|{app_time}"
        mac = self._hmac_sign(mac_input, self.key1)

        payload: dict[str, Any] = {
            "app_id": int(self.app_id),
            "app_user": "tunxiang",
            "app_time": app_time,
            "amount": amount_fen,
            "app_trans_id": app_trans_id,
            "embed_data": embed_data_str,
            "item": items_str,
            "description": description,
            "bank_code": bank_code,
            "mac": mac,
            "callback_url": callback_url,
            "device_info": device_info or {},
        }

        logger.info(
            "zalopay.create_order",
            app_trans_id=app_trans_id,
            amount_fen=amount_fen,
        )

        try:
            resp = await self._request("POST", "/v2/create", json=payload)
        except httpx.TimeoutException:
            logger.error("zalopay.create_order_timeout", app_trans_id=app_trans_id)
            raise ZaloPayTimeoutError(
                "ZaloPay create order request timed out", return_code=-1
            )

        self._check_response(resp, "create_order")
        return resp.json()

    async def query_order(self, app_trans_id: str) -> dict:
        """Query ZaloPay order status.

        POST /v2/query

        Args:
            app_trans_id: Merchant transaction ID.

        Returns:
            Order status from ZaloPay.
        """
        app_time = int(time.time() * 1000)
        mac_input = f"{self.app_id}|{app_trans_id}|{app_time}"
        mac = self._hmac_sign(mac_input, self.key1)

        payload: dict[str, Any] = {
            "app_id": int(self.app_id),
            "app_trans_id": app_trans_id,
            "mac": mac,
            "app_time": app_time,
        }

        logger.info("zalopay.query_order", app_trans_id=app_trans_id)

        try:
            resp = await self._request("POST", "/v2/query", json=payload)
        except httpx.TimeoutException:
            logger.error("zalopay.query_order_timeout", app_trans_id=app_trans_id)
            raise ZaloPayTimeoutError(
                "ZaloPay query order request timed out", return_code=-1
            )

        self._check_response(resp, "query_order")
        return resp.json()

    async def refund(
        self,
        zp_trans_id: str,
        amount_fen: int,
        description: str = "",
    ) -> dict:
        """Refund a ZaloPay transaction (partial or full).

        POST /v2/refund

        Args:
            zp_trans_id: ZaloPay transaction ID to refund.
            amount_fen:  Refund amount in VND.
            description: Refund reason.

        Returns:
            ZaloPay refund response.
        """
        if amount_fen < 0:
            raise ValueError("amount_fen must be non-negative")

        app_time = int(time.time() * 1000)
        # Refund ID: format refund_{zp_trans_id}_{timestamp}
        refund_id = f"refund_{zp_trans_id}_{app_time}"

        mac_input = f"{self.app_id}|{zp_trans_id}|{amount_fen}|{description}|{app_time}"
        mac = self._hmac_sign(mac_input, self.key1)

        payload: dict[str, Any] = {
            "app_id": int(self.app_id),
            "zp_trans_id": int(zp_trans_id),
            "amount": amount_fen,
            "description": description,
            "refund_id": refund_id,
            "mac": mac,
            "app_time": app_time,
        }

        logger.info(
            "zalopay.refund",
            zp_trans_id=zp_trans_id,
            amount_fen=amount_fen,
            refund_id=refund_id,
        )

        try:
            resp = await self._request("POST", "/v2/refund", json=payload)
        except httpx.TimeoutException:
            logger.error("zalopay.refund_timeout", zp_trans_id=zp_trans_id)
            raise ZaloPayTimeoutError(
                "ZaloPay refund request timed out", return_code=-1
            )

        self._check_response(resp, "refund")
        return resp.json()

    # ── Callback verification ───────────────────────────────────────────────

    def verify_callback(self, data: dict[str, Any]) -> bool:
        """Verify ZaloPay callback (IPN) authenticity.

        ZaloPay sends a POST callback with a 'mac' field.
        The mac is HMAC-SHA256 of the JSON-encoded 'data' field using Key2.

        Args:
            data: The full callback payload from ZaloPay.

        Returns:
            True if the callback is authentic, False otherwise.
        """
        callback_data = data.get("data")
        callback_mac = data.get("mac", "")

        if not callback_data or not callback_mac:
            logger.warning("zalopay.callback_missing_fields")
            return False

        # Convert callback_data to JSON string (must match ZaloPay format)
        if isinstance(callback_data, str):
            data_str = callback_data
        else:
            data_str = json.dumps(callback_data, separators=(",", ":"))

        expected_mac = self._hmac_sign(data_str, self.key2)

        if not hmac.compare_digest(expected_mac, callback_mac):
            logger.error("zalopay.callback_mac_mismatch")
            return False

        logger.info("zalopay.callback_verified")
        return True

    # ── Resource management ─────────────────────────────────────────────────

    async def aclose(self) -> None:
        """Close the underlying HTTP client connection pool."""
        await self._client.aclose()

    # ── Internal helpers ────────────────────────────────────────────────────

    @staticmethod
    def _hmac_sign(data: str, key: str) -> str:
        """Generate HMAC-SHA256 (hex) signature."""
        return hmac.new(
            key.encode("utf-8"),
            data.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    async def _request(
        self,
        method: str,
        path: str,
        json_body: dict[str, Any] | None = None,
    ) -> httpx.Response:
        """Send an HTTP request to ZaloPay API."""
        try:
            response = await self._client.request(
                method=method,
                url=path,
                json=json_body,
            )
            response.raise_for_status()
        except httpx.TimeoutException:
            raise ZaloPayTimeoutError(
                f"ZaloPay request timed out: {path}", return_code=-1
            )
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            body = exc.response.text[:500]
            logger.error(
                "zalopay.http_error",
                path=path,
                status_code=status,
                body=body,
            )
            raise ZaloPayError(
                f"ZaloPay HTTP error: {status}",
                return_code=-1,
                http_status=status,
            )
        return response

    @staticmethod
    def _check_response(resp: httpx.Response, operation: str) -> None:
        """Verify the ZaloPay API business-level response."""
        try:
            data = resp.json()
        except (json.JSONDecodeError, ValueError) as exc:
            logger.error(
                "zalopay.invalid_json_response",
                operation=operation,
                body_preview=resp.text[:200],
            )
            raise ZaloPayError(
                f"ZaloPay returned invalid JSON: {resp.text[:100]}",
                return_code=-1,
            ) from exc

        return_code = data.get("return_code", -1)
        if return_code != 1:
            message = data.get("return_message", "Unknown error")
            logger.error(
                "zalopay.business_error",
                operation=operation,
                return_code=return_code,
                message=message,
            )
            raise ZaloPayError(
                f"ZaloPay {operation} failed: {message}",
                return_code=return_code,
            )
