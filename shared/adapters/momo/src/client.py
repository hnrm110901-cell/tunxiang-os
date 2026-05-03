"""
MoMo e-wallet API client for Vietnamese payment integration.

Reference: MoMo Partner API v2 (OpenAPI)
           https://developers.momo.vn/

Authentication: HMAC-SHA256 signature with access_key + secret_key.
All monetary amounts are in VND (integer). VND has no decimal subunit,
so 1 VND = 1 fen in the system.

Supported flows:
  - QR Payment (generate QR code for payment)
  - Payment Confirmation (verify/confirm a payment)
  - Refund
  - Transaction Status Inquiry

Reference:
  - MoMo API Documentation: https://developers.momo.vn/v3/docs/
  - HMAC-SHA256 signing: https://developers.momo.vn/v3/docs/development-guides/signing/
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

# MoMo API base URLs
MOMO_PRODUCTION_BASE_URL = "https://payment.momo.vn"
MOMO_SANDBOX_BASE_URL = "https://test-payment.momo.vn"

# Timeout config
DEFAULT_TIMEOUT = 15.0


class MoMoError(Exception):
    """MoMo API call exception."""

    def __init__(self, message: str, code: str = "", http_status: int = 0):
        super().__init__(message)
        self.code = code
        self.http_status = http_status


class MoMoAuthError(MoMoError):
    """HMAC signature or auth failure."""
    pass


class MoMoTimeoutError(MoMoError):
    """Network timeout."""
    pass


class MoMoSignatureError(MoMoError):
    """Webhook signature verification failure."""
    pass


class MoMoClient:
    """MoMo API client — HMAC-SHA256 signed requests.

    Supports:
      - POST /v2/gateway/api/create — Create QR payment
      - POST /v2/gateway/api/confirm — Confirm payment
      - POST /v2/gateway/api/query   — Query transaction status
      - POST /v2/gateway/api/refund  — Refund transaction
    """

    def __init__(
        self,
        partner_code: str,
        access_key: str,
        secret_key: str,
        production: bool = False,
        base_url: str = "",
    ):
        """
        Args:
            partner_code: MoMo Partner Code (provided by MoMo).
            access_key:   MoMo Access Key (provided by MoMo).
            secret_key:   MoMo Secret Key (HMAC signing key).
            production:   False = sandbox environment (default).
            base_url:     Custom API base URL.
        """
        if not partner_code:
            raise ValueError("partner_code must not be empty")
        if not access_key:
            raise ValueError("access_key must not be empty")
        if not secret_key:
            raise ValueError("secret_key must not be empty")

        self.partner_code = partner_code
        self.access_key = access_key
        self.secret_key = secret_key
        self.production = production

        if base_url:
            resolved_base = base_url.rstrip("/")
        elif production:
            resolved_base = MOMO_PRODUCTION_BASE_URL
        else:
            resolved_base = MOMO_SANDBOX_BASE_URL

        self.base_url = resolved_base

        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=httpx.Timeout(DEFAULT_TIMEOUT),
            verify=True,
        )

    # ── Public API methods ──────────────────────────────────────────────────

    async def create_qr_payment(
        self,
        order_id: str,
        amount_fen: int,
        order_info: str,
        extra_data: str = "",
        request_id: Optional[str] = None,
        store_name: str = "",
        redirect_url: str = "",
        ipn_url: str = "",
    ) -> dict:
        """Create a MoMo QR payment request.

        POST /v2/gateway/api/create

        Args:
            order_id:    Merchant order ID (unique).
            amount_fen:  Payment amount in VND (integer).
            order_info:  Order description (displayed to customer).
            extra_data:  Extra data (base64 encoded JSON, optional).
            request_id:  Unique request ID (defaults to order_id).
            store_name:  Store name for display.
            redirect_url: Redirect URL after payment.
            ipn_url:     IPN (Instant Payment Notification) URL.

        Returns:
            MoMo API response containing qrCodeUrl, deeplink, etc.

        Raises:
            MoMoError, MoMoAuthError, MoMoTimeoutError
        """
        if amount_fen < 0:
            raise ValueError("amount_fen must be non-negative")

        request_id = request_id or order_id
        request_data = self._build_request(
            order_id=order_id,
            amount_fen=amount_fen,
            order_info=order_info,
            extra_data=extra_data,
            request_id=request_id,
            store_name=store_name,
            redirect_url=redirect_url,
            ipn_url=ipn_url,
        )

        logger.info(
            "momo.create_qr_payment",
            order_id=order_id,
            amount_fen=amount_fen,
        )

        try:
            resp = await self._request("POST", "/v2/gateway/api/create", json=request_data)
        except httpx.TimeoutException:
            logger.error("momo.create_qr_payment_timeout", order_id=order_id)
            raise MoMoTimeoutError("MoMo create QR payment request timed out", code="TIMEOUT")

        self._check_response(resp, "create_qr_payment")
        return resp.json()

    async def confirm_payment(
        self,
        order_id: str,
        amount_fen: int,
        request_id: Optional[str] = None,
    ) -> dict:
        """Confirm/complete a MoMo payment.

        POST /v2/gateway/api/confirm

        Args:
            order_id:   Merchant order ID.
            amount_fen: Payment amount in VND.
            request_id: Unique request ID (defaults to order_id).

        Returns:
            MoMo API confirmation response.
        """
        if amount_fen < 0:
            raise ValueError("amount_fen must be non-negative")

        request_id = request_id or order_id
        raw_sign = f"accessKey={self.access_key}&orderId={order_id}&partnerCode={self.partner_code}&requestId={request_id}"
        signature = self._hmac_sign(raw_sign)

        payload: dict[str, Any] = {
            "partnerCode": self.partner_code,
            "orderId": order_id,
            "requestId": request_id,
            "amount": str(amount_fen),
            "lang": "vi",
            "signature": signature,
        }

        logger.info("momo.confirm_payment", order_id=order_id)

        try:
            resp = await self._request("POST", "/v2/gateway/api/confirm", json=payload)
        except httpx.TimeoutException:
            logger.error("momo.confirm_payment_timeout", order_id=order_id)
            raise MoMoTimeoutError("MoMo confirm payment request timed out", code="TIMEOUT")

        self._check_response(resp, "confirm_payment")
        return resp.json()

    async def query_transaction(self, order_id: str) -> dict:
        """Query MoMo transaction status.

        POST /v2/gateway/api/query

        Args:
            order_id: Merchant order ID.

        Returns:
            Transaction status from MoMo.
        """
        request_id = order_id
        raw_sign = (
            f"accessKey={self.access_key}&orderId={order_id}"
            f"&partnerCode={self.partner_code}&requestId={request_id}"
        )
        signature = self._hmac_sign(raw_sign)

        payload: dict[str, Any] = {
            "partnerCode": self.partner_code,
            "orderId": order_id,
            "requestId": request_id,
            "lang": "vi",
            "signature": signature,
        }

        logger.info("momo.query_transaction", order_id=order_id)

        try:
            resp = await self._request("POST", "/v2/gateway/api/query", json=payload)
        except httpx.TimeoutException:
            logger.error("momo.query_transaction_timeout", order_id=order_id)
            raise MoMoTimeoutError("MoMo query transaction request timed out", code="TIMEOUT")

        self._check_response(resp, "query_transaction")
        return resp.json()

    async def refund(
        self,
        order_id: str,
        amount_fen: int,
        trans_id: str,
        description: str = "",
    ) -> dict:
        """Refund a MoMo transaction.

        POST /v2/gateway/api/refund

        Args:
            order_id:    Merchant order ID (new ID for the refund).
            amount_fen:  Refund amount in VND.
            trans_id:    Original MoMo transaction ID to refund.
            description: Refund reason/description.

        Returns:
            MoMo refund response.
        """
        if amount_fen < 0:
            raise ValueError("amount_fen must be non-negative")

        request_id = order_id
        raw_sign = (
            f"accessKey={self.access_key}&amount={amount_fen}&description={description}"
            f"&orderId={order_id}&partnerCode={self.partner_code}&requestId={request_id}"
            f"&transId={trans_id}"
        )
        signature = self._hmac_sign(raw_sign)

        payload: dict[str, Any] = {
            "partnerCode": self.partner_code,
            "orderId": order_id,
            "requestId": request_id,
            "amount": str(amount_fen),
            "transId": trans_id,
            "description": description,
            "lang": "vi",
            "signature": signature,
        }

        logger.info("momo.refund", order_id=order_id, amount_fen=amount_fen, trans_id=trans_id)

        try:
            resp = await self._request("POST", "/v2/gateway/api/refund", json=payload)
        except httpx.TimeoutException:
            logger.error("momo.refund_timeout", order_id=order_id)
            raise MoMoTimeoutError("MoMo refund request timed out", code="TIMEOUT")

        self._check_response(resp, "refund")
        return resp.json()

    # ── Signature verification ──────────────────────────────────────────────

    def verify_webhook_signature(self, raw_body: str, signature: str) -> dict:
        """Verify MoMo IPN/webhook HMAC-SHA256 signature.

        MoMo signs webhook payloads using HMAC-SHA256 with secret_key.

        Args:
            raw_body:   Raw webhook request body (JSON string).
            signature:  Signature from the request.

        Returns:
            Parsed webhook payload dict.

        Raises:
            MoMoSignatureError: signature mismatch or missing params.
        """
        if not raw_body:
            raise MoMoSignatureError("Webhook body is empty", code="EMPTY_BODY")
        if not signature:
            raise MoMoSignatureError("Webhook signature header is empty", code="EMPTY_SIGN")

        payload = json.loads(raw_body)

        expected_sign = self._hmac_sign(raw_body)

        if not hmac.compare_digest(expected_sign, signature):
            logger.error(
                "momo.webhook_signature_mismatch",
                expected=expected_sign[:16],
                received=signature[:16],
            )
            raise MoMoSignatureError(
                "MoMo webhook HMAC-SHA256 signature verification failed",
                code="SIGN_MISMATCH",
            )

        logger.info(
            "momo.webhook_signature_verified",
            order_id=payload.get("orderId", ""),
        )
        return payload

    # ── Resource management ─────────────────────────────────────────────────

    async def aclose(self) -> None:
        """Close the underlying HTTP client connection pool."""
        await self._client.aclose()

    # ── Internal helpers ────────────────────────────────────────────────────

    def _hmac_sign(self, raw_data: str) -> str:
        """Generate HMAC-SHA256 signature."""
        return hmac.new(
            self.secret_key.encode("utf-8"),
            raw_data.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    def _build_request(
        self,
        order_id: str,
        amount_fen: int,
        order_info: str,
        extra_data: str,
        request_id: str,
        store_name: str,
        redirect_url: str,
        ipn_url: str,
    ) -> dict[str, Any]:
        """Build a signed MoMo QR payment request."""
        raw_sign = (
            f"accessKey={self.access_key}&amount={amount_fen}&extraData={extra_data}"
            f"&ipnUrl={ipn_url}&orderId={order_id}&orderInfo={order_info}"
            f"&partnerCode={self.partner_code}&redirectUrl={redirect_url}"
            f"&requestId={request_id}&requestType=captureWallet"
        )
        signature = self._hmac_sign(raw_sign)

        return {
            "partnerCode": self.partner_code,
            "partnerName": store_name or "Tunxiang OS",
            "storeId": store_name or "",
            "accessKey": self.access_key,
            "requestId": request_id,
            "amount": str(amount_fen),
            "orderId": order_id,
            "orderInfo": order_info,
            "redirectUrl": redirect_url,
            "ipnUrl": ipn_url,
            "extraData": extra_data,
            "lang": "vi",
            "requestType": "captureWallet",
            "signature": signature,
        }

    async def _request(
        self,
        method: str,
        path: str,
        json: dict[str, Any] | None = None,
    ) -> httpx.Response:
        """Send an HTTP request to MoMo API."""
        try:
            response = await self._client.request(
                method=method,
                url=path,
                json=json,
            )
            response.raise_for_status()
        except httpx.TimeoutException:
            raise MoMoTimeoutError(f"MoMo request timed out: {path}", code="TIMEOUT")
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            body = exc.response.text[:500]
            logger.error(
                "momo.http_error",
                path=path,
                status_code=status,
                body=body,
            )
            raise MoMoError(
                f"MoMo HTTP error: {status}",
                code=f"HTTP_{status}",
                http_status=status,
            )
        return response

    @staticmethod
    def _check_response(resp: httpx.Response, operation: str) -> None:
        """Verify the MoMo API business-level response."""
        try:
            data = resp.json()
        except (json.JSONDecodeError, ValueError) as exc:
            logger.error(
                "momo.invalid_json_response",
                operation=operation,
                body_preview=resp.text[:200],
            )
            raise MoMoError(
                f"MoMo returned invalid JSON: {resp.text[:100]}",
                code="INVALID_RESPONSE",
            ) from exc

        result_code = data.get("resultCode", -1)
        if result_code != 0:
            message = data.get("message", data.get("localMessage", "Unknown error"))
            logger.error(
                "momo.business_error",
                operation=operation,
                result_code=result_code,
                message=message,
            )
            raise MoMoError(
                f"MoMo {operation} failed: {message}",
                code=f"RESULT_{result_code}",
            )
