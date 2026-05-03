"""
GrabFood API client for Malaysian food delivery integration.

Reference: GrabFood Partner API v1
           https://developer.grab.com/

Authentication: OAuth2 client_credentials grant type.
All monetary amounts are in fen (integer), converted to/from MYR internally.
"""

from __future__ import annotations

import asyncio
import json
import time
from datetime import datetime, timezone
from typing import Any, Optional

import httpx
import structlog

logger = structlog.get_logger()

# GrabFood API base URLs
GRABFOOD_PRODUCTION_BASE_URL = "https://partner-api.grab.com"
GRABFOOD_SANDBOX_BASE_URL = "https://partner-api.stg-myteksi.com"
GRABFOOD_PRODUCTION_AUTH_URL = "https://auth.grab.com/oauth2/token"
GRABFOOD_SANDBOX_AUTH_URL = "https://auth.sandbox.grab.com/oauth2/token"

# Token refresh margin: refresh when less than 60s remaining
TOKEN_REFRESH_MARGIN_SEC = 60


class GrabFoodError(Exception):
    """GrabFood API call exception."""

    def __init__(self, message: str, code: str = "", http_status: int = 0):
        super().__init__(message)
        self.code = code
        self.http_status = http_status


class GrabFoodAuthError(GrabFoodError):
    """OAuth2 authentication failure."""
    pass


class GrabFoodTimeoutError(GrabFoodError):
    """Network timeout."""
    pass


class GrabFoodSignatureError(GrabFoodError):
    """Webhook signature verification failure."""
    pass


class GrabFoodClient:
    """GrabFood HTTP API client — OAuth2 client_credentials auth.

    Manages OAuth2 token lifecycle (auto-refresh with mutex guard) and
    provides typed methods for each GrabFood Partner API endpoint.

    Supported endpoints:
      - POST /grabfood/v1/partner/order     Accept an order
      - GET  /grabfood/v1/order/{order_id}  Get order detail
      - POST /grabfood/v1/order/ready       Mark order as ready for pickup
      - POST /grabfood/v1/menu/sync         Sync full menu to GrabFood
      - POST /grabfood/v1/order/reject      Reject / cancel an order

    All monetary amounts are in fen (integer), converted to MYR on the wire.
    """

    # ── Timeout config ──────────────────────────────────────────────────────
    DEFAULT_TIMEOUT = 15.0
    SYNC_MENU_TIMEOUT = 30.0
    AUTH_TIMEOUT = 10.0

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        merchant_id: str,
        production: bool = False,
        base_url: str = "",
    ):
        """
        Args:
            client_id:     GrabFood Partner API Client ID.
            client_secret: GrabFood Partner API Client Secret.
            merchant_id:   GrabFood Merchant ID (required for accept/ready/reject).
            production:    False = sandbox environment (default).
            base_url:      Custom API base URL (overrides production parameter).
        """
        if not client_id:
            raise ValueError("client_id must not be empty")
        if not client_secret:
            raise ValueError("client_secret must not be empty")
        if not merchant_id:
            raise ValueError("merchant_id must not be empty")

        self.client_id = client_id
        self.client_secret = client_secret
        self.merchant_id = merchant_id
        self.production = production

        if base_url:
            resolved_base = base_url.rstrip("/")
        elif production:
            resolved_base = GRABFOOD_PRODUCTION_BASE_URL
        else:
            resolved_base = GRABFOOD_SANDBOX_BASE_URL

        self.base_url = resolved_base
        self.auth_url = (
            GRABFOOD_PRODUCTION_AUTH_URL if production else GRABFOOD_SANDBOX_AUTH_URL
        )

        # OAuth2 token state (in-memory)
        self._access_token: str | None = None
        self._token_expires_at: float = 0.0  # Unix timestamp
        self._token_lock = asyncio.Lock()

        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=httpx.Timeout(self.DEFAULT_TIMEOUT),
            verify=True,
        )

    # ── Public API methods ──────────────────────────────────────────────────

    async def accept_order(self, order_id: str) -> dict:
        """Accept an incoming GrabFood order.

        POST /grabfood/v1/partner/order

        Args:
            order_id: The GrabFood order ID to accept.

        Returns:
            {"code": "OK", "message": "Order accepted"}

        Raises:
            GrabFoodError, GrabFoodAuthError, GrabFoodTimeoutError
        """
        if not order_id:
            raise ValueError("order_id must not be empty")

        token = await self._get_token()
        payload: dict[str, Any] = {
            "orderID": order_id,
            "merchantID": self.merchant_id,
        }
        headers = self._auth_headers(token)

        logger.info("grabfood.accept_order", order_id=order_id)

        try:
            resp = await self._request(
                "POST",
                "/grabfood/v1/partner/order",
                headers=headers,
                json=payload,
            )
        except httpx.TimeoutException:
            logger.error("grabfood.accept_order_timeout", order_id=order_id)
            raise GrabFoodTimeoutError(
                "GrabFood accept order request timed out", code="TIMEOUT"
            )

        self._check_response(resp, "accept_order")
        logger.info("grabfood.accept_order_success", order_id=order_id)
        return resp.json()

    async def reject_order(self, order_id: str, reason: str) -> dict:
        """Reject / cancel a GrabFood order.

        POST /grabfood/v1/order/reject

        Args:
            order_id: The GrabFood order ID to reject.
            reason:   Reason for rejection (displayed to customer).

        Returns:
            {"code": "OK", "message": "Order rejected"}

        Raises:
            GrabFoodError, GrabFoodAuthError, GrabFoodTimeoutError
        """
        if not order_id:
            raise ValueError("order_id must not be empty")
        if not reason:
            raise ValueError("reject reason must not be empty")

        token = await self._get_token()
        payload: dict[str, Any] = {
            "orderID": order_id,
            "merchantID": self.merchant_id,
            "reason": reason,
        }
        headers = self._auth_headers(token)

        logger.info("grabfood.reject_order", order_id=order_id, reason=reason)

        try:
            resp = await self._request(
                "POST",
                "/grabfood/v1/order/reject",
                headers=headers,
                json=payload,
            )
        except httpx.TimeoutException:
            logger.error("grabfood.reject_order_timeout", order_id=order_id)
            raise GrabFoodTimeoutError(
                "GrabFood reject order request timed out", code="TIMEOUT"
            )

        self._check_response(resp, "reject_order")
        logger.info("grabfood.reject_order_success", order_id=order_id)
        return resp.json()

    async def mark_ready(self, order_id: str) -> dict:
        """Mark a GrabFood order as ready for rider pickup.

        POST /grabfood/v1/order/ready

        Args:
            order_id: The GrabFood order ID to mark ready.

        Returns:
            {"code": "OK", "message": "Order marked as ready"}

        Raises:
            GrabFoodError, GrabFoodAuthError, GrabFoodTimeoutError
        """
        if not order_id:
            raise ValueError("order_id must not be empty")

        token = await self._get_token()
        payload: dict[str, Any] = {
            "orderID": order_id,
            "merchantID": self.merchant_id,
        }
        headers = self._auth_headers(token)

        logger.info("grabfood.mark_ready", order_id=order_id)

        try:
            resp = await self._request(
                "POST",
                "/grabfood/v1/order/ready",
                headers=headers,
                json=payload,
            )
        except httpx.TimeoutException:
            logger.error("grabfood.mark_ready_timeout", order_id=order_id)
            raise GrabFoodTimeoutError(
                "GrabFood mark ready request timed out", code="TIMEOUT"
            )

        self._check_response(resp, "mark_ready")
        logger.info("grabfood.mark_ready_success", order_id=order_id)
        return resp.json()

    async def get_order_detail(self, order_id: str) -> dict:
        """Retrieve full GrabFood order detail.

        GET /grabfood/v1/order/{order_id}

        Args:
            order_id: The GrabFood order ID.

        Returns:
            Raw order payload from GrabFood.

        Raises:
            GrabFoodError, GrabFoodAuthError, GrabFoodTimeoutError
        """
        if not order_id:
            raise ValueError("order_id must not be empty")

        token = await self._get_token()
        headers = self._auth_headers(token)

        logger.info("grabfood.get_order_detail", order_id=order_id)

        try:
            resp = await self._request(
                "GET",
                f"/grabfood/v1/order/{order_id}",
                headers=headers,
            )
        except httpx.TimeoutException:
            logger.error("grabfood.get_order_detail_timeout", order_id=order_id)
            raise GrabFoodTimeoutError(
                "GrabFood get order detail request timed out", code="TIMEOUT"
            )

        self._check_response(resp, "get_order_detail")
        return resp.json()

    async def sync_menu(self, dishes: list[dict]) -> dict:
        """Synchronise full menu to GrabFood.

        POST /grabfood/v1/menu/sync

        This is a full replacement sync — all active menu items must be
        included in the request. Items not in the payload are removed.

        Args:
            dishes: List of dish dicts in GrabFood menu item format:
                [{
                    "itemCode": "SKU001",
                    "itemName": "Nasi Lemak",
                    "price": 8.50,
                    "currency": "MYR",
                    "isAvailable": True,
                    "category": "Rice",
                    "description": "...",
                }, ...]

        Returns:
            {"code": "OK", "message": "Menu sync successful"}

        Raises:
            GrabFoodError, GrabFoodAuthError, GrabFoodTimeoutError
        """
        token = await self._get_token()
        headers = self._auth_headers(token)

        payload: dict[str, Any] = {
            "merchantID": self.merchant_id,
            "menu": dishes,
        }

        logger.info("grabfood.sync_menu", dish_count=len(dishes))

        try:
            resp = await self._request(
                "POST",
                "/grabfood/v1/menu/sync",
                headers=headers,
                json=payload,
                timeout=self.SYNC_MENU_TIMEOUT,
            )
        except httpx.TimeoutException:
            logger.error("grabfood.sync_menu_timeout")
            raise GrabFoodTimeoutError(
                "GrabFood sync menu request timed out", code="TIMEOUT"
            )

        self._check_response(resp, "sync_menu")
        result = resp.json()
        logger.info(
            "grabfood.sync_menu_success",
            response=result,
        )
        return result

    # ── Signature verification ──────────────────────────────────────────────

    def verify_webhook_signature(self, raw_body: str, signature: str) -> dict:
        """Verify GrabFood webhook HMAC-SHA256 signature.

        GrabFood signs webhook payloads using HMAC-SHA256 with the
        app_secret (client_secret) as the shared key.

        Args:
            raw_body:   Raw webhook request body (JSON string).
            signature:  Signature from the X-GrabFood-Signature header.

        Returns:
            Parsed webhook payload dict.

        Raises:
            GrabFoodSignatureError: signature mismatch or missing params.
        """
        import hashlib
        import hmac

        if not raw_body:
            raise GrabFoodSignatureError(
                "Webhook body is empty", code="EMPTY_BODY"
            )
        if not signature:
            raise GrabFoodSignatureError(
                "Webhook signature header is empty", code="EMPTY_SIGN"
            )

        payload = json.loads(raw_body)

        expected_sign = hmac.new(
            self.client_secret.encode("utf-8"),
            raw_body.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

        if not hmac.compare_digest(expected_sign, signature):
            logger.error(
                "grabfood.webhook_signature_mismatch",
                expected=expected_sign[:16],
                received=signature[:16],
            )
            raise GrabFoodSignatureError(
                "GrabFood webhook HMAC-SHA256 signature verification failed",
                code="SIGN_MISMATCH",
            )

        logger.info(
            "grabfood.webhook_signature_verified",
            order_id=payload.get("orderID", ""),
        )
        return payload

    # ── Resource management ─────────────────────────────────────────────────

    async def aclose(self) -> None:
        """Close the underlying HTTP client connection pool."""
        await self._client.aclose()

    # ── OAuth2 token management ─────────────────────────────────────────────

    async def _get_token(self) -> str:
        """Get a valid OAuth2 access token, auto-refreshing if needed.

        Uses asyncio.Lock to prevent concurrent token refresh.
        """
        if self._access_token and time.time() < self._token_expires_at - TOKEN_REFRESH_MARGIN_SEC:
            return self._access_token

        async with self._token_lock:
            # Double-check: another coroutine may have refreshed already
            if self._access_token and time.time() < self._token_expires_at - TOKEN_REFRESH_MARGIN_SEC:
                return self._access_token

            await self._refresh_token()
            assert self._access_token is not None
            return self._access_token

    async def _refresh_token(self) -> None:
        """Obtain a new OAuth2 access token via client_credentials grant.

        POST /oauth2/token with client_id, client_secret, grant_type.
        """
        logger.info("grabfood.refreshing_token", production=self.production)

        payload = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "grant_type": "client_credentials",
            "scope": "partner",
        }

        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(self.AUTH_TIMEOUT)
            ) as auth_client:
                resp = await auth_client.post(
                    self.auth_url,
                    json=payload,
                    headers={"Content-Type": "application/json"},
                )
                resp.raise_for_status()
        except httpx.TimeoutException:
            logger.error("grabfood.auth_timeout")
            raise GrabFoodAuthError(
                "GrabFood OAuth2 token request timed out", code="AUTH_TIMEOUT"
            )
        except httpx.HTTPStatusError as exc:
            logger.error(
                "grabfood.auth_failed",
                status_code=exc.response.status_code,
                body=exc.response.text[:300],
            )
            raise GrabFoodAuthError(
                f"GrabFood OAuth2 authentication failed: {exc.response.status_code}",
                code="AUTH_FAILED",
                http_status=exc.response.status_code,
            )

        try:
            data = resp.json()
        except (json.JSONDecodeError, ValueError) as exc:
            logger.error("grabfood.auth_invalid_json_response")
            raise GrabFoodAuthError(
                "GrabFood OAuth2 returned invalid JSON", code="INVALID_RESPONSE"
            ) from exc

        token = data.get("access_token")
        if not token:
            logger.error("grabfood.auth_no_token_in_response", response=data)
            raise GrabFoodAuthError(
                "GrabFood OAuth2 response missing access_token",
                code="NO_TOKEN",
            )

        expires_in = data.get("expires_in", 3600)
        self._access_token = token
        self._token_expires_at = time.time() + expires_in

        logger.info(
            "grabfood.token_refreshed",
            expires_in=expires_in,
            expires_at=datetime.fromtimestamp(
                self._token_expires_at, tz=timezone.utc
            ).isoformat(),
        )

    # ── Internal helpers ────────────────────────────────────────────────────

    @staticmethod
    def _fen_to_myr(fen: int) -> str:
        """Convert fen (integer cents) to MYR string with 2 decimal places."""
        return f"{fen / 100:.2f}"

    @staticmethod
    def _myr_to_fen(myr: str) -> int:
        """Convert MYR string to fen (integer cents)."""
        try:
            return int(round(float(myr) * 100))
        except (ValueError, TypeError):
            logger.warning("grabfood.invalid_myr_amount", myr=myr)
            return 0

    def _auth_headers(self, token: str) -> dict[str, str]:
        """Build standard auth headers for GrabFood API requests."""
        return {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
        }

    async def _request(
        self,
        method: str,
        path: str,
        headers: dict[str, str] | None = None,
        json: dict[str, Any] | None = None,
        timeout: float | None = None,
    ) -> httpx.Response:
        """Send an authenticated HTTP request to the GrabFood API.

        Handles HTTP errors, auth failures, and timeouts uniformly.
        """
        request_timeout = timeout or self.DEFAULT_TIMEOUT

        try:
            response = await self._client.request(
                method=method,
                url=path,
                headers=headers,
                json=json,
                timeout=request_timeout,
            )
            response.raise_for_status()
        except httpx.TimeoutException:
            raise GrabFoodTimeoutError(
                f"GrabFood request timed out: {path}", code="TIMEOUT"
            )
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            body = exc.response.text[:500]
            logger.error(
                "grabfood.http_error",
                path=path,
                status_code=status,
                body=body,
            )
            if status == 401:
                # Force token refresh on next call
                self._access_token = None
                raise GrabFoodAuthError(
                    "GrabFood authentication failed (token expired)",
                    code="AUTH_FAILED",
                )
            raise GrabFoodError(
                f"GrabFood HTTP error: {status}",
                code=f"HTTP_{status}",
                http_status=status,
            )

        return response

    @staticmethod
    def _check_response(resp: httpx.Response, operation: str) -> None:
        """Verify the GrabFood API business-level response code."""
        try:
            data = resp.json()
        except (json.JSONDecodeError, ValueError) as exc:
            logger.error(
                "grabfood.invalid_json_response",
                operation=operation,
                body_preview=resp.text[:200],
            )
            raise GrabFoodError(
                f"GrabFood returned invalid JSON: {resp.text[:100]}",
                code="INVALID_RESPONSE",
            ) from exc

        code = data.get("code", "")
        if code != "OK":
            message = data.get("message", data.get("msg", "Unknown error"))
            logger.error(
                "grabfood.business_error",
                operation=operation,
                code=code,
                message=message,
            )
            raise GrabFoodError(
                f"GrabFood {operation} failed: {message}", code=code
            )
