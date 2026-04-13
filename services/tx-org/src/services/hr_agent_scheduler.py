"""HR Agent 定时调度器

管理6个HR Agent的定时触发：
- 合规预警Agent: 每日凌晨2:00全量扫描
- 离职风险Agent: 每周一凌晨3:00全员扫描
- 排班优化Agent: 每周日22:00生成下周方案
- 贡献度计算: 每日凌晨4:00重算前一天
- 成长教练Agent: 新菜品上线时触发（事件驱动，非定时）
- 缺勤补位Agent: 实时事件驱动（非定时）
"""

from __future__ import annotations

import asyncio
from datetime import date, timedelta
from typing import Any, Optional

import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

log = structlog.get_logger(__name__)


class HRAgentScheduler:
    """HR Agent 定时调度中心

    启动后注册4个定时任务。所有任务通过内部 HTTP 调用
    对应 Agent 的 scan/execute 端点，而非直接操作数据库。
    """

    def __init__(self, base_url: str = "http://localhost:8012"):
        self.base_url = base_url
        self.scheduler = AsyncIOScheduler()

    def start(self) -> None:
        """注册定时任务并启动调度器"""
        # 合规预警: 每日 02:00
        self.scheduler.add_job(
            self._run_compliance_scan,
            CronTrigger(hour=2, minute=0),
            id="compliance_daily_scan",
            name="Daily Compliance Scan",
            replace_existing=True,
        )
        # 离职风险: 每周一 03:00
        self.scheduler.add_job(
            self._run_turnover_scan,
            CronTrigger(day_of_week="mon", hour=3, minute=0),
            id="turnover_weekly_scan",
            name="Weekly Turnover Risk Scan",
            replace_existing=True,
        )
        # 排班优化: 每周日 22:00
        self.scheduler.add_job(
            self._run_schedule_optimization,
            CronTrigger(day_of_week="sun", hour=22, minute=0),
            id="schedule_weekly_optimization",
            name="Weekly Schedule Optimization",
            replace_existing=True,
        )
        # 贡献度重算: 每日 04:00
        self.scheduler.add_job(
            self._run_contribution_recalc,
            CronTrigger(hour=4, minute=0),
            id="contribution_daily_recalc",
            name="Daily Contribution Recalculation",
            replace_existing=True,
        )
        # 加盟费逾期自动标记: 每日 02:05（在合规扫描之后，避免资源争用）
        self.scheduler.add_job(
            self._run_mark_overdue_fees,
            CronTrigger(hour=2, minute=5),
            id="franchise_daily_mark_overdue",
            name="Daily Franchise Fee Mark Overdue",
            replace_existing=True,
        )
        # Agent ROI 指标采集: 每日 05:00（贡献度重算 04:00 完成后）
        self.scheduler.add_job(
            self._run_roi_collect,
            CronTrigger(hour=5, minute=0),
            id="agent_roi_daily_collect",
            name="Daily Agent ROI Metrics Collect",
            replace_existing=True,
        )
        self.scheduler.start()
        log.info("hr_agent_scheduler_started", jobs=6)

    def stop(self) -> None:
        """关停调度器"""
        self.scheduler.shutdown(wait=False)
        log.info("hr_agent_scheduler_stopped")

    # ── 定时任务实现 ─────────────────────────────────────────────────

    async def _run_compliance_scan(self) -> None:
        """触发合规预警Agent全量扫描

        调用 POST /api/v1/compliance-alert/scan
        Agent Level 1: 生成预警列表，由店长确认处理
        """
        import httpx

        try:
            async with httpx.AsyncClient(timeout=60) as client:
                resp = await client.post(
                    f"{self.base_url}/api/v1/compliance-alert/scan",
                    json={"scan_type": "full"},
                )
                data = resp.json()
                alert_count = len(data.get("data", {}).get("alerts", []))
                log.info(
                    "compliance_scan_completed",
                    alerts_found=alert_count,
                    status=resp.status_code,
                )
        except httpx.HTTPError as exc:
            log.error("compliance_scan_failed", error=str(exc))

    async def _run_turnover_scan(self) -> None:
        """触发离职风险Agent全员扫描

        Agent Level 1: 生成风险列表，由HR确认是否启动面谈
        """
        import httpx

        try:
            async with httpx.AsyncClient(timeout=120) as client:
                resp = await client.post(
                    f"{self.base_url}/api/v1/hr-dashboard/turnover-risk-scan",
                    json={"scan_type": "full"},
                )
                log.info(
                    "turnover_scan_completed",
                    status=resp.status_code,
                )
        except httpx.HTTPError as exc:
            log.error("turnover_scan_failed", error=str(exc))

    async def _run_schedule_optimization(self) -> None:
        """触发排班优化Agent生成下周方案

        Agent Level 2: 自动生成草稿排班，30分钟回滚窗口
        店长需在30分钟内确认或回滚
        """
        import httpx

        try:
            next_monday = date.today() + timedelta(days=(7 - date.today().weekday()) % 7 or 7)
            async with httpx.AsyncClient(timeout=120) as client:
                resp = await client.post(
                    f"{self.base_url}/api/v1/revenue-schedule/apply-plan",
                    json={
                        "week_start": next_monday.isoformat(),
                        "mode": "draft",
                        "agent_level": 2,
                        "rollback_window_min": 30,
                    },
                )
                log.info(
                    "schedule_optimization_completed",
                    week_start=next_monday.isoformat(),
                    status=resp.status_code,
                )
        except httpx.HTTPError as exc:
            log.error("schedule_optimization_failed", error=str(exc))

    async def _run_contribution_recalc(self) -> None:
        """触发贡献度重算

        Agent Level 3: 完全自主执行，仅记录日志
        每日凌晨4点重算前一天所有门店的贡献度分数
        """
        import httpx

        yesterday = date.today() - timedelta(days=1)
        try:
            async with httpx.AsyncClient(timeout=300) as client:
                # 获取所有门店列表后逐个重算
                resp = await client.post(
                    f"{self.base_url}/api/v1/contribution/recalculate",
                    json={
                        "store_id": "__all__",
                        "period_start": yesterday.isoformat(),
                        "period_end": yesterday.isoformat(),
                    },
                )
                log.info(
                    "contribution_recalc_completed",
                    date=yesterday.isoformat(),
                    status=resp.status_code,
                )
        except httpx.HTTPError as exc:
            log.error("contribution_recalc_failed", error=str(exc))

    async def _get_active_tenant_ids(self) -> list[str]:
        """查询所有活跃租户 ID（BYPASSRLS 会话，跨租户读取）。

        降级链：DB查询 → DEFAULT_TENANT_ID 环境变量 → 返回空列表。
        """
        import os as _os
        from sqlalchemy import text as _text
        from shared.ontology.src.database import get_db_no_rls

        try:
            async for db in get_db_no_rls():
                result = await db.execute(
                    _text("""
                        SELECT DISTINCT tenant_id::text
                        FROM stores
                        WHERE is_deleted = FALSE
                        ORDER BY 1
                    """)
                )
                tenant_ids = [row[0] for row in result.fetchall()]
                if tenant_ids:
                    return tenant_ids
                log.warning("hr_scheduler_stores_table_empty")
        except Exception as exc:  # noqa: BLE001
            log.error(
                "hr_scheduler_tenant_query_failed",
                error=str(exc),
                exc_info=True,
            )

        default_tenant = _os.environ.get("DEFAULT_TENANT_ID")
        if default_tenant:
            log.warning(
                "hr_scheduler_fallback_to_default_tenant",
                tenant_id=default_tenant,
            )
            return [default_tenant]

        log.warning("hr_scheduler_no_tenant_configured")
        return []

    async def _run_mark_overdue_fees(self) -> None:
        """将逾期未付的加盟费批量标记为 overdue（多租户）

        调用 POST /api/v1/franchise/fees/mark-overdue（每租户一次，携带 X-Tenant-ID）
        幂等操作：只将 due_date < 今日 且 status='pending' 的记录标记为 'overdue'。
        每日 02:05 执行，运行在合规扫描（02:00）之后避免资源争用。
        """
        import httpx

        tenant_ids = await self._get_active_tenant_ids()
        if not tenant_ids:
            log.warning("franchise_mark_overdue_no_tenants")
            return

        total_marked = 0
        errors: list[str] = []

        async with httpx.AsyncClient(timeout=60) as client:
            for tid in tenant_ids:
                try:
                    resp = await client.post(
                        f"{self.base_url}/api/v1/franchise/fees/mark-overdue",
                        headers={"X-Tenant-ID": tid},
                    )
                    if resp.status_code == 200:
                        data = resp.json()
                        marked = data.get("data", {}).get("marked_count", 0)
                        total_marked += marked
                        log.info(
                            "franchise_mark_overdue_tenant_done",
                            tenant_id=tid,
                            marked_count=marked,
                        )
                    else:
                        log.warning(
                            "franchise_mark_overdue_unexpected_status",
                            tenant_id=tid,
                            status=resp.status_code,
                            body=resp.text[:200],
                        )
                        errors.append(tid)
                except httpx.HTTPError as exc:
                    log.error(
                        "franchise_mark_overdue_tenant_failed",
                        tenant_id=tid,
                        error=str(exc),
                    )
                    errors.append(tid)

        log.info(
            "franchise_mark_overdue_completed",
            total_marked=total_marked,
            tenant_count=len(tenant_ids),
            error_count=len(errors),
            as_of=date.today().isoformat(),
        )

    async def _run_roi_collect(self) -> None:
        """触发 Agent ROI 指标每日采集（多租户）

        调用 POST /api/v1/agent/roi/collect（每租户一次，携带 X-Tenant-ID）
        采集来源：orders.discount_amount_fen + agent_auto_executions 执行计数
        幂等：同日已存在记录则跳过。每日 05:00 执行（贡献度重算 04:00 之后）。
        """
        import httpx

        tenant_ids = await self._get_active_tenant_ids()
        if not tenant_ids:
            log.warning("roi_collect_no_tenants")
            return

        total_inserted = 0
        skipped = 0
        errors: list[str] = []

        async with httpx.AsyncClient(timeout=120) as client:
            for tid in tenant_ids:
                try:
                    resp = await client.post(
                        f"{self.base_url}/api/v1/agent/roi/collect",
                        headers={"X-Tenant-ID": tid},
                    )
                    if resp.status_code == 200:
                        data = resp.json().get("data", {})
                        if data.get("skipped"):
                            skipped += 1
                        else:
                            total_inserted += data.get("inserted_count", 0)
                        log.info(
                            "roi_collect_tenant_done",
                            tenant_id=tid,
                            inserted=data.get("inserted_count", 0),
                            skipped=data.get("skipped", False),
                        )
                    else:
                        log.warning(
                            "roi_collect_unexpected_status",
                            tenant_id=tid,
                            status=resp.status_code,
                            body=resp.text[:200],
                        )
                        errors.append(tid)
                except httpx.HTTPError as exc:
                    log.error(
                        "roi_collect_tenant_failed",
                        tenant_id=tid,
                        error=str(exc),
                    )
                    errors.append(tid)

        log.info(
            "roi_collect_completed",
            total_inserted=total_inserted,
            tenants_skipped=skipped,
            tenant_count=len(tenant_ids),
            error_count=len(errors),
            as_of=date.today().isoformat(),
        )
