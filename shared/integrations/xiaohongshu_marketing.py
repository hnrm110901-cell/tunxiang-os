"""小红书营销适配器

覆盖小红书商家营销核心能力：
  - 创建品牌笔记（图文/视频）
  - 笔记效果数据（曝光/互动/收藏）
  - 门店被提及监控（UGC 口碑）
  - 广告数据回流（聚光投放 ROI）
  - POI 门店信息管理（菜单同步/营业时间）

环境变量：
  XHS_APP_KEY    — 小红书开放平台 AppKey
  XHS_APP_SECRET — 小红书开放平台 AppSecret
  XHS_STORE_ID   — 小红书商家门店 ID

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

_XHS_TOKEN_URL = "https://ark.xiaohongshu.com/oauth/token"
_XHS_BASE_URL = "https://ark.xiaohongshu.com/api/v1"


def _mask_store_id(store_id: str) -> str:
    """store_id 脱敏: store1234****5678"""
    if len(store_id) >= 12:
        return store_id[:8] + "****" + store_id[-4:]
    return store_id[:4] + "***" if len(store_id) >= 4 else "***"


class XiaohongshuMarketingAdapter:
    """小红书商家营销适配器"""

    def __init__(self) -> None:
        self._app_key = os.getenv("XHS_APP_KEY", "")
        self._app_secret = os.getenv("XHS_APP_SECRET", "")
        self._store_id = os.getenv("XHS_STORE_ID", "")
        self._is_mock = not (self._app_key and self._app_secret)
        self._access_token: Optional[str] = None
        self._token_expires_at: float = 0.0

        if self._is_mock:
            logger.info("xiaohongshu_mock_mode", reason="XHS_APP_KEY or XHS_APP_SECRET not set")

    @property
    def is_mock(self) -> bool:
        return self._is_mock

    # ─── 品牌笔记管理 ─────────────────────────────────────────────────────────

    async def create_brand_note(
        self,
        tenant_id: str,
        store_id: str,
        note_config: dict[str, Any],
    ) -> dict[str, Any]:
        """创建小红书品牌笔记（图文/视频）

        Args:
            tenant_id: 租户 ID
            store_id: 屯象门店 ID
            note_config:
                - title: str 笔记标题
                - content: str 笔记正文
                - images: list[str] 图片 URL 列表
                - note_type: "normal" | "video"  笔记类型
                - location_name: str 地点名称
                - poi_id: str 小红书 POI ID

        Returns:
            {note_id, status, platform, store_id}
        """
        op_id = f"xhs_note_{uuid.uuid4().hex[:10]}"

        if self._is_mock:
            mock_note_id = f"MOCK_XHS_{uuid.uuid4().hex[:8].upper()}"
            logger.info(
                "xiaohongshu_create_note_mock",
                op_id=op_id,
                store_id=_mask_store_id(store_id),
                note_type=note_config.get("note_type"),
            )
            return {
                "op_id": op_id,
                "note_id": mock_note_id,
                "status": "mock",
                "platform": "xiaohongshu",
                "store_id": store_id,
            }

        try:
            token = await self._get_access_token()
            payload = {
                "store_id": self._store_id or store_id,
                "title": note_config["title"],
                "content": note_config.get("content", ""),
                "images": note_config.get("images", []),
                "note_type": note_config.get("note_type", "normal"),
                "location_name": note_config.get("location_name", ""),
                "poi_id": note_config.get("poi_id", ""),
            }
            result = await self._call_api("POST", "/note/create", payload, token)
            note_id = result.get("note_id")
            logger.info("xiaohongshu_note_created", op_id=op_id, note_id=note_id)
            return {
                "op_id": op_id,
                "note_id": note_id,
                "status": "created",
                "platform": "xiaohongshu",
                "store_id": store_id,
            }
        except (ValueError, ConnectionError, TimeoutError, OSError) as exc:
            logger.error("xiaohongshu_create_note_failed", op_id=op_id, error=str(exc))
            return {"op_id": op_id, "status": "failed", "error": str(exc)}

    # ─── 笔记效果数据 ─────────────────────────────────────────────────────────

    async def get_note_performance(
        self,
        tenant_id: str,
        store_id: str,
        note_id: str,
        days: int = 7,
    ) -> dict[str, Any]:
        """获取笔记效果数据（曝光/互动/收藏/分享）

        Returns:
            {
                note_id: str,
                views: int,
                likes: int,
                comments: int,
                saves: int,
                shares: int,
                ctr: float,
                status: str
            }
        """
        if self._is_mock:
            return {
                "store_id": store_id,
                "note_id": note_id,
                "period_days": days,
                "views": 5120,
                "likes": 218,
                "comments": 47,
                "saves": 312,
                "shares": 89,
                "ctr": 0.043,
                "engagement_rate": 0.129,
                "platform": "xiaohongshu",
                "status": "mock",
            }

        try:
            token = await self._get_access_token()
            result = await self._call_api(
                "GET",
                "/note/performance",
                {"note_id": note_id, "store_id": self._store_id or store_id, "days": days},
                token,
            )
            return {"store_id": store_id, "note_id": note_id, "period_days": days, "platform": "xiaohongshu", **result}
        except (ValueError, ConnectionError, TimeoutError, OSError) as exc:
            logger.error("xiaohongshu_note_performance_failed", note_id=note_id, error=str(exc))
            return {"store_id": store_id, "note_id": note_id, "error": str(exc)}

    # ─── 门店被提及监控 ───────────────────────────────────────────────────────

    async def get_store_mentions(
        self,
        tenant_id: str,
        store_id: str,
        days: int = 7,
    ) -> dict[str, Any]:
        """获取门店 UGC 口碑数据（用户自发笔记提及）

        Returns:
            {
                total_mentions: int,
                positive: int,
                neutral: int,
                negative: int,
                top_notes: list,
                avg_sentiment: float,
                status: str
            }
        """
        if self._is_mock:
            return {
                "store_id": store_id,
                "period_days": days,
                "total_mentions": 64,
                "positive": 51,
                "neutral": 10,
                "negative": 3,
                "avg_sentiment": 0.81,
                "top_notes": [
                    {
                        "note_id": "MOCK_UGC_001",
                        "author": "美食探店君",
                        "likes": 1280,
                        "sentiment": "positive",
                        "excerpt": "这家店真的太好吃了！强烈推荐招牌菜...",
                    },
                    {
                        "note_id": "MOCK_UGC_002",
                        "author": "长沙吃货联盟",
                        "likes": 876,
                        "sentiment": "positive",
                        "excerpt": "环境超棒，服务也很周到，下次还会来...",
                    },
                ],
                "platform": "xiaohongshu",
                "status": "mock",
            }

        try:
            token = await self._get_access_token()
            result = await self._call_api(
                "GET",
                "/store/mentions",
                {"store_id": self._store_id or store_id, "days": days},
                token,
            )
            return {"store_id": store_id, "period_days": days, "platform": "xiaohongshu", **result}
        except (ValueError, ConnectionError, TimeoutError, OSError) as exc:
            logger.error("xiaohongshu_store_mentions_failed", store_id=store_id, error=str(exc))
            return {"store_id": store_id, "error": str(exc)}

    # ─── 广告数据回流 ─────────────────────────────────────────────────────────

    async def get_ad_data(
        self,
        tenant_id: str,
        store_id: str,
        start_date: str,
        end_date: str,
    ) -> dict[str, Any]:
        """获取聚光广告投放 ROI 数据

        Returns:
            {
                total_spend_fen: int,
                impressions: int,
                clicks: int,
                roi: float,
                cpc_fen: int,
                status: str
            }
        """
        if self._is_mock:
            return {
                "store_id": store_id,
                "start_date": start_date,
                "end_date": end_date,
                "total_spend_fen": 48000,
                "impressions": 210000,
                "clicks": 6300,
                "total_orders": 94,
                "total_revenue_fen": 705000,
                "roi": 14.7,
                "ctr": 0.03,
                "cpc_fen": 762,
                "platform": "xiaohongshu",
                "status": "mock",
            }

        try:
            token = await self._get_access_token()
            result = await self._call_api(
                "GET",
                "/ad/data",
                {
                    "store_id": self._store_id or store_id,
                    "start_date": start_date,
                    "end_date": end_date,
                },
                token,
            )
            return {
                "store_id": store_id,
                "start_date": start_date,
                "end_date": end_date,
                "platform": "xiaohongshu",
                **result,
            }
        except (ValueError, ConnectionError, TimeoutError, OSError) as exc:
            logger.error("xiaohongshu_ad_data_failed", store_id=store_id, error=str(exc))
            return {"store_id": store_id, "error": str(exc)}

    # ─── POI 门店信息管理 ─────────────────────────────────────────────────────

    async def manage_poi_store(
        self,
        tenant_id: str,
        store_id: str,
        action: str = "get_info",
    ) -> dict[str, Any]:
        """管理小红书 POI 门店信息

        Args:
            tenant_id: 租户 ID
            store_id: 屯象门店 ID
            action: "get_info" | "sync_menu" | "update_hours"

        Returns:
            {poi_id, store_name, status, action}
        """
        op_id = f"xhs_poi_{uuid.uuid4().hex[:8]}"

        if self._is_mock:
            logger.info(
                "xiaohongshu_manage_poi_mock",
                op_id=op_id,
                store_id=_mask_store_id(store_id),
                action=action,
            )
            return {
                "op_id": op_id,
                "poi_id": f"MOCK_POI_{store_id[:8].upper()}",
                "store_name": "屯象示例餐厅（Mock）",
                "address": "湖南省长沙市天心区示例街道88号",
                "action": action,
                "last_synced_at": datetime.now(timezone.utc).isoformat(),
                "platform": "xiaohongshu",
                "status": "mock",
            }

        try:
            token = await self._get_access_token()
            endpoint_map = {
                "get_info": "/poi/info",
                "sync_menu": "/poi/menu/sync",
                "update_hours": "/poi/hours/update",
            }
            endpoint = endpoint_map.get(action)
            if not endpoint:
                raise ValueError(f"Unknown POI action: {action}")

            result = await self._call_api(
                "GET" if action == "get_info" else "POST",
                endpoint,
                {"store_id": self._store_id or store_id},
                token,
            )
            logger.info("xiaohongshu_poi_action_done", op_id=op_id, action=action)
            return {
                "op_id": op_id,
                "action": action,
                "platform": "xiaohongshu",
                **result,
            }
        except (ValueError, ConnectionError, TimeoutError, OSError) as exc:
            logger.error("xiaohongshu_poi_action_failed", op_id=op_id, action=action, error=str(exc))
            return {"op_id": op_id, "action": action, "status": "failed", "error": str(exc)}

    # ─── 内部：Token + API 调用 ───────────────────────────────────────────────

    async def _get_access_token(self) -> str:
        """获取小红书 OAuth2 access_token（缓存，提前5分钟刷新）"""
        now = time.time()
        if self._access_token and now < self._token_expires_at:
            return self._access_token

        import aiohttp

        payload = {
            "app_key": self._app_key,
            "app_secret": self._app_secret,
            "grant_type": "client_credentials",
        }
        async with (
            aiohttp.ClientSession() as session,
            session.post(
                _XHS_TOKEN_URL,
                json=payload,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp,
        ):
            result = await resp.json()
            data = result.get("data", {})
            if not data.get("access_token"):
                raise ValueError(f"XHS token error: {result.get('message')}")
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
        """调用小红书开放平台 API（HMAC-SHA256 签名）"""
        timestamp = str(int(time.time()))
        nonce = uuid.uuid4().hex[:16]

        # 小红书 API 签名：按参数名字典序拼接 + HMAC-SHA256
        sign_str = self._app_secret + "".join(f"{k}{v}" for k, v in sorted(params.items())) + timestamp + nonce
        signature = hmac.new(
            self._app_secret.encode("utf-8"),
            sign_str.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

        headers = {
            "Authorization": f"Bearer {access_token}",
            "x-xhs-app-key": self._app_key,
            "x-timestamp": timestamp,
            "x-nonce": nonce,
            "x-sign": signature,
            "Content-Type": "application/json",
        }
        url = f"{_XHS_BASE_URL}{path}"

        import aiohttp

        async with aiohttp.ClientSession() as session:
            if method == "GET":
                req = session.get(url, params=params, headers=headers, timeout=aiohttp.ClientTimeout(total=15))
            else:
                req = session.post(url, json=params, headers=headers, timeout=aiohttp.ClientTimeout(total=15))

            async with req as resp:
                data = await resp.json()
                code = data.get("code", 0)
                if code != 0:
                    raise ValueError(f"XHS API error {code}: {data.get('msg')}")
                return data.get("data", {})
