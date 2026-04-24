"""抖音本地生活营销适配器

覆盖抖音/TikTok 本地生活商家营销核心能力：
  - 创建/管理 POI 活动（团购券/代金券）
  - 内容效果数据（达人带货 ROI）
  - 广告 ROI 回流
  - 直播间订单同步
  - 到店客流归因

环境变量：
  DOUYIN_APP_KEY    — 抖音开放平台 AppKey
  DOUYIN_APP_SECRET — 抖音开放平台 AppSecret
  DOUYIN_SHOP_ID    — 抖音商家店铺 ID

未配置时进入 Mock 模式。所有金额单位：分（整数）。
"""

from __future__ import annotations

import hashlib
import hmac
import os
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

import structlog

logger = structlog.get_logger(__name__)

_DOUYIN_TOKEN_URL = "https://open.douyin.com/oauth/client_token/"
_DOUYIN_BASE_URL = "https://open-api.douyin.com/api/v2"


class DouyinMarketingAdapter:
    """抖音本地生活商家营销适配器"""

    def __init__(self) -> None:
        self._app_key = os.getenv("DOUYIN_APP_KEY", "")
        self._app_secret = os.getenv("DOUYIN_APP_SECRET", "")
        self._shop_id = os.getenv("DOUYIN_SHOP_ID", "")
        self._is_mock = not (self._app_key and self._app_secret)
        self._access_token: Optional[str] = None
        self._token_expires_at: float = 0.0

        if self._is_mock:
            logger.info("douyin_mock_mode", reason="DOUYIN_APP_KEY or DOUYIN_APP_SECRET not set")

    @property
    def is_mock(self) -> bool:
        return self._is_mock

    # ─── POI 活动管理 ─────────────────────────────────────────────────────────

    async def create_poi_activity(
        self,
        tenant_id: str,
        store_id: str,
        activity_config: dict[str, Any],
    ) -> dict[str, Any]:
        """创建抖音 POI 活动（团购券/代金券）

        Args:
            tenant_id: 租户 ID
            store_id: 屯象门店 ID
            activity_config:
                - name: str 活动名称
                - activity_type: "group_buy" | "voucher" | "combo"
                - original_price_fen: int 原价（分）
                - sale_price_fen: int 售价（分）
                - total_stock: int 库存数量
                - start_time: str ISO 时间
                - end_time: str ISO 时间
                - poi_id: str 抖音 POI ID
                - description: str 活动描述

        Returns:
            {activity_id, status, platform, douyin_poi_id}
        """
        op_id = f"dy_act_{uuid.uuid4().hex[:10]}"

        if self._is_mock:
            mock_activity_id = f"MOCK_DY_{uuid.uuid4().hex[:8].upper()}"
            logger.info(
                "douyin_create_activity_mock",
                op_id=op_id,
                store_id=store_id,
                activity_type=activity_config.get("activity_type"),
                sale_price_fen=activity_config.get("sale_price_fen"),
            )
            return {
                "op_id": op_id,
                "activity_id": mock_activity_id,
                "status": "mock",
                "platform": "douyin",
                "store_id": store_id,
            }

        try:
            token = await self._get_access_token()
            payload = {
                "poi_id": activity_config.get("poi_id", self._shop_id),
                "activity_name": activity_config["name"],
                "activity_type": activity_config.get("activity_type", "voucher"),
                "original_price": activity_config["original_price_fen"],
                "sale_price": activity_config["sale_price_fen"],
                "stock_num": activity_config.get("total_stock", 100),
                "start_time": activity_config["start_time"],
                "end_time": activity_config["end_time"],
                "desc": activity_config.get("description", ""),
            }
            result = await self._call_api("POST", "/poi/activity/create", payload, token)
            activity_id = result.get("activity_id")
            logger.info("douyin_activity_created", op_id=op_id, activity_id=activity_id)
            return {
                "op_id": op_id,
                "activity_id": activity_id,
                "status": "created",
                "platform": "douyin",
                "store_id": store_id,
            }
        except (ValueError, ConnectionError, TimeoutError, OSError) as exc:
            logger.error("douyin_create_activity_failed", op_id=op_id, error=str(exc))
            return {"op_id": op_id, "status": "failed", "error": str(exc)}

    # ─── 内容效果数据 ─────────────────────────────────────────────────────────

    async def get_content_performance(
        self,
        tenant_id: str,
        store_id: str,
        days: int = 7,
    ) -> dict[str, Any]:
        """获取内容效果数据（达人带货 ROI + 自然内容流量）

        Returns:
            {
                period_days: int,
                total_views: int,
                total_clicks: int,
                total_orders: int,
                total_revenue_fen: int,
                content_roi: float,
                top_creators: list of creator performance,
                organic_vs_paid: dict
            }
        """
        if self._is_mock:
            return {
                "store_id": store_id,
                "period_days": days,
                "total_views": 128000,
                "total_clicks": 6400,
                "total_orders": 312,
                "total_revenue_fen": 2340000,
                "content_roi": 5.8,
                "avg_order_value_fen": 7500,
                "top_creators": [
                    {
                        "creator_id": "MOCK_KOL_001",
                        "nickname": "美食探店达人",
                        "orders": 89,
                        "revenue_fen": 667500,
                        "commission_pct": 8.0,
                    },
                    {
                        "creator_id": "MOCK_KOL_002",
                        "nickname": "长沙吃喝玩乐",
                        "orders": 67,
                        "revenue_fen": 502500,
                        "commission_pct": 7.5,
                    },
                ],
                "organic_vs_paid": {
                    "organic_views": 89600,
                    "paid_views": 38400,
                    "organic_order_pct": 62.5,
                    "paid_order_pct": 37.5,
                },
                "platform": "douyin",
                "status": "mock",
            }

        try:
            token = await self._get_access_token()
            result = await self._call_api(
                "GET",
                "/content/performance",
                {"shop_id": self._shop_id or store_id, "days": days},
                token,
            )
            return {"store_id": store_id, "period_days": days, "platform": "douyin", **result}
        except (ValueError, ConnectionError, TimeoutError, OSError) as exc:
            logger.error("douyin_content_performance_failed", store_id=store_id, error=str(exc))
            return {"store_id": store_id, "error": str(exc)}

    async def get_ad_roi_data(
        self,
        tenant_id: str,
        store_id: str,
        campaign_id: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> dict[str, Any]:
        """获取广告 ROI 数据（DOU+/千川投流）

        Returns:
            {
                total_spend_fen: int,
                total_orders: int,
                total_revenue_fen: int,
                roi: float,
                cpa_fen: int,  # 单次获客成本
                campaigns: list
            }
        """
        if self._is_mock:
            return {
                "store_id": store_id,
                "campaign_id": campaign_id,
                "total_spend_fen": 96000,
                "impression_count": 320000,
                "click_count": 9600,
                "total_orders": 178,
                "total_revenue_fen": 1335000,
                "roi": 13.9,
                "ctr": 0.03,
                "cvr": 0.0186,
                "cpa_fen": 539,
                "platform": "douyin",
                "status": "mock",
            }

        try:
            token = await self._get_access_token()
            params: dict[str, Any] = {"shop_id": self._shop_id or store_id}
            if campaign_id:
                params["campaign_id"] = campaign_id
            if start_date:
                params["start_date"] = start_date
            if end_date:
                params["end_date"] = end_date

            result = await self._call_api("GET", "/ad/roi", params, token)
            return {"store_id": store_id, "platform": "douyin", **result}
        except (ValueError, ConnectionError, TimeoutError, OSError) as exc:
            logger.error("douyin_ad_roi_failed", store_id=store_id, error=str(exc))
            return {"store_id": store_id, "error": str(exc)}

    async def sync_live_orders(
        self,
        tenant_id: str,
        store_id: str,
        live_room_id: Optional[str] = None,
    ) -> dict[str, Any]:
        """同步直播间订单到屯象 OS

        Returns:
            {synced_count: int, orders: list, last_sync_time: str}
        """
        op_id = f"dy_live_sync_{uuid.uuid4().hex[:8]}"

        if self._is_mock:
            logger.info("douyin_sync_live_orders_mock", op_id=op_id, store_id=store_id)
            return {
                "op_id": op_id,
                "synced_count": 12,
                "orders": [
                    {
                        "douyin_order_id": f"DY_ORD_{i:04d}",
                        "amount_fen": 8800 + i * 100,
                        "status": "paid",
                        "source": "live_room",
                    }
                    for i in range(1, 4)
                ],
                "last_sync_time": datetime.now(timezone.utc).isoformat(),
                "platform": "douyin",
                "status": "mock",
            }

        try:
            token = await self._get_access_token()
            params: dict[str, Any] = {"shop_id": self._shop_id or store_id}
            if live_room_id:
                params["room_id"] = live_room_id

            result = await self._call_api("GET", "/live/orders", params, token)
            orders = result.get("orders", [])
            logger.info("douyin_live_orders_synced", op_id=op_id, count=len(orders))
            return {
                "op_id": op_id,
                "synced_count": len(orders),
                "orders": orders,
                "last_sync_time": datetime.now(timezone.utc).isoformat(),
                "platform": "douyin",
            }
        except (ValueError, ConnectionError, TimeoutError, OSError) as exc:
            logger.error("douyin_sync_live_orders_failed", op_id=op_id, error=str(exc))
            return {"op_id": op_id, "synced_count": 0, "error": str(exc)}

    async def get_store_traffic_data(
        self,
        tenant_id: str,
        store_id: str,
        date: str,
    ) -> dict[str, Any]:
        """获取到店客流归因数据（抖音带来的线下到店）

        Returns:
            {
                date: str,
                total_visits: int,
                douyin_attributed_visits: int,
                attribution_rate: float,
                source_breakdown: {from_video/from_live/from_search/from_ad}: int
            }
        """
        if self._is_mock:
            return {
                "store_id": store_id,
                "date": date,
                "total_visits": 486,
                "douyin_attributed_visits": 134,
                "attribution_rate": 0.276,
                "source_breakdown": {
                    "from_video": 67,
                    "from_live": 28,
                    "from_search": 24,
                    "from_ad": 15,
                },
                "platform": "douyin",
                "status": "mock",
            }

        try:
            token = await self._get_access_token()
            result = await self._call_api(
                "GET",
                "/poi/traffic",
                {"poi_id": self._shop_id or store_id, "date": date},
                token,
            )
            return {"store_id": store_id, "date": date, "platform": "douyin", **result}
        except (ValueError, ConnectionError, TimeoutError, OSError) as exc:
            logger.error("douyin_traffic_data_failed", store_id=store_id, date=date, error=str(exc))
            return {"store_id": store_id, "date": date, "error": str(exc)}

    # ─── 内部：Token + API 调用 ───────────────────────────────────────────────

    async def _get_access_token(self) -> str:
        """获取抖音客户端凭证 access_token（缓存，提前5分钟刷新）"""
        now = time.time()
        if self._access_token and now < self._token_expires_at:
            return self._access_token

        import aiohttp

        payload = {
            "client_key": self._app_key,
            "client_secret": self._app_secret,
            "grant_type": "client_credential",
        }
        async with (
            aiohttp.ClientSession() as session,
            session.post(
                _DOUYIN_TOKEN_URL,
                json=payload,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp,
        ):
            result = await resp.json()
            data = result.get("data", {})
            if not data.get("access_token"):
                raise ValueError(f"Douyin token error: {result.get('message')}")
            self._access_token = data["access_token"]
            self._token_expires_at = now + data.get("expires_in", 7200) - 300
            return self._access_token

    async def _call_api(
        self,
        method: str,
        path: str,
        params: dict[str, Any],
        access_token: str,
    ) -> dict[str, Any]:
        """调用抖音开放平台 API"""
        timestamp = str(int(time.time()))
        nonce = uuid.uuid4().hex[:16]

        # 抖音 API 签名：按参数名字典序拼接 + HMAC-SHA256
        sign_str = self._app_secret + "".join(f"{k}{v}" for k, v in sorted(params.items())) + timestamp + nonce
        signature = hmac.new(
            self._app_secret.encode("utf-8"),
            sign_str.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

        headers = {
            "access-token": access_token,
            "x-timestamp": timestamp,
            "x-nonce": nonce,
            "x-sign": signature,
            "Content-Type": "application/json",
        }
        url = f"{_DOUYIN_BASE_URL}{path}"

        import aiohttp

        async with aiohttp.ClientSession() as session:
            if method == "GET":
                req = session.get(url, params=params, headers=headers, timeout=aiohttp.ClientTimeout(total=15))
            else:
                req = session.post(url, json=params, headers=headers, timeout=aiohttp.ClientTimeout(total=15))

            async with req as resp:
                data = await resp.json()
                err_no = data.get("err_no", 0)
                if err_no != 0:
                    raise ValueError(f"Douyin API error {err_no}: {data.get('err_tips')}")
                return data.get("data", {})
