"""Foodpanda Malaysia API client.

API documentation references:
  - Foodpanda Merchant API (panda API)
  - Base URL: https://api.foodpanda.my (production)
  - Sandbox:  https://api.foodpanda.my/staging
  - Auth: API Key + HMAC-SHA256 signing on sorted query params

All real API calls are stubbed with NotImplementedError.
"""
from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any, Optional

import structlog

from ...delivery_platform_base import DeliveryPlatformAdapter

logger = structlog.get_logger(__name__)


class FoodpandaClient:
    """Foodpanda API HTTP client (stub — real HTTP calls raise NotImplementedError)."""

    BASE_URL_PRODUCTION = "https://api.foodpanda.my"
    BASE_URL_SANDBOX = "https://api.foodpanda.my/staging"

    def __init__(
        self,
        api_key: str,
        api_secret: str,
        store_map: dict[str, str],
        sandbox: bool = False,
        timeout: int = 10,
    ) -> None:
        self.api_key = api_key
        self.api_secret = api_secret
        self.store_map = store_map
        self.base_url = self.BASE_URL_SANDBOX if sandbox else self.BASE_URL_PRODUCTION
        self.timeout = timeout

    # ── 签名 ──────────────────────────────────────────────────────

    def _sign_request(self, method: str, path: str, params: dict[str, Any]) -> str:
        """Foodpanda HMAC-SHA256 签名.

        规则（Foodpanda Merchant API）:
          1. 按 key 字典序排序所有 query / body 参数
          2. 拼接为 key=value&key=value...
          3. sign = HMAC-SHA256(api_secret, sorted_query_string)
        """
        sorted_keys = sorted(params.keys())
        sorted_str = "&".join(
            f"{k}={params[k]}" for k in sorted_keys if params[k] is not None
        )
        signature = hmac.new(
            self.api_secret.encode("utf-8"),
            sorted_str.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        logger.debug(
            "foodpanda_sign",
            method=method,
            path=path,
            params_keys=list(params.keys()),
            signature=signature[:16] + "...",
        )
        return signature

    # ── API 调用（stub） ────────────────────────────────────────────

    async def accept_order(self, platform_order_id: str) -> dict[str, Any]:
        """接单.

        POST /api/v1/orders/{order_id}/accept
        """
        raise NotImplementedError(
            f"Foodpanda accept_order({platform_order_id}) — "
            f"生产环境需通过 httpx 调用 {self.base_url}/api/v1/orders/{platform_order_id}/accept"
        )

    async def reject_order(
        self, platform_order_id: str, reason: str
    ) -> dict[str, Any]:
        """拒单.

        POST /api/v1/orders/{order_id}/reject
        """
        raise NotImplementedError(
            f"Foodpanda reject_order({platform_order_id}) — "
            f"生产环境需通过 httpx 调用 {self.base_url}/api/v1/orders/{platform_order_id}/reject"
        )

    async def mark_ready(self, platform_order_id: str) -> dict[str, Any]:
        """标记出餐完成.

        POST /api/v1/orders/{order_id}/ready
        """
        raise NotImplementedError(
            f"Foodpanda mark_ready({platform_order_id}) — "
            f"生产环境需通过 httpx 调用 {self.base_url}/api/v1/orders/{platform_order_id}/ready"
        )

    async def get_order_detail(self, platform_order_id: str) -> dict[str, Any]:
        """获取订单详情.

        GET /api/v1/orders/{order_id}
        """
        raise NotImplementedError(
            f"Foodpanda get_order_detail({platform_order_id}) — "
            f"生产环境需通过 httpx 调用 {self.base_url}/api/v1/orders/{platform_order_id}"
        )

    async def sync_menu(
        self, store_id: str, dishes: list[dict[str, Any]]
    ) -> dict[str, Any]:
        """同步菜品到 Foodpanda.

        POST /api/v1/menus/sync
        """
        raise NotImplementedError(
            f"Foodpanda sync_menu({store_id}) — "
            f"生产环境需通过 httpx 调用 {self.base_url}/api/v1/menus/sync"
        )

    async def update_stock(
        self, platform_sku_id: str, available: bool
    ) -> dict[str, Any]:
        """更新菜品上下架状态.

        PUT /api/v1/products/{product_id}/availability
        """
        raise NotImplementedError(
            f"Foodpanda update_stock({platform_sku_id}, available={available}) — "
            f"生产环境需通过 httpx 调用 {self.base_url}/api/v1/products/{platform_sku_id}/availability"
        )

    async def close(self) -> None:
        """释放资源（stub）"""
        logger.info("foodpanda_client_closed")
