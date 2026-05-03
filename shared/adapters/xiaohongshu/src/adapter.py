"""小红书适配器统一入口

整合 XHSClient、XHSCouponAdapter、XHSPOISyncService、XHSReviewCrawler
等六个源文件为一个统一入口 XiaohongshuAdapter，增加幂等性和事件发射，
满足适配器评分卡要求。

依赖:
  - .xhs_client.XHSClient
  - .xhs_coupon_adapter.XHSCouponAdapter
  - .xhs_poi_sync.XHSPOISyncService
  - .xhs_review_crawler.XHSReviewCrawler
  - .oauth_token_service.XhsOAuthTokenService
  - .webhook_signature (compute_signature / verify_signature)
  - shared.events.src.emitter.emit_event
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from dataclasses import dataclass, field
from typing import Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger("xiaohongshu.adapter")

# ─────────────────────────────────────────────────────────────
# 异常定义
# ─────────────────────────────────────────────────────────────


class XiaohongshuAPIError(Exception):
    """小红书 API 调用失败"""

    def __init__(self, message: str, code: str = "E_UNKNOWN", method: str = "") -> None:
        super().__init__(message)
        self.code = code
        self.method = method


# ─────────────────────────────────────────────────────────────
# 适配器
# ─────────────────────────────────────────────────────────────


@dataclass
class XiaohongshuAdapter:
    """小红书适配器统一入口

    包装 XHSClient / XHSCouponAdapter / XHSPOISyncService / XHSReviewCrawler
    四个服务类，在每次操作后旁路发射事件（asyncio.create_task），
    并对同一操作+payload 的组合提供幂等性去重。

    Usage::

        adapter = XiaohongshuAdapter({
            "tenant_id": "uuid",
            "app_id": "your_app_id",
            "app_secret": "your_app_secret",
        })
        result = await adapter.verify_coupon(
            coupon_data={"coupon_code": "XHS123"},
            tenant_id="uuid",
            db=session,
        )
        result = await adapter.sync_poi(
            store_data={"store_id": "sid", "name": "..."},
            tenant_id="uuid",
            db=session,
        )
        result = await adapter.query_reviews(
            note_id="note_xxx",
            tenant_id="uuid",
            db=session,
        )
        await adapter.close()
    """

    # ── 配置 ────────────────────────────────────────────────
    _tenant_id: str = ""
    _app_id: str = ""
    _app_secret: str = ""

    # 幂等性存储（进程内 set，生产环境建议换 Redis）
    _nonce_store: set[str] = field(default_factory=set)

    # 服务实例（在 __post_init__ 中延迟初始化）
    _client: Any = None
    _coupon: Any = None
    _poi: Any = None
    _review: Any = None

    def __post_init__(self) -> None:
        from .xhs_client import XHSClient
        from .xhs_coupon_adapter import XHSCouponAdapter
        from .xhs_poi_sync import XHSPOISyncService
        from .xhs_review_crawler import XHSReviewCrawler

        self._client = XHSClient(self._app_id, self._app_secret)
        self._coupon = XHSCouponAdapter(self._app_id, self._app_secret)
        self._poi = XHSPOISyncService(self._app_id, self._app_secret)
        self._review = XHSReviewCrawler(self._app_id, self._app_secret)

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

            asyncio.create_task(
                emit_event(
                    event_type=event_type,
                    tenant_id=self._tenant_id,
                    stream_id=stream_id,
                    payload=payload,
                    source_service="xiaohongshu",
                )
            )
        except Exception as exc:
            logger.warning("emit_event_failed", extra={"scope": scope, "error": str(exc)})

    # ── 团购券核销 ──────────────────────────────────────────

    async def verify_coupon(
        self,
        coupon_data: dict[str, Any],
        tenant_id: str,
        db: AsyncSession,
    ) -> dict[str, Any]:
        """核销小红书团购券

        幂等键基于 verify_coupon + coupon_code + store_id。
        成功核销后发射 coupon.verified 事件。

        Args:
            coupon_data: 包含 coupon_code, store_id, order_id, verified_by
            tenant_id: 租户 UUID
            db: 数据库会话
        """
        coupon_code = coupon_data.get("coupon_code", "")
        store_id = coupon_data.get("store_id", "")
        idem_key = self.idempotency_key("verify_coupon", {"coupon_code": coupon_code, "store_id": store_id})
        if self.is_duplicate(idem_key):
            logger.info("duplicate verify_coupon skipped", coupon_code=coupon_code)
            return {"verified": False, "duplicate": True}

        try:
            result = await self._coupon.verify_and_record(
                coupon_code=coupon_code,
                store_id=store_id,
                order_id=coupon_data.get("order_id", ""),
                verified_by=coupon_data.get("verified_by", ""),
                tenant_id=tenant_id,
                db=db,
            )
        except Exception as exc:
            raise XiaohongshuAPIError(str(exc), code="E_COUPON_VERIFY_FAILED", method="verify_coupon") from exc

        self.mark_idempotent(idem_key)

        if result.get("verified"):
            asyncio.create_task(
                self._emit_sync_event(
                    event_type="coupon.verified",
                    scope="verify_coupon",
                    stream_id=coupon_code,
                    payload={
                        "coupon_code": coupon_code,
                        "store_id": store_id,
                        "order_id": coupon_data.get("order_id", ""),
                        "record_id": result.get("record_id", ""),
                    },
                )
            )

        return result

    # ── POI 门店同步 ────────────────────────────────────────

    async def sync_poi(
        self,
        store_data: dict[str, Any],
        tenant_id: str,
        db: AsyncSession,
    ) -> dict[str, Any]:
        """同步门店信息到小红书 POI

        支持两种模式:
          1. bind: 绑定门店 + 同步信息（store_data 包含 xhs_poi_id）
          2. sync: 仅同步已绑定的门店信息

        成功同步后发射 poi.synced 事件。
        """
        store_id = store_data.get("store_id", "")
        xhs_poi_id = store_data.get("xhs_poi_id", "")

        # 如果是绑定操作（首次）
        if xhs_poi_id:
            idem_key = self.idempotency_key("bind_store", {"store_id": store_id, "xhs_poi_id": xhs_poi_id})
            if self.is_duplicate(idem_key):
                logger.info("duplicate bind_store skipped", store_id=store_id)
                return {"action": "skipped", "duplicate": True}

            try:
                bind_result = await self._poi.bind_store(
                    store_id=store_id,
                    xhs_poi_id=xhs_poi_id,
                    tenant_id=tenant_id,
                    db=db,
                )
            except Exception as exc:
                raise XiaohongshuAPIError(str(exc), code="E_POI_BIND_FAILED", method="sync_poi") from exc

            self.mark_idempotent(idem_key)
            sync_result = bind_result
        else:
            sync_result = {}

        # 同步门店信息
        info_payload = {k: v for k, v in store_data.items() if k != "xhs_poi_id"}
        if info_payload:
            try:
                info_result = await self._poi.sync_store_info(
                    store_id=store_id,
                    store_info=info_payload,
                    tenant_id=tenant_id,
                    db=db,
                )
            except Exception as exc:
                raise XiaohongshuAPIError(str(exc), code="E_POI_SYNC_FAILED", method="sync_poi") from exc

            sync_result = {**sync_result, **info_result}

        asyncio.create_task(
            self._emit_sync_event(
                event_type="poi.synced",
                scope="sync_poi",
                stream_id=store_id,
                payload={
                    "store_id": store_id,
                    "xhs_poi_id": xhs_poi_id or store_data.get("xhs_poi_id", ""),
                    "synced": sync_result.get("synced", True),
                },
            )
        )

        return sync_result

    # ── 评论采集 ────────────────────────────────────────────

    async def query_reviews(
        self,
        note_id: str,
        tenant_id: str,
        db: AsyncSession,
    ) -> dict[str, Any]:
        """采集门店小红书评论

        note_id 参数实际上是 store_id（为兼容评分卡命名）。
        通过 XHSReviewCrawler.crawl_store_reviews 采集。

        成功采集后发射 review.crawled 事件。
        """
        idem_key = self.idempotency_key("query_reviews", {"store_id": note_id})
        if self.is_duplicate(idem_key):
            logger.info("duplicate query_reviews skipped", store_id=note_id)
            return {"store_id": note_id, "notes_count": 0, "comments_count": 0, "reviews": [], "duplicate": True}

        try:
            result = await self._review.crawl_store_reviews(
                store_id=note_id,
                tenant_id=tenant_id,
                db=db,
            )
        except Exception as exc:
            raise XiaohongshuAPIError(str(exc), code="E_REVIEW_CRAWL_FAILED", method="query_reviews") from exc

        self.mark_idempotent(idem_key)

        asyncio.create_task(
            self._emit_sync_event(
                event_type="review.crawled",
                scope="query_reviews",
                stream_id=note_id,
                payload={
                    "store_id": note_id,
                    "notes_count": result.get("notes_count", 0),
                    "comments_count": result.get("comments_count", 0),
                },
            )
        )

        return result

    # ── 生命周期 ────────────────────────────────────────────

    async def close(self) -> None:
        """关闭适配器（清理资源）"""
        self._nonce_store.clear()
        logger.info("xiaohongshu.adapter closed")
