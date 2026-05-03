"""Redis 滑动窗口限流器 — 按 API Key 限流

使用 Redis Sorted Set 实现滑动窗口算法：
  - key:  `ratelimit:{key_id}:{window_sec}`
  - score: 当前时间戳 (毫秒)
  窗口内请求数 < rate_limit 则通过。
"""
import time
from typing import Optional

import structlog

logger = structlog.get_logger()


class RateLimiter:
    """滑动窗口限流器"""

    def __init__(self, redis_client: Optional["Redis"] = None):
        self._redis = redis_client

    @property
    def redis(self):
        if self._redis is None:
            raise RuntimeError("Redis client not configured for RateLimiter")
        return self._redis

    async def check(self, key_id: str, rps: int, window_sec: int = 1) -> bool:
        """检查请求是否允许通过。

        Args:
            key_id:  API Key ID
            rps:     每秒允许请求数
            window_sec: 窗口大小（秒）

        Returns:
            True 允许通过, False 触发限流
        """
        if rps <= 0:
            return False

        now_ms = int(time.time() * 1000)
        window_key = f"ratelimit:{key_id}:{window_sec}"
        window_start = now_ms - window_sec * 1000

        pipe = self.redis.pipeline()
        pipe.zremrangebyscore(window_key, 0, window_start)  # 清除过期
        pipe.zcard(window_key)                                # 当前窗口计数
        pipe.zadd(window_key, {str(now_ms): now_ms})         # 加入当前请求
        pipe.expire(window_key, window_sec * 2)               # TTL
        _, count, _, _ = await pipe.execute()

        allowed = count < rps
        if not allowed:
            logger.warning("ratelimit.hit", key_id=key_id, rps=rps, count=count)

        return allowed

    async def get_remaining(self, key_id: str, rps: int, window_sec: int = 1) -> int:
        """返回当前窗口剩余可用次数。"""
        now_ms = int(time.time() * 1000)
        window_key = f"ratelimit:{key_id}:{window_sec}"
        window_start = now_ms - window_sec * 1000

        await self.redis.zremrangebyscore(window_key, 0, window_start)
        count = await self.redis.zcard(window_key)
        return max(0, rps - count)
