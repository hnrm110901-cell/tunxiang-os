"""ShopeeFood Malaysia API client.

API documentation references:
  - ShopeeFood Partner API (马来西亚)
  - Base URL: https://partner.shopeefood.com.my/api/v1
  - Auth: OAuth2 (access_token) + API Key (X-API-Key header)
  - Signature: HMAC-SHA256 with app_secret on sorted query params + request body

All real API calls are stubbed with NotImplementedError.
"""
from __future__ import annotations

import hashlib
import hmac
from typing import Any, Optional

import structlog

logger = structlog.get_logger(__name__)


class ShopeeFoodClient:
    """ShopeeFood API HTTP client (stub — real HTTP calls raise NotImplementedError)."""

    BASE_URL = "https://partner.shopeefood.com.my/api/v1"

    def __init__(
        self,
        api_key: str,
        app_secret: str,
        store_map: dict[str, str],
        access_token: str = "",
        timeout: int = 10,
    ) -> None:
        self.api_key = api_key
        self.app_secret = app_secret
        self.store_map = store_map
        self.access_token = access_token
        self.base_url = self.BASE_URL
        self.timeout = timeout

    # ── OAuth2 令牌管理（stub） ───────────────────────────────────

    async def refresh_access_token(self) -> str:
        """刷新 OAuth2 access_token.

        POST /api/v1/auth/token/refresh
          Body: {"api_key": "...", "app_secret": "..."}
          返回: {"access_token": "...", "expires_in": 86400}
        """
        raise NotImplementedError(
            "ShopeeFood refresh_access_token — "
            "生产环境需调用 /api/v1/auth/token/refresh 获取新 token"
        )

    # ── 签名 ──────────────────────────────────────────────────────

    def _sign_request(
        self, method: str, path: str, params: dict[str, Any], body: str = ""
    ) -> str:
        """ShopeeFood HMAC-SHA256 签名.

        规则:
          1. 按 key 字典序排序 query params
          2. 拼接为 sorted_query_string + body（JSON 字符串）
          3. sign = HMAC-SHA256(app_secret, sorted_query_string + body)
        """
        sorted_keys = sorted(params.keys())
        sorted_str = "&".join(
            f"{k}={params[k]}" for k in sorted_keys if params[k] is not None
        )
        payload_str = sorted_str + body
        signature = hmac.new(
            self.app_secret.encode("utf-8"),
            payload_str.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        logger.debug(
            "shopeefood_sign",
            method=method,
            path=path,
            params_keys=list(params.keys()),
            signature=signature[:16] + "...",
        )
        return signature

    # ── API 调用（stub） ────────────────────────────────────────────

    async def accept_order(self, platform_order_id: str) -> dict[str, Any]:
        """接单.

        POST /api/v1/order/accept
          Body: {"order_id": "..."}
          Header: X-API-Key, Authorization: Bearer <token>
        """
        raise NotImplementedError(
            f"ShopeeFood accept_order({platform_order_id}) — "
            f"生产环境需通过 httpx 调用 {self.base_url}/order/accept"
        )

    async def reject_order(
        self, platform_order_id: str, reason: str
    ) -> dict[str, Any]:
        """拒单.

        POST /api/v1/order/reject
          Body: {"order_id": "...", "reason": "..."}
        """
        raise NotImplementedError(
            f"ShopeeFood reject_order({platform_order_id}) — "
            f"生产环境需通过 httpx 调用 {self.base_url}/order/reject"
        )

    async def mark_ready(self, platform_order_id: str) -> dict[str, Any]:
        """标记出餐完成.

        POST /api/v1/order/ready
          Body: {"order_id": "..."}
        """
        raise NotImplementedError(
            f"ShopeeFood mark_ready({platform_order_id}) — "
            f"生产环境需通过 httpx 调用 {self.base_url}/order/ready"
        )

    async def get_order_detail(self, platform_order_id: str) -> dict[str, Any]:
        """获取订单详情.

        GET /api/v1/order/detail?order_id={order_id}
        """
        raise NotImplementedError(
            f"ShopeeFood get_order_detail({platform_order_id}) — "
            f"生产环境需通过 httpx 调用 {self.base_url}/order/detail"
        )

    async def sync_menu(
        self, store_id: str, dishes: list[dict[str, Any]]
    ) -> dict[str, Any]:
        """同步菜品到 ShopeeFood.

        POST /api/v1/menu/sync
          Body: {"shop_id": "...", "items": [...]}
        """
        raise NotImplementedError(
            f"ShopeeFood sync_menu({store_id}) — "
            f"生产环境需通过 httpx 调用 {self.base_url}/menu/sync"
        )

    async def update_stock(
        self, platform_sku_id: str, available: bool
    ) -> dict[str, Any]:
        """更新菜品上下架状态.

        PUT /api/v1/product/stock
          Body: {"sku_id": "...", "available": true/false}
        """
        raise NotImplementedError(
            f"ShopeeFood update_stock({platform_sku_id}, available={available}) — "
            f"生产环境需通过 httpx 调用 {self.base_url}/product/stock"
        )

    async def close(self) -> None:
        """释放资源（stub）"""
        logger.info("shopeefood_client_closed")
