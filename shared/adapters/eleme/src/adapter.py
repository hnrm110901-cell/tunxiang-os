"""
饿了么开放平台API适配器
提供订单管理、商品管理、门店管理、配送管理等功能

底层 HTTP 调用委托给 ElemeClient，本类只做业务编排和数据映射。

饿了么开放平台文档: https://open.shop.ele.me
"""

from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional

import structlog

from .client import ElemeClient

logger = structlog.get_logger()


class ElemeAdapter:
    """饿了么开放平台适配器（委托 ElemeClient 处理认证/签名/HTTP）"""

    def __init__(self, config: Dict[str, Any]):
        """
        初始化适配器

        Args:
            config: 配置字典，包含:
                - app_key: 应用Key
                - app_secret: 应用密钥
                - store_id: 门店ID（可选）
                - sandbox: 是否沙箱环境 (默认False)
                - timeout: 超时时间（秒）
                - retry_times: 重试次数
        """
        self.config = config
        self.client = ElemeClient(
            app_key=config.get("app_key"),
            app_secret=config.get("app_secret"),
            store_id=config.get("store_id"),
            sandbox=config.get("sandbox", False),
            timeout=config.get("timeout", 30),
            retry_times=config.get("retry_times", 3),
        )

        logger.info(
            "饿了么适配器初始化",
            sandbox=config.get("sandbox", False),
        )

    # ==================== 订单管理接口 ====================

    async def query_orders(
        self,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        status: Optional[int] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> Dict[str, Any]:
        """
        查询订单列表

        Args:
            start_time: 开始时间 (ISO8601)
            end_time: 结束时间 (ISO8601)
            status: 订单状态筛选
            page: 页码
            page_size: 每页数量

        Returns:
            订单列表及分页信息
        """
        data: Dict[str, Any] = {
            "page": page,
            "page_size": page_size,
        }
        if start_time:
            data["start_time"] = start_time
        if end_time:
            data["end_time"] = end_time
        if status is not None:
            data["status"] = status

        logger.info("饿了么查询订单列表", page=page, page_size=page_size)
        response = await self.client.request("GET", "/orders", data=data)
        return response.get("data", {})

    async def get_order_detail(self, order_id: str) -> Dict[str, Any]:
        """
        获取订单详情

        Args:
            order_id: 饿了么订单ID

        Returns:
            订单详情
        """
        logger.info("饿了么查询订单详情", order_id=order_id)
        return await self.client.query_order(order_id)

    async def confirm_order(self, order_id: str) -> Dict[str, Any]:
        """
        确认接单

        Args:
            order_id: 饿了么订单ID

        Returns:
            确认结果
        """
        logger.info("饿了么确认订单", order_id=order_id)
        return await self.client.confirm_order(order_id)

    async def cancel_order(
        self,
        order_id: str,
        reason_code: int,
        reason: str,
    ) -> Dict[str, Any]:
        """
        取消订单

        Args:
            order_id: 饿了么订单ID
            reason_code: 取消原因代码
            reason: 取消原因描述

        Returns:
            取消结果
        """
        logger.info("饿了么取消订单", order_id=order_id, reason=reason)
        return await self.client.cancel_order(order_id, reason_code, reason)

    async def query_refund(self, order_id: str) -> Dict[str, Any]:
        """
        查询退款信息

        Args:
            order_id: 饿了么订单ID

        Returns:
            退款详情
        """
        logger.info("饿了么查询退款", order_id=order_id)
        response = await self.client.request("GET", "/order/refund", data={"order_id": order_id})
        return response.get("data", {})

    # ==================== 商品管理接口 ====================

    async def query_foods(
        self,
        category_id: Optional[str] = None,
        page: int = 1,
        page_size: int = 50,
    ) -> List[Dict[str, Any]]:
        """
        查询商品列表

        Args:
            category_id: 分类ID（可选筛选）
            page: 页码
            page_size: 每页数量

        Returns:
            商品列表
        """
        data: Dict[str, Any] = {"page": page, "page_size": page_size}
        if category_id:
            data["category_id"] = category_id

        logger.info("饿了么查询商品", page=page)
        response = await self.client.request("GET", "/foods", data=data)
        return response.get("data", [])

    async def update_food_stock(
        self,
        food_id: str,
        stock: int,
    ) -> Dict[str, Any]:
        """
        更新商品库存

        Args:
            food_id: 商品ID
            stock: 库存数量

        Returns:
            更新结果
        """
        logger.info("饿了么更新库存", food_id=food_id, stock=stock)
        return await self.client.update_food(food_id, {"stock": stock})

    async def sold_out_food(self, food_id: str) -> Dict[str, Any]:
        """
        商品售罄（下架）

        Args:
            food_id: 商品ID

        Returns:
            操作结果
        """
        logger.info("饿了么商品售罄", food_id=food_id)
        response = await self.client.request("POST", "/food/soldout", data={"food_id": food_id})
        return response.get("data", {})

    async def on_sale_food(self, food_id: str) -> Dict[str, Any]:
        """
        商品上架

        Args:
            food_id: 商品ID

        Returns:
            操作结果
        """
        logger.info("饿了么商品上架", food_id=food_id)
        response = await self.client.request("POST", "/food/onsale", data={"food_id": food_id})
        return response.get("data", {})

    # ==================== 门店管理接口 ====================

    async def get_shop_info(self, shop_id: Optional[str] = None) -> Dict[str, Any]:
        """
        查询门店信息

        Args:
            shop_id: 门店ID（可选，默认当前绑定门店）

        Returns:
            门店信息
        """
        data: Dict[str, Any] = {}
        if shop_id:
            data["shop_id"] = shop_id

        logger.info("饿了么查询门店信息", shop_id=shop_id)
        response = await self.client.request("GET", "/shop/info", data=data)
        return response.get("data", {})

    async def update_shop_status(
        self,
        status: int,
        shop_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        更新门店营业状态

        Args:
            status: 营业状态 (1=营业中, 0=休息中)
            shop_id: 门店ID（可选）

        Returns:
            更新结果
        """
        data: Dict[str, Any] = {"status": status}
        if shop_id:
            data["shop_id"] = shop_id

        logger.info("饿了么更新门店状态", status=status, shop_id=shop_id)
        response = await self.client.request("POST", "/shop/status", data=data)
        return response.get("data", {})

    # ==================== 配送管理接口 ====================

    async def query_delivery_status(self, order_id: str) -> Dict[str, Any]:
        """
        查询配送状态

        Args:
            order_id: 订单ID

        Returns:
            配送信息（骑手位置、状态、预计到达时间等）
        """
        logger.info("饿了么查询配送状态", order_id=order_id)
        return await self.client.query_delivery_status(order_id)

    # ==================== 标准化数据总线接口 ====================

    def to_order(self, raw: Dict[str, Any], store_id: str, brand_id: str) -> Any:
        """
        将饿了么原始订单字段映射到标准 OrderSchema

        饿了么订单字段参考：
          order_id, eleme_order_id, create_time, status, total_price,
          food_list (food_id, food_name, quantity, price),
          shop_id, user_id
        """
        import os as _os
        import sys

        _src_dir = _os.path.dirname(__file__)
        _repo_root = _os.path.abspath(_os.path.join(_src_dir, "../../../.."))
        _gateway_src = _os.path.join(_repo_root, "apps", "api-gateway", "src")
        if _gateway_src not in sys.path:
            sys.path.insert(0, _gateway_src)

        from schemas.restaurant_standard_schema import (
            DishCategory,
            OrderItemSchema,
            OrderSchema,
            OrderStatus,
            OrderType,
        )

        # 饿了么订单状态映射
        # 0=待付款, 1=待接单, 2=已接单, 3=配送中, 4=已完成, 5=已取消, 9=退款中
        _STATUS_MAP = {
            0: OrderStatus.PENDING,
            1: OrderStatus.PENDING,
            2: OrderStatus.CONFIRMED,
            3: OrderStatus.CONFIRMED,
            4: OrderStatus.COMPLETED,
            5: OrderStatus.CANCELLED,
            9: OrderStatus.CANCELLED,
        }
        order_status = _STATUS_MAP.get(int(raw.get("status", 1)), OrderStatus.PENDING)

        # 订单项映射
        items = []
        food_list = raw.get("food_list", raw.get("items", []))
        for idx, item in enumerate(food_list, start=1):
            unit_price = Decimal(str(item.get("price", 0))) / 100  # 分 -> 元
            qty = int(item.get("quantity", item.get("count", 1)))
            items.append(
                OrderItemSchema(
                    item_id=str(item.get("item_id", f"{raw.get('order_id', '')}_{idx}")),
                    dish_id=str(item.get("food_id", item.get("sku_id", ""))),
                    dish_name=str(item.get("food_name", item.get("name", ""))),
                    dish_category=DishCategory.MAIN_COURSE,
                    quantity=qty,
                    unit_price=unit_price,
                    subtotal=unit_price * qty,
                    special_requirements=item.get("remark"),
                )
            )

        total = Decimal(str(raw.get("total_price", raw.get("order_amount", 0)))) / 100
        discount = Decimal(str(raw.get("discount_price", raw.get("shop_discount", 0)))) / 100
        subtotal = total + discount

        create_time_raw = raw.get("create_time", raw.get("created_at", ""))
        try:
            if isinstance(create_time_raw, (int, float)) and create_time_raw > 1e9:
                created_at = datetime.fromtimestamp(create_time_raw)
            else:
                created_at = datetime.fromisoformat(str(create_time_raw).replace("T", " "))
        except (ValueError, TypeError, OSError):
            created_at = datetime.utcnow()

        return OrderSchema(
            order_id=str(raw.get("order_id", raw.get("eleme_order_id", ""))),
            order_number=str(raw.get("day_seq", raw.get("order_id", ""))),
            order_type=OrderType.TAKEOUT,
            order_status=order_status,
            store_id=store_id,
            brand_id=brand_id,
            table_number=None,
            customer_id=str(raw.get("user_id", "")) or None,
            items=items,
            subtotal=subtotal,
            discount=discount,
            service_charge=Decimal("0"),
            total=total,
            created_at=created_at,
            waiter_id=None,
            notes=raw.get("remark", raw.get("caution")),
        )

    async def close(self) -> None:
        """关闭适配器，释放资源"""
        logger.info("关闭饿了么适配器")
        await self.client.close()
