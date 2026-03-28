"""
抖音生活服务开放平台 HTTP Client
负责认证、签名、请求发送，供 DouyinAdapter 调用

抖音开放平台文档: https://open.douyin.com/
"""
import hashlib
import hmac
import os
import time
from typing import Any, Dict, Optional

import httpx
import structlog

logger = structlog.get_logger()

DOUYIN_PRODUCTION_URL = "https://open.douyin.com"
DOUYIN_SANDBOX_URL = "https://open-sandbox.douyin.com"


class DouyinClient:
    """
    抖音生活服务开放平台底层 HTTP Client

    职责：
      - access_token 管理（client_credential 模式）
      - SHA256 签名
      - HTTP 请求发送（含重试）

    环境变量：
      - DOUYIN_APP_ID
      - DOUYIN_APP_SECRET
    """

    def __init__(
        self,
        app_id: Optional[str] = None,
        app_secret: Optional[str] = None,
        sandbox: bool = False,
        timeout: int = 30,
        retry_times: int = 3,
    ):
        self.app_id = app_id or os.environ.get("DOUYIN_APP_ID", "")
        self.app_secret = app_secret or os.environ.get("DOUYIN_APP_SECRET", "")
        self.sandbox = sandbox
        self.timeout = timeout
        self.retry_times = retry_times

        if not self.app_id or not self.app_secret:
            raise ValueError("DOUYIN_APP_ID 和 DOUYIN_APP_SECRET 不能为空")

        base_url = DOUYIN_SANDBOX_URL if sandbox else DOUYIN_PRODUCTION_URL
        self._http = httpx.AsyncClient(
            base_url=base_url,
            timeout=self.timeout,
            follow_redirects=True,
        )

        self._access_token: Optional[str] = None
        self._token_expires_at: float = 0

        logger.info(
            "douyin_client_init",
            app_id=self.app_id,
            sandbox=self.sandbox,
        )

    # ── 签名 ──────────────────────────────────────────────

    def sign(self, params: Dict[str, Any], timestamp: str) -> str:
        """
        SHA256 签名

        算法：sorted(params) 拼接为 key=value&... + timestamp，
        以 app_secret 为 HMAC key 做 SHA256
        """
        sorted_params = sorted(params.items())
        sign_str = ""
        for k, v in sorted_params:
            sign_str += f"{k}={v}&"
        sign_str += f"timestamp={timestamp}"

        signature = hmac.new(
            self.app_secret.encode("utf-8"),
            sign_str.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        return signature

    # ── Token ─────────────────────────────────────────────

    async def _refresh_token(self) -> None:
        """通过 client_credential 模式获取 access_token"""
        try:
            response = await self._http.post(
                "/oauth/client_token/",
                json={
                    "client_key": self.app_id,
                    "client_secret": self.app_secret,
                    "grant_type": "client_credential",
                },
            )
            response.raise_for_status()
            result = response.json()
        except httpx.HTTPStatusError as e:
            logger.error("douyin_token_http_error", status_code=e.response.status_code)
            raise ConnectionError(
                f"抖音 token 请求失败: {e.response.status_code}"
            ) from e

        data = result.get("data", {})
        if data.get("error_code", 0) != 0:
            err_msg = data.get("description", "未知错误")
            raise PermissionError(f"抖音获取 token 失败: {err_msg}")

        self._access_token = data["access_token"]
        self._token_expires_at = time.time() + data.get("expires_in", 7200)
        logger.info("douyin_token_refreshed", expires_in=data.get("expires_in"))

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
        params: Optional[Dict[str, Any]] = None,
        need_auth: bool = True,
    ) -> Dict[str, Any]:
        """
        发送带签名和 token 的 HTTP 请求（含重试）

        Args:
            method: GET / POST
            endpoint: API 路径
            data: POST body
            params: URL query params
            need_auth: 是否需要 access_token

        Returns:
            API 响应 JSON
        """
        for attempt in range(self.retry_times):
            try:
                headers: Dict[str, str] = {"Content-Type": "application/json"}

                if need_auth:
                    token = await self.get_access_token()
                    headers["access-token"] = token

                timestamp = str(int(time.time()))
                sign_data = {**(data or {}), **(params or {})}
                headers["X-Signature"] = self.sign(sign_data, timestamp)
                headers["X-Timestamp"] = timestamp

                if method.upper() == "GET":
                    resp = await self._http.get(
                        endpoint, params=params, headers=headers,
                    )
                elif method.upper() == "POST":
                    resp = await self._http.post(
                        endpoint, json=data, params=params, headers=headers,
                    )
                else:
                    raise ValueError(f"不支持的 HTTP 方法: {method}")

                resp.raise_for_status()
                result = resp.json()
                _check_biz_error(result)
                return result

            except httpx.HTTPStatusError as e:
                logger.error(
                    "douyin_http_error",
                    endpoint=endpoint,
                    status_code=e.response.status_code,
                    attempt=attempt + 1,
                )
                if attempt == self.retry_times - 1:
                    raise ConnectionError(
                        f"抖音 HTTP 请求失败: {e.response.status_code}"
                    ) from e

            except (httpx.ConnectError, httpx.TimeoutException) as e:
                logger.error(
                    "douyin_request_error",
                    endpoint=endpoint,
                    error=str(e),
                    attempt=attempt + 1,
                )
                if attempt == self.retry_times - 1:
                    raise

        raise RuntimeError("抖音请求失败，已达到最大重试次数")

    # ── 业务方法 ──────────────────────────────────────────

    async def verify_certificate(
        self,
        encrypted_code: str,
        shop_id: str,
    ) -> Dict[str, Any]:
        """
        团购核销

        Args:
            encrypted_code: 加密券码
            shop_id: 抖音门店 ID

        Returns:
            核销结果
        """
        logger.info("douyin_verify_certificate", shop_id=shop_id)
        result = await self.request(
            "POST",
            "/api/goodlife/v1/fulfilment/certificate/verify",
            data={
                "encrypted_code": encrypted_code,
                "shop_id": shop_id,
            },
        )
        return result.get("data", {})

    async def query_order(self, order_id: str) -> Dict[str, Any]:
        """查询订单"""
        logger.info("douyin_query_order", order_id=order_id)
        result = await self.request(
            "GET",
            "/api/goodlife/v1/trade/order/query",
            params={"order_id": order_id},
        )
        return result.get("data", {})

    async def save_product(self, product_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        同步商品到抖音

        Args:
            product_data: 商品数据（符合抖音 product/save 接口规范）

        Returns:
            保存结果
        """
        logger.info("douyin_save_product")
        result = await self.request(
            "POST",
            "/api/goodlife/v1/goods/product/save",
            data=product_data,
        )
        return result.get("data", {})

    # ── 资源释放 ──────────────────────────────────────────

    async def close(self) -> None:
        """关闭 HTTP 连接"""
        await self._http.aclose()
        logger.info("douyin_client_closed")


def _check_biz_error(response: Dict[str, Any]) -> None:
    """检查业务错误码"""
    data = response.get("data", response)
    error_code = data.get("error_code", 0)
    if error_code != 0:
        message = data.get("description", response.get("message", "未知错误"))
        raise ValueError(f"抖音 API 错误 [{error_code}]: {message}")
