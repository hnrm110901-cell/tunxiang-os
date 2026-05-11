"""
美团外卖平台适配器（DeliveryPlatformAdapter 实现）

CH-02.7a a2 起本文件是美团 HTTP 客户端（MeituanClient）的唯一 SoT — 真接入路径
（签名/OAuth2/底层请求）从原 shared/adapters/meituan-saas/src/client.py 并入。
a3 已删除 saas/src/client.py 并把 saas/adapter.py 切到本文件 import。

配置（环境变量）：
  MEITUAN_DELIVERY_APP_KEY
  MEITUAN_DELIVERY_APP_SECRET
  MEITUAN_DELIVERY_STORE_MAP        JSON: {"txos_store_001": "mt_poi_888"}
  MEITUAN_DELIVERY_USE_REAL_API     "true" 启用真接入；默认 false（mock 路径不变）
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

import httpx
import structlog

from .delivery_platform_base import (
    DeliveryPlatformAdapter,
    DeliveryPlatformError,
)

logger = structlog.get_logger()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  MeituanClient — HTTP 客户端 SoT（CH-02.7a a2 并入）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

_MEITUAN_APP_ID_ENV = os.getenv("MEITUAN_APP_ID", "")
_MEITUAN_APP_SECRET_ENV = os.getenv("MEITUAN_APP_SECRET", "")
_MEITUAN_STORE_ID_ENV = os.getenv("MEITUAN_STORE_ID", "")
_MEITUAN_BASE_URL_ENV = os.getenv("MEITUAN_BASE_URL", "https://waimaiopen.meituan.com/api/v2")


class MeituanAuthError(Exception):
    """OAuth2 认证失败"""


class MeituanAPIError(Exception):
    """美团 API 业务错误"""

    def __init__(self, code: int, message: str):
        self.code = code
        self.message = message
        super().__init__(f"美团API错误 [{code}]: {message}")


class MeituanClient:
    """美团外卖开放平台 HTTP 客户端（基于 httpx.AsyncClient 连接池）

    支持：MD5 签名计算 / OAuth2 token 自动刷新 / 订单确认-取消-查询 / 菜品上传 / 结算对账。
    SoT 自 CH-02.7a a2 起为本文件；a3 删除 saas/src/client.py、saas/adapter.py
    切本文件 import，双源 drift 风险窗口关闭。
    """

    def __init__(
        self,
        app_id: str = "",
        app_secret: str = "",
        store_id: str = "",
        base_url: str = "",
        timeout: int = 30,
        max_retries: int = 3,
    ):
        self.app_id = app_id or _MEITUAN_APP_ID_ENV
        self.app_secret = app_secret or _MEITUAN_APP_SECRET_ENV
        self.store_id = store_id or _MEITUAN_STORE_ID_ENV
        self.base_url = (base_url or _MEITUAN_BASE_URL_ENV).rstrip("/")
        self.max_retries = max_retries

        if not self.app_id or not self.app_secret:
            raise ValueError("MEITUAN_APP_ID 和 MEITUAN_APP_SECRET 不能为空")

        self._http = httpx.AsyncClient(timeout=timeout, follow_redirects=True)
        self._access_token: str = ""
        self._token_expires_at: float = 0.0

        logger.info(
            "meituan_client_init",
            app_id=self.app_id,
            store_id=self.store_id,
            base_url=self.base_url,
        )

    @staticmethod
    def compute_sign(url: str, params: Dict[str, Any], app_secret: str) -> str:
        """美团请求签名：MD5(url + sorted "k=v" 拼接 + app_secret)"""
        sorted_pairs = sorted(params.items(), key=lambda kv: kv[0])
        param_str = "".join(f"{k}={v}" for k, v in sorted_pairs)
        raw = url + param_str + app_secret
        return hashlib.md5(raw.encode("utf-8")).hexdigest().lower()

    @staticmethod
    def verify_callback_sign(params: Dict[str, Any], sign: str, app_secret: str) -> bool:
        """美团回调签名验证：MD5(sorted "k=v" + app_secret)（不含 URL）"""
        filtered = {k: v for k, v in params.items() if k != "sign"}
        sorted_pairs = sorted(filtered.items(), key=lambda kv: kv[0])
        param_str = "".join(f"{k}={v}" for k, v in sorted_pairs)
        raw = param_str + app_secret
        expected = hashlib.md5(raw.encode("utf-8")).hexdigest().lower()
        return hmac.compare_digest(expected, sign.lower())

    async def _ensure_token(self) -> str:
        if self._access_token and time.time() < self._token_expires_at - 60:
            return self._access_token
        return await self._refresh_token()

    async def _refresh_token(self) -> str:
        url = f"{self.base_url}/token"
        params = {
            "app_id": self.app_id,
            "app_secret": self.app_secret,
            "grant_type": "client_credentials",
        }
        try:
            resp = await self._http.post(url, data=params)
            resp.raise_for_status()
            data = resp.json()
        except httpx.HTTPStatusError as exc:
            raise MeituanAuthError(f"Token 请求 HTTP 失败: {exc.response.status_code}") from exc
        except httpx.TimeoutException as exc:
            raise MeituanAuthError(f"Token 请求超时: {exc}") from exc

        if data.get("error"):
            raise MeituanAuthError(f"Token 错误: {data.get('error_description', data.get('error'))}")

        self._access_token = data["access_token"]
        self._token_expires_at = time.time() + int(data.get("expires_in", 7200))
        logger.info("meituan_token_refreshed", expires_in=data.get("expires_in"))
        return self._access_token

    async def _request(
        self,
        method: str,
        path: str,
        params: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """发送签名请求到美团 API，带重试。

        Raises:
            MeituanAPIError: 业务错误 / 重试耗尽
            MeituanAuthError: 认证失败
        """
        url = f"{self.base_url}{path}"
        token = await self._ensure_token()
        request_params: Dict[str, Any] = {
            "app_id": self.app_id,
            "access_token": token,
            "timestamp": str(int(time.time())),
            **(params or {}),
        }
        request_params["sign"] = self.compute_sign(url, request_params, self.app_secret)

        last_exc: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            try:
                if method.upper() == "GET":
                    resp = await self._http.get(url, params=request_params)
                else:
                    resp = await self._http.post(url, data=request_params)

                resp.raise_for_status()
                result = resp.json()

                code = result.get("code")
                if code not in (0, "ok", "OK"):
                    raise MeituanAPIError(
                        code=int(code) if isinstance(code, (int, str)) and str(code).lstrip("-").isdigit() else -1,
                        message=result.get("msg", result.get("message", "未知错误")),
                    )
                logger.info("meituan_api_ok", path=path, attempt=attempt)
                return result.get("data", result)
            except MeituanAPIError:
                raise
            except httpx.HTTPStatusError as exc:
                last_exc = exc
                logger.warning("meituan_api_http_error", path=path, status=exc.response.status_code, attempt=attempt)
            except (httpx.ConnectError, httpx.TimeoutException) as exc:
                last_exc = exc
                logger.warning("meituan_api_network_error", path=path, error=str(exc), attempt=attempt)

        raise MeituanAPIError(
            code=-1,
            message=f"请求 {path} 失败（{self.max_retries}次重试后）: {last_exc}",
        )

    async def confirm_order(self, order_id: str) -> Dict[str, Any]:
        return await self._request("POST", "/order/confirm", {"order_id": order_id})

    async def cancel_order(self, order_id: str, reason_code: int, reason: str) -> Dict[str, Any]:
        return await self._request(
            "POST",
            "/order/cancel",
            {"order_id": order_id, "reason_code": str(reason_code), "reason": reason},
        )

    async def query_order(self, order_id: str) -> Dict[str, Any]:
        return await self._request("GET", "/order/detail", {"order_id": order_id})

    async def upload_food(self, food_data: Dict[str, Any]) -> Dict[str, Any]:
        payload = {"app_poi_code": self.store_id, **food_data}
        return await self._request("POST", "/food/upload", payload)

    async def query_store_info(self) -> Dict[str, Any]:
        return await self._request("GET", "/store/info", {"app_poi_code": self.store_id})

    async def query_settlement(self, date_str: str) -> Dict[str, Any]:
        return await self._request(
            "GET",
            "/settlement/queryByDate",
            {"app_poi_code": self.store_id, "date": date_str},
        )

    async def close(self) -> None:
        await self._http.aclose()
        logger.info("meituan_client_closed")

# ── 美团订单状态 → 屯象统一状态 ──────────────────────────
MEITUAN_STATUS_MAP: Dict[int, str] = {
    1: "pending",  # 用户已下单
    2: "confirmed",  # 商家已接单
    3: "preparing",  # 备餐中
    4: "delivering",  # 骑手已取餐
    5: "completed",  # 已完成
    6: "cancelled",  # 已取消
    8: "refunded",  # 已退款
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
        self._use_real_api = os.environ.get("MEITUAN_DELIVERY_USE_REAL_API", "false").lower() == "true"
        self._client: Optional[MeituanClient] = None

        logger.info(
            "meituan_delivery_adapter_init",
            store_count=len(self.store_map),
            mock_mode=not self._use_real_api,
        )

    # ── 真接入 HTTP 客户端（lazy）────────────────────────────

    async def _ensure_client(self) -> MeituanClient:
        if self._client is None:
            self._client = MeituanClient(
                app_id=self.app_key,
                app_secret=self.app_secret,
                base_url=self.base_url,
                timeout=self.timeout,
            )
        return self._client

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
            items.append(
                {
                    "name": food.get("food_name", ""),
                    "quantity": int(food.get("quantity", 1)),
                    "price_fen": int(food.get("price", 0)),
                    "sku_id": str(food.get("app_food_code", "")),
                    "notes": food.get("food_property", ""),
                    "internal_dish_id": "",  # 需要业务层映射
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
                "detail": json.dumps(
                    [
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
                    ]
                ),
                "recipient_phone": "138****8888",
                "recipient_address": "长沙市天心区测试路1号",
                "delivery_time": str(now_ts + 2400),
                "caution": "少放辣",
            }
        ]

    # ── DeliveryPlatformAdapter 接口实现 ─────────────────────

    async def pull_orders(self, store_id: str, since: datetime) -> list[dict]:
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
        """接受美团订单（USE_REAL_API=true 时走 MeituanClient.confirm_order）"""
        logger.info("meituan_accept_order", order_id=order_id, real_api=self._use_real_api)
        if self._use_real_api:
            client = await self._ensure_client()
            await client.confirm_order(order_id)
            return True
        return True

    async def reject_order(self, order_id: str, reason: str) -> bool:
        """拒绝美团订单（USE_REAL_API=true 时走 MeituanClient.cancel_order）"""
        if not reason:
            raise DeliveryPlatformError(
                platform="meituan",
                code=400,
                message="拒单原因不能为空",
            )
        logger.info("meituan_reject_order", order_id=order_id, reason=reason, real_api=self._use_real_api)
        if self._use_real_api:
            client = await self._ensure_client()
            await client.cancel_order(order_id, reason_code=0, reason=reason)
            return True
        return True

    async def mark_ready(self, order_id: str) -> bool:
        """标记出餐完成（Mock）"""
        logger.info("meituan_mark_ready", order_id=order_id)
        # Mock：直接返回成功
        return True

    async def sync_menu(self, store_id: str, dishes: list[dict]) -> dict:
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
                errors.append(
                    {
                        "dish_id": dish.get("id", "unknown"),
                        "error": str(exc),
                    }
                )
                logger.warning(
                    "meituan_sync_dish_failed",
                    dish_id=dish.get("id"),
                    error=str(exc),
                )

        return {"synced": synced, "failed": failed, "errors": errors}

    async def update_stock(self, store_id: str, dish_id: str, available: bool) -> bool:
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
        """获取美团订单详情（USE_REAL_API=true 时走 MeituanClient.query_order）"""
        logger.info("meituan_get_order_detail", order_id=order_id, real_api=self._use_real_api)
        if self._use_real_api:
            client = await self._ensure_client()
            raw = await client.query_order(order_id)
            return self._map_order(raw)

        now_ts = int(time.time())
        mock_raw = {
            "order_id": order_id,
            "day_seq": "001",
            "status": 2,
            "order_total_price": 3500,
            "detail": json.dumps(
                [
                    {
                        "food_name": "宫保鸡丁",
                        "quantity": 1,
                        "price": 2800,
                        "app_food_code": "FOOD_001",
                        "food_property": "微辣",
                    },
                ]
            ),
            "recipient_phone": "138****8888",
            "recipient_address": "长沙市天心区测试路1号",
            "delivery_time": str(now_ts + 2400),
            "caution": "少放辣",
        }
        return self._map_order(mock_raw)

    # ── Task 3.1 增强：退款同步 / 配送状态 / 对账单 / 回调验签 ──────

    async def sync_refund(
        self,
        order_id: str,
        refund_amount_fen: int,
        reason: str = "",
    ) -> dict:
        """同步退款到美团平台（当前 Mock，接入真实 API 时切换）。

        美团退款 API: ecommerce/order/cancelAfterSales
        需要 order_id + refund_amount + reason。
        """
        logger.info(
            "meituan_sync_refund",
            order_id=order_id,
            refund_amount_fen=refund_amount_fen,
            reason=reason,
        )
        # Mock: 返回模拟成功
        return {
            "ok": True,
            "order_id": order_id,
            "refund_status": "success",
            "refund_amount_fen": refund_amount_fen,
            "platform_refund_id": f"mt_refund_{order_id}_{int(time.time())}",
            "mock": True,
        }

    async def get_delivery_status(self, order_id: str) -> dict:
        """查询美团配送状态（当前 Mock）。

        美团配送状态码：
          0=未配送, 10=已分配骑手, 20=骑手已到店, 30=骑手已取餐,
          40=配送中, 50=已送达, 60=异常

        Returns:
            {status, rider_name, rider_phone, estimated_delivery_time, current_position}
        """
        logger.info("meituan_get_delivery_status", order_id=order_id)
        now_ts = int(time.time())
        return {
            "order_id": order_id,
            "delivery_status": 40,  # 配送中
            "delivery_status_desc": "配送中",
            "rider_name": "骑手_MT001",
            "rider_phone": "139****0000",
            "estimated_delivery_time": str(now_ts + 1800),
            "current_position": {"lat": 28.1948, "lng": 112.9725},
            "mock": True,
        }

    async def download_bill(
        self,
        store_id: str,
        bill_date: str,  # YYYY-MM-DD
    ) -> dict:
        """下载美团对账单（当前 Mock 返回示例数据）。

        美团账单 API: ecommerce/order/downloadBill
        账单类型：订单明细 / 退款明细 / 佣金明细
        """
        poi_id = self._get_poi_id(store_id)
        logger.info(
            "meituan_download_bill",
            store_id=store_id,
            poi_id=poi_id,
            bill_date=bill_date,
        )
        return {
            "bill_date": bill_date,
            "store_id": store_id,
            "poi_id": poi_id,
            "summary": {
                "total_orders": 45,
                "total_amount_fen": 125000,
                "total_refund_fen": 8000,
                "platform_commission_fen": 18750,
                "net_settlement_fen": 98250,
            },
            "orders": [
                {
                    "order_id": f"mt_order_{bill_date}_001",
                    "amount_fen": 3500,
                    "commission_fen": 525,
                    "status": "completed",
                },
            ],
            "mock": True,
        }

    async def verify_webhook(
        self,
        body: bytes,
        headers: dict,
    ) -> dict:
        """验证美团回调签名（当前 Mock 模式，生产需接入美团开放平台验签）。

        美团开放平台使用 HMAC-SHA256，通过 app_secret 对请求体签名。
        X-Meituan-Signature header = Base64(HMAC-SHA256(app_secret, body))
        """
        signature = headers.get("x-meituan-signature", "")
        if not signature:
            logger.warning("meituan_webhook_no_signature")
            if os.environ.get("TX_ENV") == "production":
                raise DeliveryPlatformError(
                    platform="meituan",
                    code=401,
                    message="回调缺少签名",
                )

        # Mock: 接受任何签名
        logger.info(
            "meituan_webhook_verified",
            signature=signature[:16] + "..." if len(signature) > 16 else signature,
        )
        try:
            payload = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise DeliveryPlatformError(
                platform="meituan",
                code=400,
                message=f"回调体解析失败: {exc}",
            )
        return payload

    async def close(self) -> None:
        """释放资源（若启用了真接入则关 MeituanClient 连接池）"""
        if self._client is not None:
            await self._client.close()
            self._client = None
        logger.info("meituan_delivery_adapter_closed")
