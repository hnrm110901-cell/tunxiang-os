"""抖音外卖/团购平台适配器

字段映射参考抖音开放平台文档（open.douyin.com/platform/doc/delivery）。
签名算法：SHA256（将 token + timestamp + nonce + encrypt_msg 排序后拼接再 SHA256）。
"""

from __future__ import annotations

import hashlib
import hmac
import json
from datetime import datetime, timezone
from typing import Optional

import structlog

from .base_adapter import BaseDeliveryAdapter, DeliveryOrder, DeliveryOrderItem

logger = structlog.get_logger(__name__)


class DouyinAdapter(BaseDeliveryAdapter):
    """抖音外卖/团购订单适配器"""

    platform = "douyin"

    def parse_order(self, raw: dict) -> DeliveryOrder:
        """
        抖音外卖 Webhook 字段映射：
          order_id           → platform_order_id
          product_list       → items（list of {sku_id, title, num, price, ...}）
          order_amount       → total_fen（抖音金额单位为分）
          delivery_amount    → delivery_fee_fen
          delivery_info.address → delivery_address
          delivery_info.receiver_name / receiver_phone → customer_*
          expect_time        → estimated_delivery_at（Unix 时间戳，秒）
        """
        log = logger.bind(
            platform=self.platform,
            order_id=raw.get("order_id", ""),
        )

        try:
            total_fen: int = int(raw.get("order_amount", 0))
            delivery_fee_fen: int = int(raw.get("delivery_amount", 0))

            raw_items: list[dict] = raw.get("product_list", [])
            items: list[DeliveryOrderItem] = []
            for ri in raw_items:
                unit_price_fen: int = int(ri.get("price", 0))
                qty: int = int(ri.get("num", 1))
                items.append(
                    DeliveryOrderItem(
                        platform_item_id=str(ri.get("sku_id", "")),
                        name=ri.get("title", ""),
                        qty=qty,
                        unit_price_fen=unit_price_fen,
                        spec=ri.get("spec_name"),
                        total_fen=unit_price_fen * qty,
                    )
                )

            delivery_info: dict = raw.get("delivery_info", {})
            expect_ts: Optional[int] = raw.get("expect_time")
            estimated_delivery_at: Optional[datetime] = (
                datetime.fromtimestamp(expect_ts, tz=timezone.utc) if expect_ts else None
            )

            order = DeliveryOrder(
                platform=self.platform,
                platform_order_id=str(raw["order_id"]),
                status="pending",
                items=items,
                total_fen=total_fen,
                delivery_fee_fen=delivery_fee_fen,
                customer_name=delivery_info.get("receiver_name"),
                customer_phone=delivery_info.get("receiver_phone"),
                delivery_address=delivery_info.get("address"),
                estimated_delivery_at=estimated_delivery_at,
                raw_payload=raw,
            )
            log.info("douyin_parse_order_ok", items_count=len(items), total_fen=total_fen)
            return order

        except (KeyError, TypeError, ValueError) as exc:
            log.error("douyin_parse_order_failed", error=str(exc), exc_info=True)
            raise ValueError(f"抖音订单解析失败: {exc}") from exc

    def verify_signature(self, payload: bytes, signature: str) -> bool:
        """
        抖音签名验证算法：
          将 [token, timestamp, nonce, encrypt_msg] 排序后拼接为字符串，
          再进行 SHA1 得到签名。
          注：此处 payload 中包含 JSON，从中提取相关字段。
        """
        try:
            body: dict = json.loads(payload)
            token = self.app_secret  # 抖音使用 token 而非 secret 做签名
            timestamp = str(body.get("timestamp", ""))
            nonce = str(body.get("nonce", ""))
            encrypt_msg = str(body.get("encrypt", ""))

            tmp_list = sorted([token, timestamp, nonce, encrypt_msg])
            tmp_str = "".join(tmp_list)
            expected = hashlib.sha1(tmp_str.encode("utf-8")).hexdigest()
            return hmac.compare_digest(expected, signature.lower())
        except (json.JSONDecodeError, AttributeError, TypeError):
            return False

    async def confirm_order(self, platform_order_id: str) -> bool:
        """
        调用抖音接单 API：
          POST https://open.douyin.com/api/delivery/v1/order/confirm
          参数：order_id, access_token, app_id
        生产环境需通过 httpx.AsyncClient 调用，此处返回 True 作为骨架实现。
        """
        logger.info(
            "douyin_confirm_order",
            platform_order_id=platform_order_id,
            note="生产环境需调用抖音开放平台 /order/confirm 接口",
        )
        return True

    async def reject_order(self, platform_order_id: str, reason: str) -> bool:
        """
        调用抖音拒单 API：
          POST https://open.douyin.com/api/delivery/v1/order/reject
          参数：order_id, reject_reason, access_token, app_id
        生产环境需通过 httpx.AsyncClient 调用，此处返回 True 作为骨架实现。
        """
        logger.info(
            "douyin_reject_order",
            platform_order_id=platform_order_id,
            reason=reason,
            note="生产环境需调用抖音开放平台 /order/reject 接口",
        )
        return True
