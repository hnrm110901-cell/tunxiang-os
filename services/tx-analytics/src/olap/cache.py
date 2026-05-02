"""OLAP 查询缓存 — Redis 缓存包装器

缓存策略:
  - 键格式: olap:{tenant_id}:{md5(canonical_query_json)}
  - TTL: 轻量查询 60s, 重量查询 300s
  - 结果存为 JSON 字符串 (OLAPResult.model_dump_json())
  - 手动失效: 通过 cache_key 前缀删除

依赖: redis.asyncio (项目已有的 Redis 异步客户端)
"""

from __future__ import annotations

import hashlib
import json
import os
from typing import Optional

import redis.asyncio as redis
import structlog

log = structlog.get_logger(__name__)

# ─── 配置 ──────────────────────────────────────────────────────────────────────

REDIS_URL: str = os.getenv("OLAP_CACHE_REDIS_URL", os.getenv("REDIS_URL", "redis://localhost:6379/2"))
DEFAULT_TTL: int = int(os.getenv("OLAP_CACHE_TTL", "60"))          # 默认 60 秒
HEAVY_TTL: int = int(os.getenv("OLAP_CACHE_HEAVY_TTL", "300"))    # 重量查询 300 秒

# 重量查询阈值：维度数 + 度量数 >= HEAVY_QUERY_THRESHOLD
HEAVY_QUERY_THRESHOLD: int = 4


# ─── Client ────────────────────────────────────────────────────────────────────

# 全局单例 Redis 连接（惰性初始化）
_redis_client: Optional[redis.Redis] = None


async def _get_redis() -> redis.Redis:
    """获取 Redis 连接（惰性初始化 + 连接检查）"""
    global _redis_client
    if _redis_client is None:
        _redis_client = redis.from_url(REDIS_URL, decode_responses=True)
    try:
        await _redis_client.ping()
    except (redis.ConnectionError, redis.TimeoutError, OSError):
        # Redis 不可用时返回 None，由调用方降级
        log.warning("olap_cache_redis_unavailable", url=REDIS_URL)
        raise OLAPCacheUnavailableError("Redis cache backend is not available")
    return _redis_client


# ─── 核心 API ─────────────────────────────────────────────────────────────────


def make_cache_key(tenant_id: str, query_json: str) -> str:
    """生成缓存键

    将查询 JSON 序列化为规范格式（排序键），取 MD5 前 16 位作为标识。
    """
    canonical = _canonicalize_json(query_json)
    digest = hashlib.md5(canonical.encode("utf-8")).hexdigest()[:16]
    return f"olap:{tenant_id}:{digest}"


def _canonicalize_json(query_json: str) -> str:
    """将查询 JSON 规范化为稳定格式（键排序、无空格），确保一致性。"""
    try:
        parsed = json.loads(query_json)
        return json.dumps(parsed, sort_keys=True, separators=(",", ":"))
    except (json.JSONDecodeError, TypeError):
        # 如果无法解析，直接返回原始字符串的 strip 版本
        return query_json.strip()


async def get_cached_result(tenant_id: str, query_json: str) -> Optional[str]:
    """从 Redis 获取缓存的 OLAP 结果

    Returns:
        JSON 字符串 (OLAPResult.model_dump_json()) 或 None（未命中/不可用）
    """
    try:
        r = await _get_redis()
        key = make_cache_key(tenant_id, query_json)
        value = await r.get(key)
        if value is not None:
            log.debug("olap_cache_hit", key=key)
        else:
            log.debug("olap_cache_miss", key=key)
        return value
    except OLAPCacheUnavailableError:
        return None
    except (redis.ConnectionError, redis.TimeoutError, redis.RedisError) as exc:
        log.warning("olap_cache_get_error", exc_info=True, error=str(exc))
        return None


async def set_cached_result(
    tenant_id: str,
    query_json: str,
    result_json: str,
    is_heavy: bool = False,
) -> bool:
    """将 OLAP 结果写入 Redis 缓存

    Args:
        tenant_id: 租户 ID
        query_json: 原始查询 JSON
        result_json: OLAPResult 序列化 JSON
        is_heavy: 是否为重量查询（影响 TTL）

    Returns:
        True 写入成功，False 写入失败
    """
    ttl = HEAVY_TTL if is_heavy else DEFAULT_TTL
    try:
        r = await _get_redis()
        key = make_cache_key(tenant_id, query_json)
        await r.setex(key, ttl, result_json)
        log.debug("olap_cache_set", key=key, ttl=ttl)
        return True
    except OLAPCacheUnavailableError:
        return False
    except (redis.ConnectionError, redis.TimeoutError, redis.RedisError) as exc:
        log.warning("olap_cache_set_error", exc_info=True, error=str(exc))
        return False


async def invalidate_cache(tenant_id: str, pattern: str = "*") -> int:
    """手动使缓存失效

    删除匹配 olap:{tenant_id}:{pattern} 的所有键。

    Args:
        tenant_id: 租户 ID
        pattern: 键匹配模式（默认 "*" 删除该租户所有 OLAP 缓存）

    Returns:
        删除的键数量
    """
    key_pattern = f"olap:{tenant_id}:{pattern}"
    try:
        r = await _get_redis()
        cursor = 0
        deleted = 0
        while True:
            cursor, keys = await r.scan(cursor=cursor, match=key_pattern, count=100)
            if keys:
                deleted += await r.delete(*keys)
            if cursor == 0:
                break
        log.info("olap_cache_invalidated", tenant_id=tenant_id, deleted=deleted)
        return deleted
    except OLAPCacheUnavailableError:
        return 0
    except (redis.ConnectionError, redis.TimeoutError, redis.RedisError) as exc:
        log.warning("olap_cache_invalidate_error", exc_info=True, error=str(exc))
        return 0


def is_heavy_query(num_dimensions: int, num_measures: int) -> bool:
    """判断查询是否为重量查询（返回更多行/更大计算量）"""
    return (num_dimensions + num_measures) >= HEAVY_QUERY_THRESHOLD


# ─── Custom Exceptions ─────────────────────────────────────────────────────────


class OLAPCacheUnavailableError(Exception):
    """Redis 缓存后端不可用"""
    pass
