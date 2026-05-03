"""Webhook 订阅与投递服务 — 第三方开发者事件通知

支持：
  - 订阅管理（CRUD）
  - 事件投递（HTTP POST + HMAC 签名）
  - 自动重试（指数退避）
  - 投递日志
"""
import hashlib
import hmac
import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import httpx
import structlog

logger = structlog.get_logger()

SUBSCRIPTIONS_TABLE = "webhook_subscriptions"
DELIVERY_LOGS_TABLE = "webhook_delivery_logs"

# 最大重试次数
MAX_RETRY_COUNT = 5
# 指数退避基数（秒）
RETRY_BASE_SECONDS = 60


class WebhookNotFoundError(LookupError):
    """Webhook 订阅不存在"""


class WebhookService:
    """Webhook 订阅管理 + 事件投递"""

    def __init__(self, db, tenant_id: str):
        self.db = db
        self.tenant_id = tenant_id

    # ── 订阅管理 ──────────────────────────────────────────────────────────

    async def create_subscription(
        self,
        url: str,
        events: list[str],
        secret: Optional[str] = None,
        api_key_id: Optional[uuid.UUID] = None,
        retry_count: int = 3,
        timeout_ms: int = 5000,
    ) -> dict[str, Any]:
        """创建 Webhook 订阅。"""
        sub_id = uuid.uuid4()
        await self.db.execute(
            f"INSERT INTO {SUBSCRIPTIONS_TABLE} "
            f"(id, tenant_id, api_key_id, url, secret, events, status, retry_count, timeout_ms) "
            f"VALUES (:id, :tenant_id, :api_key_id, :url, :secret, :events, 'active', :retry_count, :timeout_ms)",
            {
                "id": sub_id,
                "tenant_id": self.tenant_id,
                "api_key_id": api_key_id,
                "url": url,
                "secret": secret or "",
                "events": events,
                "retry_count": min(retry_count, MAX_RETRY_COUNT),
                "timeout_ms": timeout_ms,
            },
        )
        await self.db.commit()
        logger.info("webhook.created", sub_id=str(sub_id), tenant_id=self.tenant_id, url=url)
        return {
            "id": str(sub_id),
            "url": url,
            "events": events,
            "status": "active",
            "retry_count": retry_count,
            "timeout_ms": timeout_ms,
        }

    async def list_subscriptions(self) -> list[dict[str, Any]]:
        """列出租户下的 Webhook 订阅。"""
        result = await self.db.execute(
            f"SELECT id, url, events, status, retry_count, timeout_ms, created_at "
            f"FROM {SUBSCRIPTIONS_TABLE} "
            f"WHERE tenant_id = :tenant_id AND is_deleted = FALSE "
            f"ORDER BY created_at DESC",
            {"tenant_id": self.tenant_id},
        )
        rows = result.fetchall()
        return [dict(row._mapping) for row in rows]

    async def delete_subscription(self, sub_id: uuid.UUID) -> None:
        """删除 Webhook 订阅（软删除）。"""
        result = await self.db.execute(
            f"UPDATE {SUBSCRIPTIONS_TABLE} SET is_deleted = TRUE, updated_at = :now "
            f"WHERE id = :id AND tenant_id = :tenant_id RETURNING id",
            {
                "id": sub_id,
                "tenant_id": self.tenant_id,
                "now": datetime.now(timezone.utc),
            },
        )
        if not result.fetchone():
            raise WebhookNotFoundError(f"Webhook {sub_id} 不存在")
        await self.db.commit()
        logger.info("webhook.deleted", sub_id=str(sub_id))

    # ── 事件投递 ──────────────────────────────────────────────────────────

    @staticmethod
    def _sign_payload(payload: str, secret: str) -> str:
        """HMAC-SHA256 签名 payload。"""
        return hmac.new(
            secret.encode(), payload.encode(), hashlib.sha256
        ).hexdigest()

    async def deliver_event(
        self,
        event_type: str,
        payload: dict[str, Any],
        db_session=None,
    ) -> int:
        """投递事件到所有匹配的活跃订阅。

        Args:
            event_type: 事件类型（如 "order.paid"）
            payload: 事件数据
            db_session: 可选，用于记录投递日志

        Returns:
            匹配的订阅数
        """
        result = await self.db.execute(
            f"SELECT id, url, secret, retry_count, timeout_ms "
            f"FROM {SUBSCRIPTIONS_TABLE} "
            f"WHERE status = 'active' AND is_deleted = FALSE "
            f"AND (events @> :event_type OR events @> '[\"*\"]')",
            {"event_type": json.dumps([event_type])},
        )
        subs = result.fetchall()

        if not subs:
            return 0

        async with httpx.AsyncClient(timeout=30) as client:
            for sub in subs:
                sub_id = sub.id
                url = sub.url
                secret = sub.secret or ""
                retry_count = sub.retry_count
                timeout_ms = sub.timeout_ms

                body = json.dumps(
                    {
                        "event_type": event_type,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "payload": payload,
                    },
                    ensure_ascii=False,
                )
                signature = self._sign_payload(body, secret)

                try:
                    resp = await client.post(
                        url,
                        content=body,
                        headers={
                            "Content-Type": "application/json",
                            "X-Webhook-Signature": signature,
                            "X-Webhook-Event": event_type,
                            "User-Agent": "TunxiangOS-Webhook/1.0",
                        },
                        timeout=timeout_ms / 1000,
                    )
                    log_status = "delivered" if resp.is_success else "failed"
                    logger.info(
                        "webhook.delivered",
                        sub_id=str(sub_id),
                        event=event_type,
                        status=resp.status_code,
                    )
                    await self._log_delivery(
                        sub_id, event_type, body, log_status, resp.status_code, resp.text
                    )
                except httpx.TimeoutException:
                    logger.warning("webhook.timeout", sub_id=str(sub_id), url=url)
                    await self._log_delivery(sub_id, event_type, body, "timeout", None, None)
                    await self._schedule_retry(sub_id, retry_count)
                except httpx.RequestError as exc:
                    logger.warning("webhook.network_error", sub_id=str(sub_id), error=str(exc))
                    await self._log_delivery(sub_id, event_type, body, "network_error", None, None)
                    await self._schedule_retry(sub_id, retry_count)

        return len(subs)

    async def _log_delivery(
        self,
        sub_id: uuid.UUID,
        event_type: str,
        payload: str,
        status: str,
        http_status: Optional[int],
        response_body: Optional[str],
    ) -> None:
        """记录投递日志。"""
        log_id = uuid.uuid4()
        await self.db.execute(
            f"INSERT INTO {DELIVERY_LOGS_TABLE} "
            f"(id, subscription_id, tenant_id, event_type, payload, status, "
            f"http_status, response_body, attempt) "
            f"VALUES (:id, :sub_id, :tenant_id, :event_type, :payload::json, "
            f":status, :http_status, :response_body, 1)",
            {
                "id": log_id,
                "sub_id": sub_id,
                "tenant_id": self.tenant_id,
                "event_type": event_type,
                "payload": payload,
                "status": status,
                "http_status": http_status,
                "response_body": response_body[:1000] if response_body else None,
            },
        )
        await self.db.commit()

    async def _schedule_retry(self, sub_id: uuid.UUID, max_retries: int) -> None:
        """安排重试（将现有 failed/timeout 日志的 next_retry_at 设为指数退避）。"""
        for attempt in range(1, max_retries + 1):
            delay = RETRY_BASE_SECONDS * (2 ** (attempt - 1))
            next_retry = datetime.now(timezone.utc) + timedelta(seconds=delay)
            await self.db.execute(
                f"UPDATE {DELIVERY_LOGS_TABLE} "
                f"SET next_retry_at = :next_retry, attempt = :attempt "
                f"WHERE subscription_id = :sub_id AND status IN ('failed', 'timeout', 'network_error') "
                f"AND attempt = :current_attempt",
                {
                    "next_retry": next_retry,
                    "attempt": attempt,
                    "sub_id": sub_id,
                    "current_attempt": attempt - 1,
                },
            )
        await self.db.commit()

    async def retry_failed_deliveries(self) -> int:
        """重试所有到期的失败投递（由定时任务调用）。"""
        now = datetime.now(timezone.utc)
        result = await self.db.execute(
            f"SELECT dl.id, dl.subscription_id, dl.event_type, dl.payload, "
            f"s.url, s.secret, s.timeout_ms "
            f"FROM {DELIVERY_LOGS_TABLE} dl "
            f"JOIN {SUBSCRIPTIONS_TABLE} s ON dl.subscription_id = s.id "
            f"WHERE dl.status IN ('failed', 'timeout', 'network_error') "
            f"AND dl.next_retry_at <= :now "
            f"AND dl.attempt < s.retry_count "
            f"LIMIT 50",
            {"now": now},
        )
        logs = result.fetchall()
        if not logs:
            return 0

        async with httpx.AsyncClient(timeout=30) as client:
            for log_row in logs:
                await self._retry_one(log_row, client)

        return len(logs)

    async def _retry_one(self, log_row, client: httpx.AsyncClient) -> None:
        """重试单条投递。"""
        log_id = log_row.id
        url = log_row.url
        secret = log_row.secret or ""
        payload = log_row.payload
        timeout_ms = log_row.timeout_ms
        event_type = log_row.event_type

        if isinstance(payload, str):
            body = payload
        else:
            body = json.dumps(payload, ensure_ascii=False)

        signature = self._sign_payload(body, secret)

        try:
            resp = await client.post(
                url,
                content=body,
                headers={
                    "Content-Type": "application/json",
                    "X-Webhook-Signature": signature,
                    "X-Webhook-Event": event_type,
                    "User-Agent": "TunxiangOS-Webhook/1.0",
                },
                timeout=(timeout_ms or 5000) / 1000,
            )
            new_status = "delivered" if resp.is_success else "failed"
            await self.db.execute(
                f"UPDATE {DELIVERY_LOGS_TABLE} SET status = :status, "
                f"http_status = :http_status, response_body = :body, "
                f"delivered_at = :now "
                f"WHERE id = :id",
                {
                    "status": new_status,
                    "http_status": resp.status_code,
                    "body": resp.text[:1000],
                    "now": datetime.now(timezone.utc),
                    "id": log_id,
                },
            )
            await self.db.commit()
        except Exception as exc:
            logger.warning("webhook.retry_failed", log_id=str(log_id), error=str(exc))

    # ── 投递日志查询 ──────────────────────────────────────────────────────

    async def get_delivery_logs(
        self,
        status_filter: Optional[str] = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """查询投递日志。"""
        query = (
            f"SELECT dl.id, dl.subscription_id, dl.event_type, dl.status, "
            f"dl.http_status, dl.attempt, dl.delivered_at, dl.created_at, "
            f"s.url "
            f"FROM {DELIVERY_LOGS_TABLE} dl "
            f"JOIN {SUBSCRIPTIONS_TABLE} s ON dl.subscription_id = s.id "
            f"WHERE dl.tenant_id = :tenant_id"
        )
        params: dict[str, Any] = {"tenant_id": self.tenant_id}

        if status_filter:
            query += " AND dl.status = :status"
            params["status"] = status_filter

        query += " ORDER BY dl.created_at DESC LIMIT :limit"
        params["limit"] = limit

        result = await self.db.execute(query, params)
        rows = result.fetchall()
        return [dict(row._mapping) for row in rows]
