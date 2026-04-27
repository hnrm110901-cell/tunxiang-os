"""饿了么平台适配器

字段映射参考饿了么开放平台文档（open.ele.me/openapi）。
签名算法：HMAC-SHA256（app_secret 为 key，按参数名字典序拼接为 data）。
"""

from __future__ import annotations

import hashlib
import hmac
from datetime import datetime
from typing import Optional

import structlog

from .base_adapter import BaseDeliveryAdapter, DeliveryOrder, DeliveryOrderItem

logger = structlog.get_logger(__name__)


class ElemeAdapter(BaseDeliveryAdapter):
    """饿了么外卖订单适配器"""

    platform = "eleme"

    def parse_order(self, raw: dict) -> DeliveryOrder:
        """
        饿了么 Webhook 字段映射：
          id               → platform_order_id
          groups           → items（list of {item_id, name, quantity, price, ...}）
          totalPrice       → total_fen（饿了么金额单位为元，需 ×100 转换）
          deliverFee       → delivery_fee_fen
          address          → delivery_address
          consignee / phone → customer_*
          deliverTime      → estimated_delivery_at（ISO 字符串）
        """
        log = logger.bind(
            platform=self.platform,
            order_id=raw.get("id", ""),
        )

        try:
            # 饿了么金额单位为元（字符串），转换为分
            total_yuan: float = float(raw.get("totalPrice", 0))
            total_fen: int = round(total_yuan * 100)
            deliver_fee_yuan: float = float(raw.get("deliverFee", 0))
            delivery_fee_fen: int = round(deliver_fee_yuan * 100)

            # 饿了么商品列表在 groups 字段下的 items 中
            raw_groups: list[dict] = raw.get("groups", [])
            items: list[DeliveryOrderItem] = []
            for group in raw_groups:
                for ri in group.get("items", []):
                    unit_price_yuan: float = float(ri.get("price", 0))
                    unit_price_fen: int = round(unit_price_yuan * 100)
                    qty: int = int(ri.get("quantity", 1))
                    items.append(
                        DeliveryOrderItem(
                            platform_item_id=str(ri.get("id", "")),
                            name=ri.get("name", ""),
                            qty=qty,
                            unit_price_fen=unit_price_fen,
                            spec=ri.get("sku_id"),
                            total_fen=unit_price_fen * qty,
                        )
                    )

            # 配送时间：饿了么使用 ISO 8601 字符串
            deliver_time_str: Optional[str] = raw.get("deliverTime")
            estimated_delivery_at: Optional[datetime] = None
            if deliver_time_str:
                try:
                    estimated_delivery_at = datetime.fromisoformat(deliver_time_str.replace("Z", "+00:00"))
                except ValueError:
                    pass

            order = DeliveryOrder(
                platform=self.platform,
                platform_order_id=str(raw["id"]),
                status="pending",
                items=items,
                total_fen=total_fen,
                delivery_fee_fen=delivery_fee_fen,
                customer_name=raw.get("consignee"),
                customer_phone=raw.get("phone"),
                delivery_address=raw.get("address"),
                estimated_delivery_at=estimated_delivery_at,
                raw_payload=raw,
            )
            log.info("eleme_parse_order_ok", items_count=len(items), total_fen=total_fen)
            return order

        except (KeyError, TypeError, ValueError) as exc:
            log.error("eleme_parse_order_failed", error=str(exc), exc_info=True)
            raise ValueError(f"饿了么订单解析失败: {exc}") from exc

    def verify_signature(self, payload: bytes, signature: str) -> bool:
        """
        饿了么签名算法：
          sign = HMAC-SHA256(key=app_secret, msg=raw_body_bytes).hexdigest()
          签名在 HTTP Header X-Eleme-RequestId 之外的 signature 字段传递
        """
        try:
            expected = hmac.new(
                self.app_secret.encode("utf-8"),
                payload,
                hashlib.sha256,
            ).hexdigest()
            return hmac.compare_digest(expected, signature.lower())
        except (AttributeError, TypeError):
            return False

    async def confirm_order(self, platform_order_id: str) -> bool:
        """
        调用饿了么接单 API：
          POST https://open.ele.me/api/openapi/confirm_order
          参数：order_id, app_key, timestamp, sign
        生产环境需通过 httpx.AsyncClient 调用，此处返回 True 作为骨架实现。
        """
        logger.info(
            "eleme_confirm_order",
            platform_order_id=platform_order_id,
            note="生产环境需调用饿了么开放平台 /confirm_order 接口",
        )
        return True

    async def reject_order(self, platform_order_id: str, reason: str) -> bool:
        """
        调用饿了么拒单 API：
          POST https://open.ele.me/api/openapi/cancel_order
          参数：order_id, reason_code, app_key, timestamp, sign
        生产环境需通过 httpx.AsyncClient 调用，此处返回 True 作为骨架实现。
        """
        logger.info(
            "eleme_reject_order",
            platform_order_id=platform_order_id,
            reason=reason,
            note="生产环境需调用饿了么开放平台 /cancel_order 接口",
        )
        return True
