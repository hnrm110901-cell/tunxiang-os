"""tx-sync-worker · 企业微信 daily SOP job (W2 P1 issue #758).

**业务函数 0 diff** copy from services/gateway/src/main.py:73-115 _run_daily_sop.
Phase 1 双轨并行, gateway 仍跑; Phase 2 follow-up 关 gateway 切单轨.

跨服务 import (per plan §7.6, P0-3 hotfix #815):
  - services.gateway.src.wecom_group_service (拆 shared/wecom/ 留 FU #806 DOD)
  - services.gateway.src.models.wecom_group   (同上)
  - shared.ontology.src.database.async_session_factory  ← P0-3 修正
    (原写法 services.gateway.src.database.get_async_session 不存在)
  Dockerfile COPY services/gateway/ → /app/services/gateway/, PYTHONPATH=/app 解析.

**dry_run 模式 (Q3 决议 A)**:
  RUN_MODE=dry_run (env unset 默认 true) → cron fire 时只 log + metric, 不调 WecomGroupService
  RUN_MODE=live → 真路径 (Phase 2 翻; 必须**先**关 gateway scheduler 再翻, 防 dup fire)
"""

from __future__ import annotations

import os
import time
from typing import Any  # noqa: F401 — placeholder for future db type hints

import structlog

from ..metrics import (
    sync_duration_seconds,
    sync_executions_total,
    sync_last_run_timestamp_seconds,
)

logger = structlog.get_logger(__name__)


def _is_dry_run() -> bool:
    """Phase 1 dry_run 模式开关 — 与 pinzhi_sync 一致语义."""
    return os.environ.get("RUN_MODE", "dry_run").strip().lower() != "live"


async def _run_daily_sop() -> None:
    """每天 9:00 扫描所有租户的 active 群，执行 daily SOP.

    注意：此函数从数据库获取所有活跃租户列表后逐个执行。
    实际部署时需注入数据库会话，此处为集成占位符 (与 gateway main.py:73-115 一致语义).
    """
    log = logger.bind(task="wecom_group_daily_sop")
    fire_start = time.monotonic()
    log.info("wecom_group_daily_sop_job_start", dry_run=_is_dry_run())

    if _is_dry_run():
        duration_s = time.monotonic() - fire_start
        sync_executions_total.labels(job="wecom_group_daily_sop", status="dry_run").inc()
        sync_last_run_timestamp_seconds.labels(job="wecom_group_daily_sop").set(time.time())
        sync_duration_seconds.labels(job="wecom_group_daily_sop").observe(duration_s)
        log.info(
            "dry_run_skip",
            job="wecom_group_daily_sop",
            action="would_call_wecom_group_service",
            duration_s=duration_s,
        )
        return

    try:
        from sqlalchemy import distinct, select, text

        # 真 helper 路径 (P0-3 hotfix #815): gateway/src/database.py 不存在,
        # gateway 实际用 shared/ontology/src/database.py:async_session_factory.
        # WecomGroupConfig / WecomGroupService 跨服务 import 留 Phase 2 拆 shared/wecom/ (FU #806 DOD).
        from shared.ontology.src.database import async_session_factory

        from services.gateway.src.models.wecom_group import WecomGroupConfig  # type: ignore[import]
        from services.gateway.src.wecom_group_service import WecomGroupService  # type: ignore[import]

        service = WecomGroupService()

        # Step 1 — 跨租户聚合 SELECT (RLS BYPASS 视角): 需 BYPASSRLS role 或
        # RLS policy USING true. 此处 session 不 set_config('app.tenant_id'),
        # 由 DB role 配置允许跨租户读 wecom_group_config (与 gateway scheduler 同语义).
        async with async_session_factory() as db:
            stmt = select(distinct(WecomGroupConfig.tenant_id)).where(WecomGroupConfig.status == "active")
            result = await db.execute(stmt)
            tenant_ids = list(result.scalars().all())

        # Step 2 — 每租户独立 session + set_config 强 RLS 隔离 (per CLAUDE.md §6/§13).
        for tenant_id in tenant_ids:
            try:
                async with async_session_factory() as tenant_db:
                    await tenant_db.execute(
                        text("SELECT set_config('app.tenant_id', :tid, true)"),
                        {"tid": str(tenant_id)},
                    )
                    sop_result = await service.scan_and_execute_daily_sop(tenant_id, tenant_db)
                    log.info(
                        "wecom_group_daily_sop_tenant_done",
                        tenant_id=str(tenant_id),
                        result=sop_result,
                    )
            except (ValueError, RuntimeError, OSError) as exc:
                # 单租户失败不阻塞其他租户 (与 pinzhi_sync.py 同 narrow 异常清单).
                log.error(
                    "wecom_group_daily_sop_tenant_error",
                    tenant_id=str(tenant_id),
                    error=str(exc),
                    exc_info=True,
                )
        sync_executions_total.labels(job="wecom_group_daily_sop", status="success").inc()
    except ImportError:
        log.warning("wecom_group_daily_sop_db_not_configured")
        sync_executions_total.labels(job="wecom_group_daily_sop", status="error").inc()
    except (ValueError, RuntimeError, OSError) as exc:
        log.error("wecom_group_daily_sop_job_error", error=str(exc), exc_info=True)
        sync_executions_total.labels(job="wecom_group_daily_sop", status="error").inc()
    finally:
        duration_s = time.monotonic() - fire_start
        sync_last_run_timestamp_seconds.labels(job="wecom_group_daily_sop").set(time.time())
        sync_duration_seconds.labels(job="wecom_group_daily_sop").observe(duration_s)
        log.info("wecom_group_daily_sop_job_finished", duration_s=duration_s)
