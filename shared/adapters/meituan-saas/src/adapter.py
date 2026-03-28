"""
美团餐饮SAAS平台API适配器
提供订单管理、门店管理、商品管理、配送管理等功能。

v2: 注入 MeituanClient 替换 mock，真实 API 调用。
"""
from decimal import Decimal
from datetime import datetime
from typing import Dict, Any, Optional, List
import structlog
import httpx
import hashlib
import json

from .client import MeituanClient, MeituanAPIError

logger = structlog.get_logger()

# 美团外卖订单状态码 → 内部状态
MEITUAN_STATUS_MAP: Dict[int, str] = {
    1: "pending",       # 待接单
    2: "confirmed",     # 已接单
    3: "preparing",     # 备餐中
    4: "delivering",    # 配送中
    5: "completed",     # 已完成
    6: "cancelled",     # 已取消
    8: "refunded",      # 已退款
}

# 美团 dish_id → 屯象 dish_id 映射缓存（运行时从数据库/配置加载）
_dish_id_map: Dict[str, str] = {}


def set_dish_id_map(mapping: Dict[str, str]) -> None:
    """设置美团 dish_id → 屯象 dish_id 映射

    Args:
        mapping: {"MT_FOOD_001": "txos_dish_uuid_xxx", ...}
    """
    _dish_id_map.clear()
    _dish_id_map.update(mapping)


def get_internal_dish_id(meituan_dish_id: str) -> str:
    """查询屯象内部 dish_id，未映射返回空字符串"""
    return _dish_id_map.get(meituan_dish_id, "")


class MeituanSaasAdapter:
    """美团餐饮SAAS平台适配器

    注入 MeituanClient 实现真实 API 调用。
    """

    def __init__(self, config: Dict[str, Any], client: Optional[MeituanClient] = None):
        """
        初始化适配器

        Args:
            config: 配置字典，包含:
                - base_url: API基础URL
                - app_key: 应用Key
                - app_secret: 应用密钥
                - poi_id: 门店ID (Point of Interest)
                - timeout: 超时时间（秒）
                - retry_times: 重试次数
            client: 可选注入 MeituanClient（不传则根据 config 创建）
        """
        self.config = config
        self.base_url = config.get("base_url", "https://waimaiopen.meituan.com")
        self.app_key = config.get("app_key")
        self.app_secret = config.get("app_secret")
        self.poi_id = config.get("poi_id")
        self.timeout = config.get("timeout", 30)
        self.retry_times = config.get("retry_times", 3)

        if not self.app_key or not self.app_secret:
            raise ValueError("app_key和app_secret不能为空")

        # 注入或创建 MeituanClient
        if client is not None:
            self.api_client = client
        else:
            self.api_client = MeituanClient(
                app_id=self.app_key,
                app_secret=self.app_secret,
                store_id=self.poi_id or "",
                base_url=self.base_url + "/api/v2",
                timeout=self.timeout,
                max_retries=self.retry_times,
            )

        # 保留旧的 httpx client 用于兼容已有 _request 调用
        self.client = self.api_client._http

        logger.info("美团SAAS适配器初始化", base_url=self.base_url, poi_id=self.poi_id)

    def _generate_sign(self, params: Dict[str, Any]) -> str:
        """
        生成API签名（美团签名算法）

        Args:
            params: 请求参数

        Returns:
            签名字符串
        """
        # 按key排序
        sorted_params = sorted(params.items())
        # 拼接字符串
        sign_str = self.app_secret
        for k, v in sorted_params:
            sign_str += f"{k}{v}"
        sign_str += self.app_secret
        # MD5加密
        return hashlib.md5(sign_str.encode()).hexdigest().lower()

    def authenticate(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        认证方法，添加认证参数

        Args:
            params: 原始请求参数

        Returns:
            包含认证信息的参数字典
        """
        timestamp = str(int(datetime.now().timestamp()))
        auth_params = {
            "app_key": self.app_key,
            "timestamp": timestamp,
            **params,
        }
        # 生成签名
        auth_params["sign"] = self._generate_sign(auth_params)
        return auth_params

    async def _request(
        self,
        method: str,
        endpoint: str,
        data: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        发送HTTP请求（保留用于非外卖API的兼容调用）

        Args:
            method: HTTP方法 (GET/POST)
            endpoint: API端点
            data: 请求数据

        Returns:
            API响应数据

        Raises:
            MeituanAPIError: API 业务错误
            RuntimeError: 重试耗尽
        """
        for attempt in range(self.retry_times):
            try:
                request_data = data or {}
                # 添加认证参数
                auth_data = self.authenticate(request_data)

                headers = {"Content-Type": "application/x-www-form-urlencoded"}

                if method.upper() == "GET":
                    response = await self.client.get(endpoint, params=auth_data, headers=headers)
                elif method.upper() == "POST":
                    response = await self.client.post(endpoint, data=auth_data, headers=headers)
                else:
                    raise ValueError(f"不支持的HTTP方法: {method}")

                response.raise_for_status()
                result = response.json()
                self.handle_error(result)
                return result

            except httpx.HTTPStatusError as e:
                logger.error(
                    "HTTP请求失败",
                    endpoint=endpoint,
                    status_code=e.response.status_code,
                    attempt=attempt + 1,
                )
                if attempt == self.retry_times - 1:
                    raise MeituanAPIError(
                        code=e.response.status_code,
                        message=f"HTTP请求失败: {e.response.status_code}",
                    ) from e

            except (httpx.ConnectError, httpx.TimeoutException, httpx.DecodingError, ValueError) as e:
                logger.error(
                    "请求异常",
                    endpoint=endpoint,
                    error=str(e),
                    attempt=attempt + 1,
                )
                if attempt == self.retry_times - 1:
                    raise

        raise RuntimeError("请求失败，已达到最大重试次数")

    def handle_error(self, response: Dict[str, Any]) -> None:
        """
        处理业务错误

        Args:
            response: API响应数据

        Raises:
            MeituanAPIError: 业务错误
        """
        code = response.get("code")
        if code != "ok" and code != 0:
            message = response.get("message", response.get("msg", "未知错误"))
            raise MeituanAPIError(
                code=int(code) if isinstance(code, (int, str)) and str(code).lstrip("-").isdigit() else -1,
                message=message,
            )

    # ==================== 订单管理接口（真实API） ====================

    async def query_order(
        self,
        order_id: Optional[str] = None,
        day_seq: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        查询订单详情（调用真实美团API）

        Args:
            order_id: 订单ID
            day_seq: 日流水号

        Returns:
            订单详情
        """
        if not order_id and not day_seq:
            raise ValueError("order_id和day_seq至少提供一个")

        logger.info("查询订单", order_id=order_id, day_seq=day_seq)
        return await self.api_client.query_order(order_id or day_seq or "")

    async def confirm_order(
        self,
        order_id: str,
    ) -> Dict[str, Any]:
        """
        确认订单（调用真实美团API）

        Args:
            order_id: 美团订单ID

        Returns:
            确认结果
        """
        logger.info("确认订单", order_id=order_id)
        return await self.api_client.confirm_order(order_id)

    async def cancel_order(
        self,
        order_id: str,
        reason_code: int,
        reason: str,
    ) -> Dict[str, Any]:
        """
        取消订单（调用真实美团API）

        Args:
            order_id: 美团订单ID
            reason_code: 取消原因代码
            reason: 取消原因描述

        Returns:
            取消结果
        """
        logger.info("取消订单", order_id=order_id, reason=reason)
        return await self.api_client.cancel_order(order_id, reason_code, reason)

    async def refund_order(
        self,
        order_id: str,
        reason: str,
    ) -> Dict[str, Any]:
        """
        订单退款

        Args:
            order_id: 订单ID
            reason: 退款原因

        Returns:
            退款结果
        """
        data = {
            "order_id": order_id,
            "reason": reason,
        }

        logger.info("订单退款", order_id=order_id, reason=reason)

        response = await self._request("POST", "/api/order/refund", data=data)
        return response.get("data", {})

    def receive_order(self, raw: Dict[str, Any]) -> Dict[str, Any]:
        """处理美团推送的原始订单 JSON，映射为标准字段

        美团推送字段参考:
          order_id, day_seq, status, order_total_price(分),
          detail([{app_food_code, food_name, quantity, price, food_property}]),
          recipient_phone, recipient_address, delivery_time, caution

        Returns:
            标准化订单字典，可直接传给 DeliveryPlatformAdapter.receive_order()
        """
        import json as _json

        detail_str = raw.get("detail", "[]")
        try:
            food_list = _json.loads(detail_str) if isinstance(detail_str, str) else detail_str
        except (_json.JSONDecodeError, TypeError):
            food_list = []

        items: List[Dict[str, Any]] = []
        for food in food_list:
            mt_food_code = str(food.get("app_food_code", ""))
            internal_id = get_internal_dish_id(mt_food_code)
            items.append({
                "name": food.get("food_name", ""),
                "quantity": int(food.get("quantity", 1)),
                "price_fen": int(food.get("price", 0)),
                "sku_id": mt_food_code,
                "notes": food.get("food_property", ""),
                "internal_dish_id": internal_id,
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

    # ==================== 商品管理接口 ====================

    async def query_food(
        self,
        food_id: Optional[str] = None,
        category_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        查询商品

        Args:
            food_id: 商品ID
            category_id: 分类ID

        Returns:
            商品列表
        """
        data = {"app_poi_code": self.poi_id}
        if food_id:
            data["food_id"] = food_id
        if category_id:
            data["category_id"] = category_id

        logger.info("查询商品", data=data)

        response = await self._request("GET", "/api/food/query", data=data)
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
        data = {
            "app_poi_code": self.poi_id,
            "food_id": food_id,
            "stock": stock,
        }

        logger.info("更新商品库存", food_id=food_id, stock=stock)

        response = await self._request("POST", "/api/food/updateStock", data=data)
        return response.get("data", {})

    async def update_food_price(
        self,
        food_id: str,
        price: int,
    ) -> Dict[str, Any]:
        """
        更新商品价格

        Args:
            food_id: 商品ID
            price: 价格（分）

        Returns:
            更新结果
        """
        data = {
            "app_poi_code": self.poi_id,
            "food_id": food_id,
            "price": price,
        }

        logger.info("更新商品价格", food_id=food_id, price=price)

        response = await self._request("POST", "/api/food/updatePrice", data=data)
        return response.get("data", {})

    async def sold_out_food(
        self,
        food_id: str,
    ) -> Dict[str, Any]:
        """
        商品售罄

        Args:
            food_id: 商品ID

        Returns:
            操作结果
        """
        data = {
            "app_poi_code": self.poi_id,
            "food_id": food_id,
        }

        logger.info("商品售罄", food_id=food_id)

        response = await self._request("POST", "/api/food/soldout", data=data)
        return response.get("data", {})

    async def on_sale_food(
        self,
        food_id: str,
    ) -> Dict[str, Any]:
        """
        商品上架

        Args:
            food_id: 商品ID

        Returns:
            操作结果
        """
        data = {
            "app_poi_code": self.poi_id,
            "food_id": food_id,
        }

        logger.info("商品上架", food_id=food_id)

        response = await self._request("POST", "/api/food/onsale", data=data)
        return response.get("data", {})

    # ==================== 门店管理接口 ====================

    async def query_poi_info(self) -> Dict[str, Any]:
        """
        查询门店信息

        Returns:
            门店信息
        """
        data = {"app_poi_code": self.poi_id}

        logger.info("查询门店信息", poi_id=self.poi_id)

        response = await self._request("GET", "/api/poi/query", data=data)
        return response.get("data", {})

    async def update_poi_status(
        self,
        is_online: int,
    ) -> Dict[str, Any]:
        """
        更新门店营业状态

        Args:
            is_online: 营业状态 (1-营业中 0-休息中)

        Returns:
            更新结果
        """
        data = {
            "app_poi_code": self.poi_id,
            "is_online": is_online,
        }

        logger.info("更新门店状态", poi_id=self.poi_id, is_online=is_online)

        response = await self._request("POST", "/api/poi/updateStatus", data=data)
        return response.get("data", {})

    # ==================== 配送管理接口 ====================

    async def query_logistics(
        self,
        order_id: str,
    ) -> Dict[str, Any]:
        """
        查询配送信息

        Args:
            order_id: 订单ID

        Returns:
            配送信息
        """
        data = {"order_id": order_id}

        logger.info("查询配送信息", order_id=order_id)

        response = await self._request("GET", "/api/logistics/query", data=data)
        return response.get("data", {})

    async def close(self) -> None:
        """关闭适配器，释放资源"""
        logger.info("关闭美团SAAS适配器")
        await self.api_client.close()

    # ==================== 标准化数据总线接口 ====================

    def to_order(self, raw: Dict[str, Any], store_id: str, brand_id: str) -> Any:
        """
        将美团SAAS原始订单字段映射到标准 OrderSchema

        美团SAAS订单字段参考：
          order_id, day_seq, create_time, status, total_price,
          food_list (food_id, food_name, count, price),
          app_poi_code, operator_id
        """
        import sys
        import os as _os
        _src_dir = _os.path.dirname(__file__)
        _repo_root = _os.path.abspath(_os.path.join(_src_dir, "../../../.."))
        _gateway_src = _os.path.join(_repo_root, "apps", "api-gateway", "src")
        if _gateway_src not in sys.path:
            sys.path.insert(0, _gateway_src)

        from schemas.restaurant_standard_schema import (
            OrderSchema, OrderStatus, OrderType, OrderItemSchema, DishCategory
        )

        # 状态映射（美团：1=待接单, 2=已接单, 3=配送中, 4=已完成, 5=已取消, 8=退款）
        _STATUS_MAP = {
            1: OrderStatus.PENDING,
            2: OrderStatus.CONFIRMED,
            3: OrderStatus.CONFIRMED,
            4: OrderStatus.COMPLETED,
            5: OrderStatus.CANCELLED,
            8: OrderStatus.CANCELLED,
        }
        order_status = _STATUS_MAP.get(int(raw.get("status", 1)), OrderStatus.PENDING)

        # 订单项映射
        items = []
        for idx, item in enumerate(raw.get("food_list", raw.get("detail_items", [])), start=1):
            unit_price = Decimal(str(item.get("price", 0))) / 100  # 分 → 元
            qty = int(item.get("count", item.get("quantity", 1)))
            items.append(OrderItemSchema(
                item_id=str(item.get("cart_id", f"{raw.get('order_id', '')}_{idx}")),
                dish_id=str(item.get("food_id", item.get("app_food_code", ""))),
                dish_name=str(item.get("food_name", "")),
                dish_category=DishCategory.MAIN_COURSE,
                quantity=qty,
                unit_price=unit_price,
                subtotal=unit_price * qty,
                special_requirements=item.get("remark"),
            ))

        total = Decimal(str(raw.get("total_price", raw.get("order_total_price", 0)))) / 100
        discount = Decimal(str(raw.get("discount_price", raw.get("poi_discount", 0)))) / 100
        subtotal = total + discount

        create_time_raw = raw.get("create_time", raw.get("order_create_time", ""))
        try:
            # 美团时间戳可能是 unix epoch（秒）
            if isinstance(create_time_raw, (int, float)) and create_time_raw > 1e9:
                created_at = datetime.fromtimestamp(create_time_raw)
            else:
                created_at = datetime.fromisoformat(str(create_time_raw).replace("T", " "))
        except (ValueError, TypeError, OSError):
            created_at = datetime.utcnow()

        return OrderSchema(
            order_id=str(raw.get("order_id", raw.get("mt_order_id", ""))),
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
            notes=raw.get("caution"),
        )

    def to_staff_action(self, raw: Dict[str, Any], store_id: str, brand_id: str) -> Any:
        """
        将美团SAAS原始操作数据映射为标准 StaffAction

        原始字段参考（后台操作日志）：
          action_type, operator_id, amount, reason, approved_by, action_time
        """
        import sys
        import os as _os
        _src_dir = _os.path.dirname(__file__)
        _repo_root = _os.path.abspath(_os.path.join(_src_dir, "../../../.."))
        _gateway_src = _os.path.join(_repo_root, "apps", "api-gateway", "src")
        if _gateway_src not in sys.path:
            sys.path.insert(0, _gateway_src)

        from schemas.restaurant_standard_schema import StaffAction

        action_time_raw = raw.get("action_time", raw.get("create_time", ""))
        try:
            if isinstance(action_time_raw, (int, float)) and action_time_raw > 1e9:
                created_at = datetime.fromtimestamp(action_time_raw)
            else:
                created_at = datetime.fromisoformat(str(action_time_raw).replace("T", " "))
        except (ValueError, TypeError, OSError):
            created_at = datetime.utcnow()

        amount_raw = raw.get("amount", raw.get("discount_price"))
        amount = Decimal(str(amount_raw)) / 100 if amount_raw is not None else None

        return StaffAction(
            action_type=str(raw.get("action_type", raw.get("type", "unknown"))),
            brand_id=brand_id,
            store_id=store_id,
            operator_id=str(raw.get("operator_id", raw.get("user_id", ""))),
            amount=amount,
            reason=raw.get("reason"),
            approved_by=raw.get("approved_by"),
            created_at=created_at,
        )
