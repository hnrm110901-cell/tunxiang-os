"""health_routes — 系统健康监控端点

提供事件总线、Agent系统、Redis 的实时健康状态。
不需要认证，监控系统直接访问。响应时间目标 < 200ms。
"""

import os

import redis.asyncio as aioredis
from fastapi import APIRouter

router = APIRouter(prefix="/api/v1/health", tags=["health"])

_REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
_REDIS_TIMEOUT = 2  # 秒，保证响应时间 < 200ms

_DOMAIN_STREAMS = [
    "trade_events",
    "supply_events",
    "finance_events",
    "org_events",
    "menu_events",
    "ops_events",
    "agent_events",
]


@router.get("")
async def system_health() -> dict:
    """系统整体健康检查"""
    checks = {
        "redis": await _check_redis(),
        "event_streams": await _check_event_streams(),
        "model_router": await _check_model_router(),
    }
    all_ok = all(c["ok"] for c in checks.values())
    return {
        "ok": all_ok,
        "status": "healthy" if all_ok else "degraded",
        "checks": checks,
    }


@router.get("/events")
async def event_bus_stats() -> dict:
    """事件总线统计（各 Stream 积压量 + Consumer Group pending 数）"""
    try:
        r = await aioredis.from_url(
            _REDIS_URL,
            decode_responses=True,
            socket_connect_timeout=_REDIS_TIMEOUT,
            socket_timeout=_REDIS_TIMEOUT,
        )
        result: dict[str, dict] = {}
        for stream in _DOMAIN_STREAMS:
            try:
                info = await r.xinfo_stream(stream)
                # 获取 Consumer Group 列表及各组 pending 数
                try:
                    groups_raw = await r.xinfo_groups(stream)
                    consumer_groups = [
                        {
                            "name": g.get("name", ""),
                            "pending": g.get("pending", 0),
                            "consumers": g.get("consumers", 0),
                            "last_delivered_id": g.get("last-delivered-id", ""),
                        }
                        for g in groups_raw
                    ]
                except (OSError, RuntimeError):
                    consumer_groups = []

                result[stream] = {
                    "length": info.get("length", 0),
                    "consumer_groups": consumer_groups,
                }
            except Exception:  # noqa: BLE001 — stream 不存在时跳过，不影响其他流
                result[stream] = {"length": 0, "exists": False, "consumer_groups": []}

        await r.aclose()
        return {"ok": True, "streams": result}
    except (OSError, RuntimeError) as exc:
        return {"ok": False, "error": str(exc), "streams": {}}


# ─────────────────────────────────────────────────────────────────────────────
# 内部检查函数
# ─────────────────────────────────────────────────────────────────────────────


async def _check_redis() -> dict:
    """检查 Redis 连通性"""
    try:
        r = await aioredis.from_url(
            _REDIS_URL,
            socket_connect_timeout=_REDIS_TIMEOUT,
            socket_timeout=_REDIS_TIMEOUT,
        )
        await r.ping()
        await r.aclose()
        return {"ok": True}
    except (OSError, RuntimeError) as exc:
        return {"ok": False, "error": str(exc)}


async def _check_event_streams() -> dict:
    """检查各业务域 Redis Stream 的积压量"""
    try:
        r = await aioredis.from_url(
            _REDIS_URL,
            decode_responses=True,
            socket_connect_timeout=_REDIS_TIMEOUT,
            socket_timeout=_REDIS_TIMEOUT,
        )
        result: dict[str, dict] = {}
        for stream in _DOMAIN_STREAMS:
            try:
                info = await r.xinfo_stream(stream)
                result[stream] = {
                    "length": info.get("length", 0),
                    "first_entry": info.get("first-entry"),
                    "last_entry": info.get("last-entry"),
                }
            except Exception:  # noqa: BLE001 — stream 不存在时跳过
                result[stream] = {"length": 0, "exists": False}
        await r.aclose()
        return {"ok": True, "streams": result}
    except (OSError, RuntimeError) as exc:
        return {"ok": False, "error": str(exc)}


async def _check_model_router() -> dict:
    """检查 ModelRouter 是否可用（验证 API Key 配置）"""
    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    if not api_key or not api_key.startswith("sk-"):
        return {"ok": False, "error": "ANTHROPIC_API_KEY not configured"}
    return {"ok": True, "key_prefix": api_key[:8] + "..."}
