"""
抖音外卖平台适配器（DeliveryPlatformAdapter 实现）

当前阶段：Mock 模式，不调用真实抖音外卖 API。
签名算法（HMAC-SHA256 + app_secret）已实现占位，接入真实 API 时切换 _mock -> _request 即可。

配置（环境变量）：
  DOUYIN_DELIVERY_APP_KEY
  DOUYIN_DELIVERY_APP_SECRET
  DOUYIN_DELIVERY_STORE_MAP   JSON 格式: {"txos_store_001": "dy_shop_888"}

抖音外卖特有功能：
  - 达人探店订单识别（is_influencer_order）
  - 直播间订单标记（is_livestream_order）
  - Webhook 回调处理（order.created / order.cancelled / order.refunded）
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
)

logger = structlog.get_logger()

# -- 抖音外卖订单状态 -> 屯象统一状态 --------------------------------
DOUYIN_STATUS_MAP: Dict[int, str] = {
    1: "pending",  # 待接单
    2: "confirmed",  # 已接单
    3: "preparing",  # 备餐中
    4: "delivering",  # 骑手已取餐
    5: "completed",  # 已完成
    6: "cancelled",  # 已取消
    9: "refunded",  # 已退款
}

# -- 抖音外卖订单来源标记 --------------------------------------------
DOUYIN_ORDER_SOURCE: Dict[int, str] = {
    0: "normal",  # 普通下单
    1: "influencer",  # 达人探店
    2: "livestream",  # 直播间下单
    3: "short_video",  # 短视频挂链
}


def _load_store_mapping() -> Dict[str, str]:
    """从环境变量加载 屯象门店ID -> 抖音门店ID 映射"""
    raw = os.environ.get("DOUYIN_DELIVERY_STORE_MAP", "{}")
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        logger.warning("douyin_store_map_parse_failed", raw=raw)
        return {}


class DouyinDeliveryAdapter(DeliveryPlatformAdapter):
    """抖音外卖平台适配器

    实现 DeliveryPlatformAdapter 全部方法。
    当前为 Mock 模式，所有 API 调用返回模拟数据。

    抖音外卖特有功能：
      - 达人探店订单识别
      - 直播间订单标记
      - Webhook 回调处理
    """

    def __init__(
        self,
        app_key: Optional[str] = None,
        app_secret: Optional[str] = None,
        store_map: Optional[Dict[str, str]] = None,
        base_url: str = "https://open.douyin.com/api/trade/v2",
        timeout: int = 30,
    ):
        self.app_key = app_key or os.environ.get("DOUYIN_DELIVERY_APP_KEY", "")
        self.app_secret = app_secret or os.environ.get("DOUYIN_DELIVERY_APP_SECRET", "")
        self.store_map = store_map or _load_store_mapping()
        self.base_url = base_url
        self.timeout = timeout

        # Webhook 事件处理器注册表
        self._webhook_handlers: Dict[str, Callable[..., Coroutine[Any, Any, None]]] = {}

        logger.info(
            "douyin_delivery_adapter_init",
            store_count=len(self.store_map),
            mock_mode=True,
        )

    # -- 签名算法（HMAC-SHA256） ------------------------------------

    def _generate_sign(self, params: Dict[str, Any]) -> str:
        """抖音外卖 HMAC-SHA256 签名

        算法：
          1. 参数按 key 字典序排列
          2. 拼接为 key1=value1&key2=value2&...
          3. 以 app_secret 为 key 做 HMAC-SHA256
          4. 返回小写 hex
        """
        sorted_params = sorted(params.items())
        sign_str = "&".join(f"{k}={v}" for k, v in sorted_params)
        signature = hmac_mod.new(
            self.app_secret.encode("utf-8"),
            sign_str.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        return signature

    def _build_auth_params(self, biz_params: Dict[str, Any]) -> Dict[str, Any]:
        """构造带签名的请求参数"""
        auth_params = {
            "app_key": self.app_key,
            "timestamp": str(int(time.time())),
            **biz_params,
        }
        auth_params["sign"] = self._generate_sign(auth_params)
        return auth_params

    # -- 内部工具 ---------------------------------------------------

    def _get_shop_id(self, store_id: str) -> str:
        """屯象门店ID -> 抖音门店ID"""
        shop_id = self.store_map.get(store_id, "")
        if not shop_id:
            logger.warning("douyin_store_not_mapped", store_id=store_id)
        return shop_id

    def _map_order(self, raw: Dict[str, Any]) -> dict:
        """抖音外卖原始订单 -> 屯象统一订单格式

        额外字段：
          is_influencer_order: bool   达人探店订单
          is_livestream_order: bool   直播间订单
          order_source_type: str      订单来源类型
        """
        food_list = raw.get("food_list", [])
        if isinstance(food_list, str):
            try:
                food_list = json.loads(food_list)
            except (json.JSONDecodeError, TypeError):
                food_list = []

        items: List[Dict[str, Any]] = []
        for food in food_list:
            items.append(
                {
                    "name": food.get("food_name", ""),
                    "quantity": int(food.get("quantity", 1)),
                    "price_fen": int(food.get("price", 0)),
                    "sku_id": str(food.get("sku_id", food.get("food_id", ""))),
                    "notes": food.get("remark", ""),
                    "internal_dish_id": "",  # 需要业务层映射
                }
            )

        status_code = int(raw.get("status", 1))
        order_source = int(raw.get("order_source", 0))
        source_type = DOUYIN_ORDER_SOURCE.get(order_source, "normal")

        return {
            "platform": "douyin",
            "platform_order_id": str(raw.get("order_id", "")),
            "day_seq": str(raw.get("day_seq", "")),
            "status": DOUYIN_STATUS_MAP.get(status_code, "pending"),
            "items": items,
            "total_fen": int(raw.get("total_price", 0)),
            "customer_phone": str(raw.get("customer_phone", "")),
            "delivery_address": str(raw.get("delivery_address", "")),
            "expected_time": str(raw.get("expected_delivery_time", "")),
            "notes": str(raw.get("remark", "")),
            # 抖音特有字段
            "is_influencer_order": source_type == "influencer",
            "is_livestream_order": source_type == "livestream",
            "order_source_type": source_type,
        }

    def _map_dish_to_douyin(self, dish: dict) -> dict:
        """屯象统一菜品格式 -> 抖音外卖商品格式"""
        return {
            "sku_id": dish.get("id", dish.get("external_id", "")),
            "food_name": dish.get("name", ""),
            "category_name": dish.get("category_name", "默认分类"),
            "price": int(float(dish.get("price", 0)) * 100),  # 元 -> 分
            "unit": dish.get("unit", "份"),
            "description": dish.get("specification", ""),
            "stock_status": 1 if dish.get("is_available", True) else 0,
        }

    # -- Webhook 处理 -----------------------------------------------

    def verify_webhook_signature(
        self,
        payload: str,
        signature: str,
        timestamp: str,
    ) -> bool:
        """验证抖音 Webhook 回调签名

        算法：HMAC-SHA256(app_secret, payload + timestamp)
        """
        sign_str = f"{payload}{timestamp}"
        expected = hmac_mod.new(
            self.app_secret.encode("utf-8"),
            sign_str.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        return expected == signature

    def register_webhook_handler(
        self,
        event_type: str,
        handler: Callable[..., Coroutine[Any, Any, None]],
    ) -> None:
        """注册 Webhook 事件处理器"""
        self._webhook_handlers[event_type] = handler
        logger.info("douyin_webhook_handler_registered", event_type=event_type)

    async def handle_webhook_event(
        self,
        event_type: str,
        data: dict,
    ) -> dict:
        """处理 Webhook 事件"""
        handler = self._webhook_handlers.get(event_type)
        if handler is None:
            logger.info("douyin_webhook_no_handler", event_type=event_type)
            return {"success": True, "message": f"no handler for {event_type}"}

        await handler(data)
        logger.info("douyin_webhook_handled", event_type=event_type)
        return {"success": True, "event_type": event_type}

    # -- Mock 数据生成 -----------------------------------------------

    def _mock_orders(self, shop_id: str, since: datetime) -> list[dict]:
        """生成 Mock 订单数据（含达人探店和直播间订单）"""
        now_ts = int(time.time())
        return [
            {
                "order_id": f"DY{now_ts}001",
                "day_seq": "001",
                "status": 1,
                "total_price": 4200,
                "order_source": 0,  # 普通订单
                "food_list": [
                    {
                        "food_name": "剁椒鱼头",
                        "quantity": 1,
                        "price": 3500,
                        "sku_id": "DY_FOOD_001",
                        "remark": "多放剁椒",
                    },
                    {
                        "food_name": "米饭",
                        "quantity": 1,
                        "price": 700,
                        "sku_id": "DY_FOOD_002",
                        "remark": "",
                    },
                ],
                "customer_phone": "139****9999",
                "delivery_address": "长沙市岳麓区测试路2号",
                "expected_delivery_time": str(now_ts + 2400),
                "remark": "不要香菜",
            },
            {
                "order_id": f"DY{now_ts}002",
                "day_seq": "002",
                "status": 1,
                "total_price": 6800,
                "order_source": 1,  # 达人探店订单
                "food_list": [
                    {
                        "food_name": "达人套餐A",
                        "quantity": 1,
                        "price": 6800,
                        "sku_id": "DY_FOOD_100",
                        "remark": "",
                    },
                ],
                "customer_phone": "137****7777",
                "delivery_address": "长沙市天心区达人路1号",
                "expected_delivery_time": str(now_ts + 3000),
                "remark": "达人探店",
            },
            {
                "order_id": f"DY{now_ts}003",
                "day_seq": "003",
                "status": 1,
                "total_price": 2900,
                "order_source": 2,  # 直播间订单
                "food_list": [
                    {
                        "food_name": "直播特惠套餐",
                        "quantity": 1,
                        "price": 2900,
                        "sku_id": "DY_FOOD_200",
                        "remark": "",
                    },
                ],
                "customer_phone": "136****6666",
                "delivery_address": "长沙市开福区直播路3号",
                "expected_delivery_time": str(now_ts + 2700),
                "remark": "直播间下单",
            },
        ]

    # -- DeliveryPlatformAdapter 接口实现 ----------------------------

    async def pull_orders(
        self,
        store_id: str,
        since: datetime,
    ) -> list[dict]:
        """拉取抖音外卖新订单（Mock）"""
        shop_id = self._get_shop_id(store_id)
        logger.info(
            "douyin_pull_orders",
            store_id=store_id,
            shop_id=shop_id,
            since=since.isoformat(),
        )

        # Mock：返回模拟订单
        raw_orders = self._mock_orders(shop_id, since)
        return [self._map_order(raw) for raw in raw_orders]

    async def accept_order(self, order_id: str) -> bool:
        """接受抖音外卖订单（Mock）"""
        logger.info("douyin_accept_order", order_id=order_id)
        return True

    async def reject_order(self, order_id: str, reason: str) -> bool:
        """拒绝抖音外卖订单（Mock）"""
        logger.info("douyin_reject_order", order_id=order_id, reason=reason)
        if not reason:
            raise DeliveryPlatformError(
                platform="douyin",
                code=400,
                message="拒单原因不能为空",
            )
        return True

    async def mark_ready(self, order_id: str) -> bool:
        """标记出餐完成（Mock）"""
        logger.info("douyin_mark_ready", order_id=order_id)
        return True

    async def sync_menu(
        self,
        store_id: str,
        dishes: list[dict],
    ) -> dict:
        """同步菜品到抖音外卖（Mock）"""
        shop_id = self._get_shop_id(store_id)
        logger.info(
            "douyin_sync_menu",
            store_id=store_id,
            shop_id=shop_id,
            dish_count=len(dishes),
        )

        synced = 0
        failed = 0
        errors: list[dict] = []

        for dish in dishes:
            try:
                dy_food = self._map_dish_to_douyin(dish)
                logger.debug("douyin_sync_dish", food=dy_food)
                synced += 1
            except (KeyError, ValueError, TypeError) as exc:
                failed += 1
                errors.append(
                    {
                        "dish_id": dish.get("id", "unknown"),
                        "error": str(exc),
                    }
                )
                logger.warning(
                    "douyin_sync_dish_failed",
                    dish_id=dish.get("id"),
                    error=str(exc),
                )

        return {"synced": synced, "failed": failed, "errors": errors}

    async def update_stock(
        self,
        store_id: str,
        dish_id: str,
        available: bool,
    ) -> bool:
        """更新菜品上下架状态（Mock）"""
        shop_id = self._get_shop_id(store_id)
        action = "上架" if available else "售罄"
        logger.info(
            "douyin_update_stock",
            shop_id=shop_id,
            dish_id=dish_id,
            action=action,
        )
        return True

    async def get_order_detail(self, order_id: str) -> dict:
        """获取抖音外卖订单详情（Mock）"""
        logger.info("douyin_get_order_detail", order_id=order_id)

        now_ts = int(time.time())
        mock_raw = {
            "order_id": order_id,
            "day_seq": "001",
            "status": 2,
            "total_price": 4200,
            "order_source": 0,
            "food_list": [
                {
                    "food_name": "剁椒鱼头",
                    "quantity": 1,
                    "price": 3500,
                    "sku_id": "DY_FOOD_001",
                    "remark": "多放剁椒",
                },
            ],
            "customer_phone": "139****9999",
            "delivery_address": "长沙市岳麓区测试路2号",
            "expected_delivery_time": str(now_ts + 2400),
            "remark": "不要香菜",
        }
        return self._map_order(mock_raw)

    async def close(self) -> None:
        """释放资源"""
        logger.info("douyin_delivery_adapter_closed")
