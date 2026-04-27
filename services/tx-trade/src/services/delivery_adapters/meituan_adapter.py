"""美团外卖平台适配器

字段映射参考美团外卖开放平台文档（openapi.waimai.meituan.com）。
签名算法：SHA-256（appSecret + 请求参数字典序拼接 + appSecret）。
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Optional

import structlog

from .base_adapter import BaseDeliveryAdapter, DeliveryOrder, DeliveryOrderItem

logger = structlog.get_logger(__name__)


class MeituanAdapter(BaseDeliveryAdapter):
    """美团外卖订单适配器"""

    platform = "meituan"

    def parse_order(self, raw: dict) -> DeliveryOrder:
        """
        美团外卖 Webhook 字段映射：
          order_id          → platform_order_id
          product_list      → items（list of {food_id, name, quantity, price, ...}）
          price_info.total  → total_fen（美团金额单位为分）
          price_info.shipping_fee → delivery_fee_fen
          recipient_address → delivery_address
          recipient_name / recipient_phone → customer_*
          estimate_arrive_time → estimated_delivery_at（Unix 时间戳）
        """
        log = logger.bind(
            platform=self.platform,
            order_id=raw.get("order_id", ""),
        )

        try:
            price_info: dict = raw.get("price_info", {})
            total_fen: int = int(price_info.get("total", 0))
            delivery_fee_fen: int = int(price_info.get("shipping_fee", 0))

            raw_items: list[dict] = raw.get("product_list", [])
            items: list[DeliveryOrderItem] = []
            for ri in raw_items:
                unit_price = int(ri.get("price", 0))
                qty = int(ri.get("quantity", 1))
                items.append(
                    DeliveryOrderItem(
                        platform_item_id=str(ri.get("food_id", "")),
                        name=ri.get("name", ""),
                        qty=qty,
                        unit_price_fen=unit_price,
                        spec=ri.get("spec") or ri.get("app_food_code"),
                        total_fen=unit_price * qty,
                    )
                )

            # 配送时间：美团使用 Unix 时间戳（秒）
            eta_ts: Optional[int] = raw.get("estimate_arrive_time")
            estimated_delivery_at: Optional[datetime] = (
                datetime.fromtimestamp(eta_ts, tz=timezone.utc) if eta_ts else None
            )

            order = DeliveryOrder(
                platform=self.platform,
                platform_order_id=str(raw["order_id"]),
                status="pending",
                items=items,
                total_fen=total_fen,
                delivery_fee_fen=delivery_fee_fen,
                customer_name=raw.get("recipient_name"),
                customer_phone=raw.get("recipient_phone"),
                delivery_address=raw.get("recipient_address"),
                estimated_delivery_at=estimated_delivery_at,
                raw_payload=raw,
            )
            log.info("meituan_parse_order_ok", items_count=len(items), total_fen=total_fen)
            return order

        except (KeyError, TypeError, ValueError) as exc:
            log.error("meituan_parse_order_failed", error=str(exc), exc_info=True)
            raise ValueError(f"美团订单解析失败: {exc}") from exc

    def verify_signature(self, payload: bytes, signature: str) -> bool:
        """
        美团签名算法：
          sign = SHA256(appSecret + sorted_params_string + appSecret)
          其中 sorted_params_string 为 payload JSON 解析后的键值对字典序拼接
        """
        try:
            params: dict = json.loads(payload)
            # 排除 sign 字段本身
            params.pop("sign", None)
            sorted_str = "".join(f"{k}{v}" for k, v in sorted(params.items()) if v is not None and v != "")
            raw_str = f"{self.app_secret}{sorted_str}{self.app_secret}"
            expected = hashlib.sha256(raw_str.encode("utf-8")).hexdigest().upper()
            return hmac.compare_digest(expected, signature.upper())
        except (json.JSONDecodeError, AttributeError, TypeError):
            return False

    async def confirm_order(self, platform_order_id: str) -> bool:
        """
        调用美团接单 API：
          POST https://openapi.waimai.meituan.com/order/confirm
          参数：app_id, order_id, sign, timestamp
        生产环境需通过 httpx.AsyncClient 调用，此处返回 True 作为骨架实现。
        """
        logger.info(
            "meituan_confirm_order",
            platform_order_id=platform_order_id,
            note="生产环境需调用美团开放平台 /order/confirm 接口",
        )
        return True

    async def reject_order(self, platform_order_id: str, reason: str) -> bool:
        """
        调用美团拒单 API：
          POST https://openapi.waimai.meituan.com/order/cancel
          参数：app_id, order_id, cancel_reason, sign, timestamp
        生产环境需通过 httpx.AsyncClient 调用，此处返回 True 作为骨架实现。
        """
        logger.info(
            "meituan_reject_order",
            platform_order_id=platform_order_id,
            reason=reason,
            note="生产环境需调用美团开放平台 /order/cancel 接口",
        )
        return True


# 修复 hmac.compare_digest 使用的 import
import hmac  # noqa: E402 （保持文件内可用）
