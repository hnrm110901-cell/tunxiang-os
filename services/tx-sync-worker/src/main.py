"""tx-sync-worker · FastAPI app + lifespan (W2 P1 issue #758).

战略 plan §23 W2 / §24 举措 #1 服务收敛:
  端口 :8021 (plan §0.1 verify).
  Phase 1 dry_run 默认开启 (env RUN_MODE=dry_run), Phase 2 follow-up issue 翻 RUN_MODE=live
  并**同时**关 gateway scheduler 切单轨 (per plan §7.1 P0 风险缓解).

endpoint:
  GET /health     — 5 jobs 注册状态 + scheduler.running + RUN_MODE
  GET /metrics    — Prometheus exposition (sync_executions_total / last_run / dry_run_active)
"""
from __future__ import annotations

import os
from contextlib import asynccontextmanager
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

from .metrics import sync_dry_run_active

logger = structlog.get_logger(__name__)


# 全局 runtime state (lifespan 管理)
_state: dict[str, Any] = {
    "scheduler": None,
    "run_mode": None,
}


def _current_run_mode() -> str:
    """读 RUN_MODE env, default dry_run."""
    return os.environ.get("RUN_MODE", "dry_run").strip().lower()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """启动 APScheduler 5 jobs, shutdown 收尾.

    fail-open: 若 apscheduler 不可用 (CI minimal deps), lifespan 不启 scheduler,
    /health 返 degraded; 不阻塞 /metrics + /health import smoke.
    """
    run_mode = _current_run_mode()
    _state["run_mode"] = run_mode
    is_dry_run = run_mode != "live"
    sync_dry_run_active.set(1 if is_dry_run else 0)

    scheduler = None
    try:
        from .scheduler import create_sync_scheduler

        scheduler = create_sync_scheduler()
        scheduler.start()
        _state["scheduler"] = scheduler
        logger.info(
            "tx_sync_worker_started",
            port=8021,
            run_mode=run_mode,
            dry_run=is_dry_run,
            jobs_count=len(scheduler.get_jobs()),
        )
    except (ImportError, RuntimeError) as exc:
        # CI minimal deps / apscheduler 不可用 — 不阻塞 import smoke
        logger.error(
            "tx_sync_worker_scheduler_unavailable_degraded",
            error=str(exc),
            error_type=type(exc).__name__,
            exc_info=True,
        )
    except Exception as exc:  # noqa: BLE001 — startup 兜底, per CLAUDE.md §14 exc_info
        logger.error(
            "tx_sync_worker_startup_failed_degraded",
            error=str(exc),
            error_type=type(exc).__name__,
            exc_info=True,
        )

    try:
        yield
    finally:
        if scheduler is not None:
            try:
                scheduler.shutdown(wait=False)
                logger.info("tx_sync_worker_shutdown")
            except Exception as exc:  # noqa: BLE001 — shutdown 兜底
                logger.warning(
                    "tx_sync_worker_shutdown_error",
                    error=str(exc),
                    exc_info=True,
                )


app = FastAPI(
    title="tx-sync-worker · 屯象 品智POS 同步 + 企微 daily SOP daemon",
    version="1.0.0",
    description="W2 P1 #758 Gateway 瘦身: 抽出 5 cron jobs (Phase 1 dry_run 默认).",
    lifespan=lifespan,
)


@app.get("/health")
async def health() -> dict[str, Any]:
    """sync-worker 健康状态.

    返回 5 jobs 注册情况 + scheduler.running + RUN_MODE.
    """
    scheduler = _state.get("scheduler")
    run_mode = _state.get("run_mode") or _current_run_mode()
    jobs: list[dict[str, Any]] = []
    if scheduler is not None:
        for job in scheduler.get_jobs():
            jobs.append(
                {
                    "id": job.id,
                    "next_run_time": job.next_run_time.isoformat() if job.next_run_time else None,
                }
            )

    return {
        "ok": True,
        "service": "tx-sync-worker",
        "port": 8021,
        "run_mode": run_mode,
        "dry_run": run_mode != "live",
        "scheduler_running": scheduler is not None and getattr(scheduler, "running", False),
        "jobs": jobs,
    }


@app.get("/metrics")
async def metrics() -> Response:
    """Prometheus exposition endpoint."""
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)
