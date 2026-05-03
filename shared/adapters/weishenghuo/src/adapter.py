"""
微生活会员管理平台适配器（i200.cn 开放平台）

Base URL: https://open.i200.cn
认证方式: appid + app_secret → access_token（Token 缓存，过期自动刷新）
响应格式: {"errcode": 0, "errmsg": "ok", "data": {...}}

环境变量：
    WSH_BASE_URL      — 默认 https://open.i200.cn
    WSH_APPID         — 应用ID
    WSH_APP_SECRET    — 应用密钥（仅用于获取 token，不随业务请求发送）
    WSH_TIMEOUT       — 超时秒数，默认 30
    WSH_RETRY_TIMES   — 重试次数，默认 3
    WSH_TENANT_ID     — 屯象租户 ID（事件发射用）
"""

import asyncio
import hashlib
import json
import os
import time
from typing import Any, Dict, List, Optional, Set

import httpx
import structlog

from shared.adapters.base.src.event_bus import emit_adapter_event
from shared.events.src.event_types import AdapterEventType

logger = structlog.get_logger()


class WeishenghuoAdapter:
    """
    微生活会员管理平台适配器。

    核心能力：
      - 会员信息查询（手机号/会员ID）
      - 会员列表分页拉取（支持增量同步）
      - 交易记录查询
      - 积分余额 & 储值余额查询
      - 门店列表查询
    """

    def __init__(self, config: Dict[str, Any]) -> None:
        self.base_url = config.get("base_url", os.getenv("WSH_BASE_URL", "https://open.i200.cn"))
        self.appid = config.get("appid", os.getenv("WSH_APPID", ""))
        self.app_secret = config.get("app_secret", os.getenv("WSH_APP_SECRET", ""))
        self.timeout = config.get("timeout", int(os.getenv("WSH_TIMEOUT", "30")))
        self.retry_times = config.get("retry_times", int(os.getenv("WSH_RETRY_TIMES", "3")))
        self._tenant_id = config.get("tenant_id", os.getenv("WSH_TENANT_ID", ""))
        self._nonce_store: Set[str] = set()

        if not self.appid or not self.app_secret:
            logger.warning("微生活 appid/app_secret 未配置，将使用降级模式")

        # Token 缓存：(token_str, expire_timestamp)
        self._access_token: Optional[str] = None
        self._token_expires_at: float = 0.0

        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=self.timeout,
            follow_redirects=True,
        )
        logger.info("微生活适配器初始化", base_url=self.base_url)

    # ── 认证 ──────────────────────────────────────────────────────────────────

    async def _get_access_token(self) -> str:
        """
        获取 access_token，带本地缓存。
        POST /auth/token  body: {"appid": "...", "app_secret": "..."}
        返回: {"errcode": 0, "data": {"access_token": "xxx", "expires_in": 7200}}

        提前 60 秒刷新，避免临界过期。
        """
        now = time.time()
        if self._access_token and now < self._token_expires_at:
            return self._access_token

        logger.info("微生活获取 access_token")
        response = await self._client.post(
            "/auth/token",
            json={"appid": self.appid, "app_secret": self.app_secret},
        )
        response.raise_for_status()
        result = response.json()

        errcode = result.get("errcode", -1)
        if errcode != 0:
            errmsg = result.get("errmsg", "未知错误")
            raise Exception(f"微生活获取 token 失败 [errcode={errcode}]: {errmsg}")

        data = result.get("data", {})
        self._access_token = data["access_token"]
        expires_in = data.get("expires_in", 7200)
        # 提前 60 秒刷新
        self._token_expires_at = now + expires_in - 60

        logger.info("微生活 access_token 获取成功", expires_in=expires_in)
        return self._access_token

    # ── 通用请求 ───────────────────────────────────────────────────────────────

    async def _request(
        self,
        method: str,
        endpoint: str,
        params: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        通用请求，带 token 认证和指数退避重试。

        微生活 API 响应格式: {"errcode": 0, "errmsg": "ok", "data": {...}}
        业务错误（errcode != 0）立即抛出，不重试。
        """
        last_exc: Optional[Exception] = None

        for attempt in range(self.retry_times):
            if attempt > 0:
                await asyncio.sleep(0.5 * (2 ** (attempt - 1)))
            try:
                token = await self._get_access_token()
                headers = {"Authorization": f"Bearer {token}"}

                if method.upper() == "GET":
                    response = await self._client.get(endpoint, params=params, headers=headers)
                else:
                    response = await self._client.post(endpoint, json=params or {}, headers=headers)

                response.raise_for_status()
                result = response.json()

                errcode = result.get("errcode", -1)
                if errcode != 0:
                    errmsg = result.get("errmsg", "未知错误")
                    raise Exception(f"微生活业务错误 [errcode={errcode}]: {errmsg}")

                return result.get("data", result)

            except (httpx.ConnectError, httpx.TimeoutException, httpx.DecodingError) as e:
                last_exc = e
                logger.warning(
                    "微生活请求失败，准备重试",
                    endpoint=endpoint,
                    attempt=attempt + 1,
                    max_attempts=self.retry_times,
                    error=str(e),
                )

        raise RuntimeError(f"微生活请求失败，已重试 {self.retry_times} 次: {last_exc}")

    async def aclose(self) -> None:
        """关闭 httpx 客户端连接"""
        await self._client.aclose()

    async def __aenter__(self) -> "WeishenghuoAdapter":
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.aclose()

    # ── 幂等性保障 ──────────────────────────────────────────────────────────────

    def idempotency_key(self, operation: str, payload: Dict[str, Any]) -> str:
        """基于 operation + payload 生成确定性幂等键。"""
        raw = f"{operation}:{self._tenant_id}:{json.dumps(payload, sort_keys=True)}"
        return hashlib.md5(raw.encode()).hexdigest()

    def is_duplicate(self, key: str) -> bool:
        return key in self._nonce_store

    def mark_idempotent(self, key: str) -> None:
        self._nonce_store.add(key)

    # ── 事件发射 ──────────────────────────────────────────────────────────────

    async def _emit_sync_event(
        self,
        event_type: AdapterEventType,
        scope: str,
        stream_id: str,
        payload: Dict[str, Any],
    ) -> None:
        """发射适配器事件（fire-and-forget，失败只记 warning）。"""
        try:
            await emit_adapter_event(
                adapter_name="weishenghuo",
                event_type=event_type,
                tenant_id=self._tenant_id,
                scope=scope,
                stream_id=stream_id,
                payload=payload,
            )
        except Exception:  # noqa: BLE001 — 事件发射失败不阻断主流程
            logger.warning("weishenghuo.event_emit_failed", scope=scope, stream_id=stream_id)

    # ── 会员接口 ───────────────────────────────────────────────────────────────

    async def get_member_info(
        self,
        mobile: Optional[str] = None,
        member_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        获取会员详情（积分、余额、等级、卡号等）。
        mobile 与 member_id 至少填写一个。

        Args:
            mobile:    手机号
            member_id: 会员ID

        Returns:
            会员信息字典，包含 points / balance / level / card_no 等字段。
            查询失败时返回空字典。
        """
        if not mobile and not member_id:
            raise ValueError("mobile 和 member_id 至少填写一个")

        params: Dict[str, Any] = {}
        if mobile:
            params["mobile"] = mobile
        if member_id:
            params["member_id"] = member_id

        logger.info("获取微生活会员信息", mobile=mobile, member_id=member_id)
        try:
            result = await self._request("GET", "/member/info", params)
            asyncio.create_task(
                self._emit_sync_event(
                    event_type=AdapterEventType.MEMBER_SYNCED,
                    scope="member_info",
                    stream_id=f"weishenghuo:member:{member_id or mobile}",
                    payload=result,
                )
            )
            return result
        except (httpx.HTTPError, RuntimeError, ValueError) as e:
            logger.warning("获取微生活会员信息失败", error=str(e), exc_info=True)
            return {}

    async def list_members(
        self,
        page: int = 1,
        page_size: int = 100,
        updated_after: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        分页拉取会员列表，支持增量同步。

        Args:
            page:          页码，从 1 开始
            page_size:     每页条数，最大 100
            updated_after: 增量同步起始时间（ISO 格式，如 "2026-03-01"），
                          仅返回该时间之后有变更的会员

        Returns:
            {"list": [...], "total": N, "page": P, "page_size": S}
        """
        params: Dict[str, Any] = {
            "page": page,
            "page_size": min(page_size, 100),
        }
        if updated_after:
            params["updated_after"] = updated_after

        logger.info(
            "拉取微生活会员列表",
            page=page,
            page_size=page_size,
            updated_after=updated_after,
        )
        try:
            result = await self._request("GET", "/member/list", params)
            asyncio.create_task(
                self._emit_sync_event(
                    event_type=AdapterEventType.MEMBER_SYNCED,
                    scope="member_list",
                    stream_id=f"weishenghuo:member_list:{page}",
                    payload={"page": page, "page_size": page_size, "total": result.get("total", 0)},
                )
            )
            return result
        except (httpx.HTTPError, RuntimeError, ValueError) as e:
            logger.warning("拉取微生活会员列表失败", error=str(e), exc_info=True)
            return {"list": [], "total": 0, "page": page, "page_size": page_size}

    async def get_member_transactions(
        self,
        member_id: str,
        start_date: str,
        end_date: str,
        page: int = 1,
    ) -> Dict[str, Any]:
        """
        查询会员交易记录。

        Args:
            member_id:  会员ID
            start_date: 起始日期（如 "2026-03-01"）
            end_date:   结束日期（如 "2026-03-17"）
            page:       页码，从 1 开始

        Returns:
            {"list": [...], "total": N, "page": P}
            金额字段单位为分（fen），调用方按需转换为元。
        """
        params: Dict[str, Any] = {
            "member_id": member_id,
            "start_date": start_date,
            "end_date": end_date,
            "page": page,
        }
        logger.info(
            "查询微生活会员交易记录",
            member_id=member_id,
            start_date=start_date,
            end_date=end_date,
        )
        try:
            result = await self._request("GET", "/member/transactions", params)
            asyncio.create_task(
                self._emit_sync_event(
                    event_type=AdapterEventType.SYNC_FINISHED,
                    scope="member_transactions",
                    stream_id=f"weishenghuo:transactions:{member_id}",
                    payload={"member_id": member_id, "start_date": start_date, "end_date": end_date},
                )
            )
            return result
        except (httpx.HTTPError, RuntimeError, ValueError) as e:
            logger.warning("查询微生活会员交易记录失败", error=str(e), exc_info=True)
            return {"list": [], "total": 0, "page": page}

    async def get_member_points(self, member_id: str) -> Dict[str, Any]:
        """
        查询会员积分余额及变动历史。

        Args:
            member_id: 会员ID

        Returns:
            {"balance": N, "history": [...]}
            balance 为当前可用积分。
        """
        logger.info("查询微生活会员积分", member_id=member_id)
        try:
            result = await self._request("GET", "/member/points", {"member_id": member_id})
            asyncio.create_task(
                self._emit_sync_event(
                    event_type=AdapterEventType.SYNC_FINISHED,
                    scope="member_points",
                    stream_id=f"weishenghuo:points:{member_id}",
                    payload={"member_id": member_id, "balance": result.get("balance", 0)},
                )
            )
            return result
        except (httpx.HTTPError, RuntimeError, ValueError) as e:
            logger.warning("查询微生活会员积分失败", error=str(e), exc_info=True)
            return {"balance": 0, "history": []}

    async def get_member_stored_value(self, member_id: str) -> Dict[str, Any]:
        """
        查询会员储值余额。

        Args:
            member_id: 会员ID

        Returns:
            {"balance": N}
            balance 单位为分（fen）。
        """
        logger.info("查询微生活会员储值余额", member_id=member_id)
        try:
            result = await self._request("GET", "/member/stored-value", {"member_id": member_id})
            asyncio.create_task(
                self._emit_sync_event(
                    event_type=AdapterEventType.SYNC_FINISHED,
                    scope="member_stored_value",
                    stream_id=f"weishenghuo:stored_value:{member_id}",
                    payload={"member_id": member_id, "balance": result.get("balance", 0)},
                )
            )
            return result
        except (httpx.HTTPError, RuntimeError, ValueError) as e:
            logger.warning("查询微生活会员储值余额失败", error=str(e), exc_info=True)
            return {"balance": 0}

    async def get_shop_list(self) -> List[Dict[str, Any]]:
        """
        获取当前账号下所有门店列表。

        Returns:
            门店列表 [{"shop_id": "...", "shop_name": "...", ...}, ...]
        """
        logger.info("获取微生活门店列表")
        try:
            result = await self._request("GET", "/shop/list", {})
            asyncio.create_task(
                self._emit_sync_event(
                    event_type=AdapterEventType.SYNC_FINISHED,
                    scope="shop_list",
                    stream_id="weishenghuo:shop_list",
                    payload={},
                )
            )
            # API 可能返回 {"list": [...]} 或直接返回列表
            if isinstance(result, list):
                return result
            return result.get("list", [])
        except (httpx.HTTPError, RuntimeError, ValueError) as e:
            logger.warning("获取微生活门店列表失败", error=str(e), exc_info=True)
            return []
