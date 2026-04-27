"""任务自动生成器（Sprint R1 Track B）

定时器驱动：每日/每小时扫描触发源，产生任务并调用 ``TaskDispatchService.dispatch_task``。

触发源与任务类型映射：
  - 生日当月 T-7 日        → TaskType.BIRTHDAY
  - 结婚/纪念日 T-7        → TaskType.ANNIVERSARY
  - 沉睡客户（距上次消费 >N天）→ TaskType.DORMANT_RECALL
  - 新客 48h 无二次消费    → TaskType.NEW_CUSTOMER
  - 餐后 D+1 回访          → TaskType.DINING_FOLLOWUP
  - 核餐 T-2h（预订确认）   → TaskType.CONFIRM_ARRIVAL
  - 宴会 6 阶段节点        → TaskType.BANQUET_STAGE
  - 宴会餐后              → TaskType.BANQUET_FOLLOWUP
  - 商机跟进逾期           → TaskType.LEAD_FOLLOW_UP

典型调度：
  - ``generate_daily_tasks(tenant_id, now)``：凌晨 02:00 跑一次，扫全部日级触发源
  - ``generate_hourly_tasks(tenant_id, now)``：每小时跑一次，扫核餐 T-2h 等小时级源

本模块负责：
  1. 批量扫描候选（内存或 DB，由数据源回调提供）
  2. 拼装 payload.escalation_chain（由门店配置提供，缺失时降级为无链路）
  3. 调用 TaskDispatchService 幂等派单（重复跑不会重复建任务）

设计要点（CLAUDE.md §15）：
  - 不直接读取跨服务数据表；消费者注入 "candidate provider" 回调，
    由上层服务（tx-member / tx-trade / tx-agent）在事件消费后回填
  - 所有 emit_event 继承自 TaskDispatchService（幂等 + 因果链）
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Awaitable, Callable, Optional
from uuid import UUID

import structlog
from services.task_dispatch_service import TaskDispatchService

from shared.ontology.src.extensions.tasks import Task, TaskType

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)


# ──────────────────────────────────────────────────────────────────────
# 候选数据结构
# ──────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class TaskCandidate:
    """一个待派单候选（由各触发源回填）。"""

    task_type: TaskType
    assignee_employee_id: UUID
    customer_id: Optional[UUID]
    due_at: datetime
    payload: dict = field(default_factory=dict)
    store_id: Optional[UUID] = None
    source_event_id: Optional[UUID] = None


#: 回调签名：(tenant_id, now) -> list[TaskCandidate]
CandidateProvider = Callable[[UUID, datetime], Awaitable[list[TaskCandidate]]]


# ──────────────────────────────────────────────────────────────────────
# 生成器
# ──────────────────────────────────────────────────────────────────────


@dataclass
class TaskAutoGenerator:
    """任务自动生成编排器。

    各业务模块注册自己的 CandidateProvider：

    .. code-block:: python

        gen = TaskAutoGenerator(service=TaskDispatchService(repo=...))
        gen.register_daily_provider("birthday_t_minus_7", birthday_provider)
        gen.register_hourly_provider("confirm_arrival_2h", arrival_provider)
        await gen.generate_daily_tasks(tenant_id, now)
    """

    service: TaskDispatchService
    _daily_providers: dict[str, CandidateProvider] = field(default_factory=dict)
    _hourly_providers: dict[str, CandidateProvider] = field(default_factory=dict)

    # ── 注册 ────────────────────────────────────────────────────────

    def register_daily_provider(self, name: str, provider: CandidateProvider) -> None:
        self._daily_providers[name] = provider

    def register_hourly_provider(self, name: str, provider: CandidateProvider) -> None:
        self._hourly_providers[name] = provider

    # ── 扫描 ────────────────────────────────────────────────────────

    async def generate_daily_tasks(self, tenant_id: UUID, now: datetime) -> list[Task]:
        """日级扫描：凌晨跑一次即可。

        返回实际新增（或因幂等命中返回已存在）的 Task 列表。
        """
        return await self._run_providers(self._daily_providers, tenant_id, now)

    async def generate_hourly_tasks(self, tenant_id: UUID, now: datetime) -> list[Task]:
        """小时级扫描：关注 T-2h 核餐等时效性强的触发源。"""
        return await self._run_providers(self._hourly_providers, tenant_id, now)

    async def _run_providers(
        self,
        providers: dict[str, CandidateProvider],
        tenant_id: UUID,
        now: datetime,
    ) -> list[Task]:
        if not providers:
            return []

        results: list[Task] = []
        # 各 provider 互不依赖，并发扫描
        provider_tasks = [
            self._run_one(name, provider, tenant_id, now)
            for name, provider in providers.items()
        ]
        gathered = await asyncio.gather(*provider_tasks, return_exceptions=True)
        for item in gathered:
            if isinstance(item, Exception):
                logger.warning("task_auto_generator_provider_failed", error=str(item))
                continue
            results.extend(item)
        logger.info(
            "task_auto_generator_batch_done",
            tenant_id=str(tenant_id),
            produced=len(results),
            providers=list(providers.keys()),
        )
        return results

    async def _run_one(
        self,
        name: str,
        provider: CandidateProvider,
        tenant_id: UUID,
        now: datetime,
    ) -> list[Task]:
        """运行单个 provider 并批量派单。"""
        try:
            candidates = await provider(tenant_id, now)
        except (KeyError, ValueError, TypeError, asyncio.TimeoutError) as exc:
            logger.warning(
                "task_auto_generator_provider_error",
                provider=name,
                tenant_id=str(tenant_id),
                error=str(exc),
            )
            return []

        dispatched: list[Task] = []
        for cand in candidates:
            task = await self.service.dispatch_task(
                task_type=cand.task_type,
                assignee_employee_id=cand.assignee_employee_id,
                customer_id=cand.customer_id,
                due_at=cand.due_at,
                payload=cand.payload,
                tenant_id=tenant_id,
                store_id=cand.store_id,
                source_event_id=cand.source_event_id,
            )
            dispatched.append(task)
        logger.info(
            "task_auto_generator_provider_done",
            provider=name,
            tenant_id=str(tenant_id),
            dispatched=len(dispatched),
        )
        return dispatched


# ──────────────────────────────────────────────────────────────────────
# 便捷工厂：根据常见的触发时间戳计算 due_at
# ──────────────────────────────────────────────────────────────────────


def build_birthday_due_at(birthday_mmdd: tuple[int, int], ref_today: date) -> datetime:
    """生日当月 T-7：如果距生日剩 7 天，due_at 定在生日当天 10:00 UTC。

    若 ``ref_today`` 已过今年生日，计算下一年。
    """
    month, day = birthday_mmdd
    year = ref_today.year
    try:
        this_year_birthday = date(year, month, day)
    except ValueError:
        # 2月29日等边界：降到 28
        this_year_birthday = date(year, month, min(day, 28))
    if ref_today > this_year_birthday:
        this_year_birthday = this_year_birthday.replace(year=year + 1)
    return datetime.combine(this_year_birthday, datetime.min.time(), tzinfo=timezone.utc).replace(hour=10)


def build_confirm_arrival_due_at(scheduled_at: datetime) -> datetime:
    """核餐 T-2h：预订到店时间前 2 小时。"""
    return scheduled_at - timedelta(hours=2)


def build_dormant_due_at(now: datetime) -> datetime:
    """沉睡客户召回：当日 20:00 UTC（或次日晚高峰）。"""
    today = now.astimezone(timezone.utc)
    target = today.replace(hour=20, minute=0, second=0, microsecond=0)
    if target <= now:
        target = target + timedelta(days=1)
    return target


__all__ = [
    "TaskAutoGenerator",
    "TaskCandidate",
    "CandidateProvider",
    "build_birthday_due_at",
    "build_confirm_arrival_due_at",
    "build_dormant_due_at",
]
