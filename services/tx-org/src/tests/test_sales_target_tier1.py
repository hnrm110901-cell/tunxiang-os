"""Sprint R1 Track C — 销售目标 Tier 1 测试

对应：
  services/tx-org/src/services/sales_target_service.py
  services/tx-org/src/repositories/sales_target_repo.py
  services/tx-org/src/api/sales_target_routes.py

测试矩阵（Tier 1 ≥ 6 条）：
  01 test_set_target_writes_event
  02 test_decompose_year_to_months_sum_equals_year
  03 test_decompose_month_to_days_workday_weight
  04 test_record_progress_updates_achievement_rate
  05 test_idempotent_same_source_event_id
  06 test_6_metric_types_all_trackable
  07 test_leaderboard_ranking_correct
  08 test_tenant_isolation_rls
  09 test_200_concurrent_progress_updates_no_race
"""

from __future__ import annotations

import asyncio
import os
import sys
import types
from datetime import date, datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest

# ──────────────────────────────────────────────────────────────────────────────
# 路径注入：让 services/tx-org/src 与仓库根目录可被 import
# ──────────────────────────────────────────────────────────────────────────────
_SRC = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_ROOT = os.path.abspath(os.path.join(_SRC, "..", "..", ".."))
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

# 发射器降级为 no-op（防止测试触发真实 Redis/PG 写入）
_events_pkg = types.ModuleType("shared.events")
_events_src_pkg = types.ModuleType("shared.events.src")
_emitter_mod = types.ModuleType("shared.events.src.emitter")
_evt_types_mod = types.ModuleType("shared.events.src.event_types")

_EVENT_RECORD: list[dict] = []


async def _fake_emit_event(**kwargs):  # noqa: D401
    """测试用事件捕获器。"""
    _EVENT_RECORD.append(kwargs)
    return str(uuid4())


_emitter_mod.emit_event = _fake_emit_event
_emitter_mod.emits = lambda *a, **k: (lambda f: f)


class _SalesTargetEventType:
    SET = "sales_target.set"
    PROGRESS_UPDATED = "sales_target.progress_updated"


_evt_types_mod.SalesTargetEventType = _SalesTargetEventType

_shared_root = os.path.abspath(os.path.join(_ROOT, "shared"))
_shared_pkg = types.ModuleType("shared")
_shared_pkg.__path__ = [_shared_root]  # type: ignore[attr-defined]

sys.modules.setdefault("shared", _shared_pkg)
sys.modules.setdefault("shared.events", _events_pkg)
sys.modules.setdefault("shared.events.src", _events_src_pkg)
sys.modules["shared.events.src.emitter"] = _emitter_mod
sys.modules["shared.events.src.event_types"] = _evt_types_mod

# ontology：让 shared.ontology.src 作为正常 package 解析（挂上真实 __path__），
# 这样 `shared.ontology.src.extensions.sales_targets` 可被正常 import；
# 但对可能触发真实 DB engine 初始化的 `shared.ontology.src.database`
# 单独 stub 掉，避免测试去连真实 PG。
_real_onto_root = os.path.abspath(
    os.path.join(_ROOT, "shared", "ontology")
)
_real_onto_src = os.path.join(_real_onto_root, "src")

_onto_pkg = types.ModuleType("shared.ontology")
_onto_pkg.__path__ = [_real_onto_root]  # type: ignore[attr-defined]
_onto_src_pkg = types.ModuleType("shared.ontology.src")
_onto_src_pkg.__path__ = [_real_onto_src]  # type: ignore[attr-defined]

_db_mod = types.ModuleType("shared.ontology.src.database")


async def _stub_get_db():
    yield MagicMock()


_db_mod.get_db = _stub_get_db
_db_mod.async_session_factory = MagicMock()

sys.modules.setdefault("shared.ontology", _onto_pkg)
sys.modules.setdefault("shared.ontology.src", _onto_src_pkg)
sys.modules["shared.ontology.src.database"] = _db_mod

# 直接 import 真实的 pydantic 扩展契约（只依赖 pydantic + stdlib）
# 注入 extensions 子包 path，然后 importlib 即可解析
_real_ext_dir = os.path.join(_real_onto_src, "extensions")
_ext_pkg_mod = types.ModuleType("shared.ontology.src.extensions")
_ext_pkg_mod.__path__ = [_real_ext_dir]  # type: ignore[attr-defined]
sys.modules.setdefault("shared.ontology.src.extensions", _ext_pkg_mod)

import importlib.util  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "shared.ontology.src.extensions.sales_targets",
    os.path.join(_real_ext_dir, "sales_targets.py"),
)
assert _spec is not None and _spec.loader is not None
_targets_mod = importlib.util.module_from_spec(_spec)
sys.modules["shared.ontology.src.extensions.sales_targets"] = _targets_mod
_spec.loader.exec_module(_targets_mod)

# ──────────────────────────────────────────────────────────────────────────────
# 构造虚拟父包 txorg，让 sales_target_service 中的
# `from ..repositories.sales_target_repo import ...` 相对导入能解析。
# ──────────────────────────────────────────────────────────────────────────────
import importlib.util as _ilu  # noqa: E402

_txorg = types.ModuleType("txorg")
_txorg.__path__ = [_SRC]  # type: ignore[attr-defined]
sys.modules["txorg"] = _txorg

_txorg_repo = types.ModuleType("txorg.repositories")
_txorg_repo.__path__ = [os.path.join(_SRC, "repositories")]  # type: ignore[attr-defined]
sys.modules["txorg.repositories"] = _txorg_repo

_txorg_svc = types.ModuleType("txorg.services")
_txorg_svc.__path__ = [os.path.join(_SRC, "services")]  # type: ignore[attr-defined]
sys.modules["txorg.services"] = _txorg_svc


def _load_as(name: str, filepath: str, package: str) -> types.ModuleType:
    spec = _ilu.spec_from_file_location(name, filepath)
    assert spec is not None and spec.loader is not None
    mod = _ilu.module_from_spec(spec)
    mod.__package__ = package
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


_repo_mod = _load_as(
    "txorg.repositories.sales_target_repo",
    os.path.join(_SRC, "repositories", "sales_target_repo.py"),
    "txorg.repositories",
)
_svc_mod = _load_as(
    "txorg.services.sales_target_service",
    os.path.join(_SRC, "services", "sales_target_service.py"),
    "txorg.services",
)

SalesTargetRepository = _repo_mod.SalesTargetRepository
SalesTargetService = _svc_mod.SalesTargetService

PeriodType = _targets_mod.PeriodType
MetricType = _targets_mod.MetricType


# ──────────────────────────────────────────────────────────────────────────────
# 内存 Fake DB — 模拟 sales_targets / sales_progress 两表
# ──────────────────────────────────────────────────────────────────────────────


class _FakeRow:
    def __init__(self, mapping: dict) -> None:
        self._mapping = mapping
        for k, v in mapping.items():
            setattr(self, k, v)


class _FakeResult:
    def __init__(self, rows: list[_FakeRow] | None = None) -> None:
        self._rows = rows or []

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return list(self._rows)

    def scalar(self):
        if not self._rows:
            return None
        row = self._rows[0]
        # 返回首个字段
        if row._mapping:
            return next(iter(row._mapping.values()))
        return None


class FakeDB:
    """内存 DB，隔离每个租户的数据；支持 v266 两张表。

    模拟 SQL 语义：
      - INSERT INTO sales_targets / sales_progress → 存到内存并 RETURNING
      - SELECT ... FROM sales_targets WHERE tenant_id=:tenant_id AND ... → 过滤
      - 支持 check_source_event_exists / leaderboard / aggregate_metric
    """

    def __init__(self) -> None:
        self.targets: list[dict] = []
        self.progress: list[dict] = []
        self.pnl_rows: list[dict] = []  # mv_store_pnl 模拟
        self._lock = asyncio.Lock()
        self.commit = AsyncMock()
        self.rollback = AsyncMock()
        self.close = AsyncMock()

    async def execute(self, sql, params=None):  # type: ignore[override]
        params = params or {}
        s = str(sql).upper()

        # ── INSERT sales_targets ─────────────────────────────
        if "INSERT INTO SALES_TARGETS" in s:
            async with self._lock:
                self._enforce_unique_target(params)
                row = {
                    "target_id": UUID(params["target_id"]),
                    "tenant_id": UUID(params["tenant_id"]),
                    "store_id": UUID(params["store_id"]) if params.get("store_id") else None,
                    "employee_id": UUID(params["employee_id"]),
                    "period_type": params["period_type"],
                    "period_start": params["period_start"],
                    "period_end": params["period_end"],
                    "metric_type": params["metric_type"],
                    "target_value": int(params["target_value"]),
                    "parent_target_id": (
                        UUID(params["parent_target_id"])
                        if params.get("parent_target_id")
                        else None
                    ),
                    "notes": params.get("notes"),
                    "created_by": (
                        UUID(params["created_by"])
                        if params.get("created_by")
                        else None
                    ),
                    "created_at": datetime.now(timezone.utc),
                    "updated_at": datetime.now(timezone.utc),
                }
                self.targets.append(row)
                return _FakeResult([_FakeRow(row)])

        # ── INSERT sales_progress ────────────────────────────
        if "INSERT INTO SALES_PROGRESS" in s:
            async with self._lock:
                row = {
                    "progress_id": UUID(params["progress_id"]),
                    "tenant_id": UUID(params["tenant_id"]),
                    "target_id": UUID(params["target_id"]),
                    "actual_value": int(params["actual_value"]),
                    "achievement_rate": Decimal(str(params["achievement_rate"])),
                    "snapshot_at": datetime.now(timezone.utc),
                    "source_event_id": (
                        UUID(params["source_event_id"])
                        if params.get("source_event_id")
                        else None
                    ),
                    "created_at": datetime.now(timezone.utc),
                }
                self.progress.append(row)
                return _FakeResult([_FakeRow(row)])

        # ── SELECT 1 FROM sales_progress WHERE ... source_event_id ── 幂等检查
        if (
            "FROM SALES_PROGRESS" in s
            and "SOURCE_EVENT_ID = :SOURCE_EVENT_ID" in s
            and "LIMIT 1" in s
        ):
            match = [
                p
                for p in self.progress
                if str(p["tenant_id"]) == params["tenant_id"]
                and str(p["target_id"]) == params["target_id"]
                and p["source_event_id"] is not None
                and str(p["source_event_id"]) == params["source_event_id"]
            ]
            if match:
                return _FakeResult([_FakeRow({"one": 1})])
            return _FakeResult([])

        # ── SELECT ... FROM sales_progress ORDER BY snapshot_at DESC LIMIT N
        # 仅匹配单表（非 CTE）路径：params 中不含 period_type/metric_type
        if (
            "FROM SALES_PROGRESS" in s
            and "FROM SALES_TARGETS" not in s
            and "ORDER BY" in s
            and "LIMIT" in s
            and "period_type" not in params
        ):
            limit = int(params.get("limit", 1))
            rows = [
                p
                for p in self.progress
                if str(p["tenant_id"]) == params["tenant_id"]
                and str(p["target_id"]) == params["target_id"]
            ]
            rows.sort(key=lambda r: r["snapshot_at"], reverse=True)
            return _FakeResult([_FakeRow(r) for r in rows[:limit]])

        # ── SELECT ... FROM sales_targets WHERE tenant_id=... AND target_id=...
        if (
            "FROM SALES_TARGETS" in s
            and "AND TARGET_ID = :TARGET_ID" in s
        ):
            match = [
                t
                for t in self.targets
                if str(t["tenant_id"]) == params["tenant_id"]
                and str(t["target_id"]) == params["target_id"]
            ]
            return _FakeResult([_FakeRow(t) for t in match])

        # ── SELECT ... FROM sales_targets WHERE ... parent_target_id=:parent
        if "FROM SALES_TARGETS" in s and "PARENT_TARGET_ID = :PARENT" in s:
            match = [
                t
                for t in self.targets
                if str(t["tenant_id"]) == params["tenant_id"]
                and t["parent_target_id"] is not None
                and str(t["parent_target_id"]) == params["parent"]
            ]
            return _FakeResult([_FakeRow(t) for t in match])

        # ── SELECT ... FROM sales_targets WHERE ... employee_id = ...
        if "FROM SALES_TARGETS" in s and "EMPLOYEE_ID = :EMPLOYEE_ID" in s:
            rows = [
                t
                for t in self.targets
                if str(t["tenant_id"]) == params["tenant_id"]
                and str(t["employee_id"]) == params["employee_id"]
            ]
            if "PERIOD_TYPE = :PERIOD_TYPE" in s:
                rows = [r for r in rows if r["period_type"] == params["period_type"]]
            if "BETWEEN PERIOD_START AND PERIOD_END" in s:
                today = params["today"]
                rows = [
                    r for r in rows if r["period_start"] <= today <= r["period_end"]
                ]
            rows.sort(key=lambda r: r["period_start"], reverse=True)
            return _FakeResult([_FakeRow(r) for r in rows])

        # ── SELECT ... FROM sales_targets WHERE tenant_id=... (active_targets 无 employee)
        if (
            "FROM SALES_TARGETS" in s
            and "BETWEEN PERIOD_START AND PERIOD_END" in s
        ):
            today = params["today"]
            rows = [
                t
                for t in self.targets
                if str(t["tenant_id"]) == params["tenant_id"]
                and t["period_start"] <= today <= t["period_end"]
            ]
            if "PERIOD_TYPE = :PERIOD_TYPE" in s:
                rows = [r for r in rows if r["period_type"] == params["period_type"]]
            return _FakeResult([_FakeRow(r) for r in rows])

        # ── Leaderboard SELECT DISTINCT ON ...
        if "FROM SALES_TARGETS ST" in s and "LATEST" in s:
            today = params["today"]
            period_type = params["period_type"]
            metric_type = params["metric_type"]

            targets = [
                t
                for t in self.targets
                if str(t["tenant_id"]) == params["tenant_id"]
                and t["period_type"] == period_type
                and t["metric_type"] == metric_type
                and t["period_start"] <= today <= t["period_end"]
            ]
            # 每个 target 取最新 progress
            rows_out = []
            for t in targets:
                prog = [
                    p
                    for p in self.progress
                    if p["target_id"] == t["target_id"]
                ]
                prog.sort(key=lambda r: r["snapshot_at"], reverse=True)
                latest = prog[0] if prog else None
                rows_out.append(
                    {
                        "target_id": t["target_id"],
                        "employee_id": t["employee_id"],
                        "store_id": t["store_id"],
                        "metric_type": t["metric_type"],
                        "period_type": t["period_type"],
                        "period_start": t["period_start"],
                        "period_end": t["period_end"],
                        "target_value": t["target_value"],
                        "actual_value": int(latest["actual_value"]) if latest else 0,
                        "achievement_rate": (
                            latest["achievement_rate"] if latest else Decimal("0")
                        ),
                        "snapshot_at": latest["snapshot_at"] if latest else None,
                    }
                )
            rows_out.sort(
                key=lambda r: (r["achievement_rate"], r["actual_value"]),
                reverse=True,
            )
            return _FakeResult([_FakeRow(r) for r in rows_out[: params["limit"]]])

        # ── mv_store_pnl 聚合（未填数据时返回 0）
        if "FROM MV_STORE_PNL" in s:
            rows = [
                p
                for p in self.pnl_rows
                if str(p.get("tenant_id")) == params["tenant_id"]
                and p["stat_date"] >= params["period_start"]
                and p["stat_date"] <= params["period_end"]
            ]
            if "store_id" in params:
                rows = [r for r in rows if str(r.get("store_id")) == params["store_id"]]
            if not rows:
                return _FakeResult([_FakeRow({"actual": 0})])
            # 简化：返回 gross_revenue_fen 和（其他指标测试不涉及）
            total = sum(int(r.get("gross_revenue_fen", 0)) for r in rows)
            return _FakeResult([_FakeRow({"actual": total})])

        # 默认空结果
        return _FakeResult([])

    def _enforce_unique_target(self, params):
        """模拟 UNIQUE (tenant_id, employee_id, period_type, period_start, metric_type)"""
        for t in self.targets:
            if (
                str(t["tenant_id"]) == params["tenant_id"]
                and str(t["employee_id"]) == params["employee_id"]
                and t["period_type"] == params["period_type"]
                and t["period_start"] == params["period_start"]
                and t["metric_type"] == params["metric_type"]
            ):
                raise ValueError("UNIQUE violation in test FakeDB")


# ──────────────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _reset_events():
    _EVENT_RECORD.clear()
    yield
    _EVENT_RECORD.clear()


@pytest.fixture
def fake_db():
    return FakeDB()


@pytest.fixture
def service():
    return SalesTargetService()


TENANT_A = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
TENANT_B = UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
EMP_1 = UUID("11111111-1111-1111-1111-111111111111")
EMP_2 = UUID("22222222-2222-2222-2222-222222222222")
STORE_1 = UUID("55555555-5555-5555-5555-555555555555")


# ──────────────────────────────────────────────────────────────────────────────
# 工具：等待所有 pending emit_event 任务完成
# ──────────────────────────────────────────────────────────────────────────────


async def _drain_tasks():
    """让 asyncio.create_task(emit_event) 有机会运行完。"""
    await asyncio.sleep(0)
    # 再排一次，让后续写入完整
    pending = [t for t in asyncio.all_tasks() if not t.done() and t is not asyncio.current_task()]
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)


# ──────────────────────────────────────────────────────────────────────────────
# Tests
# ──────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_set_target_writes_event(fake_db, service):
    """01 set_target 应写入 sales_targets + 触发 SalesTargetEventType.SET 事件。"""
    target = await service.set_target(
        fake_db,
        tenant_id=TENANT_A,
        employee_id=EMP_1,
        period_type=PeriodType.MONTH,
        period_start=date(2026, 4, 1),
        period_end=date(2026, 4, 30),
        metric_type=MetricType.REVENUE_FEN,
        target_value=10_000_000,  # 10 万元 = 10,000,000 分
        store_id=STORE_1,
    )
    await _drain_tasks()

    assert target["target_value"] == 10_000_000
    assert len(fake_db.targets) == 1
    assert len(_EVENT_RECORD) == 1
    ev = _EVENT_RECORD[0]
    assert ev["event_type"] == _SalesTargetEventType.SET or (
        hasattr(ev["event_type"], "value")
        and ev["event_type"].value == "sales_target.set"
    )
    assert ev["payload"]["target_value"] == 10_000_000
    assert ev["payload"]["metric_type"] == "revenue_fen"


@pytest.mark.asyncio
async def test_decompose_year_to_months_sum_equals_year(fake_db, service):
    """02 年目标分解为 12 月，月目标加和严格 = 年目标（整数守恒）。"""
    year_target = await service.set_target(
        fake_db,
        tenant_id=TENANT_A,
        employee_id=EMP_1,
        period_type=PeriodType.YEAR,
        period_start=date(2026, 1, 1),
        period_end=date(2026, 12, 31),
        metric_type=MetricType.REVENUE_FEN,
        target_value=120_000_000,  # 120 万元
    )
    children = await service.decompose_target(
        fake_db,
        tenant_id=TENANT_A,
        year_target_id=year_target["target_id"],
    )
    months = [c for c in children if c["period_type"] == "month"]
    days = [c for c in children if c["period_type"] == "day"]

    assert len(months) == 12, f"应有 12 个月目标，实际 {len(months)}"
    assert sum(m["target_value"] for m in months) == 120_000_000, (
        "12 月加和必须精确等于年目标"
    )
    # 每月内日加和必须等于月目标
    for m in months:
        m_days = [d for d in days if d["parent_target_id"] == m["target_id"]]
        assert sum(d["target_value"] for d in m_days) == m["target_value"], (
            f"月 {m['period_start']} 日加和 {sum(d['target_value'] for d in m_days)} "
            f"!= 月目标 {m['target_value']}"
        )


@pytest.mark.asyncio
async def test_decompose_month_to_days_workday_weight(fake_db, service):
    """03 月内分解时，工作日权重 > 周末权重，且加和仍守恒。"""
    # 2026-02 有 20 个工作日 + 8 个周末（共 28 天，权重 20*1.2+8*0.9 = 24+7.2=31.2）
    year_target = await service.set_target(
        fake_db,
        tenant_id=TENANT_A,
        employee_id=EMP_1,
        period_type=PeriodType.YEAR,
        period_start=date(2026, 2, 1),
        period_end=date(2027, 1, 31),
        metric_type=MetricType.ORDER_COUNT,
        target_value=365_000,  # 足够大便于观察工作日>周末
    )
    children = await service.decompose_target(
        fake_db,
        tenant_id=TENANT_A,
        year_target_id=year_target["target_id"],
    )
    # 找 2026-02 月
    feb = next(
        c
        for c in children
        if c["period_type"] == "month" and c["period_start"] == date(2026, 2, 1)
    )
    feb_days = [
        c
        for c in children
        if c["period_type"] == "day"
        and c["parent_target_id"] == feb["target_id"]
    ]
    assert len(feb_days) == 28  # 2026-02 有 28 天

    workdays = [d for d in feb_days if d["period_start"].weekday() < 5]
    weekends = [d for d in feb_days if d["period_start"].weekday() >= 5]
    # 每个工作日平均 > 每个周末平均（差异化权重生效）
    avg_work = sum(d["target_value"] for d in workdays) / len(workdays)
    avg_weekend = sum(d["target_value"] for d in weekends) / len(weekends)
    assert avg_work > avg_weekend, (
        f"工作日均值 {avg_work} 应 > 周末均值 {avg_weekend}（权重 1.2 vs 0.9）"
    )
    assert sum(d["target_value"] for d in feb_days) == feb["target_value"]


@pytest.mark.asyncio
async def test_record_progress_updates_achievement_rate(fake_db, service):
    """04 写入进度后 achievement_rate = actual/target，Decimal 字符串化。"""
    target = await service.set_target(
        fake_db,
        tenant_id=TENANT_A,
        employee_id=EMP_1,
        period_type=PeriodType.MONTH,
        period_start=date(2026, 4, 1),
        period_end=date(2026, 4, 30),
        metric_type=MetricType.REVENUE_FEN,
        target_value=10_000_000,
    )
    progress = await service.record_progress(
        fake_db,
        tenant_id=TENANT_A,
        target_id=target["target_id"],
        actual_value=3_333_333,
        source_event_id=uuid4(),
    )
    await _drain_tasks()

    # 3,333,333 / 10,000,000 = 0.3333
    assert progress["achievement_rate"] == Decimal("0.3333")

    # 达成率查询
    ach = await service.get_achievement(
        fake_db, tenant_id=TENANT_A, target_id=target["target_id"]
    )
    assert ach["achievement_rate"] == "0.3333"
    assert ach["actual_value"] == 3_333_333

    # 事件中金额全为整数，rate 为字符串
    prog_events = [e for e in _EVENT_RECORD if "progress" in str(e["event_type"]).lower()]
    assert len(prog_events) == 1
    assert isinstance(prog_events[0]["payload"]["achievement_rate"], str)


@pytest.mark.asyncio
async def test_idempotent_same_source_event_id(fake_db, service):
    """05 同一 source_event_id 触发多次 record_progress，只写入一次。"""
    target = await service.set_target(
        fake_db,
        tenant_id=TENANT_A,
        employee_id=EMP_1,
        period_type=PeriodType.MONTH,
        period_start=date(2026, 4, 1),
        period_end=date(2026, 4, 30),
        metric_type=MetricType.REVENUE_FEN,
        target_value=10_000_000,
    )
    event_id = uuid4()
    p1 = await service.record_progress(
        fake_db,
        tenant_id=TENANT_A,
        target_id=target["target_id"],
        actual_value=1_000_000,
        source_event_id=event_id,
    )
    p2 = await service.record_progress(
        fake_db,
        tenant_id=TENANT_A,
        target_id=target["target_id"],
        actual_value=9_999_999,  # 第二次：如被幂等拦截则保持第一次的值
        source_event_id=event_id,
    )
    await _drain_tasks()

    # 仅一条 progress
    assert len(fake_db.progress) == 1
    assert p1["progress_id"] == p2["progress_id"]
    # 第二次返回的仍是第一次的值（幂等）
    assert int(p2["actual_value"]) == 1_000_000


@pytest.mark.asyncio
async def test_6_metric_types_all_trackable(fake_db, service):
    """06 六种 metric_type 全部可写入并可读取达成率。"""
    metrics = [
        MetricType.REVENUE_FEN,
        MetricType.ORDER_COUNT,
        MetricType.TABLE_COUNT,
        MetricType.UNIT_AVG_FEN,
        MetricType.PER_GUEST_AVG_FEN,
        MetricType.NEW_CUSTOMER_COUNT,
    ]
    created = []
    for i, mt in enumerate(metrics):
        t = await service.set_target(
            fake_db,
            tenant_id=TENANT_A,
            employee_id=UUID(f"0000000{i}-0000-0000-0000-000000000000"),
            period_type=PeriodType.MONTH,
            period_start=date(2026, 4, 1),
            period_end=date(2026, 4, 30),
            metric_type=mt,
            target_value=100 + i,
        )
        created.append(t)

    # 为每个写一次进度
    for t in created:
        await service.record_progress(
            fake_db,
            tenant_id=TENANT_A,
            target_id=t["target_id"],
            actual_value=50,
            source_event_id=uuid4(),
        )

    for t in created:
        ach = await service.get_achievement(
            fake_db, tenant_id=TENANT_A, target_id=t["target_id"]
        )
        assert ach["actual_value"] == 50
        # 每个 metric_type 都有达成率
        assert ach["achievement_rate"] != "0.0000" or t["target_value"] == 0


@pytest.mark.asyncio
async def test_leaderboard_ranking_correct(fake_db, service):
    """07 排行榜按达成率 DESC 正确排序。"""
    employees = [EMP_1, EMP_2, UUID("33333333-3333-3333-3333-333333333333")]
    actuals = [500, 900, 200]  # 分别对应达成率 50%, 90%, 20%
    targets = []
    for emp, act in zip(employees, actuals):
        t = await service.set_target(
            fake_db,
            tenant_id=TENANT_A,
            employee_id=emp,
            period_type=PeriodType.MONTH,
            period_start=date(2026, 4, 1),
            period_end=date(2026, 4, 30),
            metric_type=MetricType.REVENUE_FEN,
            target_value=1000,
        )
        targets.append(t)
        await service.record_progress(
            fake_db,
            tenant_id=TENANT_A,
            target_id=t["target_id"],
            actual_value=act,
            source_event_id=uuid4(),
        )

    board = await service.leaderboard(
        fake_db,
        tenant_id=TENANT_A,
        period_type=PeriodType.MONTH,
        metric_type=MetricType.REVENUE_FEN,
        today=date(2026, 4, 15),
    )
    assert len(board) == 3
    # 达成率降序：90% > 50% > 20%
    assert Decimal(board[0]["achievement_rate"]) > Decimal(board[1]["achievement_rate"])
    assert Decimal(board[1]["achievement_rate"]) > Decimal(board[2]["achievement_rate"])
    assert board[0]["employee_id"] == str(EMP_2)  # 90% 第一


@pytest.mark.asyncio
async def test_tenant_isolation_rls(fake_db, service):
    """08 不同 tenant_id 的查询互不可见。"""
    t_a = await service.set_target(
        fake_db,
        tenant_id=TENANT_A,
        employee_id=EMP_1,
        period_type=PeriodType.MONTH,
        period_start=date(2026, 4, 1),
        period_end=date(2026, 4, 30),
        metric_type=MetricType.REVENUE_FEN,
        target_value=1_000_000,
    )
    await service.set_target(
        fake_db,
        tenant_id=TENANT_B,
        employee_id=EMP_1,  # 同 employee_id，不同 tenant
        period_type=PeriodType.MONTH,
        period_start=date(2026, 4, 1),
        period_end=date(2026, 4, 30),
        metric_type=MetricType.REVENUE_FEN,
        target_value=2_000_000,
    )

    # A 租户查到自己那条
    ach_a = await service.get_achievement(
        fake_db, tenant_id=TENANT_A, target_id=t_a["target_id"]
    )
    assert ach_a["target_value"] == 1_000_000

    # B 租户用 A 的 target_id 查应 → ValueError
    with pytest.raises(ValueError):
        await service.get_achievement(
            fake_db, tenant_id=TENANT_B, target_id=t_a["target_id"]
        )


@pytest.mark.asyncio
async def test_200_concurrent_progress_updates_no_race(fake_db, service):
    """09 200 并发 record_progress（不同 source_event_id），数据一致、无竞态。"""
    target = await service.set_target(
        fake_db,
        tenant_id=TENANT_A,
        employee_id=EMP_1,
        period_type=PeriodType.MONTH,
        period_start=date(2026, 4, 1),
        period_end=date(2026, 4, 30),
        metric_type=MetricType.ORDER_COUNT,
        target_value=1000,
    )

    async def _one(i: int):
        await service.record_progress(
            fake_db,
            tenant_id=TENANT_A,
            target_id=target["target_id"],
            actual_value=i + 1,
            source_event_id=uuid4(),
        )

    await asyncio.gather(*[_one(i) for i in range(200)])
    await _drain_tasks()

    assert len(fake_db.progress) == 200
    # 每条 actual_value 均有对应 progress
    vals = sorted(int(p["actual_value"]) for p in fake_db.progress)
    assert vals == list(range(1, 201))
