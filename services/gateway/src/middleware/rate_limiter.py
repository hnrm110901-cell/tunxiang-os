"""速率限制中间件 — 滑动窗口算法，基于Redis实现

每个app_id + 分钟桶作为key，使用INCR + EXPIRE实现计数。
Redis不可用时优雅降级：放行请求并记录警告，不拒绝服务。
"""

import time
from typing import Optional

import structlog

logger = structlog.get_logger()


class RateLimiter:
    """滑动窗口速率限制器。

    key格式: f"rl:{app_id}:{minute_bucket}"
    TTL: 2分钟（保证跨分钟边界的计数窗口完整）

    返回值说明:
        allowed   — 是否允许本次请求
        remaining — 当前窗口剩余配额
        reset_at  — 当前窗口重置时间戳（Unix秒）
    """

    _TTL_SECONDS = 120  # 2分钟TTL

    def __init__(self, redis_client=None) -> None:
        self._redis = redis_client

    def set_redis(self, redis_client) -> None:
        """注入Redis客户端（支持延迟初始化）"""
        self._redis = redis_client

    async def check_rate_limit(
        self, app_id: str, limit_per_min: int
    ) -> tuple[bool, int, int]:
        """检查速率限制。

        Args:
            app_id:        应用ID
            limit_per_min: 每分钟最大请求数

        Returns:
            (allowed, remaining, reset_at_ts)
            - allowed:      True表示允许，False表示超限
            - remaining:    当前窗口剩余配额（可能为负数时返回0）
            - reset_at_ts:  下一分钟窗口开始时间（Unix秒）
        """
        now = int(time.time())
        minute_bucket = now // 60
        reset_at = (minute_bucket + 1) * 60
        key = f"rl:{app_id}:{minute_bucket}"

        if self._redis is None:
            logger.warning(
                "rate_limiter_redis_not_configured",
                app_id=app_id,
                degraded=True,
            )
            return True, limit_per_min, reset_at

        try:
            current_count = await self._redis.incr(key)

            # 首次写入时设置TTL
            if current_count == 1:
                await self._redis.expire(key, self._TTL_SECONDS)

            remaining = max(0, limit_per_min - current_count)
            allowed = current_count <= limit_per_min

            if not allowed:
                logger.warning(
                    "rate_limit_exceeded",
                    app_id=app_id,
                    current_count=current_count,
                    limit=limit_per_min,
                    reset_at=reset_at,
                )

            return allowed, remaining, reset_at

        except ConnectionError as exc:
            # Redis连接断开 — 优雅降级，放行请求
            logger.warning(
                "rate_limiter_redis_connection_error",
                app_id=app_id,
                error=str(exc),
                degraded=True,
            )
            return True, limit_per_min, reset_at

        except TimeoutError as exc:
            # Redis超时 — 优雅降级，放行请求
            logger.warning(
                "rate_limiter_redis_timeout",
                app_id=app_id,
                error=str(exc),
                degraded=True,
            )
            return True, limit_per_min, reset_at

        except OSError as exc:
            # 网络层错误 — 优雅降级，放行请求
            logger.warning(
                "rate_limiter_redis_os_error",
                app_id=app_id,
                error=str(exc),
                degraded=True,
            )
            return True, limit_per_min, reset_at

    async def reset_app_limit(self, app_id: str) -> bool:
        """重置指定应用的当前分钟计数（测试/运维用）"""
        if self._redis is None:
            return False

        now = int(time.time())
        minute_bucket = now // 60
        key = f"rl:{app_id}:{minute_bucket}"

        try:
            deleted = await self._redis.delete(key)
            return bool(deleted)
        except (ConnectionError, TimeoutError, OSError) as exc:
            logger.warning(
                "rate_limiter_reset_failed",
                app_id=app_id,
                error=str(exc),
            )
            return False

    async def get_current_count(self, app_id: str) -> Optional[int]:
        """获取当前分钟的请求计数（监控用）"""
        if self._redis is None:
            return None

        now = int(time.time())
        minute_bucket = now // 60
        key = f"rl:{app_id}:{minute_bucket}"

        try:
            val = await self._redis.get(key)
            return int(val) if val is not None else 0
        except (ConnectionError, TimeoutError, OSError) as exc:
            logger.warning(
                "rate_limiter_get_count_failed",
                app_id=app_id,
                error=str(exc),
            )
            return None


class LoginBruteForceProtection:
    """
    等保三级要求：连续失败5次→锁定30分钟
    独立于普通限速，专门针对登录接口
    Key: "login_fail:ip:{ip}" 和 "login_fail:user:{username}"
    """

    MAX_ATTEMPTS = 5
    LOCKOUT_SECONDS = 1800  # 30分钟

    def __init__(self, redis_client=None) -> None:
        self._redis = redis_client

    def set_redis(self, client) -> None:
        self._redis = client

    async def record_failure(self, ip: str, username: str) -> int:
        """记录失败，返回剩余尝试次数。Redis不可用时降级为放行。"""
        if not self._redis:
            return self.MAX_ATTEMPTS
        try:
            pipe = self._redis.pipeline()
            ip_key = f"login_fail:ip:{ip}"
            user_key = f"login_fail:user:{username}"
            pipe.incr(ip_key)
            pipe.expire(ip_key, self.LOCKOUT_SECONDS)
            pipe.incr(user_key)
            pipe.expire(user_key, self.LOCKOUT_SECONDS)
            results = await pipe.execute()
            count = max(results[0], results[2])
            remaining = max(0, self.MAX_ATTEMPTS - count)
            logger.info(
                "login_failure_recorded",
                ip=ip,
                username=username,
                count=count,
                remaining=remaining,
            )
            return remaining
        except Exception as exc:  # noqa: BLE001 — Redis故障不阻断登录（降级）
            logger.warning("brute_force_redis_error", error=str(exc))
            return self.MAX_ATTEMPTS

    async def is_locked(self, ip: str, username: str) -> bool:
        """检查IP或用户名是否已被锁定。"""
        if not self._redis:
            return False
        try:
            ip_key = f"login_fail:ip:{ip}"
            user_key = f"login_fail:user:{username}"
            ip_count = await self._redis.get(ip_key) or 0
            user_count = await self._redis.get(user_key) or 0
            return int(ip_count) >= self.MAX_ATTEMPTS or int(user_count) >= self.MAX_ATTEMPTS
        except Exception as exc:  # noqa: BLE001 — Redis故障降级为放行
            logger.warning("brute_force_check_error", error=str(exc))
            return False

    async def clear_on_success(self, ip: str, username: str) -> None:
        """登录成功后清除失败计数。"""
        if not self._redis:
            return
        try:
            await self._redis.delete(
                f"login_fail:ip:{ip}", f"login_fail:user:{username}"
            )
        except Exception as exc:  # noqa: BLE001 — Redis故障不阻断成功登录
            logger.warning("brute_force_clear_error", error=str(exc))
