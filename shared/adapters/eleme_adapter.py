"""
饿了么外卖平台适配器（DeliveryPlatformAdapter 实现）

当前阶段：Mock 模式，不调用真实饿了么 API。
签名算法（HMAC-SHA256）已实现占位，OAuth2 token 管理已实现 Mock。

配置（环境变量）：
  ELEME_DELIVERY_APP_KEY
  ELEME_DELIVERY_APP_SECRET
  ELEME_DELIVERY_STORE_MAP   JSON 格式: {"txos_store_001": "eleme_shop_888"}
"""
from __future__ import annotations

import hashlib
import hmac as hmac_mod
import json
import os
import time
from datetime import datetime
from typing import Any, Callable, Coroutine, Dict, List, Optional

import structlog

from .delivery_platform_base import (
    DeliveryPlatformAdapter,
    DeliveryPlatformError,
    DeliveryPlatformSignError,
    DeliveryPlatformTimeoutError,
)

logger = structlog.get_logger()

# ── 饿了么订单状态 → 屯象统一状态 ────────────────────────
ELEME_STATUS_MAP: Dict[int, str] = {
    0: "pending",       # 待付款
    1: "pending",       # 待接单
    2: "confirmed",     # 已接单
    3: "preparing",     # 备餐中
    4: "delivering",    # 配送中
    5: "completed",     # 已完成
    6: "cancelled",     # 已取消
    9: "refunded",      # 已退款
}


def _load_store_mapping() -> Dict[str, str]:
    """从环境变量加载 屯象门店ID → 饿了么门店ID 映射"""
    raw = os.environ.get("ELEME_DELIVERY_STORE_MAP", "{}")
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        logger.warning("eleme_store_map_parse_failed", raw=raw)
        return {}


class ElemeDeliveryAdapter(DeliveryPlatformAdapter):
    """饿了么外卖平台适配器

    实现 DeliveryPlatformAdapter 全部方法。
    当前为 Mock 模式，所有 API 调用返回模拟数据。

    OAuth2 token 管理已实现 Mock（client_credentials 模式）。
    """

    def __init__(
        self,
        app_key: Optional[str] = None,
        app_secret: Optional[str] = None,
        store_map: Optional[Dict[str, str]] = None,
        sandbox: bool = False,
        timeout: int = 30,
    ):
        self.app_key = app_key or os.environ.get("ELEME_DELIVERY_APP_KEY", "")
        self.app_secret = app_secret or os.environ.get("ELEME_DELIVERY_APP_SECRET", "")
        self.store_map = store_map or _load_store_mapping()
        self.sandbox = sandbox
        self.timeout = timeout

        # OAuth2 token 缓存
        self._access_token: Optional[str] = None
        self._token_expires_at: float = 0

        # Webhook 事件处理器注册表
        self._webhook_handlers: Dict[
            str, Callable[[Dict[str, Any]], Coroutine[Any, Any, None]]
        ] = {}

        logger.info(
            "eleme_delivery_adapter_init",
            store_count=len(self.store_map),
            sandbox=sandbox,
            mock_mode=True,
        )

    # ── 签名算法（饿了么 HMAC-SHA256） ──────────────────────

    def _generate_sign(self, params: Dict[str, Any]) -> str:
        """饿了么 HMAC-SHA256 签名

        算法：
          1. 参数按 key 字典序排列
          2. 拼接 app_secret + key1value1key2value2... + app_secret
          3. HMAC-SHA256 (key=app_secret) 取大写 hex
        """
        sorted_params = sorted(params.items())
        sign_str = self.app_secret
        for k, v in sorted_params:
            sign_str += f"{k}{v}"
        sign_str += self.app_secret

        signature = hmac_mod.new(
            self.app_secret.encode("utf-8"),
            sign_str.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest().upper()
        return signature

    # ── OAuth2 Token 管理（Mock）──────────────────────────────

    async def _refresh_token(self) -> None:
        """Mock: 模拟 OAuth2 client_credentials 获取 token"""
        logger.info("eleme_token_refresh_mock")
        self._access_token = f"mock_token_{int(time.time())}"
        self._token_expires_at = time.time() + 86400  # 24h
        logger.info("eleme_token_refreshed", expires_in=86400)

    async def get_access_token(self) -> str:
        """获取有效 access_token（过期自动刷新）"""
        now = time.time()
        if self._access_token and now < self._token_expires_at - 60:
            return self._access_token
        await self._refresh_token()
        assert self._access_token is not None
        return self._access_token

    # ── 内部工具 ─────────────────────────────────────────────

    def _get_shop_id(self, store_id: str) -> str:
        """屯象门店ID → 饿了么门店ID"""
        shop_id = self.store_map.get(store_id, "")
        if not shop_id:
            logger.warning("eleme_store_not_mapped", store_id=store_id)
        return shop_id

    def _map_order(self, raw: Dict[str, Any]) -> dict:
        """饿了么原始订单 → 屯象统一订单格式"""
        food_list = raw.get("food_list", raw.get("items", []))

        items: List[Dict[str, Any]] = []
        for food in food_list:
            items.append({
                "name": food.get("food_name", food.get("name", "")),
                "quantity": int(food.get("quantity", food.get("count", 1))),
                "price_fen": int(food.get("price", 0)),
                "sku_id": str(food.get("food_id", food.get("sku_id", ""))),
                "notes": food.get("remark", food.get("food_property", "")),
                "internal_dish_id": "",  # 需要业务层映射
            })

        status_code = int(raw.get("status", 1))
        return {
            "platform": "eleme",
            "platform_order_id": str(raw.get("order_id", raw.get("eleme_order_id", ""))),
            "day_seq": str(raw.get("day_seq", "")),
            "status": ELEME_STATUS_MAP.get(status_code, "pending"),
            "items": items,
            "total_fen": int(raw.get("total_price", raw.get("order_amount", 0))),
            "customer_phone": str(raw.get("consignee_phone", raw.get("recipient_phone", ""))),
            "delivery_address": str(raw.get("delivery_address", raw.get("address", ""))),
            "expected_time": str(raw.get("expected_delivery_time", raw.get("delivery_time", ""))),
            "notes": str(raw.get("remark", raw.get("caution", ""))),
        }

    def _map_dish_to_eleme(self, dish: dict) -> dict:
        """屯象统一菜品格式 → 饿了么商品格式"""
        return {
            "food_id": dish.get("id", dish.get("external_id", "")),
            "name": dish.get("name", ""),
            "category_name": dish.get("category_name", "默认分类"),
            "price": int(float(dish.get("price", 0)) * 100),  # 元 → 分
            "unit": dish.get("unit", "份"),
            "description": dish.get("specification", ""),
            "is_available": 1 if dish.get("is_available", True) else 0,
        }

    # ── Webhook 回调处理 ─────────────────────────────────────

    def register_webhook_handler(
        self,
        event_type: str,
        handler: Callable[[Dict[str, Any]], Coroutine[Any, Any, None]],
    ) -> None:
        """注册 Webhook 事件处理函数

        支持的事件类型：
          - order.created       新订单
          - order.cancelled     订单取消
          - order.refunded      订单退款
          - delivery.status     配送状态变更

        Args:
            event_type: 事件类型标识
            handler: 异步处理函数
        """
        self._webhook_handlers[event_type] = handler
        logger.info("eleme_webhook_handler_registered", event_type=event_type)

    def verify_webhook_signature(
        self,
        payload: str,
        signature: str,
        timestamp: str,
    ) -> bool:
        """验证 Webhook 回调签名

        饿了么签名规则：
          sign = SHA256(app_secret + payload + timestamp + app_secret)
          取大写hex

        Args:
            payload: 原始请求体字符串
            signature: 饿了么传入的签名
            timestamp: 饿了么传入的时间戳

        Returns:
            签名是否合法
        """
        try:
            ts = int(timestamp)
            now = int(time.time())
            if abs(now - ts) > 300:
                logger.warning("eleme_webhook_timestamp_expired", diff=abs(now - ts))
                return False
        except (ValueError, TypeError):
            logger.warning("eleme_webhook_bad_timestamp", timestamp=timestamp)
            return False

        sign_str = f"{self.app_secret}{payload}{timestamp}{self.app_secret}"
        expected = hashlib.sha256(sign_str.encode("utf-8")).hexdigest().upper()
        return hmac_mod.compare_digest(expected, signature.upper())

    async def handle_webhook_event(
        self,
        event_type: str,
        data: Dict[str, Any],
    ) -> Dict[str, Any]:
        """分发 Webhook 事件到注册的处理器

        Args:
            event_type: 事件类型
            data: 事件数据

        Returns:
            处理结果
        """
        logger.info("eleme_webhook_event", event_type=event_type)
        handler = self._webhook_handlers.get(event_type)
        if not handler:
            logger.warning("eleme_webhook_no_handler", event_type=event_type)
            return {"success": True, "message": "no handler registered, event acknowledged"}

        try:
            await handler(data)
            return {"success": True, "event_type": event_type}
        except Exception as exc:  # noqa: BLE001 — Webhook 兜底：不能因 handler 异常导致回调失败
            logger.error(
                "eleme_webhook_handler_error",
                event_type=event_type,
                error=str(exc),
                exc_info=True,
            )
            return {"success": False, "event_type": event_type, "error": str(exc)}

    # ── Mock 数据生成 ────────────────────────────────────────

    def _mock_orders(self, shop_id: str, since: datetime) -> list[dict]:
        """生成 Mock 订单数据"""
        now_ts = int(time.time())
        return [
            {
                "order_id": f"EL{now_ts}001",
                "day_seq": "001",
                "status": 1,
                "total_price": 4200,
                "food_list": [
                    {
                        "food_name": "麻辣香锅",
                        "quantity": 1,
                        "price": 3500,
                        "food_id": "EL_FOOD_001",
                        "remark": "多加花椒",
                    },
                    {
                        "food_name": "可乐",
                        "quantity": 1,
                        "price": 700,
                        "food_id": "EL_FOOD_002",
                        "remark": "",
                    },
                ],
                "consignee_phone": "139****9999",
                "delivery_address": "长沙市岳麓区测试街2号",
                "expected_delivery_time": str(now_ts + 2700),
                "remark": "不要香菜",
            }
        ]

    # ── DeliveryPlatformAdapter 接口实现 ─────────────────────

    async def pull_orders(
        self, store_id: str, since: datetime
    ) -> list[dict]:
        """拉取饿了么新订单（Mock）"""
        shop_id = self._get_shop_id(store_id)
        logger.info(
            "eleme_pull_orders",
            store_id=store_id,
            shop_id=shop_id,
            since=since.isoformat(),
        )

        # 确保 token 有效
        await self.get_access_token()

        # Mock：返回模拟订单
        raw_orders = self._mock_orders(shop_id, since)
        return [self._map_order(raw) for raw in raw_orders]

    async def accept_order(self, order_id: str) -> bool:
        """接受饿了么订单（Mock）"""
        await self.get_access_token()
        logger.info("eleme_accept_order", order_id=order_id)
        # Mock：直接返回成功
        return True

    async def reject_order(self, order_id: str, reason: str) -> bool:
        """拒绝饿了么订单（Mock）"""
        await self.get_access_token()
        logger.info("eleme_reject_order", order_id=order_id, reason=reason)
        if not reason:
            raise DeliveryPlatformError(
                platform="eleme",
                code=400,
                message="拒单原因不能为空",
            )
        # Mock：直接返回成功
        return True

    async def mark_ready(self, order_id: str) -> bool:
        """标记出餐完成（Mock）"""
        await self.get_access_token()
        logger.info("eleme_mark_ready", order_id=order_id)
        # Mock：直接返回成功
        return True

    async def sync_menu(
        self, store_id: str, dishes: list[dict]
    ) -> dict:
        """同步菜品到饿了么（Mock）"""
        shop_id = self._get_shop_id(store_id)
        await self.get_access_token()
        logger.info(
            "eleme_sync_menu",
            store_id=store_id,
            shop_id=shop_id,
            dish_count=len(dishes),
        )

        synced = 0
        failed = 0
        errors: list[dict] = []

        for dish in dishes:
            try:
                eleme_food = self._map_dish_to_eleme(dish)
                logger.debug("eleme_sync_dish", food=eleme_food)
                synced += 1
            except (KeyError, ValueError, TypeError) as exc:
                failed += 1
                errors.append({
                    "dish_id": dish.get("id", "unknown"),
                    "error": str(exc),
                })
                logger.warning(
                    "eleme_sync_dish_failed",
                    dish_id=dish.get("id"),
                    error=str(exc),
                )

        return {"synced": synced, "failed": failed, "errors": errors}

    async def update_stock(
        self, store_id: str, dish_id: str, available: bool
    ) -> bool:
        """更新菜品上下架状态（Mock）"""
        shop_id = self._get_shop_id(store_id)
        await self.get_access_token()
        action = "上架" if available else "售罄"
        logger.info(
            "eleme_update_stock",
            shop_id=shop_id,
            dish_id=dish_id,
            action=action,
        )
        # Mock：直接返回成功
        return True

    async def get_order_detail(self, order_id: str) -> dict:
        """获取饿了么订单详情（Mock）"""
        await self.get_access_token()
        logger.info("eleme_get_order_detail", order_id=order_id)

        now_ts = int(time.time())
        mock_raw = {
            "order_id": order_id,
            "day_seq": "001",
            "status": 2,
            "total_price": 4200,
            "food_list": [
                {
                    "food_name": "麻辣香锅",
                    "quantity": 1,
                    "price": 3500,
                    "food_id": "EL_FOOD_001",
                    "remark": "多加花椒",
                },
            ],
            "consignee_phone": "139****9999",
            "delivery_address": "长沙市岳麓区测试街2号",
            "expected_delivery_time": str(now_ts + 2700),
            "remark": "不要香菜",
        }
        return self._map_order(mock_raw)

    async def close(self) -> None:
        """释放资源"""
        logger.info("eleme_delivery_adapter_closed")
