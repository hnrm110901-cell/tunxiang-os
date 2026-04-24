"""小红书开放平台 HTTP 客户端

认证方式：OAuth2 + 请求签名（SHA256）
API Base: https://ark.xiaohongshu.com/ark/open_api/v3

签名规则：
  1. 按 key 字典序排列参数
  2. 拼接为 key=value&key=value 字符串
  3. 追加 app_secret
  4. SHA256 哈希
"""

from __future__ import annotations

import hashlib
import time
import uuid
from typing import Any, Optional

import structlog

logger = structlog.get_logger(__name__)

XHS_API_BASE = "https://ark.xiaohongshu.com/ark/open_api/v3"


class XHSClient:
    """小红书开放平台客户端"""

    def __init__(self, app_id: str, app_secret: str) -> None:
        self.app_id = app_id
        self.app_secret = app_secret
        self._access_token: Optional[str] = None
        self._token_expires_at: float = 0.0

    def _sign(self, params: dict[str, str]) -> str:
        """生成请求签名"""
        sorted_keys = sorted(params.keys())
        sign_str = "&".join(f"{k}={params[k]}" for k in sorted_keys)
        sign_str += self.app_secret
        return hashlib.sha256(sign_str.encode("utf-8")).hexdigest()

    def _build_common_params(self) -> dict[str, str]:
        """构建公共请求参数"""
        return {
            "app_id": self.app_id,
            "timestamp": str(int(time.time())),
            "nonce": uuid.uuid4().hex[:16],
        }

    async def _request(
        self,
        method: str,
        path: str,
        params: Optional[dict] = None,
        body: Optional[dict] = None,
    ) -> dict[str, Any]:
        """发送签名请求到小红书开放平台

        生产环境使用 httpx.AsyncClient 发送真实请求。
        当前为占位实现，返回模拟响应。
        """
        common = self._build_common_params()
        if params:
            common.update({k: str(v) for k, v in params.items()})
        common["sign"] = self._sign(common)

        url = f"{XHS_API_BASE}{path}"
        logger.info(
            "xhs_api_request",
            method=method,
            url=url,
            app_id=self.app_id,
        )

        # TODO: 替换为 httpx.AsyncClient 真实请求
        # async with httpx.AsyncClient() as client:
        #     if method == "GET":
        #         resp = await client.get(url, params=common)
        #     else:
        #         resp = await client.post(url, params=common, json=body)
        #     resp.raise_for_status()
        #     return resp.json()

        return {"code": 0, "msg": "ok", "data": {}}

    # ── 团购券核销 ────────────────────────────────────────────

    async def verify_coupon(self, coupon_code: str, shop_id: str) -> dict[str, Any]:
        """核销小红书团购券

        Returns:
            {"verified": bool, "coupon_info": {...}, "error": str|None}
        """
        result = await self._request(
            "POST",
            "/coupon/verify",
            body={"coupon_code": coupon_code, "shop_id": shop_id},
        )
        if result.get("code") != 0:
            return {
                "verified": False,
                "error": result.get("msg", "unknown_error"),
            }
        return {
            "verified": True,
            "coupon_info": result.get("data", {}),
            "error": None,
        }

    async def query_coupon(self, coupon_code: str) -> dict[str, Any]:
        """查询团购券状态"""
        return await self._request(
            "GET",
            "/coupon/query",
            params={"coupon_code": coupon_code},
        )

    # ── POI 门店同步 ─────────────────────────────────────────

    async def sync_poi(
        self,
        poi_id: str,
        store_info: dict,
    ) -> dict[str, Any]:
        """同步门店信息到小红书 POI"""
        return await self._request(
            "POST",
            "/poi/update",
            body={"poi_id": poi_id, **store_info},
        )

    async def get_poi_info(self, poi_id: str) -> dict[str, Any]:
        """查询小红书 POI 信息"""
        return await self._request(
            "GET",
            "/poi/info",
            params={"poi_id": poi_id},
        )

    # ── 评论/笔记 ────────────────────────────────────────────

    async def get_store_notes(
        self,
        poi_id: str,
        page: int = 1,
        size: int = 20,
    ) -> dict[str, Any]:
        """获取门店关联的小红书笔记"""
        return await self._request(
            "GET",
            "/content/notes",
            params={"poi_id": poi_id, "page": page, "size": size},
        )

    async def get_note_comments(
        self,
        note_id: str,
        page: int = 1,
        size: int = 20,
    ) -> dict[str, Any]:
        """获取笔记评论"""
        return await self._request(
            "GET",
            "/content/comments",
            params={"note_id": note_id, "page": page, "size": size},
        )
