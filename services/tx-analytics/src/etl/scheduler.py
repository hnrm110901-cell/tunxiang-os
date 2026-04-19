"""ETL 调度器 — APScheduler 驱动的定时同步

调度策略:
- 每日 02:00 执行全量日同步（拉取前一天数据）
- 每 4 小时执行增量同步（拉取最近 4 小时窗口对应日期的数据）
- 支持手动触发（通过 API 端点）

为三个租户（尝在一起、最黔线、尚宫厨）循环执行同步。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from .pipeline import ETLPipeline
from .tenant_config import (
    PinzhiTenantConfig,
    get_tenant_config_by_id,
    init_tenant_registry,
    load_tenant_configs,
)

logger = structlog.get_logger()


class SyncLogEntry:
    """同步日志条目"""

    def __init__(self, job_id: str, tenant_id: str, tenant_name: str, sync_type: str) -> None:
        self.job_id = job_id
        self.tenant_id = tenant_id
        self.tenant_name = tenant_name
        self.sync_type = sync_type
        self.status: str = "running"
        self.started_at: datetime = datetime.now(timezone.utc)
        self.finished_at: datetime | None = None
        self.result: dict[str, Any] | None = None
        self.error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "tenant_id": self.tenant_id,
            "tenant_name": self.tenant_name,
            "sync_type": self.sync_type,
            "status": self.status,
            "started_at": self.started_at.isoformat(),
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "result": self.result,
            "error": self.error,
        }


class ETLScheduler:
    """ETL 调度器 — 管理定时同步任务"""

    MAX_LOG_ENTRIES = 200

    def __init__(self) -> None:
        self.scheduler = AsyncIOScheduler(timezone="Asia/Shanghai")
        self.tenant_configs: list[PinzhiTenantConfig] = []
        self.sync_logs: list[SyncLogEntry] = []
        self._last_sync_times: dict[str, datetime] = {}
        self._is_running = False

    def init(self) -> None:
        init_tenant_registry()
        self.tenant_configs = load_tenant_configs()
        logger.info(
            "etl_scheduler_init",
            tenant_count=len(self.tenant_configs),
            tenants=[cfg.tenant_name for cfg in self.tenant_configs],
        )
        self.scheduler.add_job(
            self._daily_full_sync,
            trigger=CronTrigger(hour=2, minute=0),
            id="daily_full_sync",
            name="每日全量同步",
            replace_existing=True,
        )
        self.scheduler.add_job(
            self._incremental_sync,
            trigger=IntervalTrigger(hours=4),
            id="incremental_sync_4h",
            name="4小时增量同步",
            replace_existing=True,
        )

    def start(self) -> None:
        if not self._is_running:
            self.scheduler.start()
            self._is_running = True
            logger.info("etl_scheduler_started")

    def shutdown(self) -> None:
        if self._is_running:
            self.scheduler.shutdown(wait=False)
            self._is_running = False
            logger.info("etl_scheduler_stopped")

    @property
    def is_running(self) -> bool:
        return self._is_running

    async def _daily_full_sync(self) -> None:
        yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")
        logger.info("daily_full_sync_triggered", date=yesterday)
        for cfg in self.tenant_configs:
            await self._run_tenant_sync(cfg, "daily_full", yesterday, yesterday)

    async def _incremental_sync(self) -> None:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        logger.info("incremental_sync_triggered", date=today)
        for cfg in self.tenant_configs:
            await self._run_tenant_sync(cfg, "incremental", today, today)

    async def trigger_full_sync(self) -> list[dict[str, Any]]:
        yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")
        results: list[dict[str, Any]] = []
        for cfg in self.tenant_configs:
            result = await self._run_tenant_sync(cfg, "manual_full", yesterday, yesterday)
            results.append(result)
        return results

    async def trigger_tenant_sync(
        self, tenant_id: str, start_date: str | None = None, end_date: str | None = None
    ) -> dict[str, Any]:
        cfg = get_tenant_config_by_id(tenant_id)
        if cfg is None:
            return {"ok": False, "error": f"租户 {tenant_id} 未找到"}
        if start_date is None:
            start_date = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")
        if end_date is None:
            end_date = start_date
        return await self._run_tenant_sync(cfg, "manual_single", start_date, end_date)

    async def _run_tenant_sync(
        self, cfg: PinzhiTenantConfig, sync_type: str, start_date: str, end_date: str
    ) -> dict[str, Any]:
        job_id = str(uuid.uuid4())[:8]
        log_entry = SyncLogEntry(
            job_id=job_id, tenant_id=str(cfg.tenant_id), tenant_name=cfg.tenant_name, sync_type=sync_type
        )
        self.sync_logs.append(log_entry)
        self._trim_logs()
        logger.info(
            "tenant_sync_started",
            job_id=job_id,
            tenant=cfg.tenant_name,
            sync_type=sync_type,
            start_date=start_date,
            end_date=end_date,
        )
        pipeline = ETLPipeline(cfg)
        try:
            result = await pipeline.run_full_sync(start_date, end_date)
            log_entry.status = "completed"
            log_entry.result = result
            self._last_sync_times[str(cfg.tenant_id)] = datetime.now(timezone.utc)
            logger.info("tenant_sync_completed", job_id=job_id, tenant=cfg.tenant_name, result=result)
            return {
                "ok": True,
                "job_id": job_id,
                "tenant_id": str(cfg.tenant_id),
                "tenant_name": cfg.tenant_name,
                "result": result,
            }
        except (ConnectionError, TimeoutError, RuntimeError, ValueError) as exc:
            log_entry.status = "failed"
            log_entry.error = str(exc)
            logger.error("tenant_sync_failed", job_id=job_id, tenant=cfg.tenant_name, error=str(exc))
            return {
                "ok": False,
                "job_id": job_id,
                "tenant_id": str(cfg.tenant_id),
                "tenant_name": cfg.tenant_name,
                "error": str(exc),
            }
        finally:
            log_entry.finished_at = datetime.now(timezone.utc)
            await pipeline.close()

    def get_status(self) -> dict[str, Any]:
        tenant_statuses = []
        for cfg in self.tenant_configs:
            tid = str(cfg.tenant_id)
            last_sync = self._last_sync_times.get(tid)
            tenant_statuses.append(
                {
                    "tenant_id": tid,
                    "tenant_name": cfg.tenant_name,
                    "last_sync_at": last_sync.isoformat() if last_sync else None,
                    "store_count": len(cfg.store_ognids),
                }
            )
        scheduled_jobs = []
        if self._is_running:
            for job in self.scheduler.get_jobs():
                scheduled_jobs.append(
                    {
                        "job_id": job.id,
                        "name": str(job.name),
                        "next_run_time": job.next_run_time.isoformat() if job.next_run_time else None,
                    }
                )
        return {
            "scheduler_running": self._is_running,
            "tenant_count": len(self.tenant_configs),
            "tenants": tenant_statuses,
            "scheduled_jobs": scheduled_jobs,
        }

    def get_logs(self, limit: int = 50, tenant_id: str | None = None) -> list[dict[str, Any]]:
        logs = self.sync_logs
        if tenant_id:
            logs = [log for log in logs if log.tenant_id == tenant_id]
        return [log.to_dict() for log in reversed(logs)][:limit]

    def _trim_logs(self) -> None:
        if len(self.sync_logs) > self.MAX_LOG_ENTRIES:
            self.sync_logs = self.sync_logs[-self.MAX_LOG_ENTRIES :]


_scheduler: ETLScheduler | None = None


def get_etl_scheduler() -> ETLScheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = ETLScheduler()
        _scheduler.init()
    return _scheduler
