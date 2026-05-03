"""
GoPay API client for Indonesian payment processing.

Reference: GoPay Merchant API docs (Production)
           https://developer.gopay.co.id/

Authentication: OAuth2 client_credentials grant type.
All monetary amounts are in fen (integer), converted to/from IDR internally.
IDR has no decimal places, so 1 IDR = 1 fen.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import time
from datetime import datetime, timezone
from typing import Any, Optional

import httpx
import structlog

logger = structlog.get_logger()

# GoPay API endpoints
GOPAY_SANDBOX_BASE_URL = "https://api-sandbox.gopay.co.id/v2"
GOPAY_PRODUCTION_BASE_URL = "https://api.gopay.co.id/v2"
GOPAY_SANDBOX_AUTH_URL = "https://auth-sandbox.gopay.co.id/oauth2/token"
GOPAY_PRODUCTION_AUTH_URL = "https://auth.gopay.co.id/oauth2/token"

# Token refresh margin: refresh when less than 60s remaining
TOKEN_REFRESH_MARGIN_SEC = 60


class GoPayError(Exception):
    """GoPay API调用异常"""

    def __init__(self, message: str, code: str = "", http_status: int = 0):
        super().__init__(message)
        self.code = code
        self.http_status = http_status


class GoPayAuthError(GoPayError):
    """OAuth2 认证失败"""
    pass


class GoPayTimeoutError(GoPayError):
    """网络超时"""
    pass


class GoPaySignatureError(GoPayError):
    """回调签名校验失败"""
    pass


class GoPayClient:
    """GoPay HTTP 客户端 — 使用 OAuth2 client_credentials 认证

    支持以下核心接口:
      - create_payment:   创建支付订单（QR / H5 支付链接）
      - query_payment:    查询支付状态
      - refund:           退款
      - verify_callback:  验证异步回调签名

    OAuth2 Token 自动管理：
      - 首次调用自动获取
      - 过期前自动刷新（带互斥锁防并发刷新）
      - token 和过期时间保存在内存中

    All monetary amounts in fen (integer), converted to/from IDR internally.
    """

    # ─── 超时配置 ─────────────────────────────────────────────────────────────────
    CREATE_TIMEOUT = 30.0
    QUERY_TIMEOUT = 10.0
    REFUND_TIMEOUT = 15.0
    AUTH_TIMEOUT = 10.0

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
            base_url:      自定义 API 基础 URL（覆盖 production 参数）
        """
        if not client_id:
            raise ValueError("client_id 不能为空")
        if not client_secret:
            raise ValueError("client_secret 不能为空")

        self.client_id = client_id
        self.client_secret = client_secret
        self.production = production

        if base_url:
            resolved_base = base_url.rstrip("/")
        elif production:
            resolved_base = GOPAY_PRODUCTION_BASE_URL
        else:
            resolved_base = GOPAY_SANDBOX_BASE_URL

        self.base_url = resolved_base
        self.auth_url = GOPAY_PRODUCTION_AUTH_URL if production else GOPAY_SANDBOX_AUTH_URL

        # OAuth2 token 状态（内存中维护）
        self._access_token: str | None = None
        self._token_expires_at: float = 0.0  # Unix timestamp
        self._token_lock = asyncio.Lock()

        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=httpx.Timeout(self.CREATE_TIMEOUT),
            verify=True,
        )

    # ─── 公共接口 ─────────────────────────────────────────────────────────────────

    async def create_payment(
        self,
        order_id: str,
        payment_no: str,
        amount_fen: int,
        callback_url: str,
        redirect_url: str = "",
        description: str = "",
    ) -> dict:
        """创建支付订单 — 返回支付 QR 码和 URL

        顾客使用 GoPay App 扫码或在浏览器中打开支付 URL 完成付款。
        支付完成后 GoPay 服务器异步回调 callback_url。

        Args:
            order_id:       屯象订单ID
            payment_no:     商户支付流水号（唯一）
            amount_fen:     支付金额（分）
            callback_url:   异步通知地址
            redirect_url:   支付完成后跳转地址（可选）
            description:    订单描述（可选）

        Returns:
            {
                "gopay_txn_id": "GOPAY123456789",
                "payment_url": "https://...",
                "qr_code": "https://...",
                "status": "pending",
            }

        Raises:
            GoPayError:      API 调用失败
            GoPayAuthError:  认证失败
            GoPayTimeoutError: 请求超时
        """
        if not order_id:
            raise ValueError("order_id 不能为空")
        if not payment_no:
            raise ValueError("payment_no 不能为空")
        if not isinstance(amount_fen, int) or amount_fen <= 0:
            raise ValueError(f"amount_fen 必须为正整数(分)，当前值: {amount_fen}")
        if not callback_url:
            raise ValueError("callback_url 不能为空")

        amount_idr = self._fen_to_idr(amount_fen)
        token = await self._get_token()

        payload: dict[str, Any] = {
            "merchantOrderNo": payment_no,
            "orderId": order_id,
            "amount": amount_idr,
            "currency": "IDR",
            "callbackUrl": callback_url,
            "description": description or f"Order {order_id[:8]}",
        }
        if redirect_url:
            payload["redirectUrl"] = redirect_url

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
        }

        logger.info(
            "gopay.create_payment",
            payment_no=payment_no,
            amount_fen=amount_fen,
            sandbox=not self.production,
        )

        try:
            resp = await self._request("POST", "/payment/orders", headers=headers, json=payload, timeout=self.CREATE_TIMEOUT)
        except httpx.TimeoutException:
            logger.error("gopay.create_payment_timeout", payment_no=payment_no)
            raise GoPayTimeoutError("GoPay 创建支付请求超时", code="TIMEOUT")

        self._check_response(resp, "创建支付")

        data = resp.json()
        logger.info(
            "gopay.create_payment_success",
            payment_no=payment_no,
            gopay_txn_id=data.get("gopayTxnId", ""),
        )

        return {
            "gopay_txn_id": data.get("gopayTxnId", ""),
            "payment_url": data.get("paymentUrl", ""),
            "qr_code": data.get("qrCode", ""),
            "status": data.get("status", "pending"),
        }

    async def query_payment(self, gopay_txn_id: str) -> dict:
        """查询支付状态

        Args:
            gopay_txn_id: GoPay 侧交易号

        Returns:
            {
                "gopay_txn_id": "...",
                "status": "paid" | "pending" | "failed",
                "amount_fen": 8800,
                "paid_at": "2026-05-03T12:00:00+07:00",
            }
        """
        if not gopay_txn_id:
            raise ValueError("gopay_txn_id 不能为空")

        token = await self._get_token()
        headers = {"Authorization": f"Bearer {token}"}

        logger.info("gopay.query_payment", gopay_txn_id=gopay_txn_id)

        try:
            resp = await self._request(
                "GET",
                f"/payment/orders/{gopay_txn_id}",
                headers=headers,
                timeout=self.QUERY_TIMEOUT,
            )
        except httpx.TimeoutException:
            logger.error("gopay.query_payment_timeout", gopay_txn_id=gopay_txn_id)
            raise GoPayTimeoutError("GoPay 查询支付请求超时", code="TIMEOUT")

        self._check_response(resp, "查询支付")

        data = resp.json()
        amount_idr = data.get("amount", "0")
        amount_fen = self._idr_to_fen(amount_idr)

        return {
            "gopay_txn_id": data.get("gopayTxnId", gopay_txn_id),
            "status": data.get("status", "unknown"),
            "amount_fen": amount_fen,
            "paid_at": data.get("paidAt"),
            "merchant_order_no": data.get("merchantOrderNo", ""),
        }

    async def refund(
        self,
        gopay_txn_id: str,
        refund_no: str,
        amount_fen: int,
        reason: str = "",
    ) -> dict:
        """退款 — 原路退回 GoPay Wallet

        Args:
            gopay_txn_id:  GoPay 侧交易号
            refund_no:     商户退款单号（唯一）
            amount_fen:    退款金额（分）
            reason:        退款原因（可选）

        Returns:
            {
                "gopay_refund_id": "...",
                "status": "refunded",
                "amount_fen": 8800,
            }
        """
        if not gopay_txn_id:
            raise ValueError("gopay_txn_id 不能为空")
        if not refund_no:
            raise ValueError("refund_no 不能为空")
        if not isinstance(amount_fen, int) or amount_fen <= 0:
            raise ValueError(f"amount_fen 必须为正整数(分)，当前值: {amount_fen}")

        amount_idr = self._fen_to_idr(amount_fen)
        token = await self._get_token()

        payload: dict[str, Any] = {
            "merchantRefundNo": refund_no,
            "amount": amount_idr,
            "currency": "IDR",
            "reason": reason or "Customer requested refund",
        }

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
        }

        logger.info(
            "gopay.refund",
            gopay_txn_id=gopay_txn_id,
            refund_no=refund_no,
            amount_fen=amount_fen,
        )

        try:
            resp = await self._request(
                "POST",
                f"/payment/orders/{gopay_txn_id}/refund",
                headers=headers,
                json=payload,
                timeout=self.REFUND_TIMEOUT,
            )
        except httpx.TimeoutException:
            logger.error("gopay.refund_timeout", gopay_txn_id=gopay_txn_id, refund_no=refund_no)
            raise GoPayTimeoutError("GoPay 退款请求超时", code="TIMEOUT")

        self._check_response(resp, "退款")

        data = resp.json()
        refund_amount_idr = data.get("amount", "0")
        refund_amount_fen = self._idr_to_fen(refund_amount_idr)

        logger.info(
            "gopay.refund_success",
            gopay_txn_id=gopay_txn_id,
            gopay_refund_id=data.get("gopayRefundId", ""),
            amount_fen=refund_amount_fen,
        )

        return {
            "gopay_refund_id": data.get("gopayRefundId", ""),
            "status": data.get("status", "refunded"),
            "amount_fen": refund_amount_fen,
        }

    def verify_callback(self, raw_body: str, signature: str) -> dict:
        """验证 GoPay 异步回调签名

        GoPay 使用 HMAC-SHA256 签名验证机制。

        Args:
            raw_body:   回调请求体原始字符串（JSON）
            signature:  Header 中的签名字符串

        Returns:
            解析后的回调 payload 字典

        Raises:
            GoPaySignatureError: 签名校验失败
        """
        if not raw_body:
            raise GoPaySignatureError("回调 body 为空", code="EMPTY_BODY")
        if not signature:
            raise GoPaySignatureError("回调 signature 为空", code="EMPTY_SIGN")

        payload = json.loads(raw_body)

        expected_sign = hmac.new(
            self.client_secret.encode("utf-8"),
            raw_body.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

        if not hmac.compare_digest(expected_sign, signature):
            logger.error(
                "gopay.callback_signature_mismatch",
                expected=expected_sign[:16],
                received=signature[:16],
            )
            raise GoPaySignatureError("GoPay 回调签名校验失败", code="SIGN_MISMATCH")

        logger.info("gopay.callback_verified", gopay_txn_id=payload.get("gopayTxnId", ""))
        return payload

    async def aclose(self) -> None:
        """关闭 HTTP 客户端连接池"""
        await self._client.aclose()

    # ─── OAuth2 Token 管理 ───────────────────────────────────────────────────────

    async def _get_token(self) -> str:
        """获取有效的 OAuth2 access token（自动刷新）

        如果 token 不存在或即将过期（<60s），自动刷新。
        使用 asyncio.Lock 防止并发刷新。
        """
        if self._access_token and time.time() < self._token_expires_at - TOKEN_REFRESH_MARGIN_SEC:
            return self._access_token

        async with self._token_lock:
            # 二次检查（另一个协程可能已经刷新了）
            if self._access_token and time.time() < self._token_expires_at - TOKEN_REFRESH_MARGIN_SEC:
                return self._access_token

            await self._refresh_token()
            assert self._access_token is not None
            return self._access_token

    async def _refresh_token(self) -> None:
        """获取新的 OAuth2 access token（client_credentials grant）"""
        logger.info("gopay.refreshing_token", production=self.production)

        payload = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "grant_type": "client_credentials",
            "scope": "payment",
        }

        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(self.AUTH_TIMEOUT)) as auth_client:
                resp = await auth_client.post(
                    self.auth_url,
                    json=payload,
                    headers={"Content-Type": "application/json"},
                )
                resp.raise_for_status()
        except httpx.TimeoutException:
            logger.error("gopay.auth_timeout")
            raise GoPayAuthError("GoPay OAuth2 请求超时", code="AUTH_TIMEOUT")
        except httpx.HTTPStatusError as exc:
            logger.error(
                "gopay.auth_failed",
                status_code=exc.response.status_code,
                body=exc.response.text[:300],
            )
            raise GoPayAuthError(
                f"GoPay OAuth2 认证失败: {exc.response.status_code}",
                code="AUTH_FAILED",
                http_status=exc.response.status_code,
            )

        try:
            data = resp.json()
        except (json.JSONDecodeError, ValueError) as exc:
            logger.error("gopay.auth_invalid_json")
            raise GoPayAuthError("GoPay OAuth2 返回非法 JSON", code="INVALID_RESPONSE") from exc

        token = data.get("access_token")
        if not token:
            logger.error("gopay.auth_no_token", response=data)
            raise GoPayAuthError("GoPay OAuth2 响应中缺少 access_token", code="NO_TOKEN")

        expires_in = data.get("expires_in", 3600)
        self._access_token = token
        self._token_expires_at = time.time() + expires_in

        logger.info(
            "gopay.token_refreshed",
            expires_in=expires_in,
            expires_at=datetime.fromtimestamp(self._token_expires_at, tz=timezone.utc).isoformat(),
        )

    # ─── 内部方法 ─────────────────────────────────────────────────────────────────

    @staticmethod
    def _fen_to_idr(fen: int) -> str:
        """分转 IDR（IDR 没有小数位，直接返回整数）"""
        return str(int(fen))

    @staticmethod
    def _idr_to_fen(idr: str) -> int:
        """IDR 转分（IDR 没有小数位，直接解析整数）"""
        try:
            return int(float(idr))
        except (ValueError, TypeError):
            logger.warning("gopay.invalid_idr_amount", idr=idr)
            return 0

    async def _request(
        self,
        method: str,
        path: str,
        headers: dict[str, str] | None = None,
        json: dict[str, Any] | None = None,
        timeout: float | None = None,
    ) -> httpx.Response:
        """发送 HTTP 请求"""
        request_timeout = timeout or self.CREATE_TIMEOUT

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
            raise GoPayTimeoutError(f"GoPay 请求超时: {path}", code="TIMEOUT")
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            body = exc.response.text[:500]
            logger.error(
                "gopay.http_error",
                path=path,
                status_code=status,
                body=body,
            )
            if status == 401:
                raise GoPayAuthError("GoPay 认证失败（token 可能已过期）", code="AUTH_FAILED")
            raise GoPayError(
                f"GoPay HTTP 错误: {status}",
                code=f"HTTP_{status}",
                http_status=status,
            )

        return response

    @staticmethod
    def _check_response(resp: httpx.Response, operation: str) -> None:
        """检查业务响应状态码"""
        try:
            data = resp.json()
        except (json.JSONDecodeError, ValueError) as exc:
            logger.error("gopay.invalid_json", operation=operation, body_preview=resp.text[:200])
            raise GoPayError(f"GoPay 返回非法JSON: {resp.text[:100]}", code="INVALID_RESPONSE") from exc

        code = data.get("code", "0")
        if code != "0" and code != "SUCCESS":
            message = data.get("message", data.get("msg", "未知错误"))
            logger.error(
                "gopay.business_error",
                operation=operation,
                code=code,
                message=message,
            )
            raise GoPayError(f"GoPay {operation}失败: {message}", code=code)
