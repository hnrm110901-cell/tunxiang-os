"""淘宝闪购业务适配器

提供闪购外卖订单管理的业务编排层，委托 TaobaoClient 处理 HTTP 调用。
"""
from __future__ import annotations

from typing import Any, Dict

import structlog

from .client import TaobaoClient

logger = structlog.get_logger()


class TaobaoAdapter:
    """淘宝闪购平台适配器"""

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.client = TaobaoClient(
            app_key=config.get("app_key", ""),
            app_secret=config.get("app_secret", ""),
            sandbox=config.get("sandbox", False),
            timeout=config.get("timeout", 30),
            retry_times=config.get("retry_times", 3),
        )
        logger.info(
            "taobao_adapter_initialized",
            sandbox=config.get("sandbox", False),
        )

    async def pull_orders(self, store_id: str, since: str) -> list[dict]:
        result = await self.client.pull_orders(store_id, since)
        resp = result.get("alibaba_eleme_flash_order_list_response", {})
        return resp.get("orders", []) if resp else []

    async def accept_order(self, order_id: str) -> bool:
        result = await self.client.accept_order(order_id)
        resp = result.get("alibaba_eleme_flash_order_accept_response", {})
        return resp.get("success", False)

    async def reject_order(self, order_id: str, reason: str = "") -> bool:
        result = await self.client.reject_order(order_id, reason)
        resp = result.get("alibaba_eleme_flash_order_reject_response", {})
        return resp.get("success", False)

    async def update_stock(self, sku_id: str, stock: int) -> bool:
        result = await self.client.update_stock(sku_id, stock)
        resp = result.get("alibaba_eleme_flash_stock_update_response", {})
        return resp.get("success", False)

    async def close(self) -> None:
        await self.client.close()
