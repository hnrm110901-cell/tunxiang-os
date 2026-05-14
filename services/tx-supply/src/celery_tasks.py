"""tx-supply Celery 任务注册（PR-01B sub-PR B / PRD-01）

复用 root-prod celery-worker/beat 容器（D1 决策 1a）。
sub-PR A (#597) 已加 ENV guard:
    ${ENABLE_TX_SUPPLY_CERT_ALERTER:+-A services.tx_supply.src.celery_tasks}

beat_schedule：cert-expiry-daily-scan — UTC 00:00（北京 08:00）每日扫描。
"""
from __future__ import annotations

import asyncio
import os
from typing import Any, Dict

import structlog

logger = structlog.get_logger(__name__)

# ──────────────────────────────────────────────────────────────────────────────
# Celery App 初始化
# ──────────────────────────────────────────────────────────────────────────────

try:
    from celery import Celery
    from celery.schedules import crontab

    CELERY_BROKER_URL = os.environ.get("CELERY_BROKER_URL", "redis://localhost:6379/0")
    CELERY_RESULT_BACKEND = os.environ.get("CELERY_RESULT_BACKEND", "redis://localhost:6379/1")

    app = Celery(
        "tx_supply",
        broker=CELERY_BROKER_URL,
        backend=CELERY_RESULT_BACKEND,
    )
    app.conf.update(
        task_serializer="json",
        result_serializer="json",
        accept_content=["json"],
        timezone="Asia/Shanghai",
        enable_utc=True,
        task_track_started=True,
        task_acks_late=True,
        worker_prefetch_multiplier=1,
    )

    app.conf.beat_schedule = {
        "cert-expiry-daily-scan": {
            "task": "tx_supply.cert_expiry.daily_scan",
            "schedule": crontab(hour=0, minute=0),  # UTC 00:00 = 北京 08:00
            "options": {"expires": 23 * 3600},       # 23 小时内未执行则过期
        },
    }

    _CELERY_AVAILABLE = True

except ImportError:
    _CELERY_AVAILABLE = False
    app = None  # type: ignore[assignment]
    logger.warning("celery_not_installed", note="Celery 未安装，证件预警定时任务不可用")


# ──────────────────────────────────────────────────────────────────────────────
# Celery 任务定义
# ──────────────────────────────────────────────────────────────────────────────

if _CELERY_AVAILABLE:

    @app.task(
        name="tx_supply.cert_expiry.daily_scan",
        bind=True,
        max_retries=2,
        default_retry_delay=300,   # 5 分钟后重试
        soft_time_limit=600,       # 10 分钟软超时
        time_limit=720,            # 12 分钟硬超时
    )
    def cert_expiry_daily_scan(self) -> Dict[str, Any]:
        """证件临期/过期 daily scan task wrapper。

        遍历 active tenants，对每个 tenant 扫描 supplier_certificates，
        按 D-30/D-15/D-7 + D+0 起每天推送告警，cert_alert_log 幂等去重。
        """
        from .workers.cert_expiry_alerter import run_cert_expiry_scan

        try:
            return asyncio.run(run_cert_expiry_scan())
        except RuntimeError as exc:
            logger.error(
                "cert_expiry_daily_scan_task_failed",
                error=str(exc),
                exc_info=True,
            )
            raise self.retry(exc=exc)
