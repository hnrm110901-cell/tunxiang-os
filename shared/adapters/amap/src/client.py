"""高德开放平台 HTTP 客户端

封装高德开放平台 API 的认证、签名和基础 HTTP 调用。
"""
from __future__ import annotations

import hashlib
import time
from typing import Any

import httpx
import structlog

logger = structlog.get_logger()

AMAP_API_BASE = "https://openapi.amap.com"


class AmapClient:
    """高德开放平台 API 客户端"""

    def __init__(
        self,
        app_key: str,
        app_secret: str,
        sandbox: bool = False,
        timeout: int = 30,
        retry_times: int = 3,
    ):
        self.app_key = app_key
        self.app_secret = app_secret
        self.base_url = AMAP_API_BASE
        if sandbox:
            self.base_url = self.base_url.replace("openapi", "openapi-sandbox")
        self.timeout = timeout
        self.retry_times = retry_times
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=httpx.Timeout(self.timeout))
        return self._client

    def _sign(self, params: dict) -> str:
        """高德签名：MD5(params sorted + app_secret)"""
        sorted_keys = sorted(params.keys())
        raw = "&".join(f"{k}={params[k]}" for k in sorted_keys)
        raw += self.app_secret
        return hashlib.md5(raw.encode()).hexdigest().upper()

    async def _request(self, method: str, path: str, params: dict) -> dict:
        url = f"{self.base_url}{path}"
        params["app_key"] = self.app_key
        params["timestamp"] = str(int(time.time()))
        params["sign"] = self._sign(params)

        client = await self._get_client()
        for attempt in range(self.retry_times):
            try:
                if method == "GET":
                    resp = await client.get(url, params=params)
                else:
                    resp = await client.post(url, json=params)
                data: dict = resp.json()
                if data.get("code") != "10000":
                    logger.error(
                        "amap_api_error",
                        path=path,
                        code=data.get("code"),
                        msg=data.get("msg"),
                    )
                return data
            except (httpx.TimeoutException, httpx.ConnectError) as exc:
                logger.warning(
                    "amap_api_retry", path=path, attempt=attempt + 1, error=str(exc)
                )
                if attempt == self.retry_times - 1:
                    raise

    async def pull_orders(self, store_id: str, since: str) -> dict:
        return await self._request("GET", "/v1/order/list", {
            "store_id": store_id,
            "start_time": since,
        })

    async def accept_order(self, order_id: str) -> dict:
        return await self._request("POST", "/v1/order/accept", {
            "order_id": order_id,
        })

    async def reject_order(self, order_id: str, reason: str) -> dict:
        return await self._request("POST", "/v1/order/reject", {
            "order_id": order_id,
            "reason": reason,
        })

    async def update_stock(self, sku_id: str, stock: int) -> dict:
        return await self._request("POST", "/v1/stock/update", {
            "sku_id": sku_id,
            "stock": str(stock),
        })

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None
