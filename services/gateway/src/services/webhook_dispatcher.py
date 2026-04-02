"""Webhook推送服务 — 带HMAC-SHA256签名的事件推送

签名格式: X-TunXiang-Signature: sha256=<hmac_hex>
Body格式: {"event": "order.completed", "data": {...}, "timestamp": "2026-03-31T..."}

推送策略:
  - 并发推送所有订阅该事件的webhook（asyncio.gather）
  - 单个webhook失败时指数退避重试（最多retry_count次）
  - 推送结果写回last_triggered_at和last_status
"""

import asyncio
import hashlib
import hmac
import json
from datetime import datetime, timezone
from uuid import UUID

import httpx
import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger()

_PUSH_TIMEOUT_SECONDS = 10
_BACKOFF_BASE = 1.0  # 指数退避基数（秒）


class WebhookDispatcher:
    """Webhook事件推送器。

    签名格式: X-TunXiang-Signature: sha256=<hmac_hex>
    """

    async def dispatch(
        self,
        tenant_id: UUID,
        event_type: str,
        payload: dict,
        db: AsyncSession,
    ) -> list[dict]:
        """推送事件到所有订阅该event_type的webhook。

        Args:
            tenant_id:   租户ID（RLS隔离）
            event_type:  事件类型，如"order.completed"
            payload:     事件数据（不得含金额等敏感字段）
            db:          数据库会话

        Returns:
            每个webhook的推送结果列表
        """
        # 查找订阅该事件的所有active webhook
        result = await db.execute(
            text("""
                SELECT id, endpoint_url, secret_hash, retry_count
                FROM api_webhooks
                WHERE tenant_id = :tenant_id
                  AND is_active = TRUE
                  AND is_deleted = FALSE
                  AND event_types @> :event_type_json::jsonb
            """),
            {
                "tenant_id": str(tenant_id),
                "event_type_json": json.dumps([event_type]),
            },
        )
        webhooks = [dict(r) for r in result.mappings().fetchall()]

        if not webhooks:
            logger.debug(
                "webhook_no_subscribers",
                event_type=event_type,
                tenant_id=str(tenant_id),
            )
            return []

        # 构建请求体
        body_dict = {
            "event": event_type,
            "data": payload,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "tenant_id": str(tenant_id),
        }
        body_bytes = json.dumps(body_dict, ensure_ascii=False).encode("utf-8")

        # 并发推送所有webhook
        tasks = [
            self._push_with_retry(
                webhook=wh,
                body=body_bytes,
                signature=self._compute_signature(wh["secret_hash"], body_bytes),
                retry_count=wh.get("retry_count", 3),
            )
            for wh in webhooks
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # 处理结果并更新数据库
        push_results: list[dict] = []
        for wh, res in zip(webhooks, results):
            if isinstance(res, BaseException):
                push_result = {
                    "webhook_id": str(wh["id"]),
                    "success": False,
                    "error": str(res),
                    "status_code": None,
                }
                status_str = "error"
            else:
                push_result = res
                status_str = "success" if res.get("success") else "failed"

            push_results.append(push_result)

            # 异步更新最后推送状态（不阻塞主流程）
            try:
                await db.execute(
                    text("""
                        UPDATE api_webhooks
                        SET last_triggered_at = NOW(),
                            last_status = :status,
                            updated_at = NOW()
                        WHERE id = :webhook_id
                    """),
                    {"status": status_str, "webhook_id": str(wh["id"])},
                )
            except Exception as exc:  # noqa: BLE001 — 状态更新失败不阻塞推送结果
                logger.warning(
                    "webhook_status_update_failed",
                    webhook_id=str(wh["id"]),
                    error=str(exc),
                )

        try:
            await db.commit()
        except Exception as exc:  # noqa: BLE001 — commit失败不影响已推送结果
            logger.warning("webhook_dispatch_commit_failed", error=str(exc))

        logger.info(
            "webhook_dispatch_complete",
            event_type=event_type,
            tenant_id=str(tenant_id),
            total=len(webhooks),
            success=sum(1 for r in push_results if r.get("success")),
        )
        return push_results

    async def _push_with_retry(
        self,
        webhook: dict,
        body: bytes,
        signature: str,
        retry_count: int,
    ) -> dict:
        """带指数退避重试的单次推送。

        退避策略: 第n次重试等待 backoff_base * 2^(n-1) 秒
        """
        webhook_id = str(webhook["id"])
        endpoint_url = webhook["endpoint_url"]
        last_error: str | None = None
        last_status_code: int | None = None

        headers = {
            "Content-Type": "application/json; charset=utf-8",
            "X-TunXiang-Signature": signature,
            "User-Agent": "TunxiangOS-Webhook/1.0",
        }

        async with httpx.AsyncClient(timeout=_PUSH_TIMEOUT_SECONDS) as client:
            for attempt in range(retry_count + 1):
                if attempt > 0:
                    wait_secs = _BACKOFF_BASE * (2 ** (attempt - 1))
                    logger.info(
                        "webhook_retry",
                        webhook_id=webhook_id,
                        attempt=attempt,
                        wait_secs=wait_secs,
                    )
                    await asyncio.sleep(wait_secs)

                try:
                    response = await client.post(
                        endpoint_url,
                        content=body,
                        headers=headers,
                    )
                    last_status_code = response.status_code

                    if response.status_code < 500:
                        # 2xx/3xx/4xx 均视为推送成功（不重试客户端错误）
                        success = 200 <= response.status_code < 300
                        logger.info(
                            "webhook_pushed",
                            webhook_id=webhook_id,
                            status_code=response.status_code,
                            attempt=attempt,
                            success=success,
                        )
                        return {
                            "webhook_id": webhook_id,
                            "success": success,
                            "status_code": response.status_code,
                            "attempts": attempt + 1,
                            "error": None,
                        }

                    # 5xx 服务端错误 — 继续重试
                    last_error = f"HTTP {response.status_code}"
                    logger.warning(
                        "webhook_push_server_error",
                        webhook_id=webhook_id,
                        status_code=response.status_code,
                        attempt=attempt,
                    )

                except httpx.TimeoutException as exc:
                    last_error = f"timeout: {exc}"
                    logger.warning(
                        "webhook_push_timeout",
                        webhook_id=webhook_id,
                        attempt=attempt,
                        error=str(exc),
                    )

                except httpx.ConnectError as exc:
                    last_error = f"connect_error: {exc}"
                    logger.warning(
                        "webhook_push_connect_error",
                        webhook_id=webhook_id,
                        attempt=attempt,
                        error=str(exc),
                    )

                except httpx.RequestError as exc:
                    last_error = f"request_error: {exc}"
                    logger.warning(
                        "webhook_push_request_error",
                        webhook_id=webhook_id,
                        attempt=attempt,
                        error=str(exc),
                    )

        # 所有重试均失败
        logger.error(
            "webhook_push_all_retries_failed",
            webhook_id=webhook_id,
            total_attempts=retry_count + 1,
            last_error=last_error,
        )
        return {
            "webhook_id": webhook_id,
            "success": False,
            "status_code": last_status_code,
            "attempts": retry_count + 1,
            "error": last_error,
        }

    def _compute_signature(self, secret_hash: str, body: bytes) -> str:
        """HMAC-SHA256签名。

        注意: secret_hash是存储的哈希值本身作为HMAC密钥。
        实际生产中应存储secret明文或使用KMS。
        此处与存储设计保持一致（secret_hash as key）。
        """
        mac = hmac.new(
            secret_hash.encode("utf-8"),
            body,
            hashlib.sha256,
        )
        return f"sha256={mac.hexdigest()}"

    def verify_signature(self, secret_hash: str, body: bytes, signature: str) -> bool:
        """验证webhook签名（供接收方使用）"""
        expected = self._compute_signature(secret_hash, body)
        return hmac.compare_digest(expected, signature)
