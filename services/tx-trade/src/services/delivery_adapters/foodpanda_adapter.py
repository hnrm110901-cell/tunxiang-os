"""Foodpanda Malaysia 外卖平台适配器

字段映射参考 Foodpanda Merchant API (马来西亚)。
签名算法：HMAC-SHA256（shared_secret 为 key，payload 为 data）。
"""
from __future__ import annotations

import hashlib
import hmac
from datetime import datetime
from typing import Optional

import structlog

from .base_adapter import BaseDeliveryAdapter, DeliveryOrder, DeliveryOrderItem

logger = structlog.get_logger(__name__)


class FoodpandaAdapter(BaseDeliveryAdapter):
    """Foodpanda 外卖订单适配器"""

    platform = "foodpanda"

    def parse_order(self, raw: dict) -> DeliveryOrder:
        """
        Foodpanda Webhook 字段映射：
          order_id              → platform_order_id
          restaurant_id         → 门店标识（映射到 shop_id）
          order_products        → items（list of {product_id, product_name, quantity, unit_price}）
          total                 → total_fen（Foodpanda 金额单位为 MYR，需 ×100 转分）
          delivery_fee          → delivery_fee_fen
          customer.name         → customer_name
          customer.phone        → customer_phone
          customer.address      → delivery_address
          created_at            → placed_at（ISO 8601 字符串）
          estimated_delivery_time → estimated_delivery_at（ISO 8601 字符串）
        """
        log = logger.bind(
            platform=self.platform,
            order_id=raw.get("order_id", ""),
        )

        try:
            # 金额：Foodpanda 原始单位为 MYR（浮点），转分为 int
            total_myr: float = float(raw.get("total", 0))
            total_fen: int = int(round(total_myr * 100))
            delivery_fee_myr: float = float(raw.get("delivery_fee", 0))
            delivery_fee_fen: int = int(round(delivery_fee_myr * 100))

            # 商品行
            raw_items: list[dict] = raw.get("order_products", [])
            items: list[DeliveryOrderItem] = []
            for ri in raw_items:
                unit_price_myr: float = float(ri.get("unit_price", 0))
                unit_price_fen: int = int(round(unit_price_myr * 100))
                qty: int = int(ri.get("quantity", 1))
                items.append(
                    DeliveryOrderItem(
                        platform_item_id=str(ri.get("product_id", "")),
                        name=ri.get("product_name", ""),
                        qty=qty,
                        unit_price_fen=unit_price_fen,
                        spec=ri.get("sku", ri.get("product_id")),
                        total_fen=unit_price_fen * qty,
                    )
                )

            # 顾客信息
            customer: dict = raw.get("customer", {}) or {}

            # 配送时间：ISO 8601 字符串
            estimated_delivery_at: Optional[datetime] = None
            eta_str: Optional[str] = raw.get("estimated_delivery_time")
            if eta_str:
                try:
                    estimated_delivery_at = datetime.fromisoformat(
                        eta_str.replace("Z", "+00:00")
                    )
                except ValueError:
                    pass

            order = DeliveryOrder(
                platform=self.platform,
                platform_order_id=str(raw["order_id"]),
                status="pending",
                items=items,
                total_fen=total_fen,
                delivery_fee_fen=delivery_fee_fen,
                customer_name=customer.get("name"),
                customer_phone=customer.get("phone"),
                delivery_address=customer.get("address"),
                estimated_delivery_at=estimated_delivery_at,
                raw_payload=raw,
            )
            log.info(
                "foodpanda_parse_order_ok",
                items_count=len(items),
                total_fen=total_fen,
            )
            return order

        except (KeyError, TypeError, ValueError) as exc:
            log.error(
                "foodpanda_parse_order_failed",
                error=str(exc),
                exc_info=True,
            )
            raise ValueError(f"Foodpanda 订单解析失败: {exc}") from exc

    def verify_signature(self, payload: bytes, signature: str) -> bool:
        """
        Foodpanda 签名算法：

        Foodpanda 使用 HMAC-SHA256，shared_secret 为 key，
        原始请求体（raw bytes）为 data。签名在 Header X-Foodpanda-Signature 传递。

          sign = HMAC-SHA256(shared_secret, raw_body).hexdigest()
        """
        try:
            expected = hmac.new(
                self.app_secret.encode("utf-8"),
                payload,
                hashlib.sha256,
            ).hexdigest()
            return hmac.compare_digest(expected, signature.lower())
        except (AttributeError, TypeError) as exc:
            logger.warning("foodpanda_verify_signature_error", error=str(exc))
            return False

    async def confirm_order(self, platform_order_id: str) -> bool:
        """
        调用 Foodpanda 接单 API：
          POST /api/v1/orders/{order_id}/accept
        生产环境需通过 httpx.AsyncClient 调用，此处返回 True 作为骨架实现。
        """
        logger.info(
            "foodpanda_confirm_order",
            platform_order_id=platform_order_id,
            note="生产环境需调用 Foodpanda Merchant API /orders/{id}/accept 接口",
        )
        return True

    async def reject_order(self, platform_order_id: str, reason: str) -> bool:
        """
        调用 Foodpanda 拒单 API：
          POST /api/v1/orders/{order_id}/reject
        生产环境需通过 httpx.AsyncClient 调用，此处返回 True 作为骨架实现。
        """
        logger.info(
            "foodpanda_reject_order",
            platform_order_id=platform_order_id,
            reason=reason,
            note="生产环境需调用 Foodpanda Merchant API /orders/{id}/reject 接口",
        )
        return True
