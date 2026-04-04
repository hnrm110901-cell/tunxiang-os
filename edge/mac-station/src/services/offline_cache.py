"""离线缓存层 — 写入队列 / 读取优先级 / 队列回放 / 冲突标记

设计：
- 写入队列：离线时将写操作缓存到内存队列（后续可落盘 SQLite）
- 读取优先：本地 PG > 内存缓存 > 云端 API
- 队列回放：恢复连接后自动推送离线期间的操作到云端
- 冲突标记：离线写入加 _offline_origin=true 标记

Mock 模式：不依赖真实 PG 连接，内存模拟全部行为。
"""
from __future__ import annotations

import asyncio
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from typing import Any

import httpx
import structlog

logger = structlog.get_logger(__name__)

# ── 写入队列条目 ──


@dataclass
class QueueEntry:
    """离线写入队列中的一条操作记录。"""

    entry_id: str
    operation: str          # "create_order" | "update_order" | "update_inventory" | ...
    endpoint: str           # 云端目标 API 路径
    method: str             # "POST" | "PUT" | "PATCH"
    payload: dict[str, Any]
    store_id: str
    tenant_id: str
    created_at: float       # UNIX 时间戳
    retry_count: int = 0
    max_retries: int = 5
    last_error: str = ""


# ── 离线缓存服务 ──


class OfflineCache:
    """门店离线缓存服务。

    职责：
    1. 离线时将写操作缓存到内存队列
    2. 提供读取优先级逻辑
    3. 恢复在线后自动回放队列
    4. 统计缓存命中率

    Attributes:
        _write_queue: 待回放的写操作 FIFO 队列
        _read_cache: 热数据内存缓存（key → {data, cached_at}）
        _cache_ttl_s: 读缓存 TTL（秒）
        _stats: 命中率统计
    """

    def __init__(self, cache_ttl_s: int = 300) -> None:
        self._write_queue: deque[QueueEntry] = deque(maxlen=10000)
        self._read_cache: dict[str, dict[str, Any]] = {}
        self._cache_ttl_s = cache_ttl_s
        self._replay_task: asyncio.Task[None] | None = None
        self._stats: dict[str, int] = {
            "cache_hits": 0,
            "cache_misses": 0,
            "queue_enqueued": 0,
            "queue_replayed": 0,
            "queue_failed": 0,
        }

    # ── 写入队列 ──

    def enqueue_write(
        self,
        operation: str,
        endpoint: str,
        method: str,
        payload: dict[str, Any],
        store_id: str,
        tenant_id: str,
    ) -> QueueEntry:
        """将一条写操作放入离线队列。

        自动添加 _offline_origin=true 冲突标记。

        Args:
            operation: 操作类型，如 "create_order"
            endpoint: 云端目标 API 路径，如 "/api/v1/orders"
            method: HTTP 方法
            payload: 请求体
            store_id: 门店 ID
            tenant_id: 租户 ID

        Returns:
            入队的 QueueEntry 对象。
        """
        # 冲突标记
        payload["_offline_origin"] = True
        payload["_offline_enqueued_at"] = time.time()

        entry = QueueEntry(
            entry_id=str(uuid.uuid4()),
            operation=operation,
            endpoint=endpoint,
            method=method,
            payload=payload,
            store_id=store_id,
            tenant_id=tenant_id,
            created_at=time.time(),
        )
        self._write_queue.append(entry)
        self._stats["queue_enqueued"] += 1

        logger.info(
            "offline_queue_enqueued",
            entry_id=entry.entry_id,
            operation=operation,
            endpoint=endpoint,
            queue_depth=len(self._write_queue),
        )
        return entry

    def queue_depth(self) -> int:
        """返回当前写入队列深度。"""
        return len(self._write_queue)

    def peek_queue(self, limit: int = 20) -> list[dict[str, Any]]:
        """预览队列中的条目（不出队）。"""
        items: list[dict[str, Any]] = []
        for i, entry in enumerate(self._write_queue):
            if i >= limit:
                break
            items.append({
                "entry_id": entry.entry_id,
                "operation": entry.operation,
                "endpoint": entry.endpoint,
                "method": entry.method,
                "created_at": entry.created_at,
                "retry_count": entry.retry_count,
                "last_error": entry.last_error,
            })
        return items

    # ── 读取缓存 ──

    def cache_get(self, key: str) -> dict[str, Any] | None:
        """从内存缓存读取数据。

        过期条目返回 None 并清除。

        Args:
            key: 缓存键，如 "menu:store_123"

        Returns:
            缓存的数据字典，或 None。
        """
        entry = self._read_cache.get(key)
        if entry is None:
            self._stats["cache_misses"] += 1
            return None

        if time.time() - entry["cached_at"] > self._cache_ttl_s:
            del self._read_cache[key]
            self._stats["cache_misses"] += 1
            return None

        self._stats["cache_hits"] += 1
        return entry["data"]

    def cache_set(self, key: str, data: dict[str, Any]) -> None:
        """写入内存缓存。

        Args:
            key: 缓存键
            data: 要缓存的数据
        """
        self._read_cache[key] = {"data": data, "cached_at": time.time()}

    def cache_invalidate(self, key: str) -> bool:
        """使指定缓存失效。"""
        return self._read_cache.pop(key, None) is not None

    def cache_clear(self) -> int:
        """清空全部读缓存。返回清除的条目数。"""
        count = len(self._read_cache)
        self._read_cache.clear()
        return count

    # ── 队列回放 ──

    async def replay_queue(self, cloud_api_url: str, tenant_id: str) -> dict[str, int]:
        """将离线队列中的写操作按序推送到云端。

        按 FIFO 顺序逐条发送。失败的条目重新入队（最多重试 max_retries 次）。

        Args:
            cloud_api_url: 云端 API 网关根地址
            tenant_id: 租户 ID

        Returns:
            {"replayed": N, "failed": M, "remaining": R}
        """
        replayed = 0
        failed = 0
        retry_later: list[QueueEntry] = []

        while self._write_queue:
            entry = self._write_queue.popleft()

            url = f"{cloud_api_url}{entry.endpoint}"
            headers = {
                "X-Tenant-ID": tenant_id,
                "X-Store-ID": entry.store_id,
                "Content-Type": "application/json",
            }

            try:
                async with httpx.AsyncClient(timeout=10) as client:
                    if entry.method == "POST":
                        resp = await client.post(url, json=entry.payload, headers=headers)
                    elif entry.method == "PUT":
                        resp = await client.put(url, json=entry.payload, headers=headers)
                    elif entry.method == "PATCH":
                        resp = await client.patch(url, json=entry.payload, headers=headers)
                    else:
                        logger.warning("offline_replay_unknown_method", method=entry.method)
                        failed += 1
                        continue

                    if resp.status_code < 400:
                        replayed += 1
                        self._stats["queue_replayed"] += 1
                        logger.info(
                            "offline_replay_ok",
                            entry_id=entry.entry_id,
                            operation=entry.operation,
                            status=resp.status_code,
                        )
                    else:
                        entry.retry_count += 1
                        entry.last_error = f"HTTP {resp.status_code}"
                        if entry.retry_count < entry.max_retries:
                            retry_later.append(entry)
                        else:
                            failed += 1
                            self._stats["queue_failed"] += 1
                            logger.error(
                                "offline_replay_max_retries",
                                entry_id=entry.entry_id,
                                operation=entry.operation,
                                retries=entry.retry_count,
                            )

            except (httpx.ConnectError, httpx.TimeoutException, OSError) as exc:
                # 云端又断了，把当前条目和剩余的都放回去
                entry.retry_count += 1
                entry.last_error = str(exc)
                retry_later.append(entry)
                # 把队列剩余的也加回去
                retry_later.extend(self._write_queue)
                self._write_queue.clear()
                logger.warning(
                    "offline_replay_cloud_down",
                    entry_id=entry.entry_id,
                    remaining=len(retry_later),
                )
                break

        # 把需要重试的放回队列头部
        for entry in reversed(retry_later):
            self._write_queue.appendleft(entry)

        return {
            "replayed": replayed,
            "failed": failed,
            "remaining": len(self._write_queue),
        }

    async def run_replay_loop(self, cloud_api_url: str, tenant_id: str) -> None:
        """后台定期尝试回放离线队列的死循环任务。

        仅在队列非空且云端可达时执行回放。
        """
        from config import get_config

        while True:
            await asyncio.sleep(15)  # 每15秒检查一次
            cfg = get_config()
            if cfg.offline or not self._write_queue:
                continue

            logger.info("offline_replay_starting", queue_depth=len(self._write_queue))
            result = await self.replay_queue(cloud_api_url, tenant_id)
            logger.info("offline_replay_done", **result)

    # ── 统计 ──

    def stats(self) -> dict[str, Any]:
        """返回缓存命中率和队列统计。"""
        total_reads = self._stats["cache_hits"] + self._stats["cache_misses"]
        hit_rate = (
            round(self._stats["cache_hits"] / total_reads * 100, 1)
            if total_reads > 0
            else 0.0
        )
        return {
            "cache_hit_rate_pct": hit_rate,
            "cache_hits": self._stats["cache_hits"],
            "cache_misses": self._stats["cache_misses"],
            "cache_entries": len(self._read_cache),
            "queue_depth": len(self._write_queue),
            "queue_total_enqueued": self._stats["queue_enqueued"],
            "queue_total_replayed": self._stats["queue_replayed"],
            "queue_total_failed": self._stats["queue_failed"],
        }


# ── 模块级单例 ──

_cache: OfflineCache | None = None


def get_offline_cache() -> OfflineCache:
    """获取离线缓存单例（懒初始化）。"""
    global _cache
    if _cache is None:
        _cache = OfflineCache()
    return _cache
