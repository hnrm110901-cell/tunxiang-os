"""班次KDS生产报表 — 单元测试

覆盖场景：
1. 午班(11:00-14:00)报表仅包含该时段的 kds_tasks 数据
2. 厨师个人报表：完成单量、平均出品时间、重做率
3. 档口对比报表：多档口效率横向对比
4. 跨班次对比：今天午班 vs 昨天午班（trend 接口）
5. tenant_id 隔离：其他租户数据不可见
6. kds_tasks 表不存在时优雅降级（返回空报表，不抛异常）
7. 跨夜班时间窗口计算正确
8. 空任务列表时统计数值为0/0.0
"""
import os
import sys

# 将 tx-trade/src 加入 sys.path，使 import services.xxx 可以工作
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import uuid
from datetime import date, datetime, time, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from services.shift_report import (
    DeptComparison,
    DeptStats,
    OperatorStats,
    ShiftReportService,
    ShiftSummary,
    _aggregate_tasks,
    _group_by_dept,
    _group_by_operator,
    _shift_window,
)

# ─── 测试工具 ────────────────────────────────────────────────────────────────


def _uid() -> str:
    return str(uuid.uuid4())


TENANT_A = _uid()
TENANT_B = _uid()
STORE_ID = _uid()
SHIFT_ID = _uid()
DEPT_HOT = _uid()
DEPT_COLD = _uid()
OP_CHEF1 = _uid()
OP_CHEF2 = _uid()


def _make_task(
    *,
    dept_id: str = DEPT_HOT,
    dept_name: str = "热菜间",
    operator_id: str = OP_CHEF1,
    operator_name: str = "小王",
    status: str = "done",
    duration_seconds: float = 300.0,
    timeout_at=None,
    is_remade: bool = False,
    created_at: datetime = datetime(2026, 3, 30, 12, 0, 0),
) -> dict:
    return {
        "id": _uid(),
        "dept_id": dept_id,
        "dept_name": dept_name,
        "operator_id": operator_id,
        "operator_name": operator_name,
        "status": status,
        "created_at": created_at,
        "finished_at": created_at + timedelta(seconds=duration_seconds) if status == "done" else None,
        "timeout_at": timeout_at,
        "is_remade": is_remade,
        "duration_seconds": duration_seconds if status == "done" else None,
    }


class FakeMapping:
    """模拟 SQLAlchemy RowMapping 的简单包装"""
    def __init__(self, data: dict):
        self._data = data

    def __getitem__(self, key):
        return self._data[key]

    def __iter__(self):
        return iter(self._data)

    def items(self):
        return self._data.items()


class FakeMappingsResult:
    def __init__(self, rows: list[dict]):
        self._rows = rows

    def mappings(self):
        return self

    def all(self):
        return [FakeMapping(r) for r in self._rows]

    def scalars(self):
        return self

    def scalar_one_or_none(self):
        return self._rows[0] if self._rows else None

    def scalar(self):
        return self._rows[0] if self._rows else None


def _make_mock_db(tasks: list[dict] | None = None, shift_config=None):
    """构建 mock DB session。

    - select(ShiftConfig) 返回 shift_config
    - text(kds_tasks) 返回 tasks
    """
    db = AsyncMock()

    async def _execute_side_effect(stmt, params=None, **kwargs):
        stmt_str = str(stmt)
        if "kds_tasks" in stmt_str:
            return FakeMappingsResult(tasks or [])
        # ShiftConfig select
        result = MagicMock()
        result.scalars.return_value.all.return_value = [shift_config] if shift_config else []
        result.scalar_one_or_none.return_value = shift_config
        return result

    db.execute = AsyncMock(side_effect=_execute_side_effect)
    db.add = MagicMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    return db


def _make_shift_config(
    shift_id: str = SHIFT_ID,
    shift_name: str = "午班",
    start_hour: int = 11,
    start_minute: int = 0,
    end_hour: int = 14,
    end_minute: int = 0,
) -> MagicMock:
    cfg = MagicMock()
    cfg.id = uuid.UUID(shift_id)
    cfg.shift_name = shift_name
    cfg.start_time = time(start_hour, start_minute)
    cfg.end_time = time(end_hour, end_minute)
    cfg.color = "#FF6B35"
    cfg.is_active = True
    cfg.store_id = uuid.UUID(STORE_ID)
    cfg.tenant_id = uuid.UUID(TENANT_A)
    cfg.created_at = datetime(2026, 3, 1, 8, 0, 0)
    return cfg


# ─── 1. 午班报表仅包含该时段数据 ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_shift_summary_only_includes_window_tasks():
    """午班(11:00-14:00)报表中的统计数值来自正确的任务集合。"""
    # 准备：午班内的2个任务，窗口外1个任务（在测试里通过mock控制查询结果）
    inside_tasks = [
        _make_task(created_at=datetime(2026, 3, 30, 11, 30, 0), duration_seconds=240.0),
        _make_task(created_at=datetime(2026, 3, 30, 13, 0, 0), duration_seconds=360.0),
    ]
    cfg = _make_shift_config()
    db = _make_mock_db(tasks=inside_tasks, shift_config=cfg)
    svc = ShiftReportService(db, TENANT_A)

    summary = await svc.get_shift_summary(STORE_ID, date(2026, 3, 30), SHIFT_ID)

    assert summary.total_tasks == 2
    assert summary.finished_tasks == 2
    assert abs(summary.avg_duration_seconds - 300.0) < 0.01
    assert summary.date == "2026-03-30"
    assert summary.shift_name == "午班"


# ─── 2. 厨师个人报表：完成单量、平均出品时间、重做率 ─────────────────────────


@pytest.mark.asyncio
async def test_operator_stats_calculation():
    """厨师报表正确汇总完成量/出品时间/重做率"""
    tasks = [
        _make_task(operator_id=OP_CHEF1, operator_name="小王", duration_seconds=300.0, is_remade=False),
        _make_task(operator_id=OP_CHEF1, operator_name="小王", duration_seconds=600.0, is_remade=True),
        _make_task(operator_id=OP_CHEF2, operator_name="小李", duration_seconds=200.0, is_remade=False),
    ]
    ops = _group_by_operator(tasks)

    # 找出两位厨师
    chef1 = next(o for o in ops if o.operator_id == OP_CHEF1)
    chef2 = next(o for o in ops if o.operator_id == OP_CHEF2)

    assert chef1.finished_tasks == 2
    assert abs(chef1.avg_duration_seconds - 450.0) < 0.01  # (300+600)/2
    assert chef1.remake_count == 1
    assert abs(chef1.remake_rate - 0.5) < 0.001  # 1/2

    assert chef2.finished_tasks == 1
    assert abs(chef2.avg_duration_seconds - 200.0) < 0.01
    assert chef2.remake_count == 0
    assert chef2.remake_rate == 0.0


@pytest.mark.asyncio
async def test_get_operator_performance_via_service():
    """get_operator_performance 服务方法通过班次窗口查询并返回厨师列表"""
    tasks = [
        _make_task(operator_id=OP_CHEF1, operator_name="小王", duration_seconds=300.0),
        _make_task(operator_id=OP_CHEF1, operator_name="小王", duration_seconds=400.0, is_remade=True),
    ]
    cfg = _make_shift_config()
    db = _make_mock_db(tasks=tasks, shift_config=cfg)
    svc = ShiftReportService(db, TENANT_A)

    result = await svc.get_operator_performance(STORE_ID, date(2026, 3, 30), SHIFT_ID)

    assert len(result) == 1
    assert result[0].operator_name == "小王"
    assert result[0].finished_tasks == 2
    assert result[0].remake_count == 1


# ─── 3. 档口对比报表：多档口效率横向对比 ────────────────────────────────────


@pytest.mark.asyncio
async def test_dept_comparison_multiple_depts():
    """档口对比报表正确分组并排序"""
    tasks = [
        _make_task(dept_id=DEPT_HOT, dept_name="热菜间", duration_seconds=300.0),
        _make_task(dept_id=DEPT_HOT, dept_name="热菜间", duration_seconds=600.0, timeout_at=datetime(2026, 3, 30, 12, 15)),
        _make_task(dept_id=DEPT_COLD, dept_name="凉菜间", duration_seconds=150.0),
    ]
    depts = _group_by_dept(tasks)

    assert len(depts) == 2
    # 热菜间单量更多，排第一
    assert depts[0].dept_name == "热菜间"
    assert depts[0].total_tasks == 2
    assert depts[0].timeout_count == 1
    assert abs(depts[0].avg_duration_seconds - 450.0) < 0.01

    assert depts[1].dept_name == "凉菜间"
    assert depts[1].total_tasks == 1


@pytest.mark.asyncio
async def test_get_dept_comparison_service():
    """get_dept_comparison 服务方法返回 DeptComparison"""
    tasks = [
        _make_task(dept_id=DEPT_HOT, dept_name="热菜间"),
        _make_task(dept_id=DEPT_COLD, dept_name="凉菜间"),
    ]
    cfg = _make_shift_config()
    db = _make_mock_db(tasks=tasks, shift_config=cfg)
    svc = ShiftReportService(db, TENANT_A)

    comparison = await svc.get_dept_comparison(STORE_ID, date(2026, 3, 30), SHIFT_ID)

    assert isinstance(comparison, DeptComparison)
    assert comparison.date == "2026-03-30"
    assert len(comparison.depts) == 2


# ─── 4. 跨班次对比：今天午班 vs 昨天午班（trend） ────────────────────────────


@pytest.mark.asyncio
async def test_shift_trend_returns_correct_day_count():
    """trend接口返回正确天数的数据点"""
    cfg = _make_shift_config()
    db = _make_mock_db(tasks=[], shift_config=cfg)
    svc = ShiftReportService(db, TENANT_A)

    trend = await svc.get_shift_trend(STORE_ID, SHIFT_ID, days=7)

    assert len(trend) == 7
    # 结果按时间升序（最早日期在前）
    dates = [s.date for s in trend]
    assert dates == sorted(dates)


@pytest.mark.asyncio
async def test_shift_trend_each_entry_has_correct_shift_name():
    """trend 每个数据点的 shift_name 与配置一致"""
    cfg = _make_shift_config(shift_name="午班")
    db = _make_mock_db(tasks=[], shift_config=cfg)
    svc = ShiftReportService(db, TENANT_A)

    trend = await svc.get_shift_trend(STORE_ID, SHIFT_ID, days=3)

    for entry in trend:
        assert entry.shift_name == "午班"
        assert entry.shift_id == SHIFT_ID


# ─── 5. tenant_id 隔离 ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_tenant_isolation_different_tenants_get_different_data():
    """不同租户查询同一门店，mock DB应使用不同 tenant_id 参数"""
    tasks_a = [_make_task(operator_id=OP_CHEF1, operator_name="租户A厨师")]
    tasks_b = [_make_task(operator_id=OP_CHEF2, operator_name="租户B厨师")]

    cfg = _make_shift_config()
    db_a = _make_mock_db(tasks=tasks_a, shift_config=cfg)
    db_b = _make_mock_db(tasks=tasks_b, shift_config=cfg)

    svc_a = ShiftReportService(db_a, TENANT_A)
    svc_b = ShiftReportService(db_b, TENANT_B)

    result_a = await svc_a.get_operator_performance(STORE_ID, date(2026, 3, 30))
    result_b = await svc_b.get_operator_performance(STORE_ID, date(2026, 3, 30))

    assert result_a[0].operator_name == "租户A厨师"
    assert result_b[0].operator_name == "租户B厨师"


@pytest.mark.asyncio
async def test_service_stores_correct_tenant_uuid():
    """ShiftReportService 正确存储 tenant_id 为 UUID"""
    db = _make_mock_db()
    svc = ShiftReportService(db, TENANT_A)
    assert svc.tenant_id == uuid.UUID(TENANT_A)


# ─── 6. kds_tasks 表不存在时优雅降级 ────────────────────────────────────────


@pytest.mark.asyncio
async def test_graceful_degradation_when_kds_tasks_missing():
    """kds_tasks 表不存在时 get_shift_summary 返回空报表，不抛异常"""
    from sqlalchemy.exc import ProgrammingError

    cfg = _make_shift_config()

    db = AsyncMock()

    async def _execute_side_effect(stmt, params=None, **kwargs):
        stmt_str = str(stmt)
        if "kds_tasks" in stmt_str:
            raise ProgrammingError("relation kds_tasks does not exist", None, None)
        # ShiftConfig 查询正常
        result = MagicMock()
        result.scalar_one_or_none.return_value = cfg
        return result

    db.execute = AsyncMock(side_effect=_execute_side_effect)

    svc = ShiftReportService(db, TENANT_A)
    # 不应抛异常
    summary = await svc.get_shift_summary(STORE_ID, date(2026, 3, 30), SHIFT_ID)

    assert isinstance(summary, ShiftSummary)
    assert summary.total_tasks == 0
    assert summary.finished_tasks == 0
    assert summary.dept_stats == []
    assert summary.operator_stats == []


# ─── 7. 跨夜班时间窗口计算 ──────────────────────────────────────────────────


def test_shift_window_normal():
    """正常班次（结束时间大于开始时间）"""
    start, end = _shift_window(date(2026, 3, 30), time(11, 0), time(14, 0))
    assert start == datetime(2026, 3, 30, 11, 0, 0)
    assert end == datetime(2026, 3, 30, 14, 0, 0)


def test_shift_window_overnight():
    """跨夜班（开始 22:00，结束 02:00 次日）"""
    start, end = _shift_window(date(2026, 3, 30), time(22, 0), time(2, 0))
    assert start == datetime(2026, 3, 30, 22, 0, 0)
    assert end == datetime(2026, 3, 31, 2, 0, 0)


# ─── 8. 空任务列表时统计数值为0 ──────────────────────────────────────────────


def test_aggregate_empty_tasks():
    """空任务列表聚合后所有数值为0"""
    total, finished, avg_dur, timeouts, remakes = _aggregate_tasks([])
    assert total == 0
    assert finished == 0
    assert avg_dur == 0.0
    assert timeouts == 0
    assert remakes == 0


def test_dept_stats_rates_with_zero_finished():
    """finished_tasks 为 0 时 timeout_rate/remake_rate 不触发除零错误"""
    dept = DeptStats(
        dept_id="d1",
        dept_name="测试档口",
        total_tasks=3,
        finished_tasks=0,
        timeout_count=1,
        remake_count=1,
    )
    assert dept.timeout_rate == 0.0
    assert dept.remake_rate == 0.0


def test_operator_stats_remake_rate_zero_finished():
    """operator finished_tasks 为 0 时 remake_rate 不触发除零错误"""
    op = OperatorStats(
        operator_id="op1",
        operator_name="测试厨师",
        total_tasks=1,
        finished_tasks=0,
        remake_count=0,
    )
    assert op.remake_rate == 0.0


# ─── 9. shift_config_not_found 时返回占位 ShiftSummary ─────────────────────


@pytest.mark.asyncio
async def test_shift_summary_returns_placeholder_when_config_not_found():
    """班次配置不存在时返回带默认值的 ShiftSummary，不抛异常"""
    db = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = None
    db.execute = AsyncMock(return_value=result)

    svc = ShiftReportService(db, TENANT_A)
    summary = await svc.get_shift_summary(STORE_ID, date(2026, 3, 30), SHIFT_ID)

    assert isinstance(summary, ShiftSummary)
    assert summary.total_tasks == 0


# ─── 10. 超时率和重做率计算 ──────────────────────────────────────────────────


def test_aggregate_tasks_with_timeouts_and_remakes():
    """超时和重做计数正确"""
    tasks = [
        _make_task(duration_seconds=300.0, timeout_at=datetime(2026, 3, 30, 12, 5), is_remade=False),
        _make_task(duration_seconds=400.0, timeout_at=None, is_remade=True),
        _make_task(duration_seconds=200.0, timeout_at=None, is_remade=False),
        _make_task(status="cooking", duration_seconds=None),  # 未完成
    ]
    total, finished, avg_dur, timeouts, remakes = _aggregate_tasks(tasks)

    assert total == 4
    assert finished == 3
    # avg_dur from the 3 finished tasks: (300+400+200)/3 ≈ 300
    assert abs(avg_dur - 300.0) < 0.01
    assert timeouts == 1
    assert remakes == 1
