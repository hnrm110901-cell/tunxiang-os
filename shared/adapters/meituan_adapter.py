"""
美团外卖平台适配器（DeliveryPlatformAdapter 实现）

当前阶段：Mock 模式，不调用真实美团 API。
签名算法（MD5）已实现占位，接入真实 API 时切换 _mock → _request 即可。

配置（环境变量）：
  MEITUAN_DELIVERY_APP_KEY
  MEITUAN_DELIVERY_APP_SECRET
  MEITUAN_DELIVERY_STORE_MAP   JSON 格式: {"txos_store_001": "mt_poi_888"}
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

import structlog

from .delivery_platform_base import (
    DeliveryPlatformAdapter,
    DeliveryPlatformError,
    DeliveryPlatformSignError,
    DeliveryPlatformTimeoutError,
)

logger = structlog.get_logger()

# ── 美团订单状态 → 屯象统一状态 ──────────────────────────
MEITUAN_STATUS_MAP: Dict[int, str] = {
    1: "pending",       # 用户已下单
    2: "confirmed",     # 商家已接单
    3: "preparing",     # 备餐中
    4: "delivering",    # 骑手已取餐
    5: "completed",     # 已完成
    6: "cancelled",     # 已取消
    8: "refunded",      # 已退款
}


def _load_store_mapping() -> Dict[str, str]:
    """从环境变量加载 屯象门店ID → 美团POI 映射"""
    raw = os.environ.get("MEITUAN_DELIVERY_STORE_MAP", "{}")
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        logger.warning("meituan_store_map_parse_failed", raw=raw)
        return {}


class MeituanDeliveryAdapter(DeliveryPlatformAdapter):
    """美团外卖平台适配器

    实现 DeliveryPlatformAdapter 全部方法。
    当前为 Mock 模式，所有 API 调用返回模拟数据。
    """

    def __init__(
        self,
        app_key: Optional[str] = None,
        app_secret: Optional[str] = None,
        store_map: Optional[Dict[str, str]] = None,
        base_url: str = "https://waimaiopen.meituan.com/api/v2",
        timeout: int = 30,
    ):
        self.app_key = app_key or os.environ.get("MEITUAN_DELIVERY_APP_KEY", "")
        self.app_secret = app_secret or os.environ.get("MEITUAN_DELIVERY_APP_SECRET", "")
        self.store_map = store_map or _load_store_mapping()
        self.base_url = base_url
        self.timeout = timeout

        logger.info(
            "meituan_delivery_adapter_init",
            store_count=len(self.store_map),
            mock_mode=True,
        )

    # ── 签名算法（美团 MD5） ─────────────────────────────────

    def _generate_sign(self, params: Dict[str, Any]) -> str:
        """美团 MD5 签名

        算法：
          1. 参数按 key 字典序排列
          2. 拼接 app_secret + key1value1key2value2... + app_secret
          3. MD5 取小写 hex
        """
        sorted_params = sorted(params.items())
        sign_str = self.app_secret
        for k, v in sorted_params:
            sign_str += f"{k}{v}"
        sign_str += self.app_secret
        return hashlib.md5(sign_str.encode("utf-8")).hexdigest().lower()

    def _build_auth_params(self, biz_params: Dict[str, Any]) -> Dict[str, Any]:
        """构造带签名的请求参数"""
        auth_params = {
            "app_key": self.app_key,
            "timestamp": str(int(time.time())),
            **biz_params,
        }
        auth_params["sign"] = self._generate_sign(auth_params)
        return auth_params

    # ── 内部工具 ─────────────────────────────────────────────

    def _get_poi_id(self, store_id: str) -> str:
        """屯象门店ID → 美团POI ID"""
        poi_id = self.store_map.get(store_id, "")
        if not poi_id:
            logger.warning("meituan_store_not_mapped", store_id=store_id)
        return poi_id

    def _map_order(self, raw: Dict[str, Any]) -> dict:
        """美团原始订单 → 屯象统一订单格式"""
        detail_str = raw.get("detail", "[]")
        try:
            food_list = json.loads(detail_str) if isinstance(detail_str, str) else detail_str
        except (json.JSONDecodeError, TypeError):
            food_list = []

        items: List[Dict[str, Any]] = []
        for food in food_list:
            items.append({
                "name": food.get("food_name", ""),
                "quantity": int(food.get("quantity", 1)),
                "price_fen": int(food.get("price", 0)),
                "sku_id": str(food.get("app_food_code", "")),
                "notes": food.get("food_property", ""),
                "internal_dish_id": "",  # 需要业务层映射
            })

        status_code = int(raw.get("status", 1))
        return {
            "platform": "meituan",
            "platform_order_id": str(raw.get("order_id", "")),
            "day_seq": str(raw.get("day_seq", "")),
            "status": MEITUAN_STATUS_MAP.get(status_code, "pending"),
            "items": items,
            "total_fen": int(raw.get("order_total_price", 0)),
            "customer_phone": str(raw.get("recipient_phone", "")),
            "delivery_address": str(raw.get("recipient_address", "")),
            "expected_time": str(raw.get("delivery_time", "")),
            "notes": str(raw.get("caution", "")),
        }

    def _map_dish_to_meituan(self, dish: dict) -> dict:
        """屯象统一菜品格式 → 美团商品格式"""
        return {
            "app_food_code": dish.get("id", dish.get("external_id", "")),
            "food_name": dish.get("name", ""),
            "category_name": dish.get("category_name", "默认分类"),
            "price": int(float(dish.get("price", 0)) * 100),  # 元 → 分
            "unit": dish.get("unit", "份"),
            "description": dish.get("specification", ""),
            "is_sold_out": 0 if dish.get("is_available", True) else 1,
        }

    # ── Mock 数据生成 ────────────────────────────────────────

    def _mock_orders(self, poi_id: str, since: datetime) -> list[dict]:
        """生成 Mock 订单数据"""
        now_ts = int(time.time())
        return [
            {
                "order_id": f"MT{now_ts}001",
                "day_seq": "001",
                "status": 1,
                "order_total_price": 3500,
                "detail": json.dumps([
                    {
                        "food_name": "宫保鸡丁",
                        "quantity": 1,
                        "price": 2800,
                        "app_food_code": "FOOD_001",
                        "food_property": "微辣",
                    },
                    {
                        "food_name": "米饭",
                        "quantity": 1,
                        "price": 700,
                        "app_food_code": "FOOD_002",
                        "food_property": "",
                    },
                ]),
                "recipient_phone": "138****8888",
                "recipient_address": "长沙市天心区测试路1号",
                "delivery_time": str(now_ts + 2400),
                "caution": "少放辣",
            }
        ]

    # ── DeliveryPlatformAdapter 接口实现 ─────────────────────

    async def pull_orders(
        self, store_id: str, since: datetime
    ) -> list[dict]:
        """拉取美团新订单（Mock）"""
        poi_id = self._get_poi_id(store_id)
        logger.info(
            "meituan_pull_orders",
            store_id=store_id,
            poi_id=poi_id,
            since=since.isoformat(),
        )

        # Mock：返回模拟订单
        raw_orders = self._mock_orders(poi_id, since)
        return [self._map_order(raw) for raw in raw_orders]

    async def accept_order(self, order_id: str) -> bool:
        """接受美团订单（Mock）"""
        logger.info("meituan_accept_order", order_id=order_id)
        # Mock：直接返回成功
        return True

    async def reject_order(self, order_id: str, reason: str) -> bool:
        """拒绝美团订单（Mock）"""
        logger.info("meituan_reject_order", order_id=order_id, reason=reason)
        if not reason:
            raise DeliveryPlatformError(
                platform="meituan",
                code=400,
                message="拒单原因不能为空",
            )
        # Mock：直接返回成功
        return True

    async def mark_ready(self, order_id: str) -> bool:
        """标记出餐完成（Mock）"""
        logger.info("meituan_mark_ready", order_id=order_id)
        # Mock：直接返回成功
        return True

    async def sync_menu(
        self, store_id: str, dishes: list[dict]
    ) -> dict:
        """同步菜品到美团（Mock）

        将屯象统一菜品格式转换为美团商品格式后上传。
        """
        poi_id = self._get_poi_id(store_id)
        logger.info(
            "meituan_sync_menu",
            store_id=store_id,
            poi_id=poi_id,
            dish_count=len(dishes),
        )

        synced = 0
        failed = 0
        errors: list[dict] = []

        for dish in dishes:
            try:
                mt_food = self._map_dish_to_meituan(dish)
                # Mock：假设全部成功
                logger.debug("meituan_sync_dish", food=mt_food)
                synced += 1
            except (KeyError, ValueError, TypeError) as exc:
                failed += 1
                errors.append({
                    "dish_id": dish.get("id", "unknown"),
                    "error": str(exc),
                })
                logger.warning(
                    "meituan_sync_dish_failed",
                    dish_id=dish.get("id"),
                    error=str(exc),
                )

        return {"synced": synced, "failed": failed, "errors": errors}

    async def update_stock(
        self, store_id: str, dish_id: str, available: bool
    ) -> bool:
        """更新菜品上下架状态（Mock）"""
        poi_id = self._get_poi_id(store_id)
        action = "上架" if available else "售罄"
        logger.info(
            "meituan_update_stock",
            poi_id=poi_id,
            dish_id=dish_id,
            action=action,
        )
        # Mock：直接返回成功
        return True

    async def get_order_detail(self, order_id: str) -> dict:
        """获取美团订单详情（Mock）"""
        logger.info("meituan_get_order_detail", order_id=order_id)

        now_ts = int(time.time())
        mock_raw = {
            "order_id": order_id,
            "day_seq": "001",
            "status": 2,
            "order_total_price": 3500,
            "detail": json.dumps([
                {
                    "food_name": "宫保鸡丁",
                    "quantity": 1,
                    "price": 2800,
                    "app_food_code": "FOOD_001",
                    "food_property": "微辣",
                },
            ]),
            "recipient_phone": "138****8888",
            "recipient_address": "长沙市天心区测试路1号",
            "delivery_time": str(now_ts + 2400),
            "caution": "少放辣",
        }
        return self._map_order(mock_raw)

    async def close(self) -> None:
        """释放资源"""
        logger.info("meituan_delivery_adapter_closed")
