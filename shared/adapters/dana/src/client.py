"""
DANA API client for Indonesian payment processing.

Reference: DANA Merchant API docs
           https://developer.dana.id/

Authentication: API Key + HMAC-SHA256 signature.
All monetary amounts are in fen (integer), converted to/from IDR internally.
IDR has no decimal places, so 1 IDR = 1 fen.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from typing import Any, Optional

import httpx
import structlog

logger = structlog.get_logger()

# DANA API endpoints
DANA_SANDBOX_BASE_URL = "https://sandbox.api.dana.id/v1"
DANA_PRODUCTION_BASE_URL = "https://api.dana.id/v1"


class DanaError(Exception):
    """DANA API调用异常"""

    def __init__(self, message: str, code: str = "", http_status: int = 0):
        super().__init__(message)
        self.code = code
        self.http_status = http_status


class DanaAuthError(DanaError):
    """认证失败（api_key / api_secret 无效）"""
    pass


class DanaTimeoutError(DanaError):
    """网络超时"""
    pass


class DanaSignatureError(DanaError):
    """回调签名校验失败"""
    pass


class DanaClient:
    """DANA HTTP 客户端

    支持以下核心接口:
      - create_payment:   创建支付订单，返回支付二维码/URL
      - query_payment:    查询支付状态
      - refund:           退款
      - verify_callback:  验证异步回调签名

    所有金额参数单位为 分(fen)，内部自动转换为 IDR 传给 API。
    IDR 没有小数位，转换直接取整。
    使用 httpx.AsyncClient 共享连接池。
    """

    # ─── 超时配置 ─────────────────────────────────────────────────────────────────
    CREATE_TIMEOUT = 30.0
    QUERY_TIMEOUT = 10.0
    REFUND_TIMEOUT = 15.0

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
            api_key:       DANA 分配的 API Key
            api_secret:    DANA API 签名密钥
            merchant_code: 商户编码（部分版本需要）
            production:    是否生产环境（False = 沙箱环境）
            base_url:      自定义 API 基础 URL
        """
        if not api_key:
            raise ValueError("api_key 不能为空")
        if not api_secret:
            raise ValueError("api_secret 不能为空")

        self.api_key = api_key
        self.api_secret = api_secret
        self.merchant_code = merchant_code
        self.production = production

        if base_url:
            resolved_base = base_url.rstrip("/")
        elif production:
            resolved_base = DANA_PRODUCTION_BASE_URL
        else:
            resolved_base = DANA_SANDBOX_BASE_URL

        self.base_url = resolved_base

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
        """创建支付订单 — 返回支付 URL 和二维码

        顾客使用 DANA App 扫码或在浏览器中打开支付 URL 完成付款。
        支付完成后 DANA 服务器异步回调 callback_url。

        Args:
            order_id:      屯象订单ID
            payment_no:    商户支付流水号（唯一）
            amount_fen:    支付金额（分）
            callback_url:  异步通知地址
            redirect_url:  支付完成后跳转地址（可选）
            description:   订单描述（可选）

        Returns:
            {
                "dana_txn_id": "DANA123456789",
                "payment_url": "https://...",
                "qr_code": "https://...",
                "status": "pending",
            }

        Raises:
            DanaError:      API 调用失败
            DanaAuthError:  认证失败
            DanaTimeoutError: 请求超时
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
        timestamp = str(int(time.time() * 1000))  # DANA uses millisecond timestamps

        payload: dict[str, Any] = {
            "apiKey": self.api_key,
            "merchantOrderNo": payment_no,
            "orderId": order_id,
            "amount": amount_idr,
            "currency": "IDR",
            "callbackUrl": callback_url,
            "timestamp": timestamp,
        }
        if self.merchant_code:
            payload["merchantCode"] = self.merchant_code
        if redirect_url:
            payload["redirectUrl"] = redirect_url
        if description:
            payload["description"] = description

        payload["sign"] = self._sign(payload)

        logger.info(
            "dana.create_payment",
            payment_no=payment_no,
            amount_fen=amount_fen,
            sandbox=not self.production,
        )

        try:
            resp = await self._request("POST", "/payment/orders", json=payload, timeout=self.CREATE_TIMEOUT)
        except httpx.TimeoutException:
            logger.error("dana.create_payment_timeout", payment_no=payment_no)
            raise DanaTimeoutError("DANA 创建支付请求超时", code="TIMEOUT")

        self._check_response(resp, "创建支付")

        data = resp.json()
        logger.info(
            "dana.create_payment_success",
            payment_no=payment_no,
            dana_txn_id=data.get("danaTxnId", ""),
        )

        return {
            "dana_txn_id": data.get("danaTxnId", ""),
            "payment_url": data.get("paymentUrl", ""),
            "qr_code": data.get("qrCode", ""),
            "status": data.get("status", "pending"),
        }

    async def query_payment(self, dana_txn_id: str) -> dict:
        """查询支付状态

        Args:
            dana_txn_id: DANA 侧交易号

        Returns:
            {
                "dana_txn_id": "...",
                "status": "paid" | "pending" | "failed",
                "amount_fen": 8800,
                "paid_at": "2026-05-03T12:00:00+07:00",
            }
        """
        if not dana_txn_id:
            raise ValueError("dana_txn_id 不能为空")

        timestamp = str(int(time.time() * 1000))
        payload = {
            "apiKey": self.api_key,
            "danaTxnId": dana_txn_id,
            "timestamp": timestamp,
            "sign": self._sign({"apiKey": self.api_key, "danaTxnId": dana_txn_id, "timestamp": timestamp}),
        }

        logger.info("dana.query_payment", dana_txn_id=dana_txn_id)

        try:
            resp = await self._request("POST", "/payment/query", json=payload, timeout=self.QUERY_TIMEOUT)
        except httpx.TimeoutException:
            logger.error("dana.query_payment_timeout", dana_txn_id=dana_txn_id)
            raise DanaTimeoutError("DANA 查询支付请求超时", code="TIMEOUT")

        self._check_response(resp, "查询支付")

        data = resp.json()
        amount_idr = data.get("amount", "0")
        amount_fen = self._idr_to_fen(amount_idr)

        return {
            "dana_txn_id": data.get("danaTxnId", dana_txn_id),
            "status": data.get("status", "unknown"),
            "amount_fen": amount_fen,
            "paid_at": data.get("paidAt"),
            "merchant_order_no": data.get("merchantOrderNo", ""),
        }

    async def refund(
        self,
        dana_txn_id: str,
        refund_no: str,
        amount_fen: int,
        reason: str = "",
    ) -> dict:
        """退款 — 原路退回 DANA Wallet

        Args:
            dana_txn_id:  DANA 侧交易号
            refund_no:    商户退款单号（唯一）
            amount_fen:   退款金额（分）
            reason:       退款原因（可选）

        Returns:
            {
                "dana_refund_id": "...",
                "status": "refunded",
                "amount_fen": 8800,
            }
        """
        if not dana_txn_id:
            raise ValueError("dana_txn_id 不能为空")
        if not refund_no:
            raise ValueError("refund_no 不能为空")
        if not isinstance(amount_fen, int) or amount_fen <= 0:
            raise ValueError(f"amount_fen 必须为正整数(分)，当前值: {amount_fen}")

        amount_idr = self._fen_to_idr(amount_fen)
        timestamp = str(int(time.time() * 1000))

        payload: dict[str, Any] = {
            "apiKey": self.api_key,
            "danaTxnId": dana_txn_id,
            "merchantRefundNo": refund_no,
            "amount": amount_idr,
            "currency": "IDR",
            "timestamp": timestamp,
        }
        if reason:
            payload["reason"] = reason

        payload["sign"] = self._sign(payload)

        logger.info(
            "dana.refund",
            dana_txn_id=dana_txn_id,
            refund_no=refund_no,
            amount_fen=amount_fen,
        )

        try:
            resp = await self._request("POST", "/payment/refund", json=payload, timeout=self.REFUND_TIMEOUT)
        except httpx.TimeoutException:
            logger.error("dana.refund_timeout", dana_txn_id=dana_txn_id, refund_no=refund_no)
            raise DanaTimeoutError("DANA 退款请求超时", code="TIMEOUT")

        self._check_response(resp, "退款")

        data = resp.json()
        refund_amount_idr = data.get("amount", "0")
        refund_amount_fen = self._idr_to_fen(refund_amount_idr)

        logger.info(
            "dana.refund_success",
            dana_txn_id=dana_txn_id,
            dana_refund_id=data.get("danaRefundId", ""),
            amount_fen=refund_amount_fen,
        )

        return {
            "dana_refund_id": data.get("danaRefundId", ""),
            "status": data.get("status", "refunded"),
            "amount_fen": refund_amount_fen,
        }

    def verify_callback(self, raw_body: str, signature: str) -> dict:
        """验证 DANA 异步回调签名

        DANA 使用 HMAC-SHA256 签名（API Secret 作为密钥）。

        Args:
            raw_body:   回调请求体原始字符串（JSON）
            signature:  Header 中的签名字符串

        Returns:
            解析后的回调 payload 字典

        Raises:
            DanaSignatureError: 签名校验失败
        """
        if not raw_body:
            raise DanaSignatureError("回调 body 为空", code="EMPTY_BODY")
        if not signature:
            raise DanaSignatureError("回调 signature 为空", code="EMPTY_SIGN")

        payload = json.loads(raw_body)

        expected_sign = hmac.new(
            self.api_secret.encode("utf-8"),
            raw_body.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

        if not hmac.compare_digest(expected_sign, signature):
            logger.error(
                "dana.callback_signature_mismatch",
                expected=expected_sign[:16],
                received=signature[:16],
            )
            raise DanaSignatureError("DANA 回调签名校验失败", code="SIGN_MISMATCH")

        logger.info("dana.callback_verified", dana_txn_id=payload.get("danaTxnId", ""))
        return payload

    async def aclose(self) -> None:
        """关闭 HTTP 客户端连接池"""
        await self._client.aclose()

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
            logger.warning("dana.invalid_idr_amount", idr=idr)
            return 0

    def _sign(self, params: dict[str, Any]) -> str:
        """HMAC-SHA256 签名

        规则：
          1. 排除 sign 字段自身
          2. 按 key 的 ASCII 码升序排列
          3. 拼接为 key=value&key=value（None 跳过）
          4. API Secret 作为 HMAC 密钥，SHA256 摘要，输出十六进制小写
        """
        filtered = {k: v for k, v in params.items() if k != "sign" and v is not None}
        sorted_keys = sorted(filtered.keys())
        parts = []
        for k in sorted_keys:
            v = filtered[k]
            if isinstance(v, (dict, list)):
                v = json.dumps(v, ensure_ascii=False, separators=(",", ":"))
            parts.append(f"{k}={v}")

        sign_str = "&".join(parts)
        return hmac.new(
            self.api_secret.encode("utf-8"),
            sign_str.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    async def _request(
        self,
        method: str,
        path: str,
        json: dict[str, Any] | None = None,
        timeout: float | None = None,
    ) -> httpx.Response:
        """发送 HTTP 请求"""
        request_timeout = timeout or self.CREATE_TIMEOUT
        headers = {
            "Content-Type": "application/json",
            "X-API-Key": self.api_key,
        }

        try:
            response = await self._client.request(
                method=method,
                url=path,
                json=json,
                headers=headers,
                timeout=request_timeout,
            )
            response.raise_for_status()
        except httpx.TimeoutException:
            raise DanaTimeoutError(f"DANA 请求超时: {path}", code="TIMEOUT")
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            body = exc.response.text[:500]
            logger.error(
                "dana.http_error",
                path=path,
                status_code=status,
                body=body,
            )
            if status in (401, 403):
                raise DanaAuthError("DANA 认证失败，请检查 api_key / api_secret", code="AUTH_FAILED")
            raise DanaError(
                f"DANA HTTP 错误: {status}",
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
            logger.error("dana.invalid_json", operation=operation, body_preview=resp.text[:200])
            raise DanaError(f"DANA 返回非法JSON: {resp.text[:100]}", code="INVALID_RESPONSE") from exc

        code = data.get("code", "0")
        if code != "0" and code != "SUCCESS":
            message = data.get("message", data.get("msg", "未知错误"))
            logger.error(
                "dana.business_error",
                operation=operation,
                code=code,
                message=message,
            )
            if code in ("AUTH_FAILED", "INVALID_API_KEY"):
                raise DanaAuthError(f"DANA {operation}认证失败: {message}", code=code)
            raise DanaError(f"DANA {operation}失败: {message}", code=code)
