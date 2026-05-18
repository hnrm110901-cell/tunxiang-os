"""tx-event-relay · FastAPI app + lifespan (W3 P0 issue #757).

战略 plan §4 举措 3 "真 Outbox":
  端口 :8020 (创始人 Q2 决议).
  shadow mode 默认开启 (env RELAY_SHADOW_MODE=true), W11 follow-up issue #767
  评估切真路径 (shadow_mode=false).

endpoint:
  GET /health     — relay 进程状态 + last_poll_at + pending_count
  GET /metrics    — Prometheus exposition (outbox_pending_count / delivery_lag 等)
"""
from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any

import structlog
from fastapi import FastAPI

try:
    from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

    _PROM_AVAILABLE = True
except ImportError:  # pragma: no cover — CI minimal deps fallback
    _PROM_AVAILABLE = False

    CONTENT_TYPE_LATEST = "text/plain"  # type: ignore[assignment]

    def generate_latest(*_args, **_kwargs) -> bytes:  # type: ignore[no-redef]
        return b""


from fastapi.responses import Response

from .outbox_repo import count_pending, create_pool
from .relay_worker import RelayConfig, relay_loop, update_pending_count_gauge

logger = structlog.get_logger(__name__)


# 全局 runtime state (lifespan 管理)
_state: dict[str, Any] = {
    "pool": None,
    "relay_task": None,
    "shutdown_event": None,
    "last_poll_at": None,
    "config": None,
}


async def _periodic_pending_count_refresh(
    pool: Any, shutdown_event: asyncio.Event, interval_sec: float = 10.0
) -> None:
    """定期刷新 outbox_pending_count gauge + last_poll_at.

    shadow 期间表预期空, COUNT 0 IO 开销.
    """
    while not shutdown_event.is_set():
        try:
            count = await count_pending(pool)
            update_pending_count_gauge(count)
            _state["last_poll_at"] = datetime.now(timezone.utc).isoformat()
        except Exception as exc:  # noqa: BLE001 — outermost monitoring loop, exc_info+continue
            logger.warning(
                "pending_count_refresh_failed",
                error=str(exc),
                error_type=type(exc).__name__,
                exc_info=True,
            )
        await asyncio.sleep(interval_sec)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """启动 relay loop + pending count refresh, shutdown 收尾."""
    config = RelayConfig.from_env()
    _state["config"] = config
    shutdown_event = asyncio.Event()
    _state["shutdown_event"] = shutdown_event

    # 尝试建 asyncpg pool. 失败 (DATABASE_URL 缺 / asyncpg 不可用) → 不启动 relay loop,
    # 仅暴露 /health (degraded 状态) — 测试 / CI minimal deps 场景下不阻塞 import smoke.
    pool = None
    relay_task = None
    refresh_task = None
    try:
        pool = await create_pool()
        _state["pool"] = pool
        relay_task = asyncio.create_task(relay_loop(pool, config, shutdown_event))
        refresh_task = asyncio.create_task(_periodic_pending_count_refresh(pool, shutdown_event))
        _state["relay_task"] = relay_task
        logger.info("tx_event_relay_started", shadow_mode=config.shadow_mode, port=8020)
    except Exception as exc:  # noqa: BLE001 — startup degraded 兜底, exc_info per §14
        logger.error(
            "tx_event_relay_startup_failed_degraded",
            error=str(exc),
            error_type=type(exc).__name__,
            exc_info=True,
        )

    try:
        yield
    finally:
        shutdown_event.set()
        for task in (relay_task, refresh_task):
            if task is not None:
                try:
                    await asyncio.wait_for(task, timeout=5.0)
                except asyncio.TimeoutError:
                    task.cancel()
                except Exception as exc:  # noqa: BLE001 — shutdown 兜底
                    logger.warning(
                        "tx_event_relay_task_shutdown_error",
                        error=str(exc),
                        exc_info=True,
                    )
        if pool is not None:
            try:
                await pool.close()
            except Exception as exc:  # noqa: BLE001 — shutdown 兜底
                logger.warning(
                    "tx_event_relay_pool_close_error",
                    error=str(exc),
                    exc_info=True,
                )
        logger.info("tx_event_relay_shutdown")


app = FastAPI(
    title="tx-event-relay · 屯象 Outbox Relay (shadow)",
    version="1.0.0",
    description="W3 P0 #757 真 Outbox shadow mode worker (端口 8020).",
    lifespan=lifespan,
)

# /metrics 端点 Bearer + IP allowlist 鉴权 (issue #825 W3 D2 决策矩阵分母)
from shared.middleware.src.metrics_auth import MetricsAuthMiddleware  # noqa: E402

app.add_middleware(MetricsAuthMiddleware)


@app.get("/health")
async def health() -> dict[str, Any]:
    """relay 进程健康状态.

    shadow 期间正常返回 ok=true + polling=true + pending_count=0.
    """
    config: RelayConfig | None = _state.get("config")
    pool = _state.get("pool")
    relay_task = _state.get("relay_task")
    return {
        "ok": True,
        "service": "tx-event-relay",
        "port": 8020,
        "shadow_mode": config.shadow_mode if config else None,
        "polling": relay_task is not None and not relay_task.done(),
        "last_poll_at": _state.get("last_poll_at"),
        "pool_ready": pool is not None,
    }


@app.get("/metrics")
async def metrics() -> Response:
    """Prometheus exposition endpoint (验收 #5)."""
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)
