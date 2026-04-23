"""销售目标服务（Sprint R1 Track C）

职责：
  - set_target       设定销售目标（含事件发射 SalesTargetEventType.SET）
  - decompose_target 年 → 月（自然月） → 日（工作日 1.2 / 周末 0.9 加权）分解；金额加和保持一致
  - record_progress  写入 sales_progress 快照（幂等：同一 source_event_id 不重复），发射 PROGRESS_UPDATED
  - aggregate_from_orders  从 mv_store_pnl 物化视图聚合实际值（Phase 3 合规）
  - get_achievement  读取最新达成率

金额字段单位：分（整数）
达成率：Decimal（字符串化用于 JSON 序列化）

对应契约：shared.ontology.src.extensions.sales_targets (SalesTarget / SalesProgress)
对应事件：shared.events.src.event_types.SalesTargetEventType
"""

from __future__ import annotations

import asyncio
import calendar
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any
from uuid import UUID, uuid4

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from shared.events.src.emitter import emit_event
from shared.events.src.event_types import SalesTargetEventType
from shared.ontology.src.extensions.sales_targets import (
    MetricType,
    PeriodType,
)

from ..repositories.sales_target_repo import SalesTargetRepository

log = structlog.get_logger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# 常量
# ─────────────────────────────────────────────────────────────────────────────

# 金额类指标（金额分解时按日权重；非金额类 count 指标同样按权重分解，但都用整数）
_METRIC_VALUES = {m.value for m in MetricType}

# 工作日（周一=0 ~ 周五=4）权重
_WORKDAY_WEIGHT = Decimal("1.2")
# 周末（周六=5 / 周日=6）权重
_WEEKEND_WEIGHT = Decimal("0.9")

_MAX_RATE = Decimal("9.9999")


def _weight_of(d: date) -> Decimal:
    """返回某天权重（工作日 1.2 / 周末 0.9）。"""
    return _WEEKEND_WEIGHT if d.weekday() >= 5 else _WORKDAY_WEIGHT


def _last_day_of_month(year: int, month: int) -> int:
    return calendar.monthrange(year, month)[1]


def _clamp_rate(raw: Decimal) -> Decimal:
    """把达成率限制到 [0, 9.9999] 并保留 4 位小数。"""
    if raw < 0:
        raw = Decimal("0")
    if raw > _MAX_RATE:
        raw = _MAX_RATE
    return raw.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def _distribute_int_by_weights(
    total: int, weights: list[Decimal]
) -> list[int]:
    """把整数 total 按权重列表分配到 len(weights) 个整数分量，严格保持加和一致。

    算法：
      1. 先按权重比例得到浮点份额；
      2. 全部向下取整；
      3. 把余数按 fractional part 从大到小"最大余数法"补齐。
    """
    if total < 0:
        raise ValueError("total 必须 >= 0")
    if not weights:
        return []

    total_weight = sum(weights)
    if total_weight <= 0:
        # 权重全 0 时均匀分配
        n = len(weights)
        base = total // n
        remainder = total - base * n
        out = [base] * n
        for i in range(remainder):
            out[i] += 1
        return out

    # 精确分配
    raw = [(Decimal(total) * w) / total_weight for w in weights]
    floors = [int(x) for x in raw]
    allocated = sum(floors)
    remainder = total - allocated

    if remainder > 0:
        # 余数按小数部分从大到小分配
        fracs = sorted(
            range(len(raw)),
            key=lambda i: (raw[i] - Decimal(floors[i])),
            reverse=True,
        )
        for i in range(remainder):
            floors[fracs[i % len(fracs)]] += 1
    elif remainder < 0:
        # 理论不应发生，但作防御：对整数类权重可能多分
        extras = sorted(
            range(len(raw)),
            key=lambda i: (Decimal(floors[i]) - raw[i]),
            reverse=True,
        )
        for i in range(-remainder):
            floors[extras[i % len(extras)]] -= 1
    return floors


# ─────────────────────────────────────────────────────────────────────────────
# Service
# ─────────────────────────────────────────────────────────────────────────────


class SalesTargetService:
    """销售目标业务层。"""

    def __init__(
        self,
        repo: SalesTargetRepository | None = None,
    ) -> None:
        self._repo = repo or SalesTargetRepository()

    # ── 1. 设定目标 ────────────────────────────────────────────────────

    async def set_target(
        self,
        db: AsyncSession,
        *,
        tenant_id: UUID,
        employee_id: UUID,
        period_type: PeriodType | str,
        period_start: date,
        period_end: date,
        metric_type: MetricType | str,
        target_value: int,
        store_id: UUID | None = None,
        parent_target_id: UUID | None = None,
        notes: str | None = None,
        created_by: UUID | None = None,
        source_service: str = "tx-org",
    ) -> dict:
        """写入一条销售目标 + 发射 SalesTargetEventType.SET 事件。

        约束：
          - period_end >= period_start
          - target_value >= 0
          - metric_type 必须在 MetricType 枚举内
        """
        if period_end < period_start:
            raise ValueError("period_end 必须 >= period_start")
        if target_value < 0:
            raise ValueError("target_value 必须 >= 0")

        pt_value = (
            period_type.value
            if isinstance(period_type, PeriodType)
            else str(period_type)
        )
        mt_value = (
            metric_type.value
            if isinstance(metric_type, MetricType)
            else str(metric_type)
        )
        if mt_value not in _METRIC_VALUES:
            raise ValueError(f"未知 metric_type: {mt_value}")

        target = await self._repo.insert_target(
            db,
            tenant_id=tenant_id,
            employee_id=employee_id,
            period_type=pt_value,
            period_start=period_start,
            period_end=period_end,
            metric_type=mt_value,
            target_value=int(target_value),
            store_id=store_id,
            parent_target_id=parent_target_id,
            notes=notes,
            created_by=created_by,
        )

        # 旁路发射事件（不阻塞主业务）
        asyncio.create_task(
            emit_event(
                event_type=SalesTargetEventType.SET,
                tenant_id=tenant_id,
                stream_id=str(target["target_id"]),
                payload={
                    "employee_id": str(employee_id),
                    "period_type": pt_value,
                    "period_start": period_start.isoformat(),
                    "period_end": period_end.isoformat(),
                    "metric_type": mt_value,
                    "target_value": int(target_value),
                    "parent_target_id": (
                        str(parent_target_id) if parent_target_id else None
                    ),
                },
                store_id=store_id,
                source_service=source_service,
            )
        )

        return target

    # ── 2. 目标分解：年 → 12 月 → 每日（工作日/周末加权） ────────────────

    async def decompose_target(
        self,
        db: AsyncSession,
        *,
        tenant_id: UUID,
        year_target_id: UUID,
    ) -> list[dict]:
        """把年目标拆成 12 个月 + 每月再拆到天，全部落库并挂链。

        拆解规则：
          - 年 → 月：按每月权重（月内日权重之和）分配，保证 12 个月相加等于年目标。
          - 月 → 日：工作日权重 1.2、周末 0.9，保证当月所有日相加等于月目标。
          - 金额类和计数类指标都走同一个整数分配路径（整数不丢失）。

        返回所有新创建的子目标（月 + 日）列表，按 period_start 升序。
        """
        year_target = await self._repo.get_by_id(
            db, tenant_id=tenant_id, target_id=year_target_id
        )
        if year_target is None:
            raise ValueError(f"年目标不存在：{year_target_id}")

        period_type = year_target["period_type"]
        # 兼容枚举对象 / 字符串
        if hasattr(period_type, "value"):
            period_type = period_type.value
        if period_type != PeriodType.YEAR.value:
            raise ValueError(
                f"decompose_target 仅支持 period_type=year，当前：{period_type}"
            )

        period_start: date = year_target["period_start"]
        period_end: date = year_target["period_end"]
        total_value: int = int(year_target["target_value"])
        mt_value = year_target["metric_type"]
        if hasattr(mt_value, "value"):
            mt_value = mt_value.value
        employee_id = year_target["employee_id"]
        if isinstance(employee_id, str):
            employee_id = UUID(employee_id)
        store_id = year_target.get("store_id")
        if isinstance(store_id, str):
            store_id = UUID(store_id)

        # ── 一、构造 12 个月的区间（以年目标起点所在月起连续 12 个月） ──
        months: list[tuple[date, date]] = []
        y = period_start.year
        m = period_start.month
        for _ in range(12):
            first = date(y, m, 1)
            last = date(y, m, _last_day_of_month(y, m))
            # 裁剪进年目标范围
            if last > period_end:
                last = period_end
            if first < period_start:
                first = period_start
            months.append((first, last))
            if m == 12:
                y += 1
                m = 1
            else:
                m += 1

        # ── 二、按月权重把年目标切到月（月权重=该月每日权重之和） ──
        month_day_weights: list[list[Decimal]] = []
        month_total_weights: list[Decimal] = []
        for first, last in months:
            d_list: list[Decimal] = []
            d_cursor = first
            while d_cursor <= last:
                d_list.append(_weight_of(d_cursor))
                d_cursor += timedelta(days=1)
            month_day_weights.append(d_list)
            month_total_weights.append(
                sum(d_list) if d_list else Decimal("0")
            )

        month_values = _distribute_int_by_weights(
            total_value, month_total_weights
        )

        # ── 三、写 12 个月子目标，并对每个月继续分解到天 ──
        children: list[dict] = []
        for idx, ((first, last), m_value, d_weights) in enumerate(
            zip(months, month_values, month_day_weights)
        ):
            if not d_weights:
                continue

            month_target = await self._repo.insert_target(
                db,
                tenant_id=tenant_id,
                employee_id=employee_id,
                period_type=PeriodType.MONTH.value,
                period_start=first,
                period_end=last,
                metric_type=mt_value,
                target_value=int(m_value),
                store_id=store_id,
                parent_target_id=year_target_id,
                notes=f"auto: decomposed from year_target {year_target_id}",
            )
            children.append(month_target)

            # 事件：月子目标
            asyncio.create_task(
                emit_event(
                    event_type=SalesTargetEventType.SET,
                    tenant_id=tenant_id,
                    stream_id=str(month_target["target_id"]),
                    payload={
                        "employee_id": str(employee_id),
                        "period_type": PeriodType.MONTH.value,
                        "period_start": first.isoformat(),
                        "period_end": last.isoformat(),
                        "metric_type": mt_value,
                        "target_value": int(m_value),
                        "parent_target_id": str(year_target_id),
                        "decomposed_idx": idx,
                    },
                    store_id=store_id,
                    source_service="tx-org",
                )
            )

            # ── 月内按日权重分解 ──
            day_values = _distribute_int_by_weights(
                int(m_value), d_weights
            )
            d_cursor = first
            month_target_id_raw = month_target["target_id"]
            if isinstance(month_target_id_raw, str):
                month_parent_uuid = UUID(month_target_id_raw)
            else:
                month_parent_uuid = month_target_id_raw

            for day_value in day_values:
                day_target = await self._repo.insert_target(
                    db,
                    tenant_id=tenant_id,
                    employee_id=employee_id,
                    period_type=PeriodType.DAY.value,
                    period_start=d_cursor,
                    period_end=d_cursor,
                    metric_type=mt_value,
                    target_value=int(day_value),
                    store_id=store_id,
                    parent_target_id=month_parent_uuid,
                    notes=(
                        f"auto: decomposed from month_target "
                        f"{month_target_id_raw}"
                    ),
                )
                children.append(day_target)
                d_cursor += timedelta(days=1)

        return children

    # ── 3. 进度快照（幂等） ─────────────────────────────────────────────

    async def record_progress(
        self,
        db: AsyncSession,
        *,
        tenant_id: UUID,
        target_id: UUID,
        actual_value: int,
        source_event_id: UUID | None = None,
        source_service: str = "tx-org",
    ) -> dict:
        """写入进度快照 + 发射 PROGRESS_UPDATED。

        幂等性：
          - 若 source_event_id 已存在，直接返回已有快照，不重复写入、不发事件。
          - source_event_id=None 时不做幂等检查（用于定时轮询写入场景）。

        达成率 = actual / target（Decimal，4 位小数，最大 9.9999）。
        """
        if actual_value < 0:
            raise ValueError("actual_value 必须 >= 0")

        target = await self._repo.get_by_id(
            db, tenant_id=tenant_id, target_id=target_id
        )
        if target is None:
            raise ValueError(f"目标不存在：{target_id}")

        # 幂等检查
        if source_event_id is not None:
            already = await self._repo.check_source_event_exists(
                db,
                tenant_id=tenant_id,
                target_id=target_id,
                source_event_id=source_event_id,
            )
            if already:
                existing = await self._repo.get_latest_progress(
                    db, tenant_id=tenant_id, target_id=target_id
                )
                if existing is not None:
                    return existing
                # 理论不会到这（existed 但无最新），兜底重写

        target_value = int(target["target_value"] or 0)
        if target_value <= 0:
            rate = Decimal("0.0000")
        else:
            rate = _clamp_rate(Decimal(actual_value) / Decimal(target_value))

        progress = await self._repo.insert_progress(
            db,
            tenant_id=tenant_id,
            target_id=target_id,
            actual_value=int(actual_value),
            achievement_rate=rate,
            source_event_id=source_event_id,
        )

        # 事件：progress.updated（payload 内 achievement_rate 字符串化防精度丢失）
        store_id = target.get("store_id")
        if isinstance(store_id, str):
            try:
                store_id = UUID(store_id)
            except ValueError:
                store_id = None

        asyncio.create_task(
            emit_event(
                event_type=SalesTargetEventType.PROGRESS_UPDATED,
                tenant_id=tenant_id,
                stream_id=str(target_id),
                payload={
                    "target_id": str(target_id),
                    "actual_value": int(actual_value),
                    "target_value": int(target_value),
                    "achievement_rate": str(rate),
                    "metric_type": (
                        target["metric_type"].value
                        if hasattr(target["metric_type"], "value")
                        else target["metric_type"]
                    ),
                    "source_event_id": (
                        str(source_event_id) if source_event_id else None
                    ),
                },
                store_id=store_id,
                source_service=source_service,
                causation_id=source_event_id,
            )
        )
        return progress

    # ── 4. 从物化视图聚合实际值（定时任务/手动刷新） ───────────────────

    async def aggregate_from_orders(
        self,
        db: AsyncSession,
        *,
        tenant_id: UUID,
        period_type: PeriodType | str,
        period_start: date,
        period_end: date,
    ) -> list[dict]:
        """按 (period_type, period) 扫描所有目标，从 mv_store_pnl 聚合并写入进度。

        返回新写入的 progress 记录列表。
        源 event_id 用自动生成的 UUID（定时轮询场景不关联业务事件）。
        """
        pt_value = (
            period_type.value
            if isinstance(period_type, PeriodType)
            else str(period_type)
        )

        # 列出当前生效目标（today=period_start 起点）
        targets = await self._repo.list_active_targets(
            db,
            tenant_id=tenant_id,
            period_type=pt_value,
            today=period_start,
        )
        out: list[dict] = []
        for t in targets:
            mt = t["metric_type"]
            if hasattr(mt, "value"):
                mt = mt.value
            actual = await self._repo.aggregate_metric_from_views(
                db,
                tenant_id=tenant_id,
                store_id=t.get("store_id"),
                metric_type=mt,
                period_start=period_start,
                period_end=period_end,
            )
            progress = await self.record_progress(
                db,
                tenant_id=tenant_id,
                target_id=(
                    t["target_id"]
                    if isinstance(t["target_id"], UUID)
                    else UUID(str(t["target_id"]))
                ),
                actual_value=int(actual),
                source_event_id=uuid4(),
                source_service="tx-org.aggregator",
            )
            out.append(progress)
        return out

    # ── 5. 读取达成率 & 排行榜 ──────────────────────────────────────────

    async def get_achievement(
        self,
        db: AsyncSession,
        *,
        tenant_id: UUID,
        target_id: UUID,
    ) -> dict:
        target = await self._repo.get_by_id(
            db, tenant_id=tenant_id, target_id=target_id
        )
        if target is None:
            raise ValueError(f"目标不存在：{target_id}")
        latest = await self._repo.get_latest_progress(
            db, tenant_id=tenant_id, target_id=target_id
        )
        if latest is None:
            return {
                "target_id": str(target_id),
                "target_value": int(target["target_value"]),
                "actual_value": 0,
                "achievement_rate": "0.0000",
                "snapshot_at": None,
            }
        rate = latest["achievement_rate"]
        if isinstance(rate, Decimal):
            rate_str = str(rate.quantize(Decimal("0.0001")))
        else:
            rate_str = str(rate)
        return {
            "target_id": str(target_id),
            "target_value": int(target["target_value"]),
            "actual_value": int(latest["actual_value"]),
            "achievement_rate": rate_str,
            "snapshot_at": (
                latest["snapshot_at"].isoformat()
                if hasattr(latest["snapshot_at"], "isoformat")
                else latest["snapshot_at"]
            ),
        }

    async def leaderboard(
        self,
        db: AsyncSession,
        *,
        tenant_id: UUID,
        period_type: PeriodType | str,
        metric_type: MetricType | str,
        today: date | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        pt_value = (
            period_type.value
            if isinstance(period_type, PeriodType)
            else str(period_type)
        )
        mt_value = (
            metric_type.value
            if isinstance(metric_type, MetricType)
            else str(metric_type)
        )
        rows = await self._repo.leaderboard_by_period(
            db,
            tenant_id=tenant_id,
            period_type=pt_value,
            metric_type=mt_value,
            today=today or date.today(),
            limit=limit,
        )
        out: list[dict[str, Any]] = []
        for r in rows:
            rate = r.get("achievement_rate") or 0
            if isinstance(rate, Decimal):
                rate = str(rate.quantize(Decimal("0.0001")))
            out.append(
                {
                    "target_id": str(r["target_id"]),
                    "employee_id": str(r["employee_id"]),
                    "store_id": str(r["store_id"]) if r.get("store_id") else None,
                    "metric_type": (
                        r["metric_type"].value
                        if hasattr(r["metric_type"], "value")
                        else r["metric_type"]
                    ),
                    "period_type": (
                        r["period_type"].value
                        if hasattr(r["period_type"], "value")
                        else r["period_type"]
                    ),
                    "period_start": (
                        r["period_start"].isoformat()
                        if hasattr(r["period_start"], "isoformat")
                        else r["period_start"]
                    ),
                    "period_end": (
                        r["period_end"].isoformat()
                        if hasattr(r["period_end"], "isoformat")
                        else r["period_end"]
                    ),
                    "target_value": int(r["target_value"] or 0),
                    "actual_value": int(r.get("actual_value") or 0),
                    "achievement_rate": str(rate),
                }
            )
        return out
