"""GrabFood delivery platform adapter for tx-trade service layer.

Handles GrabFood-specific webhook parsing, signature verification,
and platform API calls for the Malaysian market (Phase 2 Sprint 2.1).

GrabFood webhook payload fields:
  orderID, merchantID, orderState, itemInfo[] (itemCode, itemName, quantity,
  unitPrice, currency), paymentAmount, currencyCode, dineType, createTime,
  estimatedPickupTime, recipientInfo (name, phone, address)

Signature algorithm: HMAC-SHA256 with app_secret as the shared key.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Optional

import structlog

from .base_adapter import BaseDeliveryAdapter, DeliveryOrder, DeliveryOrderItem

logger = structlog.get_logger(__name__)


class GrabFoodAdapter(BaseDeliveryAdapter):
    """GrabFood order adapter for the tx-trade delivery panel.

    Handles webhook signature verification (HMAC-SHA256), raw payload
    parsing into the unified DeliveryOrder format, and platform API
    calls for order acceptance/rejection.

    GrabFood amounts come in MYR (float); all internal amounts are fen (int).
    """

    platform = "grabfood"

    # ── GrabFood order state → canonical delivery status ──────────────────

    STATUS_MAP: dict[str, str] = {
        "OrderState.Pending": "pending",
        "OrderState.Accepted": "accepted",
        "OrderState.Preparing": "preparing",
        "OrderState.ReadyForPickup": "ready",
        "OrderState.PickedUp": "delivering",
        "OrderState.Delivered": "delivered",
        "OrderState.Completed": "completed",
        "OrderState.Cancelled": "cancelled",
        "OrderState.Rejected": "cancelled",
        "OrderState.Refunded": "refunded",
    }

    def parse_order(self, raw: dict) -> DeliveryOrder:
        """Parse GrabFood webhook payload into unified DeliveryOrder.

        GrabFood field mapping:
          orderID          → platform_order_id
          itemInfo[]       → items (itemCode, itemName, quantity, unitPrice)
          paymentAmount    → total_fen (MYR → fen conversion)
          dineType         → determines order type
          createTime       → placed_at
          estimatedPickupTime → estimated_delivery_at
          recipientInfo    → customer_name, customer_phone, delivery_address

        Returns:
            DeliveryOrder in unified format with amounts in fen.

        Raises:
            ValueError: on missing required fields or parse error.
        """
        log = logger.bind(
            platform=self.platform,
            order_id=raw.get("orderID", ""),
        )

        try:
            order_id = str(raw.get("orderID", "")).strip()
            if not order_id:
                raise ValueError("GrabFood orderID is missing or empty")

            # ── Parse items ───────────────────────────────────────────────
            raw_items: list[dict] = raw.get("itemInfo", [])
            items: list[DeliveryOrderItem] = []
            total_calculated_fen = 0
            for ri in raw_items:
                unit_price_myr = ri.get("unitPrice", 0)
                unit_price_fen = int(round(float(unit_price_myr) * 100))
                qty = int(ri.get("quantity", 1))
                item_total = unit_price_fen * qty
                total_calculated_fen += item_total
                items.append(
                    DeliveryOrderItem(
                        platform_item_id=str(ri.get("itemCode", "")),
                        name=ri.get("itemName", ""),
                        qty=qty,
                        unit_price_fen=unit_price_fen,
                        spec=None,
                        total_fen=item_total,
                    )
                )

            # ── Amounts: GrabFood sends MYR (float) → fen ────────────────
            payment_amount_myr = raw.get("paymentAmount", 0)
            total_fen = int(round(float(payment_amount_myr) * 100))

            # ── Timestamps ────────────────────────────────────────────────
            create_time = raw.get("createTime")
            estimated_delivery_at: Optional[datetime] = None
            if isinstance(create_time, str):
                try:
                    placed_at = datetime.fromisoformat(
                        create_time.replace("Z", "+00:00")
                    )
                except ValueError:
                    log.warning(
                        "grabfood.invalid_createTime",
                        create_time=create_time,
                    )
                    placed_at = datetime.now(timezone.utc)
            else:
                placed_at = datetime.now(timezone.utc)

            pickup_time = raw.get("estimatedPickupTime")
            if isinstance(pickup_time, str):
                try:
                    estimated_delivery_at = datetime.fromisoformat(
                        pickup_time.replace("Z", "+00:00")
                    )
                except ValueError:
                    pass

            # ── Customer info ─────────────────────────────────────────────
            recipient: dict = raw.get("recipientInfo", {})

            # ── Dine type ─────────────────────────────────────────────────
            dine_type = str(raw.get("dineType", "Delivery"))
            # GrabFood dineType: "Delivery" or "PickUp"
            order_type = "delivery" if dine_type.lower() == "delivery" else "pickup"

            order = DeliveryOrder(
                platform=self.platform,
                platform_order_id=order_id,
                status=self.STATUS_MAP.get(
                    raw.get("orderState", ""), "pending"
                ),
                items=items,
                total_fen=total_fen or total_calculated_fen,
                delivery_fee_fen=0,  # GrabFood does not separate delivery fee here
                customer_name=recipient.get("name"),
                customer_phone=recipient.get("phone"),
                delivery_address=recipient.get("address"),
                estimated_delivery_at=estimated_delivery_at,
                raw_payload=raw,
            )

            # ── Enrich raw_payload with order_type for downstream ─────────
            order.raw_payload["_order_type"] = order_type

            log.info(
                "grabfood_parse_order_ok",
                items_count=len(items),
                total_fen=order.total_fen,
            )
            return order

        except (KeyError, TypeError, ValueError) as exc:
            log.error(
                "grabfood_parse_order_failed",
                error=str(exc),
                exc_info=True,
            )
            raise ValueError(f"GrabFood order parse failed: {exc}") from exc

    def verify_signature(self, payload: bytes, signature: str) -> bool:
        """Verify GrabFood webhook HMAC-SHA256 signature.

        GrabFood signs webhook payloads with HMAC-SHA256 using the
        app_secret (client_secret) as the shared key. The signature
        is sent in the X-GrabFood-Signature header.

        Args:
            payload:   Raw webhook request body (bytes).
            signature: Signature from X-GrabFood-Signature header.

        Returns:
            True if signature is valid, False otherwise.
        """
        import hashlib
        import hmac

        if not payload or not signature:
            logger.warning(
                "grabfood.verify_signature.empty_params",
                has_payload=bool(payload),
                has_signature=bool(signature),
            )
            return False

        try:
            expected = hmac.new(
                self.app_secret.encode("utf-8"),
                payload,
                hashlib.sha256,
            ).hexdigest()
            return hmac.compare_digest(expected, signature)
        except (TypeError, ValueError) as exc:
            logger.warning(
                "grabfood.verify_signature.error",
                error=str(exc),
            )
            return False

    async def confirm_order(self, platform_order_id: str) -> bool:
        """Accept a GrabFood order via API.

        POST /grabfood/v1/partner/order

        Args:
            platform_order_id: GrabFood order ID.

        Returns:
            True if the platform confirmed acceptance.
        """
        logger.info(
            "grabfood_confirm_order",
            platform_order_id=platform_order_id,
            note="Production: calls GrabFood POST /grabfood/v1/partner/order via GrabFoodClient",
        )
        # Production implementation should use GrabFoodClient from
        # shared.adapters.grabfood.src.client. This stub returns True.
        return True

    async def reject_order(self, platform_order_id: str, reason: str) -> bool:
        """Reject a GrabFood order via API.

        POST /grabfood/v1/order/reject

        Args:
            platform_order_id: GrabFood order ID.
            reason:            Reason for rejection.

        Returns:
            True if the platform confirmed rejection.
        """
        logger.info(
            "grabfood_reject_order",
            platform_order_id=platform_order_id,
            reason=reason,
            note="Production: calls GrabFood POST /grabfood/v1/order/reject via GrabFoodClient",
        )
        if not reason:
            logger.warning(
                "grabfood_reject_order_no_reason",
                platform_order_id=platform_order_id,
            )
            return False
        # Production implementation should use GrabFoodClient.
        return True
