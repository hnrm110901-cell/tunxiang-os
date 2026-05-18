"""tx-sync-worker · APScheduler 工厂 (W2 P1 issue #758).

仿 services/gateway/src/sync_scheduler.py:582-648 create_sync_scheduler() 函数,
**业务函数 0 diff**, 加入 wecom_group_daily_sop @ 09:00 (gateway/src/main.py:120).

5 jobs (Q3 决议 A, 与 gateway 完全一致 Asia/Shanghai 时区):
  - daily_dishes_sync               @ cron h=2  m=0
  - daily_master_data_sync          @ cron h=3  m=0
  - hourly_orders_incremental_sync  @ interval hours=1
  - quarter_members_incremental_sync @ interval minutes=15
  - wecom_group_daily_sop           @ cron h=9  m=0

fail-open import 兜底 per memory `feedback_tier1_ci_minimal_deps_trap.md`:
  apscheduler / pytz 在 CI minimal deps workflow 中不一定可用, 模块加载层不崩溃,
  实际 lifespan 启动会要求真依赖装上 (Dockerfile + Helm 装).
"""
from __future__ import annotations

import asyncio

import structlog

from .jobs.pinzhi_sync import (
    _run_dishes_sync,
    _run_master_data_sync,
    _run_members_incremental_sync,
    _run_orders_incremental_sync,
)
from .jobs.wecom_sop import _run_daily_sop

logger = structlog.get_logger(__name__)

try:
    from apscheduler.schedulers.asyncio import AsyncIOScheduler

    _APSCHEDULER_AVAILABLE = True
except ImportError:  # pragma: no cover — CI minimal deps fallback
    _APSCHEDULER_AVAILABLE = False
    AsyncIOScheduler = None  # type: ignore[assignment,misc]


def create_sync_scheduler() -> "AsyncIOScheduler":
    """创建并配置 tx-sync-worker 5 jobs (4 pinzhi + 1 wecom).

    Returns:
        已配置但尚未启动的 AsyncIOScheduler 实例.

    Raises:
        RuntimeError: apscheduler 未装 (CI minimal deps 路径不应直接调).
    """
    if not _APSCHEDULER_AVAILABLE or AsyncIOScheduler is None:
        raise RuntimeError(
            "apscheduler not installed; install requirements.txt before starting scheduler"
        )

    scheduler = AsyncIOScheduler(timezone="Asia/Shanghai")

    # 每日 02:00 — 全量菜品 (gateway sync_scheduler.py:598)
    scheduler.add_job(
        lambda: asyncio.create_task(_run_dishes_sync()),
        "cron",
        hour=2,
        minute=0,
        id="daily_dishes_sync",
        replace_existing=True,
        misfire_grace_time=600,
    )

    # 每日 03:00 — 全量员工 + 桌台 (gateway sync_scheduler.py:609)
    scheduler.add_job(
        lambda: asyncio.create_task(_run_master_data_sync()),
        "cron",
        hour=3,
        minute=0,
        id="daily_master_data_sync",
        replace_existing=True,
        misfire_grace_time=600,
    )

    # 每小时 — 增量订单 (gateway sync_scheduler.py:620)
    scheduler.add_job(
        lambda: asyncio.create_task(_run_orders_incremental_sync()),
        "interval",
        hours=1,
        id="hourly_orders_incremental_sync",
        replace_existing=True,
        misfire_grace_time=120,
    )

    # 每15分钟 — 增量会员 (gateway sync_scheduler.py:630)
    scheduler.add_job(
        lambda: asyncio.create_task(_run_members_incremental_sync()),
        "interval",
        minutes=15,
        id="quarter_members_incremental_sync",
        replace_existing=True,
        misfire_grace_time=60,
    )

    # 每日 09:00 — 企微 daily SOP (gateway main.py:120)
    scheduler.add_job(
        lambda: asyncio.create_task(_run_daily_sop()),
        "cron",
        hour=9,
        minute=0,
        id="wecom_group_daily_sop",
        replace_existing=True,
        misfire_grace_time=600,
    )

    logger.info(
        "tx_sync_worker_scheduler_configured",
        jobs=[
            "daily_dishes_sync @ 02:00 Asia/Shanghai",
            "daily_master_data_sync @ 03:00 Asia/Shanghai",
            "hourly_orders_incremental_sync (every 1h)",
            "quarter_members_incremental_sync (every 15min)",
            "wecom_group_daily_sop @ 09:00 Asia/Shanghai",
        ],
    )
    return scheduler
