"""
GrabFood DeliveryPlatformAdapter implementation.

Wraps GrabFoodClient to implement the unified DeliveryPlatformAdapter
interface for the Malaysia market.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any, Optional

import structlog

from shared.adapters.delivery_platform_base import DeliveryPlatformAdapter
from shared.adapters.grabfood.src.client import (
    GrabFoodClient,
    GrabFoodError,
    GrabFoodTimeoutError,
)

logger = structlog.get_logger()

# GrabFood order state mapping
# Reference: GrabFood Partner API docs — OrderState enum
GRABFOOD_STATUS_MAP: dict[str, str] = {
    "OrderState.Pending": "pending",
    "OrderState.Accepted": "confirmed",
    "OrderState.Preparing": "preparing",
    "OrderState.ReadyForPickup": "preparing",
    "OrderState.PickedUp": "delivering",
    "OrderState.Delivered": "completed",
    "OrderState.Completed": "completed",
    "OrderState.Cancelled": "cancelled",
    "OrderState.Rejected": "cancelled",
    "OrderState.Refunded": "refunded",
}


def _load_store_mapping() -> dict[str, str]:
    """Load GrabFood store mapping from environment variable."""
    raw = os.environ.get("GRABFOOD_DELIVERY_STORE_MAP", "{}")
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        logger.warning("grabfood_store_map_parse_failed", raw=raw)
        return {}


class GrabFoodDeliveryAdapter(DeliveryPlatformAdapter):
    """GrabFood platform adapter for the Malaysia market.

    Implements DeliveryPlatformAdapter by wrapping GrabFoodClient.
    Current implementation: mock mode returns simulated data.
    Real API calls can be enabled by removing _mock prefix.

    Configuration (environment variables):
      GRABFOOD_CLIENT_ID          — GrabFood API client ID
      GRABFOOD_CLIENT_SECRET      — GrabFood API client secret
      GRABFOOD_MERCHANT_ID        — GrabFood merchant ID
      GRABFOOD_DELIVERY_STORE_MAP — JSON: {"txos_store_001": "gf_merchant_888"}
      GRABFOOD_SANDBOX            — set to "true" for sandbox (default: production)
    """

    def __init__(
        self,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
        merchant_id: Optional[str] = None,
        store_map: Optional[dict[str, str]] = None,
        sandbox: Optional[bool] = None,
        timeout: int = 30,
    ):
        self.client_id = client_id or os.environ.get("GRABFOOD_CLIENT_ID", "")
        self.client_secret = client_secret or os.environ.get(
            "GRABFOOD_CLIENT_SECRET", ""
        )
        self.merchant_id = merchant_id or os.environ.get(
            "GRABFOOD_MERCHANT_ID", ""
        )
        self.store_map = store_map or _load_store_mapping()
        sandbox_env = os.environ.get("GRABFOOD_SANDBOX", "false").lower()
        self.sandbox = sandbox if sandbox is not None else (sandbox_env == "true")
        self.timeout = timeout

        self._client: Optional[GrabFoodClient] = None
        self._mock_mode = not (
            self.client_id and self.client_secret and self.merchant_id
        )

        logger.info(
            "grabfood_delivery_adapter_init",
            store_count=len(self.store_map),
            mock_mode=self._mock_mode,
            sandbox=self.sandbox,
        )

    # ── Client lazy init ───────────────────────────────────────────────────

    def _get_client(self) -> GrabFoodClient:
        """Lazy-init GrabFoodClient (only created when mock_mode=False)."""
        if self._client is None and not self._mock_mode:
            self._client = GrabFoodClient(
                client_id=self.client_id,
                client_secret=self.client_secret,
                merchant_id=self.merchant_id,
                production=not self.sandbox,
            )
        return self._client  # type: ignore[return-value]

    # ── Internal helpers ───────────────────────────────────────────────────

    def _get_merchant_id_for_store(self, store_id: str) -> str:
        """Map Tunxiang store_id to GrabFood merchant_id."""
        merchant_id = self.store_map.get(store_id, "")
        if not merchant_id:
            logger.warning(
                "grabfood_store_not_mapped",
                store_id=store_id,
            )
        return merchant_id or self.merchant_id

    def _map_order(self, raw: dict[str, Any]) -> dict:
        """Map GrabFood raw order to Tunxiang unified order format.

        GrabFood webhook / order detail payload fields:
          orderID, merchantID, orderState, itemInfo[],
          paymentAmount, currencyCode, dineType,
          createTime, estimatedPickupTime,
          recipientInfo {name, phone, address}
        """
        items: list[dict[str, Any]] = []
        for item in raw.get("itemInfo", []):
            price_myr = item.get("unitPrice", 0)
            price_fen = int(round(float(price_myr) * 100)) if price_myr else 0
            qty = int(item.get("quantity", 1))
            items.append(
                {
                    "name": item.get("itemName", ""),
                    "quantity": qty,
                    "price_fen": price_fen,
                    "sku_id": item.get("itemCode", ""),
                    "notes": "",
                    "internal_dish_id": "",
                }
            )

        status_raw = raw.get("orderState", "OrderState.Pending")
        canonical_status = GRABFOOD_STATUS_MAP.get(status_raw, "pending")

        recipient = raw.get("recipientInfo", {})

        # Payment amount from GrabFood is in MYR (float)
        total_myr = raw.get("paymentAmount", 0)
        total_fen = int(round(float(total_myr) * 100)) if total_myr else 0

        return {
            "platform": "grabfood",
            "platform_order_id": str(raw.get("orderID", "")),
            "day_seq": "",
            "status": canonical_status,
            "items": items,
            "total_fen": total_fen,
            "customer_phone": recipient.get("phone", ""),
            "delivery_address": recipient.get("address", ""),
            "expected_time": raw.get("estimatedPickupTime", ""),
            "notes": "",
        }

    def _map_dish_to_grabfood(self, dish: dict) -> dict:
        """Map Tunxiang unified dish format to GrabFood menu item format.

        GrabFood menu sync expects:
          {
            "itemCode": "SKU001",
            "itemName": "Nasi Lemak",
            "price": 8.50,
            "currency": "MYR",
            "isAvailable": True,
            "category": "Rice",
            "description": "...",
          }
        """
        price_myr = dish.get("price", 0)
        return {
            "itemCode": dish.get("id", dish.get("external_id", "")),
            "itemName": dish.get("name", ""),
            "price": float(price_myr) / 100 if isinstance(price_myr, int) else float(price_myr),
            "currency": "MYR",
            "isAvailable": dish.get("is_available", True),
            "category": dish.get("category_name", "Default"),
            "description": dish.get("specification", ""),
        }

    # ── Mock helpers ───────────────────────────────────────────────────────

    def _mock_orders(self, merchant_id: str, since: datetime) -> list[dict]:
        """Generate mock GrabFood order data for testing."""
        import time as time_module

        now_ts = int(time_module.time())
        return [
            {
                "orderID": f"GF{now_ts}001",
                "merchantID": merchant_id,
                "orderState": "OrderState.Pending",
                "itemInfo": [
                    {
                        "itemCode": "SKU001",
                        "itemName": "Nasi Lemak",
                        "quantity": 2,
                        "unitPrice": 8.50,
                        "currency": "MYR",
                    },
                    {
                        "itemCode": "SKU002",
                        "itemName": "Iced Teh Tarik",
                        "quantity": 1,
                        "unitPrice": 3.50,
                        "currency": "MYR",
                    },
                ],
                "paymentAmount": 20.50,
                "currencyCode": "MYR",
                "dineType": "Delivery",
                "createTime": datetime.now(timezone.utc).isoformat(),
                "estimatedPickupTime": datetime.fromtimestamp(
                    now_ts + 1800, tz=timezone.utc
                ).isoformat(),
                "recipientInfo": {
                    "name": "Ali Bin Ahmad",
                    "phone": "60123456789",
                    "address": "12, Jalan SS2/72, Petaling Jaya",
                },
            }
        ]

    # ── DeliveryPlatformAdapter interface ──────────────────────────────────

    async def pull_orders(self, store_id: str, since: datetime) -> list[dict]:
        """Pull new GrabFood orders since given timestamp.

        In production, this polls GET /grabfood/v1/order/active or
        relies on webhook push. Mock mode returns simulated orders.
        """
        merchant_id = self._get_merchant_id_for_store(store_id)
        logger.info(
            "grabfood_pull_orders",
            store_id=store_id,
            merchant_id=merchant_id,
            since=since.isoformat(),
        )

        if self._mock_mode:
            raw_orders = self._mock_orders(merchant_id, since)
            return [self._map_order(raw) for raw in raw_orders]

        # Production: the client is expected to call get_order_detail for active orders.
        # Webhook push is the primary mechanism for GrabFood; pull is a fallback.
        logger.info(
            "grabfood_pull_orders_production",
            note="Primary order ingestion is via webhook; pull not fully implemented",
        )
        return []

    async def accept_order(self, order_id: str) -> bool:
        """Accept a GrabFood order.

        POST /grabfood/v1/partner/order
        """
        logger.info("grabfood_accept_order", order_id=order_id)

        if self._mock_mode:
            return True

        try:
            client = self._get_client()
            await client.accept_order(order_id)
            return True
        except (GrabFoodError, GrabFoodTimeoutError) as exc:
            logger.error(
                "grabfood_accept_order_failed",
                order_id=order_id,
                error=str(exc),
            )
            return False

    async def reject_order(self, order_id: str, reason: str) -> bool:
        """Reject / cancel a GrabFood order.

        POST /grabfood/v1/order/reject
        """
        logger.info("grabfood_reject_order", order_id=order_id, reason=reason)

        if not reason:
            logger.warning("grabfood_reject_order_no_reason", order_id=order_id)
            return False

        if self._mock_mode:
            return True

        try:
            client = self._get_client()
            await client.reject_order(order_id, reason)
            return True
        except (GrabFoodError, GrabFoodTimeoutError) as exc:
            logger.error(
                "grabfood_reject_order_failed",
                order_id=order_id,
                error=str(exc),
            )
            return False

    async def mark_ready(self, order_id: str) -> bool:
        """Mark a GrabFood order as ready for rider pickup.

        POST /grabfood/v1/order/ready
        """
        logger.info("grabfood_mark_ready", order_id=order_id)

        if self._mock_mode:
            return True

        try:
            client = self._get_client()
            await client.mark_ready(order_id)
            return True
        except (GrabFoodError, GrabFoodTimeoutError) as exc:
            logger.error(
                "grabfood_mark_ready_failed",
                order_id=order_id,
                error=str(exc),
            )
            return False

    async def sync_menu(self, store_id: str, dishes: list[dict]) -> dict:
        """Sync full menu to GrabFood.

        POST /grabfood/v1/menu/sync
        """
        merchant_id = self._get_merchant_id_for_store(store_id)
        logger.info(
            "grabfood_sync_menu",
            store_id=store_id,
            merchant_id=merchant_id,
            dish_count=len(dishes),
        )

        synced = 0
        failed = 0
        errors: list[dict] = []

        if self._mock_mode:
            # In mock mode, just record the mapping
            for dish in dishes:
                try:
                    gf_item = self._map_dish_to_grabfood(dish)
                    logger.debug("grabfood_sync_dish_mock", item=gf_item)
                    synced += 1
                except (KeyError, ValueError, TypeError) as exc:
                    failed += 1
                    errors.append(
                        {
                            "dish_id": dish.get("id", "unknown"),
                            "error": str(exc),
                        }
                    )
            return {"synced": synced, "failed": failed, "errors": errors}

        try:
            client = self._get_client()
            gf_dishes = [self._map_dish_to_grabfood(d) for d in dishes]
            result = await client.sync_menu(gf_dishes)
            if result.get("code") == "OK":
                synced = len(dishes)
            else:
                failed = len(dishes)
                errors.append(
                    {
                        "error": result.get("message", "sync failed"),
                        "code": result.get("code", ""),
                    }
                )
        except (GrabFoodError, GrabFoodTimeoutError) as exc:
            failed = len(dishes)
            errors.append({"error": str(exc)})
            logger.error("grabfood_sync_menu_failed", error=str(exc))

        return {"synced": synced, "failed": failed, "errors": errors}

    async def update_stock(self, store_id: str, dish_id: str, available: bool) -> bool:
        """Update a single dish's availability on GrabFood.

        GrabFood does not have a per-item stock toggle endpoint;
        the approach is to full-sync the menu. This method is a
        convenience wrapper that logs the intent.
        """
        merchant_id = self._get_merchant_id_for_store(store_id)
        action = "available" if available else "sold_out"
        logger.info(
            "grabfood_update_stock",
            merchant_id=merchant_id,
            dish_id=dish_id,
            action=action,
            note="GrabFood requires full menu sync for stock changes",
        )
        # In production, use sync_menu with the updated dish.
        return True

    async def get_order_detail(self, order_id: str) -> dict:
        """Get GrabFood order detail.

        GET /grabfood/v1/order/{order_id}
        """
        logger.info("grabfood_get_order_detail", order_id=order_id)

        if self._mock_mode:
            import time as time_module

            now_ts = int(time_module.time())
            mock_raw = {
                "orderID": order_id,
                "merchantID": self.merchant_id,
                "orderState": "OrderState.Accepted",
                "itemInfo": [
                    {
                        "itemCode": "SKU001",
                        "itemName": "Nasi Lemak",
                        "quantity": 2,
                        "unitPrice": 8.50,
                        "currency": "MYR",
                    },
                ],
                "paymentAmount": 17.00,
                "currencyCode": "MYR",
                "dineType": "Delivery",
                "createTime": datetime.now(timezone.utc).isoformat(),
                "estimatedPickupTime": datetime.fromtimestamp(
                    now_ts + 1800, tz=timezone.utc
                ).isoformat(),
                "recipientInfo": {
                    "name": "Ali Bin Ahmad",
                    "phone": "60123456789",
                    "address": "12, Jalan SS2/72, Petaling Jaya",
                },
            }
            return self._map_order(mock_raw)

        try:
            client = self._get_client()
            raw = await client.get_order_detail(order_id)
            return self._map_order(raw)
        except (GrabFoodError, GrabFoodTimeoutError) as exc:
            logger.error(
                "grabfood_get_order_detail_failed",
                order_id=order_id,
                error=str(exc),
            )
            return {}

    async def close(self) -> None:
        """Release underlying HTTP client resources."""
        if self._client is not None:
            await self._client.aclose()
        logger.info("grabfood_delivery_adapter_closed")
