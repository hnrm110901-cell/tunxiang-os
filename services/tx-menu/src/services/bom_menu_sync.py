"""BOM-to-Channel Menu Sync — auto pause/resume dishes across platforms.

When BOM inventory runs out: pause dish on all delivery platforms.
When inventory recovers: resume dish on previously-paused platforms.
"""
from __future__ import annotations

import asyncio
import os
from typing import Any

import structlog

logger = structlog.get_logger()

PLATFORMS = ("meituan", "eleme", "douyin", "amap", "taobao")


class BomMenuSyncService:
    """Sync dish availability based on BOM inventory levels."""

    async def pause_dish_on_platform(
        self, dish_id: str, platform: str, store_id: str = ""
    ) -> bool:
        """Set a dish as unavailable on one platform."""
        from shared.adapters.delivery_factory import get_delivery_adapter

        try:
            adapter = get_delivery_adapter(
                platform,
                app_key=os.environ.get(f"{platform.upper()}_APP_KEY", ""),
                app_secret=os.environ.get(f"{platform.upper()}_APP_SECRET", ""),
            )
            result = await adapter.update_stock(
                sku_id=dish_id, stock=0
            )
            await adapter.close()
            logger.info(
                "bom_menu.paused", platform=platform, dish_id=dish_id
            )
            return bool(result)
        except ValueError:
            return False
        except (OSError, ConnectionError, TimeoutError) as exc:
            logger.error("bom_menu.pause_failed", platform=platform, dish_id=dish_id, error=str(exc), exc_info=True)
            return False

    async def resume_dish_on_platform(
        self, dish_id: str, platform: str, store_id: str = ""
    ) -> bool:
        """Set a dish back to available on one platform."""
        from shared.adapters.delivery_factory import get_delivery_adapter

        try:
            adapter = get_delivery_adapter(
                platform,
                app_key=os.environ.get(f"{platform.upper()}_APP_KEY", ""),
                app_secret=os.environ.get(f"{platform.upper()}_APP_SECRET", ""),
            )
            result = await adapter.update_stock(
                sku_id=dish_id, stock=1
            )
            await adapter.close()
            logger.info(
                "bom_menu.resumed", platform=platform, dish_id=dish_id
            )
            return bool(result)
        except ValueError:
            return False
        except Exception:
            logger.exception("bom_menu.resume_failed", platform=platform, dish_id=dish_id)
            return False

    async def pause_dish_all_platforms(
        self, dish_id: str, store_id: str = ""
    ) -> dict[str, bool]:
        """Pause a dish on ALL delivery platforms."""
        results: dict[str, bool] = {}
        for platform in PLATFORMS:
            try:
                results[platform] = await self.pause_dish_on_platform(
                    dish_id, platform, store_id
                )
            except (OSError, ConnectionError, TimeoutError) as exc:
                logger.error("bom_menu.pause_unexpected", platform=platform, error=str(exc), exc_info=True)
                results[platform] = False
        return results

    async def resume_dish_all_platforms(
        self, dish_id: str, store_id: str = ""
    ) -> dict[str, bool]:
        """Resume a dish on ALL delivery platforms."""
        results: dict[str, bool] = {}
        for platform in PLATFORMS:
            try:
                results[platform] = await self.resume_dish_on_platform(
                    dish_id, platform, store_id
                )
            except Exception:
                logger.exception("bom_menu.resume_unexpected", platform=platform)
                results[platform] = False
        return results

    async def handle_bom_depleted(self, event: dict[str, Any]) -> dict[str, bool]:
        """Handle BOM depleted event: pause dish on all platforms.

        Expected event:
            {"dish_id": "internal-dish-uuid", "store_id": "...", "remaining": 0}
        """
        dish_id: str = event.get("dish_id", "")
        store_id: str = event.get("store_id", "")
        if not dish_id:
            return {}
        return await self.pause_dish_all_platforms(dish_id, store_id)

    async def handle_bom_restored(self, event: dict[str, Any]) -> dict[str, bool]:
        """Handle BOM restored event: resume dish on all platforms.

        Expected event:
            {"dish_id": "internal-dish-uuid", "store_id": "...", "remaining": 10}
        """
        dish_id: str = event.get("dish_id", "")
        store_id: str = event.get("store_id", "")
        if not dish_id:
            return {}
        return await self.resume_dish_all_platforms(dish_id, store_id)
