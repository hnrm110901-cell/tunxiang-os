"""令牌桶限流中间件 — 基于内存的 per-tenant 限流

职责：
  - 每个 tenant_id 独立限流（令牌桶算法）
  - 默认：100 req/min，突发上限 200
  - 超限返回 429 Too Many Requests
  - 响应头：X-RateLimit-Limit / X-RateLimit-Remaining / X-RateLimit-Reset
  - API Key 调用使用应用自身的 rate_limit_per_min 配置

环境变量：
  TX_RATE_LIMIT_ENABLED   — 设为 "false" 跳过限流
  TX_RATE_LIMIT_PER_MIN   — 每分钟默认请求上限（默认 100）
  TX_RATE_LIMIT_BURST     — 突发上限（默认 200）

生产环境可切换为 Redis 实现（通过 set_redis 注入 Redis 客户端）。
"""

import os
import time
from threading import Lock

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

logger = structlog.get_logger(__name__)

# 免限流路径
RATE_LIMIT_EXEMPT_PREFIXES: tuple[str, ...] = (
    "/health",
    "/docs",
    "/openapi.json",
    "/redoc",
)


class _TokenBucket:
    """单个令牌桶实例。

    tokens:     当前可用令牌数
    max_tokens: 桶容量（突发上限）
    refill_rate: 每秒补充令牌数 (= limit_per_min / 60)
    last_refill: 上次补充时间戳
    """

    __slots__ = ("tokens", "max_tokens", "refill_rate", "last_refill")

    def __init__(self, max_tokens: int, refill_rate: float) -> None:
        self.tokens = float(max_tokens)
        self.max_tokens = max_tokens
        self.refill_rate = refill_rate
        self.last_refill = time.monotonic()

    def consume(self) -> bool:
        """尝试消耗一个令牌。返回 True 表示允许，False 表示超限。"""
        now = time.monotonic()
        elapsed = now - self.last_refill
        self.last_refill = now

        # 补充令牌
        self.tokens = min(
            self.max_tokens,
            self.tokens + elapsed * self.refill_rate,
        )

        if self.tokens >= 1.0:
            self.tokens -= 1.0
            return True
        return False

    @property
    def remaining(self) -> int:
        """当前剩余令牌数（向下取整）。"""
        return max(0, int(self.tokens))


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Per-tenant 令牌桶限流中间件。

    内存实现，适合单实例部署。多实例部署时需切换为 Redis 后端。
    """

    def __init__(self, app, limit_per_min: int | None = None, burst: int | None = None) -> None:  # noqa: ANN001
        super().__init__(app)
        self._enabled = os.getenv("TX_RATE_LIMIT_ENABLED", "true").lower() != "false"
        self._default_limit = limit_per_min or int(os.getenv("TX_RATE_LIMIT_PER_MIN", "100"))
        self._default_burst = burst or int(os.getenv("TX_RATE_LIMIT_BURST", "200"))
        self._buckets: dict[str, _TokenBucket] = {}
        self._lock = Lock()

    def _get_bucket(self, key: str, limit_per_min: int, burst: int) -> _TokenBucket:
        """获取或创建令牌桶（线程安全）。"""
        if key not in self._buckets:
            with self._lock:
                if key not in self._buckets:
                    refill_rate = limit_per_min / 60.0
                    self._buckets[key] = _TokenBucket(
                        max_tokens=burst,
                        refill_rate=refill_rate,
                    )
        return self._buckets[key]

    async def dispatch(self, request: Request, call_next) -> Response:  # noqa: ANN001
        # 禁用时直接放行
        if not self._enabled:
            return await call_next(request)

        path = request.url.path

        # 免限流路径
        if any(path.startswith(prefix) for prefix in RATE_LIMIT_EXEMPT_PREFIXES):
            return await call_next(request)

        # 确定限流 key 和参数
        tenant_id = getattr(request.state, "tenant_id", None) or "anonymous"
        auth_method = getattr(request.state, "auth_method", None)

        # API Key 使用应用专属限流配置
        if auth_method == "api_key":
            app_rate_limit = getattr(request.state, "api_key_rate_limit", None)
            limit_per_min = app_rate_limit or self._default_limit
            burst = min(limit_per_min * 2, self._default_burst * 2)
            bucket_key = f"api:{getattr(request.state, 'api_key_app_id', tenant_id)}"
        else:
            limit_per_min = self._default_limit
            burst = self._default_burst
            bucket_key = f"tenant:{tenant_id}"

        bucket = self._get_bucket(bucket_key, limit_per_min, burst)
        allowed = bucket.consume()

        # 计算 reset 时间（下一个整分钟）
        now = int(time.time())
        reset_at = ((now // 60) + 1) * 60

        if not allowed:
            logger.warning(
                "rate_limit_exceeded",
                bucket_key=bucket_key,
                limit_per_min=limit_per_min,
                path=path,
                method=request.method,
            )
            return JSONResponse(
                status_code=429,
                content={
                    "ok": False,
                    "data": None,
                    "error": {
                        "code": "RATE_LIMIT_EXCEEDED",
                        "message": f"Rate limit exceeded. Limit: {limit_per_min} requests/min",
                    },
                },
                headers={
                    "X-RateLimit-Limit": str(limit_per_min),
                    "X-RateLimit-Remaining": "0",
                    "X-RateLimit-Reset": str(reset_at),
                    "Retry-After": str(reset_at - now),
                },
            )

        response = await call_next(request)

        # 注入限流响应头
        response.headers["X-RateLimit-Limit"] = str(limit_per_min)
        response.headers["X-RateLimit-Remaining"] = str(bucket.remaining)
        response.headers["X-RateLimit-Reset"] = str(reset_at)

        return response
