"""Foodpanda Malaysia DeliveryPlatformAdapter.

Implements the unified DeliveryPlatformAdapter ABC for Foodpanda.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

import structlog

from ...delivery_platform_base import DeliveryPlatformAdapter

from .client import FoodpandaClient

logger = structlog.get_logger(__name__)


class FoodpandaDeliveryAdapter(DeliveryPlatformAdapter):
    """Foodpanda Malaysia delivery platform adapter.

    All real API calls are delegated to FoodpandaClient (stub).
    """

    def __init__(
        self,
        api_key: str = "",
        api_secret: str = "",
        store_map: Optional[dict[str, str]] = None,
        sandbox: bool = False,
        timeout: int = 10,
        **kwargs: Any,
    ) -> None:
        self.api_key = api_key
        self.api_secret = api_secret
        self.store_map = store_map or {}
        self.sandbox = sandbox
        self.timeout = timeout
        self._client: Optional[FoodpandaClient] = None

    def _get_client(self) -> FoodpandaClient:
        if self._client is None:
            self._client = FoodpandaClient(
                api_key=self.api_key,
                api_secret=self.api_secret,
                store_map=self.store_map,
                sandbox=self.sandbox,
                timeout=self.timeout,
            )
        return self._client

    async def pull_orders(self, store_id: str, since: datetime) -> list[dict]:
        """拉取指定时间之后的新订单。

        GET /api/v1/orders?updated_at={since}&store_id={store_id}
        """
        logger.info(
            "foodpanda_pull_orders",
            store_id=store_id,
            since=since.isoformat(),
            note="生产环境需调用 Foodpanda 订单列表 API",
        )
        return []

    async def accept_order(self, order_id: str) -> bool:
        """接受订单"""
        log = logger.bind(platform="foodpanda", order_id=order_id)
        try:
            result = await self._get_client().accept_order(order_id)
            log.info("foodpanda_accept_order_ok", result=result)
            return True
        except NotImplementedError:
            log.info("foodpanda_accept_order_stub", note="骨架实现返回 True")
            return True

    async def reject_order(self, order_id: str, reason: str) -> bool:
        """拒绝订单"""
        log = logger.bind(platform="foodpanda", order_id=order_id, reason=reason)
        try:
            result = await self._get_client().reject_order(order_id, reason)
            log.info("foodpanda_reject_order_ok", result=result)
            return True
        except NotImplementedError:
            log.info("foodpanda_reject_order_stub", note="骨架实现返回 True")
            return True

    async def mark_ready(self, order_id: str) -> bool:
        """标记出餐完成"""
        log = logger.bind(platform="foodpanda", order_id=order_id)
        try:
            result = await self._get_client().mark_ready(order_id)
            log.info("foodpanda_mark_ready_ok", result=result)
            return True
        except NotImplementedError:
            log.info("foodpanda_mark_ready_stub", note="骨架实现返回 True")
            return True

    async def sync_menu(self, store_id: str, dishes: list[dict]) -> dict:
        """同步菜品到 Foodpanda"""
        log = logger.bind(platform="foodpanda", store_id=store_id)
        try:
            result = await self._get_client().sync_menu(store_id, dishes)
            log.info("foodpanda_sync_menu_ok", result=result)
            return {"synced": len(dishes), "failed": 0, "errors": []}
        except NotImplementedError:
            log.info("foodpanda_sync_menu_stub", note="骨架实现返回模拟成功")
            return {"synced": len(dishes), "failed": 0, "errors": []}

    async def update_stock(self, store_id: str, dish_id: str, available: bool) -> bool:
        """更新菜品上下架状态"""
        log = logger.bind(platform="foodpanda", dish_id=dish_id, available=available)
        try:
            result = await self._get_client().update_stock(dish_id, available)
            log.info("foodpanda_update_stock_ok", result=result)
            return True
        except NotImplementedError:
            log.info("foodpanda_update_stock_stub", note="骨架实现返回 True")
            return True

    async def get_order_detail(self, order_id: str) -> dict:
        """获取订单详情"""
        log = logger.bind(platform="foodpanda", order_id=order_id)
        try:
            result = await self._get_client().get_order_detail(order_id)
            log.info("foodpanda_get_order_detail_ok", result=result)
            return result
        except NotImplementedError:
            log.info("foodpanda_get_order_detail_stub", note="骨架实现返回空字典")
            return {}

    async def close(self) -> None:
        """释放资源"""
        if self._client is not None:
            await self._client.close()
