"""个性化网关中间件 — 每个请求注入用户分层信息

在 TenantMiddleware 之后执行：
1. 从JWT中提取 user_id
2. 查询Redis缓存的用户分层信息（TTL 5min）
3. 注入 X-User-Segment / X-User-Prefs / X-User-Subscription headers
4. 下游服务直接读header，无需重复查库

降级策略：Redis不可用时跳过注入，下游服务自行查询
"""

import json
import os
from typing import Optional

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

logger = structlog.get_logger()

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
CACHE_TTL = 300  # 5 minutes

# Redis连接（延迟初始化）
_redis = None


async def _get_redis():
    """获取Redis连接（单例，延迟初始化）"""
    global _redis
    if _redis is None:
        try:
            import redis.asyncio as aioredis

            _redis = await aioredis.from_url(
                REDIS_URL,
                decode_responses=True,
                socket_connect_timeout=2,
                socket_timeout=2,
            )
        except (ImportError, OSError) as exc:
            logger.warning("personalization_redis_unavailable", error=str(exc))
            return None
    return _redis


def _extract_user_id(request: Request) -> Optional[str]:
    """从Authorization header的JWT中提取user_id"""
    auth = request.headers.get("authorization", "")
    if not auth.startswith("Bearer "):
        return None
    token = auth[7:]
    try:
        import base64

        payload = token.split(".")[1]
        # 补齐base64 padding
        payload += "=" * (4 - len(payload) % 4)
        data = json.loads(base64.urlsafe_b64decode(payload))
        return data.get("user_id") or data.get("sub")
    except (IndexError, ValueError, KeyError):
        return None


class PersonalizationMiddleware(BaseHTTPMiddleware):
    """注入用户个性化上下文到请求headers"""

    async def dispatch(self, request: Request, call_next) -> Response:
        # 只对API请求注入（跳过健康检查等）
        if not request.url.path.startswith("/api/"):
            return await call_next(request)

        user_id = _extract_user_id(request)
        if not user_id:
            return await call_next(request)

        # 查询Redis缓存
        try:
            r = await _get_redis()
            if r:
                cached = await r.get(f"user_ctx:{user_id}")
                if cached:
                    ctx = json.loads(cached)
                    # 注入headers（Starlette的scope可变）
                    scope = request.scope
                    headers = dict(scope.get("headers", []))
                    headers[b"x-user-segment"] = ctx.get("segment", "S3").encode()
                    headers[b"x-user-prefs"] = json.dumps(ctx.get("prefs", {})).encode()
                    headers[b"x-user-subscription"] = ctx.get("subscription", "none").encode()
                    scope["headers"] = list(headers.items())

                    logger.debug("personalization_context_injected", user_id=user_id, segment=ctx.get("segment"))
        except (ConnectionError, TimeoutError, OSError) as exc:
            # Redis不可用→降级跳过，不影响请求
            logger.warning("personalization_redis_error", error=str(exc))

        return await call_next(request)
