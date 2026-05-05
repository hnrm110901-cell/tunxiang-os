"""InventorySyncService — push stock updates to all delivery platforms.

Key use case: dish sold out → sync stock=0 to all platforms immediately.
"""
from __future__ import annotations

import os
from typing import Any

import structlog

logger = structlog.get_logger()

PLATFORM_ORDER = ("meituan", "eleme", "douyin", "amap", "taobao")


class InventorySyncService:
    """Sync stock levels from Tunxiang OS to delivery platforms."""

    async def sync_stock_to_platform(
        self, sku_id: str, stock: int, platform: str, store_id: str = ""
    ) -> bool:
        """Push stock for a single SKU to one platform.

        Returns True on success, False if the platform skipped or failed.
        """
        from shared.adapters.delivery_factory import get_delivery_adapter

        try:
            adapter = get_delivery_adapter(
                platform,
                app_key=os.environ.get(f"{platform.upper()}_APP_KEY", ""),
                app_secret=os.environ.get(f"{platform.upper()}_APP_SECRET", ""),
            )
            result = await adapter.update_stock(
                store_id=store_id, dish_id=sku_id, available=stock
            )
            await adapter.close()
            success = bool(result)
            logger.info(
                "inventory_sync.platform_result",
                platform=platform, sku_id=sku_id,
                stock=stock, success=success,
            )
            return success
        except ValueError:
            logger.debug("inventory_sync.platform_not_registered", platform=platform)
            return False
        except (OSError, ConnectionError, TimeoutError) as exc:
            logger.error("inventory_sync.platform_error", platform=platform, error=str(exc), exc_info=True)
            return False

    async def sync_stock_to_all_platforms(
        self, sku_id: str, stock: int, store_id: str = ""
    ) -> dict[str, bool]:
        """Push stock update to all registered delivery platforms.

        Returns a dict of platform → success/failure per platform.
        Failures on individual platforms do not block other platforms.
        """
        results: dict[str, bool] = {}
        for platform in PLATFORM_ORDER:
            try:
                results[platform] = await self.sync_stock_to_platform(
                    sku_id, stock, platform, store_id
                )
            except (OSError, ConnectionError, TimeoutError) as exc:
                logger.error(
                    "inventory_sync.unexpected_error",
                    platform=platform, sku_id=sku_id,
                )
                results[platform] = False

        succeeded = sum(1 for v in results.values() if v)
        attempted = len(results)
        logger.info(
            "inventory_sync.all_platforms_done",
            sku_id=sku_id, stock=stock,
            succeeded=f"{succeeded}/{attempted}",
        )
        return results

    async def handle_inventory_consumed(self, event: dict[str, Any]) -> None:
        """Handler for INVENTORY.CONSUMED events.

        Expected event shape:
            {"sku_id": "external-platform-sku", "remaining": 0, ...}

        Fire-and-forget via asyncio.create_task() or BackgroundTasks.
        """
        sku_id: str = event.get("sku_id", "")
        remaining: int = event.get("remaining", 0)
        store_id: str = event.get("store_id", "")
        if not sku_id:
            logger.warning("inventory_sync.no_sku_id", event=event)
            return
        await self.sync_stock_to_all_platforms(sku_id, remaining, store_id)
