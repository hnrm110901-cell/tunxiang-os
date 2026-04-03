"""
饿了么开放平台 HTTP Client
负责认证、签名、请求发送，供 ElemeAdapter 调用

饿了么开放平台文档: https://open.shop.ele.me
"""
import hashlib
import hmac
import os
import time
from typing import Any, Dict, Optional

import httpx
import structlog

logger = structlog.get_logger()

# 饿了么 API 基础 URL
ELEME_PRODUCTION_URL = "https://open-api.shop.ele.me/api/v1"
ELEME_SANDBOX_URL = "https://open-api-sandbox.shop.ele.me/api/v1"


class ElemeClient:
    """
    饿了么开放平台底层 HTTP Client

    职责：
      - OAuth2 token 管理（client_credentials 模式）
      - SHA256-HMAC 签名
      - HTTP 请求发送（含重试 + 401 自动刷新）

    环境变量：
      - ELEME_APP_KEY
      - ELEME_APP_SECRET
      - ELEME_STORE_ID（可选，用于默认门店）
    """

    def __init__(
        self,
        app_key: Optional[str] = None,
        app_secret: Optional[str] = None,
        store_id: Optional[str] = None,
        sandbox: bool = False,
        timeout: int = 30,
        retry_times: int = 3,
    ):
        self.app_key = app_key or os.environ.get("ELEME_APP_KEY", "")
        self.app_secret = app_secret or os.environ.get("ELEME_APP_SECRET", "")
        self.store_id = store_id or os.environ.get("ELEME_STORE_ID", "")
        self.sandbox = sandbox
        self.timeout = timeout
        self.retry_times = retry_times

        if not self.app_key or not self.app_secret:
            raise ValueError("ELEME_APP_KEY 和 ELEME_APP_SECRET 不能为空")

        self.base_url = ELEME_SANDBOX_URL if sandbox else ELEME_PRODUCTION_URL

        self._access_token: Optional[str] = None
        self._token_expires_at: float = 0

        self._http = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=self.timeout,
            follow_redirects=True,
        )

        logger.info(
            "eleme_client_init",
            base_url=self.base_url,
            sandbox=self.sandbox,
        )

    # ── 签名 ──────────────────────────────────────────────

    def sign(self, params: Dict[str, Any]) -> str:
        """
        SHA256-HMAC 签名

        算法：
          1. 按 key 字典序排列参数
          2. 拼接 app_secret + key1value1key2value2... + app_secret
          3. HMAC-SHA256 (key = app_secret)，取大写 hex
        """
        sorted_params = sorted(params.items())
        sign_str = self.app_secret
        for k, v in sorted_params:
            sign_str += f"{k}{v}"
        sign_str += self.app_secret

        signature = hmac.new(
            self.app_secret.encode("utf-8"),
            sign_str.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest().upper()
        return signature

    # ── OAuth2 Token ──────────────────────────────────────

    async def _refresh_token(self) -> None:
        """通过 client_credentials 模式获取 access_token"""
        timestamp = str(int(time.time()))
        sign_str = f"{self.app_key}{self.app_secret}{timestamp}"
        token_sign = hashlib.sha256(sign_str.encode("utf-8")).hexdigest().upper()

        payload = {
            "grant_type": "client_credentials",
            "app_key": self.app_key,
            "timestamp": timestamp,
            "sign": token_sign,
        }

        try:
            response = await self._http.post("/token", json=payload)
            response.raise_for_status()
            data = response.json()
        except httpx.HTTPStatusError as e:
            logger.error("eleme_token_http_error", status_code=e.response.status_code)
            raise ConnectionError(f"饿了么 token 请求失败: {e.response.status_code}") from e

        if "access_token" not in data:
            error_msg = data.get("error", data.get("message", "未知错误"))
            raise PermissionError(f"饿了么获取 token 失败: {error_msg}")

        self._access_token = data["access_token"]
        expires_in = int(data.get("expires_in", 86400))
        self._token_expires_at = time.time() + expires_in
        logger.info("eleme_token_refreshed", expires_in=expires_in)

    async def get_access_token(self) -> str:
        """获取有效的 access_token（过期自动刷新）"""
        now = time.time()
        if self._access_token and now < self._token_expires_at - 60:
            return self._access_token
        await self._refresh_token()
        return self._access_token  # type: ignore[return-value]

    # ── 通用请求 ──────────────────────────────────────────

    async def request(
        self,
        method: str,
        endpoint: str,
        data: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        发送带签名和 token 的 HTTP 请求（含重试）

        Args:
            method: GET / POST
            endpoint: 相对路径，如 /order/confirm
            data: 业务参数

        Returns:
            API 响应 JSON
        """
        for attempt in range(self.retry_times):
            try:
                access_token = await self.get_access_token()
                request_data = data or {}

                timestamp = str(int(time.time()))
                auth_params = {
                    "app_key": self.app_key,
                    "access_token": access_token,
                    "timestamp": timestamp,
                    **request_data,
                }
                auth_params["sign"] = self.sign(auth_params)

                headers = {
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {access_token}",
                }

                if method.upper() == "GET":
                    resp = await self._http.get(
                        endpoint, params=auth_params, headers=headers,
                    )
                elif method.upper() == "POST":
                    resp = await self._http.post(
                        endpoint, json=auth_params, headers=headers,
                    )
                else:
                    raise ValueError(f"不支持的 HTTP 方法: {method}")

                resp.raise_for_status()
                result = resp.json()
                _check_biz_error(result)
                return result

            except httpx.HTTPStatusError as e:
                logger.error(
                    "eleme_http_error",
                    endpoint=endpoint,
                    status_code=e.response.status_code,
                    attempt=attempt + 1,
                )
                if e.response.status_code == 401:
                    self._access_token = None
                    self._token_expires_at = 0
                if attempt == self.retry_times - 1:
                    raise ConnectionError(
                        f"饿了么 HTTP 请求失败: {e.response.status_code}"
                    ) from e

            except (httpx.ConnectError, httpx.TimeoutException) as e:
                logger.error(
                    "eleme_request_error",
                    endpoint=endpoint,
                    error=str(e),
                    attempt=attempt + 1,
                )
                if attempt == self.retry_times - 1:
                    raise

        raise RuntimeError("饿了么请求失败，已达到最大重试次数")

    # ── 业务方法 ──────────────────────────────────────────

    async def confirm_order(self, order_id: str) -> Dict[str, Any]:
        """确认接单"""
        logger.info("eleme_confirm_order", order_id=order_id)
        result = await self.request("POST", "/order/confirm", data={"order_id": order_id})
        return result.get("data", {})

    async def cancel_order(
        self,
        order_id: str,
        reason_code: int,
        reason: str,
    ) -> Dict[str, Any]:
        """取消订单"""
        logger.info("eleme_cancel_order", order_id=order_id, reason=reason)
        result = await self.request("POST", "/order/cancel", data={
            "order_id": order_id,
            "reason_code": reason_code,
            "reason": reason,
        })
        return result.get("data", {})

    async def query_order(self, order_id: str) -> Dict[str, Any]:
        """查询订单详情"""
        logger.info("eleme_query_order", order_id=order_id)
        result = await self.request("GET", "/order/detail", data={"order_id": order_id})
        return result.get("data", {})

    async def query_delivery_status(self, order_id: str) -> Dict[str, Any]:
        """查询配送状态"""
        logger.info("eleme_delivery_status", order_id=order_id)
        result = await self.request("GET", "/order/delivery/status", data={"order_id": order_id})
        return result.get("data", {})

    async def update_food(
        self,
        food_id: str,
        food_data: Dict[str, Any],
    ) -> Dict[str, Any]:
        """更新菜品信息"""
        logger.info("eleme_update_food", food_id=food_id)
        result = await self.request("POST", "/food/update", data={
            "food_id": food_id,
            **food_data,
        })
        return result.get("data", {})

    async def query_settlement(
        self,
        start_date: str,
        end_date: str,
    ) -> Dict[str, Any]:
        """
        查询对账信息

        Args:
            start_date: 开始日期 YYYY-MM-DD
            end_date: 结束日期 YYYY-MM-DD

        Returns:
            对账数据（金额单位：分）
        """
        logger.info("eleme_query_settlement", start_date=start_date, end_date=end_date)
        result = await self.request("GET", "/settlement/query", data={
            "start_date": start_date,
            "end_date": end_date,
        })
        return result.get("data", {})

    # ── 资源释放 ──────────────────────────────────────────

    async def close(self) -> None:
        """关闭 HTTP 连接"""
        await self._http.aclose()
        logger.info("eleme_client_closed")


def _check_biz_error(response: Dict[str, Any]) -> None:
    """检查业务错误码"""
    code = response.get("code")
    if code is not None and code != "200" and code != 200 and code != "ok":
        message = response.get("message", response.get("msg", "未知错误"))
        raise ValueError(f"饿了么 API 错误 [{code}]: {message}")
