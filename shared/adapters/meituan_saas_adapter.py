"""美团餐饮 SAAS 平台适配器（top-level SoT）

CH-02.7a a3 起本文件是 MeituanSaasAdapter + MeituanReservationMixin +
MeituanOrderWebhookHandler 的 SoT — 原 shared/adapters/meituan-saas/src/
{adapter.py, reservation.py, order_webhook_handler.py} 三个文件并入。
HTTP 客户端 SoT（MeituanClient / MeituanAPIError / MeituanAuthError）
在 a2（PR #431）已搬到 shared/adapters/meituan_delivery_adapter.py，
本文件从那里 import 复用，不重复定义。

业务消费者：services/tx-trade/src/services/omni_channel_service.py（外卖渠道聚合）。
注册表入口：shared/adapters/base/src/registry.py POS_REGISTRY["meituan"]。
"""

import hashlib
import json as _json
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

import httpx
import structlog

from .meituan_delivery_adapter import MeituanAPIError, MeituanClient

logger = structlog.get_logger()

# 美团外卖订单状态码 → 内部状态
MEITUAN_STATUS_MAP: Dict[int, str] = {
    1: "pending",  # 待接单
    2: "confirmed",  # 已接单
    3: "preparing",  # 备餐中
    4: "delivering",  # 配送中
    5: "completed",  # 已完成
    6: "cancelled",  # 已取消
    8: "refunded",  # 已退款
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
        sorted_params = sorted(params.items())
        sign_str = self.app_secret
        for k, v in sorted_params:
            sign_str += f"{k}{v}"
        sign_str += self.app_secret
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
        detail_str = raw.get("detail", "[]")
        try:
            food_list = _json.loads(detail_str) if isinstance(detail_str, str) else detail_str
        except (_json.JSONDecodeError, TypeError):
            food_list = []

        items: List[Dict[str, Any]] = []
        for food in food_list:
            mt_food_code = str(food.get("app_food_code", ""))
            internal_id = get_internal_dish_id(mt_food_code)
            items.append(
                {
                    "name": food.get("food_name", ""),
                    "quantity": int(food.get("quantity", 1)),
                    "price_fen": int(food.get("price", 0)),
                    "sku_id": mt_food_code,
                    "notes": food.get("food_property", ""),
                    "internal_dish_id": internal_id,
                }
            )

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


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  MeituanReservationMixin — 预订操作（搬自 saas/reservation.py）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class MeituanReservationMixin:
    """美团预订操作混入类，用于扩展 MeituanSaasAdapter"""

    async def confirm_reservation(self, external_reservation_id: str) -> Dict[str, Any]:
        """确认预订"""
        params = {
            "reservation_id": external_reservation_id,
            "status": "confirmed",
        }
        result = await self._request("POST", "/api/reservation/confirm", data=params)
        logger.info("meituan_confirm_reservation", external_id=external_reservation_id)
        return result

    async def cancel_reservation(self, external_reservation_id: str, reason: str = "") -> Dict[str, Any]:
        """取消预订"""
        params = {
            "reservation_id": external_reservation_id,
            "status": "cancelled",
            "reason": reason,
        }
        result = await self._request("POST", "/api/reservation/cancel", data=params)
        logger.info("meituan_cancel_reservation", external_id=external_reservation_id)
        return result

    async def update_reservation_status(
        self,
        external_reservation_id: str,
        status: str,
    ) -> Dict[str, Any]:
        """更新预订状态（no_show/arrived/completed）"""
        params = {
            "reservation_id": external_reservation_id,
            "status": status,
        }
        result = await self._request("POST", "/api/reservation/update-status", data=params)
        logger.info("meituan_update_reservation_status", external_id=external_reservation_id, status=status)
        return result

    async def query_reservation(self, external_reservation_id: str) -> Dict[str, Any]:
        """查询预订详情"""
        params = {"reservation_id": external_reservation_id}
        result = await self._request("GET", "/api/reservation/detail", data=params)
        return result


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  MeituanOrderWebhookHandler — Webhook 事件处理（搬自 saas/order_webhook_handler.py）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# 美团核销状态码（order_verified 对应 status=5 已完成 / 自定义核销事件）
_VERIFIED_STATUSES = {5, 9}  # 5=已完成, 9=核销（部分平台用此值）


class MeituanOrderWebhookHandler:
    """处理美团外卖推送事件，核销时调用 PlatformBindingService

    事件类型：
      - order_paid      顾客下单并支付（通知接单，支持自动接单）
      - order_verified  到店核销（触发 Golden ID 绑定）
    """

    def __init__(
        self,
        binding_service: Any,
        tenant_id: uuid.UUID,
        store_id: Optional[str] = None,
    ) -> None:
        """
        Args:
            binding_service: PlatformBindingService 实例
            tenant_id: 租户 UUID
            store_id: 门店 ID（传入时启用自动接单功能）
        """
        self._svc = binding_service
        self._tenant_id = tenant_id
        self._store_id = store_id

    async def handle(
        self,
        payload: dict[str, Any],
        db: Any,  # AsyncSession
        current_hour_count: int = 0,
    ) -> dict[str, Any]:
        """统一事件入口

        Args:
            payload: 美团推送的原始 JSON 字典
            db: AsyncSession
            current_hour_count: 当前小时已自动接单数（由调用方统计后传入，用于上限判断）

        Returns:
            {"ok": True, "event_type": str, "data": dict}
        """
        event_type: str = payload.get("event_type", "")
        log = logger.bind(
            platform="meituan",
            event_type=event_type,
            order_id=payload.get("order_id"),
            tenant_id=str(self._tenant_id),
        )
        log.info("meituan_webhook_received")

        if event_type == "order_paid":
            data = await self._handle_order_paid(payload, db, log, current_hour_count)
        elif event_type == "order_verified":
            data = await self._handle_order_verified(payload, db, log)
        else:
            status = int(payload.get("status", 0))
            if status in _VERIFIED_STATUSES:
                data = await self._handle_order_verified(payload, db, log)
            else:
                log.info("meituan_webhook_ignored", reason="unknown_event_type")
                data = {"action": "ignored"}

        return {"ok": True, "event_type": event_type, "data": data}

    async def _handle_order_paid(
        self,
        payload: dict[str, Any],
        db: Any,
        log: Any,
        current_hour_count: int = 0,
    ) -> dict[str, Any]:
        """下单支付事件：判断是否自动接单，若是则调用美团接单 API。

        自动接单逻辑：
          1. 需要 store_id 已在构造时传入
          2. 调用 DeliveryOpsService.should_auto_accept() 判断（考虑开关+每小时上限）
          3. 若应自动接单，调用美团接单 API（携带当前出餐时间）
          4. 不影响手动接单流程 —— 若不满足自动接单条件，返回 action=pending_manual
        """
        order_id = str(payload.get("order_id", ""))
        store_id = self._store_id or str(payload.get("app_poi_code", ""))

        log.info(
            "meituan_order_paid",
            order_id=order_id,
            amount_fen=payload.get("order_total_price"),
            store_id=store_id,
        )

        if store_id:
            try:
                from services.tx_trade.src.services.delivery_ops_service import (  # noqa: PLC0415
                    DeliveryOpsService,
                )

                ops_svc = DeliveryOpsService()
                should_accept = await ops_svc.should_auto_accept(
                    store_id=store_id,
                    platform="meituan",
                    tenant_id=self._tenant_id,
                    current_hour_count=current_hour_count,
                    db=db,
                )

                if should_accept:
                    prep_time_min = await ops_svc.get_current_prep_time(
                        store_id=store_id,
                        platform="meituan",
                        tenant_id=self._tenant_id,
                        db=db,
                    )
                    accept_result = await self._call_meituan_accept_api(
                        order_id=order_id,
                        prep_time_min=prep_time_min,
                        log=log,
                    )
                    log.info(
                        "meituan_order_auto_accepted",
                        order_id=order_id,
                        prep_time_min=prep_time_min,
                    )
                    return {
                        "action": "auto_accepted",
                        "order_id": order_id,
                        "prep_time_min": prep_time_min,
                        "meituan_accept_result": accept_result,
                    }
                else:
                    log.info(
                        "meituan_order_pending_manual",
                        order_id=order_id,
                        reason="auto_accept_disabled_or_limit_reached",
                    )
            except ImportError:
                log.warning(
                    "meituan_auto_accept_unavailable",
                    reason="DeliveryOpsService import failed — fallback to manual",
                )
            except Exception as exc:  # noqa: BLE001 — 自动接单失败不阻断主流程
                log.error(
                    "meituan_auto_accept_error",
                    error=str(exc),
                    exc_info=True,
                )

        return {
            "action": "pending_manual",
            "order_id": order_id,
        }

    async def _call_meituan_accept_api(
        self,
        order_id: str,
        prep_time_min: int,
        log: Any,
    ) -> dict[str, Any]:
        """调用美团接单 API（通知美团已接单并设置出餐时间）。

        TODO: 配置真实 API Key 后替换此 mock 实现。
              美团接单接口文档：
              https://developer.meituan.com/openapi/docs/food/order/accept
        """
        log.info(
            "meituan_accept_api_mock",
            order_id=order_id,
            prep_time_min=prep_time_min,
            note="TODO: replace with real Meituan accept API call",
        )
        return {
            "mock": True,
            "order_id": order_id,
            "prep_time_min": prep_time_min,
            "status": "accepted",
        }

    async def _handle_order_verified(
        self,
        payload: dict[str, Any],
        db: Any,
        log: Any,
    ) -> dict[str, Any]:
        """核销事件：解析订单字段，调用 PlatformBindingService 绑定 Golden ID"""
        detail_raw = payload.get("detail", "[]")
        try:
            items = _json.loads(detail_raw) if isinstance(detail_raw, str) else detail_raw
        except (_json.JSONDecodeError, TypeError):
            items = []

        order_data = {
            "order_no": str(payload.get("order_id", payload.get("day_seq", ""))),
            "amount_fen": int(payload.get("order_total_price", 0)),
            "store_id": str(payload.get("app_poi_code", "")),
            "phone": str(payload.get("recipient_phone", "")) or None,
            "meituan_user_id": str(payload.get("meituan_user_id", "")) or None,
            "meituan_openid": str(payload.get("openid", "")) or None,
            "items": [
                {
                    "sku_id": str(item.get("app_food_code", "")),
                    "name": str(item.get("food_name", "")),
                    "quantity": int(item.get("quantity", 1)),
                    "price_fen": int(item.get("price", 0)),
                }
                for item in items
            ],
        }

        log.info(
            "meituan_order_verified",
            order_no=order_data["order_no"],
            amount_fen=order_data["amount_fen"],
            has_phone=bool(order_data["phone"]),
            has_meituan_id=bool(order_data["meituan_user_id"]),
        )

        result = await self._svc.bind_meituan_order(
            order_data=order_data,
            tenant_id=self._tenant_id,
            db=db,
        )
        return result
