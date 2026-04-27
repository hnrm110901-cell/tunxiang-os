"""销售经理教练 — 定时 Job 服务（Sprint R2 Track B）

两个作业：

1. ``run_daily_coaching_job(tenant_id, now)``
   每日 06:00 触发：对该租户内所有在岗销售员工，依次执行：
     - decompose_target（若当年度目标未分解过，补跑一次）
     - dispatch_daily_tasks（按 10 类任务派发当日任务清单）
     - audit_coverage（四象限扫描 + 沉睡率告警）
     - diagnose_gap（对该员工名下每条 active 月/周/日目标做偏差诊断）

2. ``run_weekly_profile_audit(tenant_id, now)``
   每周一 07:00 触发：扫描全店客户画像完整度，< 50% 的派 adhoc 补录任务。

关键设计：
  * 纯 Service 层，不持有 HTTP session；通过注入 ``SalesCoachAgent`` 实现可测试
  * 幂等：内置 in-memory ``_run_ledger``，同租户 + 同日 + 同作业只跑一次
  * 事件：作业完成后发射 ``SalesCoachEventType.DAILY_TASKS_DISPATCHED``
  * 租户隔离：所有行为基于入参 ``tenant_id``；跨租户调用应循环调用本 API

对齐：
  - CLAUDE.md §15 事件旁路：asyncio.create_task
  - CLAUDE.md §14 禁止 broad except；本文件仅捕获 httpx.HTTPError / ValueError / RuntimeError
  - docs/reservation-r2-contracts.md §6：sales_coach 纯策略层，硬约束豁免
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any, Optional
from uuid import UUID

import httpx
import structlog

from shared.events.src.emitter import emit_event
from shared.events.src.event_types import SalesCoachEventType

log: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)


SOURCE_SERVICE = "tx-org.sales_coach_job"


# ──────────────────────────────────────────────────────────────────────
# 抽象接口：允许测试时注入伪 Agent
# ──────────────────────────────────────────────────────────────────────


class _AgentProtocol:
    """SalesCoachAgent 的最小接口（供 Job 调用）。

    测试时可用 AsyncMock 替代，避免依赖真实 tx-agent 包导入。
    """

    async def run(self, action: str, params: dict[str, Any]) -> Any:  # pragma: no cover
        raise NotImplementedError


# ──────────────────────────────────────────────────────────────────────
# Job 服务
# ──────────────────────────────────────────────────────────────────────


@dataclass
class SalesCoachJobService:
    """销售教练定时作业调度器。

    必须注入 ``agent_factory``（根据 tenant_id 生成 SalesCoachAgent 实例），
    便于跨租户复用一份 HTTP 客户端。
    """

    agent_factory: Any = None
    employees_loader: Any = None
    active_targets_loader: Any = None
    customers_loader: Any = None
    _run_ledger: dict[tuple[str, str, str], datetime] = field(default_factory=dict)

    # ── 幂等 ─────────────────────────────────────────────────────────

    def _ledger_key(
        self, tenant_id: str, job_name: str, run_date: date
    ) -> tuple[str, str, str]:
        return (str(tenant_id), job_name, run_date.isoformat())

    def _already_ran(
        self, tenant_id: str, job_name: str, run_date: date
    ) -> bool:
        return self._ledger_key(tenant_id, job_name, run_date) in self._run_ledger

    def _mark_ran(
        self, tenant_id: str, job_name: str, run_date: date, at: datetime
    ) -> None:
        self._run_ledger[self._ledger_key(tenant_id, job_name, run_date)] = at

    # ── 每日教练作业 ─────────────────────────────────────────────────

    async def run_daily_coaching_job(
        self,
        tenant_id: UUID,
        now: Optional[datetime] = None,
    ) -> dict[str, Any]:
        """对该租户所有销售员工跑一遍 decompose → dispatch → audit → diagnose。

        Args:
          tenant_id: 租户
          now:       触发时间，为空则使用 UTC now

        Returns:
          执行报告，结构：
            {
              tenant_id, plan_date, employees_count,
              dispatched_total, gap_alerts, audit_summary,
              idempotent: bool (True 表示命中幂等，未实际执行)
            }
        """
        ref_now = now or datetime.now(timezone.utc)
        run_date = ref_now.date()

        if self._already_ran(str(tenant_id), "daily_coaching", run_date):
            log.info(
                "sales_coach_job_idempotent_skip",
                tenant_id=str(tenant_id),
                run_date=run_date.isoformat(),
            )
            return {
                "tenant_id": str(tenant_id),
                "plan_date": run_date.isoformat(),
                "idempotent": True,
                "employees_count": 0,
                "dispatched_total": 0,
                "gap_alerts": 0,
                "audit_summary": {},
            }

        if self.agent_factory is None:
            raise RuntimeError("agent_factory 未注入，无法创建 SalesCoachAgent")
        if self.employees_loader is None:
            raise RuntimeError("employees_loader 未注入")

        agent = self._build_agent(tenant_id)
        employees = await self.employees_loader(tenant_id)
        dispatched_total = 0
        gap_alerts = 0
        audit_summary: dict[str, Any] = {}

        for emp in employees:
            emp_id = emp.get("employee_id") or emp.get("id")
            if not emp_id:
                continue

            # 1. 若存在年目标且未分解 → 分解（不拦截后续动作）
            year_target_id = emp.get("year_target_id")
            if year_target_id:
                try:
                    await agent.run(
                        "decompose_target",
                        {"year_target_id": str(year_target_id)},
                    )
                except (httpx.HTTPError, RuntimeError, ValueError) as exc:
                    log.warning(
                        "daily_decompose_failed",
                        employee_id=str(emp_id),
                        error=str(exc),
                    )

            # 2. 每日派单
            dispatch_params: dict[str, Any] = {
                "employee_id": str(emp_id),
                "plan_date": run_date.isoformat(),
                "store_id": emp.get("store_id"),
            }
            customers_map = emp.get("customers_by_type")
            if customers_map:
                dispatch_params["customers_by_type"] = customers_map
            try:
                disp_result = await agent.run(
                    "dispatch_daily_tasks", dispatch_params
                )
                if getattr(disp_result, "success", False):
                    dispatched_total += int(
                        (disp_result.data or {}).get("dispatched_count", 0)
                    )
            except (httpx.HTTPError, RuntimeError, ValueError) as exc:
                log.warning(
                    "daily_dispatch_failed",
                    employee_id=str(emp_id),
                    error=str(exc),
                )

            # 3. diagnose_gap（针对该员工在跑的 active 目标）
            if self.active_targets_loader is not None:
                try:
                    targets = await self.active_targets_loader(tenant_id, emp_id)
                except (httpx.HTTPError, RuntimeError, ValueError) as exc:
                    log.warning(
                        "daily_targets_loader_failed",
                        employee_id=str(emp_id),
                        error=str(exc),
                    )
                    targets = []
                for t in targets:
                    t_id = t.get("target_id") or t.get("id")
                    if not t_id:
                        continue
                    try:
                        gap = await agent.run(
                            "diagnose_gap", {"target_id": str(t_id)}
                        )
                        if getattr(gap, "success", False):
                            if (gap.data or {}).get("has_gap"):
                                gap_alerts += 1
                    except (httpx.HTTPError, RuntimeError, ValueError) as exc:
                        log.warning(
                            "daily_diagnose_failed",
                            target_id=str(t_id),
                            error=str(exc),
                        )

        # 4. audit_coverage（租户级，每日只跑一次汇总）
        try:
            audit = await agent.run("audit_coverage", {})
            if getattr(audit, "success", False):
                audit_summary = audit.data or {}
        except (httpx.HTTPError, RuntimeError, ValueError) as exc:
            log.warning(
                "daily_audit_failed",
                tenant_id=str(tenant_id),
                error=str(exc),
            )

        # 幂等记录 & 事件
        self._mark_ran(str(tenant_id), "daily_coaching", run_date, ref_now)

        asyncio.create_task(
            emit_event(
                event_type=SalesCoachEventType.DAILY_TASKS_DISPATCHED,
                tenant_id=tenant_id,
                stream_id=str(tenant_id),
                payload={
                    "plan_date": run_date.isoformat(),
                    "dispatched_count": dispatched_total,
                    "employees_count": len(employees),
                    "gap_alerts": gap_alerts,
                },
                source_service=SOURCE_SERVICE,
            )
        )

        log.info(
            "daily_coaching_job_done",
            tenant_id=str(tenant_id),
            plan_date=run_date.isoformat(),
            employees=len(employees),
            dispatched_total=dispatched_total,
            gap_alerts=gap_alerts,
        )

        return {
            "tenant_id": str(tenant_id),
            "plan_date": run_date.isoformat(),
            "employees_count": len(employees),
            "dispatched_total": dispatched_total,
            "gap_alerts": gap_alerts,
            "audit_summary": audit_summary,
            "idempotent": False,
        }

    # ── 每周画像补录作业 ─────────────────────────────────────────────

    async def run_weekly_profile_audit(
        self,
        tenant_id: UUID,
        now: Optional[datetime] = None,
    ) -> dict[str, Any]:
        """扫描客户画像完整度，低于 50% 派 adhoc 补录任务。"""
        ref_now = now or datetime.now(timezone.utc)
        run_date = ref_now.date()

        if self._already_ran(str(tenant_id), "weekly_profile", run_date):
            return {
                "tenant_id": str(tenant_id),
                "run_date": run_date.isoformat(),
                "idempotent": True,
                "dispatched_task_count": 0,
                "below_threshold_count": 0,
            }

        if self.agent_factory is None:
            raise RuntimeError("agent_factory 未注入")
        if self.customers_loader is None:
            raise RuntimeError("customers_loader 未注入")
        if self.employees_loader is None:
            raise RuntimeError("employees_loader 未注入")

        agent = self._build_agent(tenant_id)
        employees = await self.employees_loader(tenant_id)
        total_dispatched = 0
        total_below = 0

        for emp in employees:
            emp_id = emp.get("employee_id") or emp.get("id")
            if not emp_id:
                continue
            customers = await self.customers_loader(tenant_id, emp_id)
            if not customers:
                continue
            try:
                result = await agent.run(
                    "score_profile_completeness",
                    {
                        "employee_id": str(emp_id),
                        "customers": customers,
                        "dispatch_tasks_on_low": True,
                    },
                )
            except (httpx.HTTPError, RuntimeError, ValueError) as exc:
                log.warning(
                    "weekly_profile_failed",
                    employee_id=str(emp_id),
                    error=str(exc),
                )
                continue

            if getattr(result, "success", False):
                data = result.data or {}
                total_dispatched += int(data.get("dispatched_task_count", 0))
                total_below += len(data.get("below_threshold_customer_ids", []))

        self._mark_ran(str(tenant_id), "weekly_profile", run_date, ref_now)

        log.info(
            "weekly_profile_audit_done",
            tenant_id=str(tenant_id),
            run_date=run_date.isoformat(),
            dispatched=total_dispatched,
            below_threshold=total_below,
        )

        return {
            "tenant_id": str(tenant_id),
            "run_date": run_date.isoformat(),
            "dispatched_task_count": total_dispatched,
            "below_threshold_count": total_below,
            "idempotent": False,
        }

    # ── 工具 ─────────────────────────────────────────────────────────

    def _build_agent(self, tenant_id: UUID) -> _AgentProtocol:
        agent = self.agent_factory(tenant_id=str(tenant_id))
        if agent is None:
            raise RuntimeError("agent_factory 返回 None")
        return agent


__all__ = [
    "SalesCoachJobService",
    "SOURCE_SERVICE",
]
