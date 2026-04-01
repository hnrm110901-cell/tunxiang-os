"""notification_routes — 操作员实时通知接口

GET /api/v1/notifications/pending — 轮询待处理通知（Redis list）
SSE /api/v1/notifications/stream  — 实时推送（Redis Pub/Sub → SSE）
"""
from __future__ import annotations

import asyncio
import json
import os
from typing import AsyncGenerator

import structlog
from fastapi import APIRouter, Header, HTTPException, Query
from fastapi.responses import StreamingResponse

logger = structlog.get_logger()

router = APIRouter(prefix="/api/v1/notifications", tags=["notifications"])

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
# SSE 心跳间隔（秒），防止代理/负载均衡断连
_SSE_KEEPALIVE_SECONDS = 15


# ── GET /pending ─────────────────────────────────────────────────────────────


@router.get("/pending", response_model=dict)
async def get_pending_notifications(
    operator_id: str = Query(..., description="操作员 ID（UUID）"),
    x_tenant_id: str = Header("default", alias="X-Tenant-ID"),
) -> dict:
    """从 Redis 读取当前操作员的待处理通知列表（轮询用）。

    返回最近 50 条，按写入时间倒序（最新在前）。
    消费后不自动删除，前端需调用 DELETE 端点或等待 TTL 自动过期。
    """
    try:
        import redis.asyncio as aioredis

        redis = await aioredis.from_url(REDIS_URL, decode_responses=True, socket_timeout=3)
        key = f"pending_plans:{x_tenant_id}:{operator_id}"
        raw_items = await redis.lrange(key, 0, 49)  # 最多 50 条
        await redis.aclose()

        notifications = []
        for raw in raw_items:
            try:
                notifications.append(json.loads(raw))
            except json.JSONDecodeError as exc:
                logger.warning("notification_json_decode_error", error=str(exc), raw=raw[:100])

        return {
            "ok": True,
            "data": {"items": notifications, "total": len(notifications)},
            "error": None,
        }

    except (OSError, RuntimeError) as exc:
        logger.warning("redis_pending_fetch_failed", error=str(exc))
        raise HTTPException(status_code=503, detail="通知服务暂时不可用，请稍后重试")


# ── GET /stream (SSE) ────────────────────────────────────────────────────────


@router.get("/stream")
async def stream_notifications(
    operator_id: str = Query(..., description="操作员 ID（UUID）"),
    x_tenant_id: str = Header("default", alias="X-Tenant-ID"),
) -> StreamingResponse:
    """SSE 长连接，订阅 Redis Pub/Sub 推送实时通知。

    频道：`ops_notifications:{tenant_id}`
    客户端收到通知后，再调用 /pending 获取完整通知详情（或直接使用 SSE data）。

    连接断开后客户端应自动重连（标准 SSE 行为）。
    """
    return StreamingResponse(
        _sse_generator(x_tenant_id, operator_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # 禁用 nginx 缓冲，保证实时推送
        },
    )


async def _sse_generator(tenant_id: str, operator_id: str) -> AsyncGenerator[str, None]:
    """SSE 事件生成器：订阅 Redis Pub/Sub，转换为 SSE 格式推送给客户端。"""
    channel = f"ops_notifications:{tenant_id}"

    try:
        import redis.asyncio as aioredis

        redis = await aioredis.from_url(REDIS_URL, decode_responses=True, socket_timeout=3)
        pubsub = redis.pubsub()
        await pubsub.subscribe(channel)
        logger.info("sse_subscribed", tenant_id=tenant_id, operator_id=operator_id, channel=channel)

        # 发送连接确认事件
        yield _sse_event("connected", {"channel": channel, "operator_id": operator_id})

        last_keepalive = asyncio.get_event_loop().time()

        while True:
            now = asyncio.get_event_loop().time()

            # 心跳：防止代理超时断连
            if now - last_keepalive >= _SSE_KEEPALIVE_SECONDS:
                yield ": keepalive\n\n"
                last_keepalive = now

            # 非阻塞读取消息（100ms 轮询间隔）
            message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=0.1)
            if message is None:
                await asyncio.sleep(0.05)
                continue

            data_raw = message.get("data")
            if not isinstance(data_raw, str):
                continue

            try:
                notification = json.loads(data_raw)
            except json.JSONDecodeError as exc:
                logger.warning("sse_json_decode_error", error=str(exc))
                continue

            # 仅推送给目标操作员，或广播给租户所有操作员
            target_operator = notification.get("operator_id")
            if target_operator and target_operator != operator_id:
                continue

            yield _sse_event("operation_plan_created", notification)
            logger.debug("sse_event_sent", plan_id=notification.get("plan_id"), operator_id=operator_id)

    except (OSError, RuntimeError) as exc:
        logger.warning("sse_redis_error", tenant_id=tenant_id, error=str(exc))
        yield _sse_event("error", {"message": "通知服务连接中断，请重新连接"})
    finally:
        try:
            await pubsub.unsubscribe(channel)
            await redis.aclose()
        except Exception:  # noqa: BLE001 — 清理阶段兜底，不应再抛出
            pass


def _sse_event(event_type: str, data: dict) -> str:
    """格式化为标准 SSE 事件字符串。"""
    payload = json.dumps(data, ensure_ascii=False)
    return f"event: {event_type}\ndata: {payload}\n\n"
