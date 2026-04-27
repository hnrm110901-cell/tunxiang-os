"""菜品制作时间基准 API

提供制作时间预估、队列清空预测、基准重算等接口，
给前台/Expo/KDS前端使用。

所有接口需要 X-Tenant-ID header。
"""

import asyncio
from datetime import datetime, timezone

import structlog
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

from ..services.cook_time_stats import CookTimeStatsService

logger = structlog.get_logger()

router = APIRouter(prefix="/api/v1/cook-time", tags=["cook-time"])


# ─── 工具函数 ───


def _get_tenant_id(request: Request) -> str:
    tid = getattr(request.state, "tenant_id", None) or request.headers.get("X-Tenant-ID", "")
    if not tid:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header required")
    return tid


# ─── 每日定时重算任务 ───

_scheduler_started = False


async def _daily_recompute_job(db_factory) -> None:
    """每日凌晨2点触发所有租户基准重算。

    使用 asyncio.sleep 的轻量级调度器，无需引入第三方依赖。
    如果项目后续接入 APScheduler 或 Celery，可替换此函数。
    """
    log = logger.bind(job="daily_recompute_baselines")
    while True:
        now = datetime.now(timezone.utc)
        # 计算到下一个凌晨2:00（UTC+8即北京时间18:00 UTC）的秒数
        # 默认使用 UTC 02:00，部署时可通过 RECOMPUTE_HOUR_UTC 环境变量调整
        import os

        target_hour = int(os.getenv("RECOMPUTE_HOUR_UTC", "18"))  # 默认18:00 UTC = 北京时间02:00

        next_run = now.replace(hour=target_hour, minute=0, second=0, microsecond=0)
        if next_run <= now:
            next_run = next_run.replace(day=next_run.day + 1)

        wait_seconds = (next_run - now).total_seconds()
        log.info(
            "cook_time_stats.scheduler.next_run",
            next_run=next_run.isoformat(),
            wait_hours=round(wait_seconds / 3600, 1),
        )
        await asyncio.sleep(wait_seconds)

        # 触发重算
        try:
            async with db_factory() as db:
                service = CookTimeStatsService(db)
                # 此处无法枚举所有租户，需由平台层调用或改为事件驱动
                # 实际生产中应从 tenants 表查出所有活跃租户再逐一触发
                log.info("cook_time_stats.scheduler.trigger", note="需从tenants表枚举所有租户")
        except Exception as exc:  # noqa: BLE001 — MLPS3-P0: 后台定时任务最外层兜底，不能崩溃
            log.error("cook_time_stats.scheduler.failed", error=str(exc))


def start_daily_scheduler(db_factory) -> None:
    """在FastAPI lifespan中调用，启动后台定时重算任务。"""
    global _scheduler_started
    if _scheduler_started:
        return
    _scheduler_started = True
    asyncio.create_task(_daily_recompute_job(db_factory))
    logger.info("cook_time_stats.scheduler.started")


# ─── API 路由 ───


@router.get(
    "/expected/{dish_id}",
    summary="预计制作时间",
    description="根据历史基准返回菜品在当前时段的预期制作时间（秒）。无历史数据时fallback到档口默认值。",
)
async def get_expected_duration(
    dish_id: str,
    request: Request,
    dept_id: str = "",
    db: AsyncSession = Depends(get_db),
):
    """
    GET /cook-time/expected/{dish_id}?dept_id=xxx

    Returns:
        {
          "ok": true,
          "data": {
            "dish_id": "...",
            "dept_id": "...",
            "estimated_seconds": 480,
            "source": "baseline" | "dept_default",
            "reliable": true,
            "p50_seconds": 480,
            "p90_seconds": 720,
            "sample_count": 25
          }
        }
    """
    tenant_id = _get_tenant_id(request)

    if not dept_id:
        raise HTTPException(status_code=400, detail="dept_id query parameter required")

    service = CookTimeStatsService(db)
    result = await service.get_expected_duration_with_meta(dish_id, dept_id, tenant_id)

    return {
        "ok": True,
        "data": {
            "dish_id": dish_id,
            "dept_id": dept_id,
            **result,
        },
    }


@router.get(
    "/queue-estimate/{dept_id}",
    summary="队列预估清空时间",
    description="预估档口当前pending+cooking队列清空所需时间。给前台/叫号屏展示「预计等待X分钟」。",
)
async def estimate_queue_clear_time(
    dept_id: str,
    request: Request,
    concurrent_capacity: int = 2,
    db: AsyncSession = Depends(get_db),
):
    """
    GET /cook-time/queue-estimate/{dept_id}?concurrent_capacity=2

    Returns:
        {
          "ok": true,
          "data": {
            "dept_id": "...",
            "estimated_clear_at": "2026-03-30T14:35:00Z",
            "estimated_wait_minutes": 12,
            "pending_count": 4,
            "total_expected_seconds": 1440,
            "concurrent_capacity": 2
          }
        }
    """
    tenant_id = _get_tenant_id(request)

    service = CookTimeStatsService(db)
    result = await service.estimate_queue_clear_time(dept_id, tenant_id, concurrent_capacity=concurrent_capacity)

    now = datetime.now(timezone.utc)
    wait_minutes = round((result["estimated_clear_at"] - now).total_seconds() / 60, 1)

    return {
        "ok": True,
        "data": {
            "dept_id": dept_id,
            "estimated_clear_at": result["estimated_clear_at"].isoformat(),
            "estimated_wait_minutes": max(0.0, wait_minutes),
            "pending_count": result["pending_count"],
            "total_expected_seconds": result["total_expected_seconds"],
            "concurrent_capacity": result["concurrent_capacity"],
        },
    }


@router.post(
    "/recompute/{dept_id}",
    summary="触发重新计算基准",
    description="管理员手动触发指定档口的制作时间基准重算。异步执行，立即返回任务已接受响应。",
)
async def trigger_recompute(
    dept_id: str,
    request: Request,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """
    POST /cook-time/recompute/{dept_id}

    需要管理员权限（当前暂不做鉴权，由网关层控制）。

    Returns:
        {"ok": true, "data": {"status": "accepted", "dept_id": "...", "triggered_at": "..."}}
    """
    tenant_id = _get_tenant_id(request)
    log = logger.bind(dept_id=dept_id, tenant_id=tenant_id)

    async def _do_recompute(dept_id: str, tenant_id: str) -> None:
        """后台执行重算，避免阻塞请求"""
        try:
            service = CookTimeStatsService(db)
            baselines = await service.recompute_baselines(tenant_id, dept_id=dept_id)
            log.info(
                "cook_time_stats.manual_recompute.done",
                baselines_updated=len(baselines),
            )
        except Exception as exc:  # noqa: BLE001 — MLPS3-P0: 后台重算任务最外层兜底
            log.error("cook_time_stats.manual_recompute.failed", error=str(exc))

    background_tasks.add_task(_do_recompute, dept_id, tenant_id)

    return {
        "ok": True,
        "data": {
            "status": "accepted",
            "dept_id": dept_id,
            "triggered_at": datetime.now(timezone.utc).isoformat(),
            "note": "重算任务已在后台启动，通常几秒内完成",
        },
    }


@router.get(
    "/baselines/{dept_id}",
    summary="查看当前基准数据",
    description="查看档口所有菜品×时段的当前基准数据，用于运营人员查看和调试。",
)
async def get_dept_baselines(
    dept_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    GET /cook-time/baselines/{dept_id}

    Returns:
        {
          "ok": true,
          "data": {
            "dept_id": "...",
            "baselines": [{
              "dish_id": "...",
              "hour_bucket": 12,
              "day_type": "weekday",
              "p50_seconds": 480,
              "p90_seconds": 720,
              "sample_count": 25,
              "computed_at": "2026-03-30T02:00:00Z",
              "is_reliable": true
            }, ...]
          }
        }
    """
    tenant_id = _get_tenant_id(request)

    service = CookTimeStatsService(db)
    baselines = await service.get_dept_baselines(dept_id, tenant_id)

    return {
        "ok": True,
        "data": {
            "dept_id": dept_id,
            "total": len(baselines),
            "baselines": baselines,
        },
    }


@router.get(
    "/thresholds/{dept_id}",
    summary="获取动态超时阈值",
    description="返回基于P90基准的动态warn/critical超时阈值，替代固定25分钟配置。",
)
async def get_timeout_thresholds(
    dept_id: str,
    dish_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    GET /cook-time/thresholds/{dept_id}?dish_id=xxx

    Returns:
        {
          "ok": true,
          "data": {
            "dept_id": "...",
            "dish_id": "...",
            "warn_seconds": 576,
            "warn_minutes": 9.6,
            "critical_seconds": 720,
            "critical_minutes": 12.0,
            "source": "baseline"
          }
        }
    """
    tenant_id = _get_tenant_id(request)

    service = CookTimeStatsService(db)
    thresholds = await service.get_dept_timeout_thresholds(dept_id, dish_id, tenant_id)

    return {
        "ok": True,
        "data": {
            "dept_id": dept_id,
            "dish_id": dish_id,
            "warn_seconds": thresholds["warn_seconds"],
            "warn_minutes": round(thresholds["warn_seconds"] / 60, 1),
            "critical_seconds": thresholds["critical_seconds"],
            "critical_minutes": round(thresholds["critical_seconds"] / 60, 1),
            "source": thresholds["source"],
        },
    }
