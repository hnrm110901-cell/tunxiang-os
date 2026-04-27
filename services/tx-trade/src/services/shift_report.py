"""班次KDS生产报表服务

从 kds_tasks 表查询指定班次时段内的数据，汇总：
- 完成单量 / 平均出品时间 / 超时率 / 重做率
- 每档口子报表（dept 维度）
- 每厨师子报表（operator_id 维度）
- 近N天同班次趋势

设计约束：
- kds_tasks 表由 P1-A 创建，此处优雅降级：表不存在时返回空数据，不抛异常
- tenant_id 显式传入，不从 session 读取
- 不硬编码密钥，不静默吞没异常
"""

import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Optional

import structlog
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.shift_config import ShiftConfig

logger = structlog.get_logger()


# ─── 数据结构 ────────────────────────────────────────────────────────────────


@dataclass
class DeptStats:
    dept_id: str
    dept_name: str
    total_tasks: int = 0
    finished_tasks: int = 0
    avg_duration_seconds: float = 0.0
    timeout_count: int = 0
    remake_count: int = 0

    @property
    def timeout_rate(self) -> float:
        return self.timeout_count / self.finished_tasks if self.finished_tasks else 0.0

    @property
    def remake_rate(self) -> float:
        return self.remake_count / self.finished_tasks if self.finished_tasks else 0.0


@dataclass
class OperatorStats:
    operator_id: str
    operator_name: str
    total_tasks: int = 0
    finished_tasks: int = 0
    avg_duration_seconds: float = 0.0
    remake_count: int = 0

    @property
    def remake_rate(self) -> float:
        return self.remake_count / self.finished_tasks if self.finished_tasks else 0.0


@dataclass
class ShiftSummary:
    shift_id: str
    shift_name: str
    date: str  # ISO 日期 YYYY-MM-DD
    total_tasks: int = 0
    finished_tasks: int = 0
    avg_duration_seconds: float = 0.0
    timeout_count: int = 0
    remake_count: int = 0
    dept_stats: list[DeptStats] = field(default_factory=list)
    operator_stats: list[OperatorStats] = field(default_factory=list)

    @property
    def timeout_rate(self) -> float:
        return self.timeout_count / self.finished_tasks if self.finished_tasks else 0.0

    @property
    def remake_rate(self) -> float:
        return self.remake_count / self.finished_tasks if self.finished_tasks else 0.0


@dataclass
class DeptComparison:
    date: str
    depts: list[DeptStats] = field(default_factory=list)


# ─── 辅助函数 ────────────────────────────────────────────────────────────────


def _shift_window(target_date: date, start_time: time, end_time: time) -> tuple[datetime, datetime]:
    """计算班次在指定日期的 UTC 时间窗口（本地时，不转换时区）。

    若 start_time > end_time 表示跨夜班，结束时间归属次日。
    """
    base = datetime(target_date.year, target_date.month, target_date.day)
    window_start = base.replace(hour=start_time.hour, minute=start_time.minute, second=0, microsecond=0)
    if end_time > start_time:
        window_end = base.replace(hour=end_time.hour, minute=end_time.minute, second=0, microsecond=0)
    else:
        # 跨夜班：结束时间在次日
        window_end = (base + timedelta(days=1)).replace(
            hour=end_time.hour, minute=end_time.minute, second=0, microsecond=0
        )
    return window_start, window_end


async def _table_exists(db: AsyncSession, table_name: str) -> bool:
    """检查表是否存在，用于 kds_tasks 优雅降级。"""
    result = await db.execute(
        text("SELECT EXISTS(SELECT 1 FROM information_schema.tables WHERE table_name = :name)"),
        {"name": table_name},
    )
    return bool(result.scalar())


async def _query_kds_tasks(
    db: AsyncSession,
    store_id: uuid.UUID,
    tenant_id: uuid.UUID,
    window_start: datetime,
    window_end: datetime,
) -> list[dict]:
    """查询 kds_tasks 时段数据；表不存在时返回空列表。"""
    try:
        result = await db.execute(
            text(
                """
                SELECT
                    id,
                    dept_id,
                    dept_name,
                    operator_id,
                    operator_name,
                    status,
                    created_at,
                    finished_at,
                    timeout_at,
                    is_remade,
                    duration_seconds
                FROM kds_tasks
                WHERE store_id = :store_id
                  AND tenant_id = :tenant_id
                  AND created_at >= :window_start
                  AND created_at < :window_end
                  AND is_deleted = false
                """
            ),
            {
                "store_id": store_id,
                "tenant_id": tenant_id,
                "window_start": window_start,
                "window_end": window_end,
            },
        )
        rows = result.mappings().all()
        return [dict(r) for r in rows]
    except ProgrammingError as exc:
        # kds_tasks 表尚未创建（P1-A 未完成），优雅降级
        if "kds_tasks" in str(exc) or "does not exist" in str(exc).lower():
            logger.warning("kds_tasks table not found, returning empty data", error=str(exc))
            return []
        raise


# ─── 聚合函数 ────────────────────────────────────────────────────────────────


def _aggregate_tasks(tasks: list[dict]) -> tuple[int, int, float, int, int]:
    """返回 (total, finished, avg_duration_seconds, timeout_count, remake_count)"""
    total = len(tasks)
    finished = [t for t in tasks if t.get("status") == "done"]
    finished_count = len(finished)
    durations = [t["duration_seconds"] for t in finished if t.get("duration_seconds") is not None]
    avg_duration = sum(durations) / len(durations) if durations else 0.0
    timeout_count = sum(1 for t in tasks if t.get("timeout_at") is not None)
    remake_count = sum(1 for t in tasks if t.get("is_remade"))
    return total, finished_count, avg_duration, timeout_count, remake_count


def _group_by_dept(tasks: list[dict]) -> list[DeptStats]:
    groups: dict[str, list[dict]] = {}
    for t in tasks:
        dept_id = str(t.get("dept_id") or "unknown")
        groups.setdefault(dept_id, []).append(t)

    result: list[DeptStats] = []
    for dept_id, dept_tasks in groups.items():
        dept_name = dept_tasks[0].get("dept_name") or dept_id
        total, finished, avg_dur, timeouts, remakes = _aggregate_tasks(dept_tasks)
        result.append(
            DeptStats(
                dept_id=dept_id,
                dept_name=dept_name,
                total_tasks=total,
                finished_tasks=finished,
                avg_duration_seconds=avg_dur,
                timeout_count=timeouts,
                remake_count=remakes,
            )
        )
    return sorted(result, key=lambda d: d.total_tasks, reverse=True)


def _group_by_operator(tasks: list[dict]) -> list[OperatorStats]:
    groups: dict[str, list[dict]] = {}
    for t in tasks:
        op_id = str(t.get("operator_id") or "unknown")
        groups.setdefault(op_id, []).append(t)

    result: list[OperatorStats] = []
    for op_id, op_tasks in groups.items():
        op_name = op_tasks[0].get("operator_name") or op_id
        total, finished, avg_dur, _, remakes = _aggregate_tasks(op_tasks)
        result.append(
            OperatorStats(
                operator_id=op_id,
                operator_name=op_name,
                total_tasks=total,
                finished_tasks=finished,
                avg_duration_seconds=avg_dur,
                remake_count=remakes,
            )
        )
    return sorted(result, key=lambda o: o.total_tasks, reverse=True)


# ─── 主服务 ──────────────────────────────────────────────────────────────────


class ShiftReportService:
    """班次KDS生产报表服务

    所有方法需要显式传入 tenant_id，依赖 DB session 已设置 app.tenant_id（RLS）。
    """

    def __init__(self, db: AsyncSession, tenant_id: str) -> None:
        self.db = db
        self.tenant_id = uuid.UUID(tenant_id)

    # ── 班次配置 CRUD ─────────────────────────────────────────────────────────

    async def list_shift_configs(self, store_id: str) -> list[ShiftConfig]:
        """获取门店所有班次配置（未删除）"""
        from sqlalchemy import select

        sid = uuid.UUID(store_id)
        result = await self.db.execute(
            select(ShiftConfig).where(
                ShiftConfig.store_id == sid,
                ShiftConfig.tenant_id == self.tenant_id,
                ShiftConfig.is_deleted.is_(False),
            )
        )
        return list(result.scalars().all())

    async def create_shift_config(
        self,
        store_id: str,
        shift_name: str,
        start_time: time,
        end_time: time,
        color: str = "#FF6B35",
    ) -> ShiftConfig:
        """创建班次配置"""
        config = ShiftConfig(
            store_id=uuid.UUID(store_id),
            tenant_id=self.tenant_id,
            shift_name=shift_name,
            start_time=start_time,
            end_time=end_time,
            color=color,
        )
        self.db.add(config)
        await self.db.commit()
        await self.db.refresh(config)
        logger.info("shift_config_created", shift_name=shift_name, store_id=store_id)
        return config

    async def _get_shift_config(self, shift_id: str) -> Optional[ShiftConfig]:
        from sqlalchemy import select

        sid = uuid.UUID(shift_id)
        result = await self.db.execute(
            select(ShiftConfig).where(
                ShiftConfig.id == sid,
                ShiftConfig.tenant_id == self.tenant_id,
                ShiftConfig.is_deleted.is_(False),
            )
        )
        return result.scalar_one_or_none()

    # ── 报表 ──────────────────────────────────────────────────────────────────

    async def get_shift_summary(
        self,
        store_id: str,
        target_date: date,
        shift_id: str,
    ) -> ShiftSummary:
        """获取指定日期 + 班次的 KDS 生产汇总报表。

        kds_tasks 表不存在时返回空报表（优雅降级）。
        """
        config = await self._get_shift_config(shift_id)
        if config is None:
            logger.warning("shift_config_not_found", shift_id=shift_id)
            return ShiftSummary(
                shift_id=shift_id,
                shift_name="未知班次",
                date=target_date.isoformat(),
            )

        window_start, window_end = _shift_window(target_date, config.start_time, config.end_time)
        tasks = await _query_kds_tasks(
            self.db,
            uuid.UUID(store_id),
            self.tenant_id,
            window_start,
            window_end,
        )

        total, finished, avg_dur, timeouts, remakes = _aggregate_tasks(tasks)
        return ShiftSummary(
            shift_id=shift_id,
            shift_name=config.shift_name,
            date=target_date.isoformat(),
            total_tasks=total,
            finished_tasks=finished,
            avg_duration_seconds=avg_dur,
            timeout_count=timeouts,
            remake_count=remakes,
            dept_stats=_group_by_dept(tasks),
            operator_stats=_group_by_operator(tasks),
        )

    async def get_dept_comparison(
        self,
        store_id: str,
        target_date: date,
        shift_id: Optional[str] = None,
    ) -> DeptComparison:
        """多档口横向对比。

        可选 shift_id 限定班次；不传则取当日全量。
        """
        if shift_id:
            config = await self._get_shift_config(shift_id)
            if config is None:
                return DeptComparison(date=target_date.isoformat())
            window_start, window_end = _shift_window(target_date, config.start_time, config.end_time)
        else:
            base = datetime(target_date.year, target_date.month, target_date.day)
            window_start = base
            window_end = base + timedelta(days=1)

        tasks = await _query_kds_tasks(
            self.db,
            uuid.UUID(store_id),
            self.tenant_id,
            window_start,
            window_end,
        )
        return DeptComparison(
            date=target_date.isoformat(),
            depts=_group_by_dept(tasks),
        )

    async def get_shift_trend(
        self,
        store_id: str,
        shift_id: str,
        days: int = 7,
    ) -> list[ShiftSummary]:
        """近N天同班次趋势（每天一个 ShiftSummary）。"""
        config = await self._get_shift_config(shift_id)
        if config is None:
            logger.warning("shift_config_not_found_for_trend", shift_id=shift_id)
            return []

        today = date.today()
        summaries: list[ShiftSummary] = []
        for delta in range(days - 1, -1, -1):
            target = today - timedelta(days=delta)
            window_start, window_end = _shift_window(target, config.start_time, config.end_time)
            tasks = await _query_kds_tasks(
                self.db,
                uuid.UUID(store_id),
                self.tenant_id,
                window_start,
                window_end,
            )
            total, finished, avg_dur, timeouts, remakes = _aggregate_tasks(tasks)
            summaries.append(
                ShiftSummary(
                    shift_id=shift_id,
                    shift_name=config.shift_name,
                    date=target.isoformat(),
                    total_tasks=total,
                    finished_tasks=finished,
                    avg_duration_seconds=avg_dur,
                    timeout_count=timeouts,
                    remake_count=remakes,
                )
            )
        return summaries

    async def get_operator_performance(
        self,
        store_id: str,
        target_date: date,
        shift_id: Optional[str] = None,
    ) -> list[OperatorStats]:
        """厨师个人绩效（operator_id 维度）。

        可选 shift_id 限定班次；不传则取当日全量。
        """
        if shift_id:
            config = await self._get_shift_config(shift_id)
            if config is None:
                return []
            window_start, window_end = _shift_window(target_date, config.start_time, config.end_time)
        else:
            base = datetime(target_date.year, target_date.month, target_date.day)
            window_start = base
            window_end = base + timedelta(days=1)

        tasks = await _query_kds_tasks(
            self.db,
            uuid.UUID(store_id),
            self.tenant_id,
            window_start,
            window_end,
        )
        return _group_by_operator(tasks)
