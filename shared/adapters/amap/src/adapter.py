"""高德开放平台业务适配器

提供团购订单管理的业务编排层，委托 AmapClient 处理 HTTP 调用。
"""
from __future__ import annotations

from typing import Any, Dict

import structlog

from .client import AmapClient

logger = structlog.get_logger()


class AmapAdapter:
    """高德开放平台适配器"""

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.client = AmapClient(
            app_key=config.get("app_key", ""),
            app_secret=config.get("app_secret", ""),
            sandbox=config.get("sandbox", False),
            timeout=config.get("timeout", 30),
            retry_times=config.get("retry_times", 3),
        )
        logger.info("amap_adapter_initialized", sandbox=config.get("sandbox", False))

    async def pull_orders(self, store_id: str, since: str) -> list[dict]:
        result = await self.client.pull_orders(store_id, since)
        return result.get("data", {}).get("orders", []) if result.get("code") == "10000" else []

    async def accept_order(self, order_id: str) -> bool:
        result = await self.client.accept_order(order_id)
        return result.get("code") == "10000"

    async def reject_order(self, order_id: str, reason: str = "") -> bool:
        result = await self.client.reject_order(order_id, reason)
        return result.get("code") == "10000"

    async def update_stock(self, sku_id: str, stock: int) -> bool:
        result = await self.client.update_stock(sku_id, stock)
        return result.get("code") == "10000"

    async def close(self) -> None:
        await self.client.close()
