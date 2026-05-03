"""ShopeeFood Malaysia 外卖平台适配器

字段映射参考 ShopeeFood Partner API (马来西亚)。
签名算法：HMAC-SHA256（app_secret 为 key，按字典序排序的 query params + body 为 data）。
"""
from __future__ import annotations

import hashlib
import hmac
import json
from datetime import datetime
from typing import Optional

import structlog

from .base_adapter import BaseDeliveryAdapter, DeliveryOrder, DeliveryOrderItem

logger = structlog.get_logger(__name__)


class ShopeeFoodAdapter(BaseDeliveryAdapter):
    """ShopeeFood 外卖订单适配器"""

    platform = "shopeefood"

    def parse_order(self, raw: dict) -> DeliveryOrder:
        """
        ShopeeFood Webhook 字段映射：
          order_id             → platform_order_id
          shop_id              → 门店标识
          items                → items（list of {item_id, item_name, quantity, price}）
          total_amount         → total_fen（ShopeeFood 金额单位为 MYR，需 ×100 转分）
          shipping_fee         → delivery_fee_fen
          buyer.name           → customer_name
          buyer.phone          → customer_phone
          buyer.address        → delivery_address
          order_time           → placed_at（ISO 8601 字符串）
          expect_time          → estimated_delivery_at（ISO 8601 字符串）
        """
        log = logger.bind(
            platform=self.platform,
            order_id=raw.get("order_id", ""),
        )

        try:
            # 金额：ShopeeFood 原始单位为 MYR（浮点），转分为 int
            total_myr: float = float(raw.get("total_amount", 0))
            total_fen: int = int(round(total_myr * 100))
            shipping_myr: float = float(raw.get("shipping_fee", 0))
            shipping_fen: int = int(round(shipping_myr * 100))

            # 商品行
            raw_items: list[dict] = raw.get("items", [])
            items: list[DeliveryOrderItem] = []
            for ri in raw_items:
                unit_price_myr: float = float(ri.get("price", 0))
                unit_price_fen: int = int(round(unit_price_myr * 100))
                qty: int = int(ri.get("quantity", 1))
                items.append(
                    DeliveryOrderItem(
                        platform_item_id=str(ri.get("item_id", "")),
                        name=ri.get("item_name", ""),
                        qty=qty,
                        unit_price_fen=unit_price_fen,
                        spec=ri.get("sku", ri.get("item_id")),
                        total_fen=unit_price_fen * qty,
                    )
                )

            # 顾客信息
            buyer: dict = raw.get("buyer", {}) or {}

            # 配送时间：ISO 8601 字符串
            estimated_delivery_at: Optional[datetime] = None
            eta_str: Optional[str] = raw.get("expect_time")
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
                delivery_fee_fen=shipping_fen,
                customer_name=buyer.get("name"),
                customer_phone=buyer.get("phone"),
                delivery_address=buyer.get("address"),
                estimated_delivery_at=estimated_delivery_at,
                raw_payload=raw,
            )
            log.info(
                "shopeefood_parse_order_ok",
                items_count=len(items),
                total_fen=total_fen,
            )
            return order

        except (KeyError, TypeError, ValueError) as exc:
            log.error(
                "shopeefood_parse_order_failed",
                error=str(exc),
                exc_info=True,
            )
            raise ValueError(f"ShopeeFood 订单解析失败: {exc}") from exc

    def verify_signature(self, payload: bytes, signature: str) -> bool:
        """
        ShopeeFood 签名算法：

        ShopeeFood 使用 HMAC-SHA256，app_secret 为 key，
        签名数据为：sorted_query_params + raw_body。
        签名在 Header X-ShopeeFood-Signature 传递。

          1. 解析 JSON body
          2. 提取 query 参数（按字典序排序）
          3. sign = HMAC-SHA256(app_secret, sorted_query_string + raw_body).hexdigest()
        """
        try:
            body: dict = json.loads(payload)
            # 提取并排序 query 参数（排除签名本身及 body 字段）
            query_params = {
                k: v for k, v in body.items()
                if k != "sign" and not isinstance(v, (dict, list))
            }
            sorted_keys = sorted(query_params.keys())
            sorted_str = "&".join(
                f"{k}={query_params[k]}"
                for k in sorted_keys
                if query_params[k] is not None
            )
            # 拼接排序后的 query 字符串和原始 body
            payload_str = sorted_str + payload.decode("utf-8")

            expected = hmac.new(
                self.app_secret.encode("utf-8"),
                payload_str.encode("utf-8"),
                hashlib.sha256,
            ).hexdigest()
            return hmac.compare_digest(expected, signature.lower())
        except (json.JSONDecodeError, AttributeError, TypeError) as exc:
            logger.warning("shopeefood_verify_signature_error", error=str(exc))
            return False

    async def confirm_order(self, platform_order_id: str) -> bool:
        """
        调用 ShopeeFood 接单 API：
          POST /api/v1/order/accept
          Body: {"order_id": "..."}
          Header: X-API-Key, Authorization: Bearer <token>
        生产环境需通过 httpx.AsyncClient 调用，此处返回 True 作为骨架实现。
        """
        logger.info(
            "shopeefood_confirm_order",
            platform_order_id=platform_order_id,
            note="生产环境需调用 ShopeeFood Partner API /order/accept 接口",
        )
        return True

    async def reject_order(self, platform_order_id: str, reason: str) -> bool:
        """
        调用 ShopeeFood 拒单 API：
          POST /api/v1/order/reject
          Body: {"order_id": "...", "reason": "..."}
        生产环境需通过 httpx.AsyncClient 调用，此处返回 True 作为骨架实现。
        """
        logger.info(
            "shopeefood_reject_order",
            platform_order_id=platform_order_id,
            reason=reason,
            note="生产环境需调用 ShopeeFood Partner API /order/reject 接口",
        )
        return True
