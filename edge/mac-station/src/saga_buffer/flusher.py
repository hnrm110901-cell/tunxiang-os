"""SagaFlusher — Sprint A2 Saga 缓冲补发 Worker

职责：
  - 定期扫描 SagaBuffer 中 state=pending 且未到期条目
  - POST 到 tx-trade `/api/v1/settle/retry`（见 services/tx-trade/src/api/settle_retry.py）
  - 成功 → mark_sent，失败 → mark_failed（attempts++），4h 到期 → mark_dead_letter
  - 补发后心跳一次到云端 `/api/v1/edge/saga_buffer_meta`（UPSERT 本店状态）

不改动 payment_saga_service 的 _PENDING_TIMEOUT_MINUTES=5：
  - 前端 3s soft timeout 与 saga 5min timeout 是两个独立时间轴
  - A2 在二者之外新增一条 4h 缓冲通道（断网场景专用）

关联：CLAUDE.md §8 离线优先 / §17 Tier1
"""
from __future__ import annotations

import asyncio
from typing import Optional

import structlog

from .buffer import (
    SagaBuffer,
    SagaBufferEntry,
)

logger = structlog.get_logger(__name__)


class SagaFlusher:
    """后台 Worker：扫 buffer → POST tx-trade → mark_sent/failed → heartbeat."""

    def __init__(
        self,
        buffer: SagaBuffer,
        tenant_id: str,
        http_client,  # httpx.AsyncClient 兼容接口
        retry_endpoint: str = "/api/v1/settle/retry",
        heartbeat_endpoint: str = "/api/v1/edge/saga_buffer_meta",
        base_url: str = "",
        max_attempts_before_dead: int = 20,
        flush_interval_seconds: float = 15.0,
        batch_limit: int = 50,
    ) -> None:
        self._buffer = buffer
        self._tenant_id = tenant_id
        self._http = http_client
        self._retry_endpoint = retry_endpoint
        self._heartbeat_endpoint = heartbeat_endpoint
        self._base_url = base_url.rstrip("/")
        self._max_attempts = max_attempts_before_dead
        self._interval = flush_interval_seconds
        self._batch_limit = batch_limit
        self._stop_event = asyncio.Event()

    # ─── 主循环 ───────────────────────────────────────────────────────────────

    async def run(self) -> None:
        """启动无限循环。收到 stop() 信号后优雅退出。"""
        logger.info(
            "saga_flusher_started",
            tenant_id=self._tenant_id,
            interval=self._interval,
        )
        while not self._stop_event.is_set():
            try:
                await self.flush_once()
                await self.heartbeat()
            except asyncio.CancelledError:
                raise
            except (OSError, RuntimeError, ValueError) as exc:
                # 不能 broad except：吞掉意外错误但保证循环不死
                logger.error(
                    "saga_flusher_iteration_error",
                    tenant_id=self._tenant_id,
                    error=str(exc),
                    exc_info=True,
                )

            try:
                await asyncio.wait_for(
                    self._stop_event.wait(),
                    timeout=self._interval,
                )
            except asyncio.TimeoutError:
                pass

        logger.info("saga_flusher_stopped", tenant_id=self._tenant_id)

    def stop(self) -> None:
        self._stop_event.set()

    # ─── 单次扫描 ─────────────────────────────────────────────────────────────

    async def flush_once(self) -> dict:
        """单次扫描 + 补发。返回 {sent, failed, dead_letter}。"""
        # 先清理已到期条目
        expired = await self._buffer.sweep_expired(tenant_id=self._tenant_id)
        if expired:
            logger.warning(
                "saga_flusher_dead_letter_ttl",
                tenant_id=self._tenant_id,
                count=expired,
            )

        ready = await self._buffer.flush_ready(
            tenant_id=self._tenant_id,
            limit=self._batch_limit,
        )

        sent = 0
        failed = 0
        dead_letter = expired
        for entry in ready:
            result = await self._flush_entry(entry)
            if result == "sent":
                sent += 1
            elif result == "dead_letter":
                dead_letter += 1
            else:
                failed += 1

        if sent or failed or dead_letter:
            logger.info(
                "saga_flusher_iteration_done",
                tenant_id=self._tenant_id,
                sent=sent,
                failed=failed,
                dead_letter=dead_letter,
            )
        return {"sent": sent, "failed": failed, "dead_letter": dead_letter}

    async def _flush_entry(self, entry: SagaBufferEntry) -> str:
        """补发单条。返回 'sent' / 'failed' / 'dead_letter'."""
        # attempts 达上限 → dead_letter（提前兜底）
        if entry.attempts >= self._max_attempts:
            await self._buffer.mark_dead_letter(
                entry.idempotency_key,
                f"max_attempts_{self._max_attempts}_reached",
            )
            logger.warning(
                "saga_flusher_dead_letter_max_attempts",
                idempotency_key=entry.idempotency_key,
                attempts=entry.attempts,
            )
            return "dead_letter"

        await self._buffer.mark_flushing(entry.idempotency_key)
        url = f"{self._base_url}{self._retry_endpoint}"
        body = {
            "idempotency_key": entry.idempotency_key,
            "saga_id": entry.saga_id,
            "tenant_id": entry.tenant_id,
            "store_id": entry.store_id,
            "device_id": entry.device_id,
            "payload": entry.payload,
        }
        try:
            resp = await self._http.post(
                url,
                json=body,
                headers={
                    "X-Idempotency-Key": entry.idempotency_key,
                    "X-Tenant-ID": entry.tenant_id,
                },
                timeout=8.0,
            )
        except (OSError, asyncio.TimeoutError) as exc:
            await self._buffer.mark_failed(
                entry.idempotency_key,
                f"network_error:{exc}",
            )
            return "failed"

        status = getattr(resp, "status_code", 0)
        if 200 <= status < 300:
            await self._buffer.mark_sent(entry.idempotency_key)
            return "sent"
        # 4xx 业务拒绝（如 ROLE_FORBIDDEN 跨租户）→ 直接 dead_letter 等人工
        if 400 <= status < 500:
            try:
                detail = resp.json()
            except (ValueError, AttributeError):
                detail = {"status": status}
            await self._buffer.mark_dead_letter(
                entry.idempotency_key,
                f"http_{status}:{detail}",
            )
            return "dead_letter"
        # 5xx → 重试
        await self._buffer.mark_failed(
            entry.idempotency_key,
            f"http_{status}",
        )
        return "failed"

    # ─── heartbeat 回传云端 saga_buffer_meta ──────────────────────────────────

    async def heartbeat(self) -> Optional[dict]:
        """向云端 PG saga_buffer_meta 汇报本店缓冲状态。"""
        stats = await self._buffer.stats(tenant_id=self._tenant_id)
        health = _compute_health(stats)
        body = {
            "tenant_id": self._tenant_id,
            "device_id": self._buffer.device_id,
            "buffer_count": stats.pending_count,
            "dead_letter_count": stats.dead_letter_count,
            "health_status": health,
            "mode": stats.mode,
        }
        url = f"{self._base_url}{self._heartbeat_endpoint}"
        try:
            resp = await self._http.post(
                url,
                json=body,
                headers={"X-Tenant-ID": self._tenant_id},
                timeout=5.0,
            )
            status = getattr(resp, "status_code", 0)
            if not (200 <= status < 300):
                logger.warning(
                    "saga_flusher_heartbeat_non_2xx",
                    tenant_id=self._tenant_id,
                    status=status,
                )
                return None
            return body
        except (OSError, asyncio.TimeoutError) as exc:
            # heartbeat 失败不影响补发主链路
            logger.warning(
                "saga_flusher_heartbeat_error",
                tenant_id=self._tenant_id,
                error=str(exc),
            )
            return None


def _compute_health(stats) -> str:
    """根据 pending/dead_letter 计数决定 health_status。

    - dead_letter > 0 → degraded（需人工介入）
    - pending > 50 → degraded（积压）
    - mode == memory → degraded（磁盘降级）
    - 否则 healthy
    """
    if stats.mode != "sqlite":
        return "degraded"
    if stats.dead_letter_count > 0:
        return "degraded"
    if stats.pending_count > 50:
        return "degraded"
    return "healthy"
