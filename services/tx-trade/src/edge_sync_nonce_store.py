"""Edge sync nonce store — 防重放检测的存储抽象。

审计 NEW-P0 part 2：PR #195 sync_ingest_router 用 _EDGE_SYNC_RECENT_NONCES
进程内 dict 防重放。第一轮 review P1-1 指出：HPA 副本 ≥ 2 时同 nonce 打到不同
pod 无法共享，重放被绕过 —— 业务层 change_id 幂等去重不可靠兜底。

本模块抽象出 EdgeSyncNonceStore：
  - InProcessNonceStore  — dict + GC，仅适合单副本部署
  - RedisNonceStore     — Redis SETNX EX 原子操作，多副本共享，生产推荐
  - get_nonce_store()   — env 工厂，按 EDGE_SYNC_NONCE_REDIS_URL 选择实现

部署场景：
  开发/单副本 staging — env 不配 → InProcessNonceStore（warn 一次）
  生产 + HPA replica ≥ 2 — 必须配 EDGE_SYNC_NONCE_REDIS_URL → RedisNonceStore
  生产 + EDGE_SYNC_HMAC_REQUIRED=true 但无 Redis URL → 启动期 raise（防 silent 降级）

Redis 字符串 key 设计：
  edge_sync_nonce:{store_id}:{nonce_hex}
  TTL = max(_edge_sync_skew_seconds, 60s)，过期自动 GC，无需手工清理
"""

from __future__ import annotations

import abc
import logging
import os
import time
from typing import Optional

logger = logging.getLogger(__name__)

_PRODUCTION_ENVS = ("production", "prod", "gray")


def _is_production() -> bool:
    env = (os.environ.get("TX_ENV") or os.environ.get("ENVIRONMENT") or "").strip().lower()
    return env in _PRODUCTION_ENVS


# ─── 抽象接口 ────────────────────────────────────────────────────────────────


class EdgeSyncNonceStore(abc.ABC):
    """nonce 防重放存储 — 异步接口（与 FastAPI / asyncpg 兼容）。"""

    @abc.abstractmethod
    async def seen_and_mark(self, nonce_key: str, ttl_seconds: int) -> bool:
        """原子检查 nonce 是否已用过；未用过则标记 + 设 TTL，返回 False。

        Returns:
            True  —— 已用过（重放，应拒）
            False —— 未用过，已标记，可放行
        """
        ...

    @abc.abstractmethod
    async def close(self) -> None:
        """释放底层连接（Redis client / 等）"""
        ...


# ─── 进程内实现（单副本兜底）────────────────────────────────────────────────


class InProcessNonceStore(EdgeSyncNonceStore):
    """dict + 时间戳过期，**多副本下不共享**，仅适合 dev / 单副本 staging。"""

    __slots__ = ("_seen", "_warned")

    def __init__(self) -> None:
        self._seen: dict[str, float] = {}
        self._warned: bool = False

    def _gc(self, now: float, ttl_seconds: int) -> None:
        threshold = now - ttl_seconds
        expired = [k for k, v in self._seen.items() if v < threshold]
        for k in expired:
            self._seen.pop(k, None)

    async def seen_and_mark(self, nonce_key: str, ttl_seconds: int) -> bool:
        now = time.time()
        self._gc(now, ttl_seconds)

        if not self._warned:
            logger.warning(
                "edge_sync_nonce_store_in_process replicas_unsafe=true ttl=%ds",
                ttl_seconds,
            )
            self._warned = True

        if nonce_key in self._seen:
            return True
        self._seen[nonce_key] = now
        return False

    async def close(self) -> None:
        self._seen.clear()


# ─── Redis 实现（多副本生产推荐）────────────────────────────────────────────


class RedisNonceStore(EdgeSyncNonceStore):
    """Redis SETNX EX 原子操作，多副本共享。连不上 Redis 时 fail-closed。"""

    __slots__ = ("_url", "_client", "_key_prefix")

    def __init__(self, url: str, key_prefix: str = "edge_sync_nonce:") -> None:
        if not url:
            raise ValueError("RedisNonceStore: url 不能为空")
        self._url = url
        self._client = None  # lazy connect
        self._key_prefix = key_prefix

    async def _ensure_client(self):
        if self._client is not None:
            return self._client
        try:
            import redis.asyncio as _redis
        except ImportError as exc:
            raise RuntimeError(
                "redis package not installed; run: pip install redis>=5.0"
            ) from exc
        self._client = _redis.from_url(self._url, decode_responses=True)
        return self._client

    async def seen_and_mark(self, nonce_key: str, ttl_seconds: int) -> bool:
        client = await self._ensure_client()
        full_key = f"{self._key_prefix}{nonce_key}"
        # SET NX EX 原子操作：key 不存在则设置 + 过期；存在则不设置
        # 返回 True 表示设置成功（未见过）；None/False 表示已存在（重放）
        try:
            ok = await client.set(full_key, str(int(time.time())), nx=True, ex=ttl_seconds)
        except Exception as exc:
            # Redis 连接异常 — fail-closed 视为重放，让 verify_edge_sync_auth 回 401
            # 这是有意的：生产 Redis 故障时宁可拒部分合法请求也不接受任何潜在重放
            logger.error(
                "edge_sync_nonce_store_redis_error key=%s error=%s",
                full_key,
                exc,
            )
            raise RuntimeError(f"nonce store backend error: {exc}") from exc
        return not ok  # ok=True → 未见过，返回 False；ok=False → 已存在，返回 True

    async def close(self) -> None:
        if self._client is not None:
            try:
                await self._client.close()
            except Exception as exc:
                logger.warning("edge_sync_nonce_store_redis_close_error error=%s", exc)
            self._client = None


# ─── 工厂 ──────────────────────────────────────────────────────────────────


_global_store: Optional[EdgeSyncNonceStore] = None


def get_nonce_store() -> EdgeSyncNonceStore:
    """按 env 返回单例 nonce store。

    EDGE_SYNC_NONCE_REDIS_URL 已配 → RedisNonceStore（推荐生产路径）
    未配 → InProcessNonceStore + warn

    生产 + EDGE_SYNC_HMAC_REQUIRED=true 但无 Redis URL → 启动期 raise，
    防止"以为有防重放，实际多副本不共享"的 silent 降级。
    """
    global _global_store
    if _global_store is not None:
        return _global_store

    redis_url = os.environ.get("EDGE_SYNC_NONCE_REDIS_URL", "").strip()
    hmac_required = (
        os.environ.get("EDGE_SYNC_HMAC_REQUIRED", "").strip().lower()
        in ("true", "1", "yes", "on")
    )

    if redis_url:
        _global_store = RedisNonceStore(redis_url)
        logger.info("edge_sync_nonce_store_redis url=%s", redis_url)
        return _global_store

    if _is_production() and hmac_required:
        raise RuntimeError(
            "EDGE_SYNC_NONCE_REDIS_URL 未配置但生产 + EDGE_SYNC_HMAC_REQUIRED=true —— "
            "拒绝启动以防 silent 降级到进程内 dict（HPA 多副本下防重放失效）。"
            "解决：配 EDGE_SYNC_NONCE_REDIS_URL=redis://... 到 K8s Secret，或显式接受降级"
            "（设 EDGE_SYNC_NONCE_ALLOW_INPROCESS=true）。"
        )

    if (
        _is_production()
        and os.environ.get("EDGE_SYNC_NONCE_ALLOW_INPROCESS", "").strip().lower()
        not in ("true", "1", "yes", "on")
    ):
        # 生产但 hmac_required=false（cutover 前）— 仍 warn 一次
        logger.warning(
            "edge_sync_nonce_store_inprocess_in_production redis_url_unset=true "
            "set EDGE_SYNC_NONCE_REDIS_URL before EDGE_SYNC_HMAC_REQUIRED=true cutover"
        )

    _global_store = InProcessNonceStore()
    return _global_store


def reset_nonce_store_for_testing() -> None:
    """测试用：清空 singleton 状态，避免跨测试污染。"""
    global _global_store
    _global_store = None
