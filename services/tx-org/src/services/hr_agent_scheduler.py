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
        self.scheduler.start()
        log.info("hr_agent_scheduler_started", jobs=4)

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
