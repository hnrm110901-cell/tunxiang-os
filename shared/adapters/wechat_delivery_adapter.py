"""微信自有外卖适配器 — 品牌自有外卖渠道（省去平台抽成20-25%）

与三方外卖（美团/饿了么/抖音）的区别：
- 三方外卖：平台引流+平台配送，抽成20-25%
- 微信自有外卖：品牌公众号/小程序下单+自配送或第三方配送，0抽成

实现方式：
- 下单入口：微信小程序 miniapp-customer 中的外卖入口
- 支付：微信支付直连（不经平台）
- 配送：对接达达/顺丰/闪送等第三方配送API，或商家自配送
- 订单管理：直接进入tx-trade订单系统

当前阶段：Mock 模式，不调用真实配送 API。
接入真实配送商 API 时切换内部方法即可。
"""
from __future__ import annotations

import os
from datetime import datetime
from typing import Any, Dict, List, Optional

import structlog

from .delivery_platform_base import (
    DeliveryPlatformAdapter,
    DeliveryPlatformError,
)

logger = structlog.get_logger()

# ── 微信自有外卖订单状态 → 屯象统一状态 ──────────────────
WECHAT_STATUS_MAP: Dict[str, str] = {
    "pending": "pending",          # 待接单
    "confirmed": "confirmed",      # 已接单
    "preparing": "preparing",      # 备餐中
    "dispatching": "delivering",   # 配送中
    "delivered": "completed",      # 已送达
    "cancelled": "cancelled",      # 已取消
    "refunded": "refunded",        # 已退款
}

# 可用配送商
DELIVERY_PROVIDERS = ("dada", "shunfeng", "shanshan", "self")


class WeChatDeliveryAdapter(DeliveryPlatformAdapter):
    """微信自有外卖适配器

    实现 DeliveryPlatformAdapter 全部方法。
    当前为 Mock 模式，所有 API 调用返回模拟数据。

    0% 平台抽成 — 订单和支付完全在品牌自有体系内闭环。
    """

    PLATFORM_NAME = "wechat"
    PLATFORM_CN = "微信自有外卖"
    COMMISSION_RATE = 0.0  # 0%抽成

    def __init__(
        self,
        app_key: Optional[str] = None,
        app_secret: Optional[str] = None,
        store_map: Optional[Dict[str, str]] = None,
        base_url: str = "",
        timeout: int = 30,
    ):
        self.app_key = app_key or os.environ.get("WECHAT_DELIVERY_APP_KEY", "")
        self.app_secret = app_secret or os.environ.get("WECHAT_DELIVERY_APP_SECRET", "")
        self.store_map = store_map or {}
        self.base_url = base_url
        self.timeout = timeout
        self.delivery_providers = list(DELIVERY_PROVIDERS)

        logger.info(
            "wechat_delivery_adapter_init",
            store_count=len(self.store_map),
            mock_mode=True,
        )

    # ── DeliveryPlatformAdapter 接口实现 ──────────────────

    async def pull_orders(
        self, store_id: str, since: datetime
    ) -> list[dict]:
        """拉取自有外卖新订单

        微信自有外卖的订单直接通过小程序下单进入 tx-trade，
        此方法用于兼容统一接口，返回最近未同步的自有外卖订单。
        """
        logger.info("wechat_pull_orders", store_id=store_id, since=since.isoformat())
        # Mock: 自有外卖订单直接写入 tx-trade，pull 返回空
        return []

    async def accept_order(self, order_id: str) -> bool:
        """接受订单（自有外卖默认自动接单）"""
        logger.info("wechat_accept_order", order_id=order_id)
        return True

    async def reject_order(self, order_id: str, reason: str) -> bool:
        """拒绝订单"""
        logger.info("wechat_reject_order", order_id=order_id, reason=reason)
        return True

    async def mark_ready(self, order_id: str) -> bool:
        """标记出餐完成，准备配送"""
        logger.info("wechat_mark_ready", order_id=order_id)
        return True

    async def sync_menu(
        self, store_id: str, dishes: list[dict]
    ) -> dict:
        """同步菜单（自有外卖不需要同步到第三方平台，直接管理可售菜品）"""
        logger.info("wechat_sync_menu", store_id=store_id, dish_count=len(dishes))
        return {
            "synced": len(dishes),
            "failed": 0,
            "errors": [],
            "platform": self.PLATFORM_NAME,
            "note": "self_managed",
        }

    async def update_stock(
        self, store_id: str, dish_id: str, available: bool
    ) -> bool:
        """更新菜品上下架状态"""
        logger.info("wechat_update_stock", store_id=store_id, dish_id=dish_id, available=available)
        return True

    async def get_order_detail(self, order_id: str) -> dict:
        """获取订单详情"""
        logger.info("wechat_get_order_detail", order_id=order_id)
        # Mock 返回
        return {
            "platform": self.PLATFORM_NAME,
            "platform_order_id": order_id,
            "day_seq": "",
            "status": "pending",
            "items": [],
            "total_fen": 0,
            "customer_phone": "",
            "delivery_address": "",
            "expected_time": "",
            "notes": "",
            "commission_rate": self.COMMISSION_RATE,
            "commission_fen": 0,
        }

    async def close(self) -> None:
        """释放资源"""
        logger.info("wechat_delivery_adapter_closed")

    # ── 自有外卖专属方法（三方平台没有的能力）──────────────

    async def request_delivery(
        self,
        order_id: str,
        provider: str = "dada",
        delivery_data: Optional[dict] = None,
    ) -> dict:
        """请求第三方配送

        Args:
            order_id: 订单ID
            provider: 配送商 — dada(达达) / shunfeng(顺丰) / shanshan(闪送) / self(自配送)
            delivery_data: 配送附加信息（地址/费用等）
        """
        if provider not in self.delivery_providers:
            raise DeliveryPlatformError(
                platform=self.PLATFORM_NAME,
                code=400,
                message=f"Unsupported delivery provider: {provider}, "
                        f"available: {', '.join(self.delivery_providers)}",
            )

        delivery_info: dict[str, Any] = {
            "ok": True,
            "order_id": order_id,
            "provider": provider,
            "status": "dispatching",
            "tracking_id": f"DL-{order_id}",
        }

        if provider == "self":
            delivery_info["delivery_type"] = "self_delivery"
            delivery_info["estimated_minutes"] = 20
        else:
            delivery_info["delivery_type"] = "third_party"
            delivery_info["estimated_minutes"] = 30
            delivery_info["delivery_fee_fen"] = (
                delivery_data.get("fee_fen", 500) if delivery_data else 500
            )

        logger.info("wechat_delivery_dispatched", order_id=order_id, provider=provider)
        return delivery_info

    async def handle_delivery_callback(self, callback_data: dict) -> dict:
        """处理配送回调（配送完成/异常等）"""
        event_type = callback_data.get("event", "")
        order_id = callback_data.get("order_id", "")

        status_map = {
            "pickup": "picked_up",
            "delivering": "delivering",
            "delivered": "delivered",
            "exception": "delivery_exception",
            "cancelled": "delivery_cancelled",
        }

        new_status = status_map.get(event_type, "unknown")
        logger.info("wechat_delivery_callback", order_id=order_id, event=event_type, new_status=new_status)

        return {"ok": True, "order_id": order_id, "status": new_status}

    async def get_commission_summary(self, start_date: str, end_date: str) -> dict:
        """获取佣金汇总（自有外卖 = 0佣金）"""
        return {
            "ok": True,
            "platform": self.PLATFORM_NAME,
            "period": f"{start_date} ~ {end_date}",
            "total_orders": 0,
            "total_revenue_fen": 0,
            "commission_fen": 0,
            "commission_rate": 0.0,
            "savings_vs_platform_fen": 0,  # 比平台省下的佣金（需要订单数据才能算）
        }
