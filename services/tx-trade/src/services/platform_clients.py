"""外卖平台 API 客户端 -- 美团/饿了么/抖音

负责向各平台发起主动 API 调用（接单确认、出餐通知、取消订单、菜品库存同步等）。
所有金额单位：分（fen）。

凭证通过环境变量注入：
  MEITUAN_APP_ID / MEITUAN_APP_SECRET
  ELEME_APP_ID   / ELEME_APP_SECRET
  DOUYIN_APP_ID  / DOUYIN_APP_SECRET

平台 API 调用失败不阻断订单流程 -- 仅记录日志并返回错误字典。
"""
from __future__ import annotations

import hashlib
import hmac
import os
import time
from abc import ABC, abstractmethod
from typing import Any

import httpx
import structlog

logger = structlog.get_logger(__name__)

# 默认超时（秒）
_DEFAULT_TIMEOUT = 10.0
# 重试间隔（秒）-- 指数退避基数
_RETRY_BASE_DELAY = 1.0


class BasePlatformClient(ABC):
    """平台客户端基类 -- 封装 httpx + 重试 + 日志"""

    platform: str = ""
    BASE_URL: str = ""

    def __init__(self, app_id: str, app_secret: str) -> None:
        self.app_id = app_id
        self.app_secret = app_secret
        self._client: httpx.AsyncClient | None = None

    @property
    def configured(self) -> bool:
        """凭证是否已配置"""
        return bool(self.app_id and self.app_secret)

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self.BASE_URL,
                timeout=_DEFAULT_TIMEOUT,
            )
        return self._client

    async def close(self) -> None:
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """发起带签名和重试的 HTTP 请求。

        网络错误最多重试 1 次（指数退避）。
        返回 dict：成功时为平台响应，失败时 {"ok": False, "error": ...}
        """
        client = await self._get_client()
        log = logger.bind(platform=self.platform, method=method, path=path)

        signed_params = self._sign_request(path, params=params, body=json_body)

        last_error: httpx.HTTPError | None = None
        for attempt in range(2):  # 最多 2 次（初次 + 1 次重试）
            try:
                if method.upper() == "GET":
                    resp = await client.get(path, params=signed_params)
                else:
                    resp = await client.post(path, params=signed_params, json=json_body)

                resp.raise_for_status()
                data = resp.json()
                log.info(
                    "platform_api_ok",
                    status_code=resp.status_code,
                    attempt=attempt,
                )
                return data

            except httpx.HTTPStatusError as exc:
                log.error(
                    "platform_api_http_error",
                    status_code=exc.response.status_code,
                    body=exc.response.text[:500],
                    attempt=attempt,
                )
                # HTTP 4xx/5xx 不重试（业务错误 / 服务端错误通常不可重试）
                return {
                    "ok": False,
                    "error": f"HTTP {exc.response.status_code}",
                    "detail": exc.response.text[:500],
                }

            except httpx.HTTPError as exc:
                last_error = exc
                log.warning(
                    "platform_api_network_error",
                    error=str(exc),
                    attempt=attempt,
                )
                if attempt < 1:
                    import asyncio
                    await asyncio.sleep(_RETRY_BASE_DELAY * (2 ** attempt))

        # 所有重试耗尽
        error_msg = str(last_error) if last_error else "unknown"
        log.error("platform_api_exhausted_retries", error=error_msg)
        return {"ok": False, "error": f"network_error: {error_msg}"}

    @abstractmethod
    def _sign_request(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        body: dict[str, Any] | None = None,
    ) -> dict[str, str]:
        """生成带签名的请求参数。子类实现各平台签名算法。"""
        ...

    @abstractmethod
    async def confirm_order(
        self, platform_order_id: str, estimated_minutes: int
    ) -> dict[str, Any]:
        ...

    @abstractmethod
    async def mark_ready(self, platform_order_id: str) -> dict[str, Any]:
        ...

    @abstractmethod
    async def cancel_order(
        self, platform_order_id: str, reason_code: int, reason: str
    ) -> dict[str, Any]:
        ...

    @abstractmethod
    async def sync_dish_stock(self, dish_mappings: list[dict]) -> dict[str, Any]:
        ...


# ─────────────────────────────────────────────────────────────────────────────
# 美团外卖开放平台
# ─────────────────────────────────────────────────────────────────────────────


class MeituanClient(BasePlatformClient):
    """美团外卖开放平台 API 客户端

    文档：https://openapi.waimai.meituan.com
    签名算法：MD5(appSecret + 请求参数字典序拼接 + appSecret)
    """

    platform = "meituan"
    BASE_URL = "https://waimaiopen.meituan.com/api/v1"

    def __init__(
        self,
        app_id: str | None = None,
        app_secret: str | None = None,
    ) -> None:
        super().__init__(
            app_id=app_id or os.environ.get("MEITUAN_APP_ID", ""),
            app_secret=app_secret or os.environ.get("MEITUAN_APP_SECRET", ""),
        )

    def _sign_request(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        body: dict[str, Any] | None = None,
    ) -> dict[str, str]:
        """美团签名：MD5(secret + sorted(k=v) + secret)"""
        ts = str(int(time.time()))
        all_params: dict[str, str] = {
            "app_id": self.app_id,
            "timestamp": ts,
        }
        if params:
            all_params.update({k: str(v) for k, v in params.items()})

        sorted_str = "".join(
            f"{k}{v}" for k, v in sorted(all_params.items())
        )
        raw = f"{self.app_secret}{sorted_str}{self.app_secret}"
        sig = hashlib.md5(raw.encode("utf-8")).hexdigest().upper()
        all_params["sig"] = sig
        return all_params

    async def confirm_order(
        self, platform_order_id: str, estimated_minutes: int = 30
    ) -> dict[str, Any]:
        """确认接单 -- POST /order/confirm"""
        return await self._request(
            "POST",
            "/order/confirm",
            params={"order_id": platform_order_id},
            json_body={"estimated_minutes": estimated_minutes},
        )

    async def mark_ready(self, platform_order_id: str) -> dict[str, Any]:
        """出餐完成 -- POST /order/delivering"""
        return await self._request(
            "POST",
            "/order/delivering",
            params={"order_id": platform_order_id},
        )

    async def cancel_order(
        self, platform_order_id: str, reason_code: int = 1, reason: str = ""
    ) -> dict[str, Any]:
        """取消订单 -- POST /order/cancel"""
        return await self._request(
            "POST",
            "/order/cancel",
            params={"order_id": platform_order_id},
            json_body={"reason_code": reason_code, "reason": reason},
        )

    async def sync_dish_stock(self, dish_mappings: list[dict]) -> dict[str, Any]:
        """同步菜品库存/售罄状态 -- POST /food/stock"""
        food_data = [
            {
                "app_food_code": m.get("platform_dish_id", ""),
                "stock": m.get("stock", 999),
                "is_sold_out": 1 if m.get("stock", 999) <= 0 else 0,
            }
            for m in dish_mappings
        ]
        return await self._request(
            "POST",
            "/food/stock",
            json_body={"food_data": food_data},
        )


# ─────────────────────────────────────────────────────────────────────────────
# 饿了么开放平台
# ─────────────────────────────────────────────────────────────────────────────


class ElemeClient(BasePlatformClient):
    """饿了么开放平台 API 客户端

    文档：https://open-api.shop.ele.me
    签名算法：HMAC-SHA256(secret, body)
    """

    platform = "eleme"
    BASE_URL = "https://open-api.shop.ele.me/api/v1"

    def __init__(
        self,
        app_id: str | None = None,
        app_secret: str | None = None,
    ) -> None:
        super().__init__(
            app_id=app_id or os.environ.get("ELEME_APP_ID", ""),
            app_secret=app_secret or os.environ.get("ELEME_APP_SECRET", ""),
        )

    def _sign_request(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        body: dict[str, Any] | None = None,
    ) -> dict[str, str]:
        """饿了么签名：HMAC-SHA256(secret, sorted_params)"""
        ts = str(int(time.time()))
        all_params: dict[str, str] = {
            "app_key": self.app_id,
            "timestamp": ts,
        }
        if params:
            all_params.update({k: str(v) for k, v in params.items()})

        sorted_str = "&".join(
            f"{k}={v}" for k, v in sorted(all_params.items())
        )
        sig = hmac.new(
            self.app_secret.encode("utf-8"),
            sorted_str.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        all_params["sign"] = sig
        return all_params

    async def confirm_order(
        self, platform_order_id: str, estimated_minutes: int = 30
    ) -> dict[str, Any]:
        """确认接单 -- POST /order/confirm"""
        return await self._request(
            "POST",
            "/order/confirm",
            params={"order_id": platform_order_id},
            json_body={"estimated_minutes": estimated_minutes},
        )

    async def mark_ready(self, platform_order_id: str) -> dict[str, Any]:
        """出餐完成 -- POST /order/ready"""
        return await self._request(
            "POST",
            "/order/ready",
            params={"order_id": platform_order_id},
        )

    async def cancel_order(
        self, platform_order_id: str, reason_code: int = 1, reason: str = ""
    ) -> dict[str, Any]:
        """取消订单 -- POST /order/cancel"""
        return await self._request(
            "POST",
            "/order/cancel",
            params={"order_id": platform_order_id},
            json_body={"reason_code": reason_code, "reason": reason},
        )

    async def sync_dish_stock(self, dish_mappings: list[dict]) -> dict[str, Any]:
        """同步菜品库存/售罄状态 -- POST /sku/stock"""
        sku_data = [
            {
                "sku_id": m.get("platform_dish_id", ""),
                "stock": m.get("stock", 999),
                "sold_out": m.get("stock", 999) <= 0,
            }
            for m in dish_mappings
        ]
        return await self._request(
            "POST",
            "/sku/stock",
            json_body={"sku_list": sku_data},
        )


# ─────────────────────────────────────────────────────────────────────────────
# 抖音来客 / 生活服务
# ─────────────────────────────────────────────────────────────────────────────


class DouyinClient(BasePlatformClient):
    """抖音来客/生活服务 API 客户端

    文档：https://open.douyin.com/platform/doc/delivery
    签名算法：HMAC-SHA256(secret, sorted_params)
    """

    platform = "douyin"
    BASE_URL = "https://open.douyin.com/life/v1"

    def __init__(
        self,
        app_id: str | None = None,
        app_secret: str | None = None,
    ) -> None:
        super().__init__(
            app_id=app_id or os.environ.get("DOUYIN_APP_ID", ""),
            app_secret=app_secret or os.environ.get("DOUYIN_APP_SECRET", ""),
        )

    def _sign_request(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        body: dict[str, Any] | None = None,
    ) -> dict[str, str]:
        """抖音签名：HMAC-SHA256(secret, sorted_params)"""
        ts = str(int(time.time()))
        all_params: dict[str, str] = {
            "app_id": self.app_id,
            "timestamp": ts,
        }
        if params:
            all_params.update({k: str(v) for k, v in params.items()})

        sorted_str = "&".join(
            f"{k}={v}" for k, v in sorted(all_params.items())
        )
        sig = hmac.new(
            self.app_secret.encode("utf-8"),
            sorted_str.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        all_params["sign"] = sig
        return all_params

    async def confirm_order(
        self, platform_order_id: str, estimated_minutes: int = 30
    ) -> dict[str, Any]:
        """确认接单 -- POST /order/confirm"""
        return await self._request(
            "POST",
            "/order/confirm",
            params={"order_id": platform_order_id},
            json_body={"estimated_minutes": estimated_minutes},
        )

    async def mark_ready(self, platform_order_id: str) -> dict[str, Any]:
        """出餐完成 -- POST /order/ready"""
        return await self._request(
            "POST",
            "/order/ready",
            params={"order_id": platform_order_id},
        )

    async def cancel_order(
        self, platform_order_id: str, reason_code: int = 1, reason: str = ""
    ) -> dict[str, Any]:
        """取消订单 -- POST /order/cancel"""
        return await self._request(
            "POST",
            "/order/cancel",
            params={"order_id": platform_order_id},
            json_body={"reason_code": reason_code, "reason": reason},
        )

    async def sync_dish_stock(self, dish_mappings: list[dict]) -> dict[str, Any]:
        """同步菜品库存/售罄状态 -- POST /food/stock/update"""
        food_data = [
            {
                "product_id": m.get("platform_dish_id", ""),
                "stock_num": m.get("stock", 999),
            }
            for m in dish_mappings
        ]
        return await self._request(
            "POST",
            "/food/stock/update",
            json_body={"product_stock_list": food_data},
        )


# ─────────────────────────────────────────────────────────────────────────────
# 工厂函数
# ─────────────────────────────────────────────────────────────────────────────


def get_platform_client(platform: str) -> BasePlatformClient | None:
    """根据平台名称获取客户端实例。

    如果对应平台环境变量未配置（app_id 或 app_secret 为空），返回 None。
    """
    _REGISTRY: dict[str, type[BasePlatformClient]] = {
        "meituan": MeituanClient,
        "eleme": ElemeClient,
        "douyin": DouyinClient,
    }
    cls = _REGISTRY.get(platform)
    if cls is None:
        return None
    client = cls()
    if not client.configured:
        return None
    return client
