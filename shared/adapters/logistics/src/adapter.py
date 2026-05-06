"""物流查询适配器 — Kuaidi100

为 Kuaidi100Client 提供适配器包装，增加幂等性、事件发射和统一错误处理，
满足适配器评分卡要求。

依赖:
  - .kuaidi100_client.Kuaidi100Client
  - shared.events.src.emitter.emit_event
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from dataclasses import dataclass, field
from typing import Any, Optional

logger = logging.getLogger("logistics.adapter")

# ─────────────────────────────────────────────────────────────
# 异常定义
# ─────────────────────────────────────────────────────────────


class LogisticsAPIError(Exception):
    """物流 API 调用失败"""

    def __init__(self, message: str, code: str = "E_UNKNOWN", method: str = "") -> None:
        super().__init__(message)
        self.code = code
        self.method = method


# ─────────────────────────────────────────────────────────────
# 适配器
# ─────────────────────────────────────────────────────────────


@dataclass
class LogisticsAdapter:
    """快递 100 物流查询适配器

    包装 Kuaidi100Client，在每次查询后旁路发射事件（asyncio.create_task），
    并对同一操作+payload的组合提供幂等性去重。

    Usage::

        adapter = LogisticsAdapter({
            "tenant_id": "uuid",
            "customer": "your_customer",
            "key": "your_key",
        })
        result = await adapter.query_track("SF1234567890", "shunfeng")
        await adapter.close()
    """

    # ── 配置 ────────────────────────────────────────────────
    _tenant_id: str = ""
    _customer: str = ""
    _key: str = ""

    # 幂等性存储（进程内 set，生产环境建议换 Redis）
    _nonce_store: set[str] = field(default_factory=set)

    # 在 __post_init__ 中延迟导入并初始化
    _client: Any = None

    def __post_init__(self) -> None:
        from .kuaidi100_client import Kuaidi100Client

        self._client = Kuaidi100Client(self._customer, self._key)

    # ── 幂等性 ──────────────────────────────────────────────

    def idempotency_key(self, operation: str, payload: dict[str, Any]) -> str:
        """生成幂等键: SHA256(operation + sorted_json(payload))"""
        raw = operation + json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def is_duplicate(self, key: str) -> bool:
        return key in self._nonce_store

    def mark_idempotent(self, key: str) -> None:
        self._nonce_store.add(key)

    # ── 事件发射 ────────────────────────────────────────────

    async def _emit_sync_event(
        self,
        event_type: object,
        scope: str,
        stream_id: str,
        payload: dict[str, Any],
    ) -> None:
        """旁路发射事件，不阻塞调用方。"""
        try:
            from shared.events.src.emitter import emit_event

            # 用 create_task 避免阻塞
            asyncio.create_task(
                emit_event(
                    event_type=event_type,
                    tenant_id=self._tenant_id,
                    stream_id=stream_id,
                    payload=payload,
                    source_service="logistics",
                )
            )
        except Exception as exc:
            logger.warning("emit_event_failed", extra={"scope": scope, "error": str(exc)})

    # ── 业务方法 ────────────────────────────────────────────

    async def query_track(
        self,
        tracking_no: str,
        carrier_code: str = "",
    ) -> dict[str, Any]:
        """查询物流轨迹

        幂等键基于 query_track + tracking_no + carrier_code。
        成功查询后发射 logistics.track_queried 事件。
        """
        idem_key = self.idempotency_key("query_track", {"tracking_no": tracking_no, "carrier_code": carrier_code})
        if self.is_duplicate(idem_key):
            logger.info("duplicate query_track skipped", tracking_no=tracking_no)
            return {"status": "ok", "duplicate": True, "tracking_no": tracking_no}

        try:
            result = await self._client.query_track(tracking_no, carrier_code)
        except Exception as exc:
            raise LogisticsAPIError(str(exc), code="E_QUERY_FAILED", method="query_track") from exc

        if result.get("status") != "ok":
            raise LogisticsAPIError(
                result.get("message", "unknown error"),
                code="E_QUERY_FAILED",
                method="query_track",
            )

        self.mark_idempotent(idem_key)

        # 旁路发射事件
        asyncio.create_task(
            self._emit_sync_event(
                event_type="logistics.track_queried",
                scope="query_track",
                stream_id=tracking_no,
                payload={
                    "tracking_no": tracking_no,
                    "carrier_code": carrier_code or result.get("carrier_code", ""),
                    "state": result.get("state", ""),
                },
            )
        )

        return result

    async def auto_detect(self, tracking_no: str) -> dict[str, Any]:
        """自动识别快递公司

        成功识别后发射 logistics.auto_detected 事件。
        """
        idem_key = self.idempotency_key("auto_detect", {"tracking_no": tracking_no})
        if self.is_duplicate(idem_key):
            logger.info("duplicate auto_detect skipped", tracking_no=tracking_no)
            return {"carrier_code": "", "carrier_name": "", "duplicate": True}

        try:
            result = await self._client.auto_detect(tracking_no)
        except Exception as exc:
            raise LogisticsAPIError(str(exc), code="E_AUTO_DETECT_FAILED", method="auto_detect") from exc

        self.mark_idempotent(idem_key)

        asyncio.create_task(
            self._emit_sync_event(
                event_type="logistics.auto_detected",
                scope="auto_detect",
                stream_id=tracking_no,
                payload={
                    "tracking_no": tracking_no,
                    "carrier_code": result.get("carrier_code", ""),
                    "carrier_name": result.get("carrier_name", ""),
                },
            )
        )

        return result

    async def subscribe_push(
        self,
        tracking_no: str,
        carrier_code: str,
        callback_url: str,
    ) -> dict[str, Any]:
        """订阅物流推送

        幂等键基于 subscribe_push + tracking_no + carrier_code。
        成功订阅后发射 logistics.subscribed 事件。
        """
        idem_key = self.idempotency_key(
            "subscribe_push",
            {"tracking_no": tracking_no, "carrier_code": carrier_code, "callback_url": callback_url},
        )
        if self.is_duplicate(idem_key):
            logger.info("duplicate subscribe_push skipped", tracking_no=tracking_no)
            return {"status": "ok", "subscribed": True, "duplicate": True}

        try:
            result = await self._client.subscribe_push(tracking_no, carrier_code, callback_url)
        except Exception as exc:
            raise LogisticsAPIError(str(exc), code="E_SUBSCRIBE_FAILED", method="subscribe_push") from exc

        self.mark_idempotent(idem_key)

        asyncio.create_task(
            self._emit_sync_event(
                event_type="logistics.subscribed",
                scope="subscribe_push",
                stream_id=tracking_no,
                payload={
                    "tracking_no": tracking_no,
                    "carrier_code": carrier_code,
                    "callback_url": callback_url,
                },
            )
        )

        return result

    async def close(self) -> None:
        """关闭适配器（清理资源）"""
        self._nonce_store.clear()
        logger.info("logistics.adapter closed")
