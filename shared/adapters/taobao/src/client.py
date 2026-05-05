"""淘宝开放平台 / 饿了么闪购 HTTP 客户端

封装淘宝开放平台的认证、签名和基础 HTTP 调用。
淘宝/饿了么闪购使用阿里云 OpenAPI 体系（Top协议）。
"""
from __future__ import annotations

import hashlib
import hmac
import time
from typing import Any

import httpx
import structlog

logger = structlog.get_logger()

TAOBAO_API_BASE = "https://api.taobao.com/router/rest"


class TaobaoClient:
    """淘宝开放平台 API 客户端"""

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
        self.base_url = TAOBAO_API_BASE
        if sandbox:
            self.base_url = "https://api-sandbox.taobao.com/router/rest"
        self.timeout = timeout
        self.retry_times = retry_times
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=httpx.Timeout(self.timeout))
        return self._client

    def _sign(self, params: dict) -> str:
        """淘宝签名：MD5(sorted key=value + app_secret)"""
        sorted_keys = sorted(params.keys())
        raw = "".join(f"{k}{params[k]}" for k in sorted_keys)
        raw += self.app_secret
        return hashlib.md5(raw.encode()).hexdigest().upper()

    async def _request(self, method: str, params: dict) -> dict:
        params["app_key"] = self.app_key
        params["timestamp"] = time.strftime(
            "%Y-%m-%d %H:%M:%S", time.localtime()
        )
        params["format"] = "json"
        params["v"] = "2.0"
        params["sign_method"] = "md5"
        params["sign"] = self._sign(params)

        client = await self._get_client()
        for attempt in range(self.retry_times):
            try:
                resp = await client.post(self.base_url, data=params)
                data: dict = resp.json()
                if "error_response" in data:
                    err = data["error_response"]
                    logger.error(
                        "taobao_api_error",
                        code=err.get("code", ""),
                        msg=err.get("msg", ""),
                    )
                return data
            except (httpx.TimeoutException, httpx.ConnectError) as exc:
                logger.warning(
                    "taobao_api_retry",
                    attempt=attempt + 1,
                    error=str(exc),
                )
                if attempt == self.retry_times - 1:
                    raise

    async def pull_orders(self, store_id: str, since: str) -> dict:
        return await self._request("POST", {
            "method": "alibaba.eleme.flash.order.list",
            "store_id": store_id,
            "start_time": since,
        })

    async def accept_order(self, order_id: str) -> dict:
        return await self._request("POST", {
            "method": "alibaba.eleme.flash.order.accept",
            "order_id": order_id,
        })

    async def reject_order(self, order_id: str, reason: str) -> dict:
        return await self._request("POST", {
            "method": "alibaba.eleme.flash.order.reject",
            "order_id": order_id,
            "reason": reason,
        })

    async def update_stock(self, sku_id: str, stock: int) -> dict:
        return await self._request("POST", {
            "method": "alibaba.eleme.flash.stock.update",
            "sku_id": sku_id,
            "stock": str(stock),
        })

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None
