"""组织排班与门店运营路由测试 — test_org_schedule_ops.py

覆盖三个路由文件：
  1. hr_dashboard_routes.py      — 人力中枢首页 API
  2. unified_schedule_routes.py  — 统一排班中心 API
  3. store_ops_routes.py         — 门店人力作战台 BFF API

测试矩阵（每文件 ≥ 3 个，共 13 个）：
  hr_dashboard（3 个）：
    [1]  GET  /api/v1/hr/dashboard/   — 正常返回聚合数据
    [2]  GET  /api/v1/hr/dashboard/   — DB OperationalError 降级（仍返回 200）
    [3]  GET  /api/v1/hr/dashboard/   — 缺少 X-Tenant-ID → 400

  unified_schedule（5 个）：
    [4]  GET  /api/v1/schedules/week     — 正常返回周排班矩阵
    [5]  POST /api/v1/schedules          — 正常创建单条排班
    [6]  POST /api/v1/schedules/batch    — 批量创建排班
    [7]  PUT  /api/v1/schedules/{id}     — 非法 status 值 → 400
    [8]  GET  /api/v1/schedules/conflicts — 冲突检测列表

  store_ops（5 个）：
    [9]  GET  /api/v1/store-ops/today          — 正常返回作战台数据
    [10] GET  /api/v1/store-ops/anomalies      — 考勤异常列表
    [11] POST /api/v1/store-ops/quick-action   — 正常快速操作
    [12] POST /api/v1/store-ops/quick-action   — service ValueError → 400
    [13] GET  /api/v1/store-ops/labor-metrics  — 月度人力指标
"""

from __future__ import annotations

import importlib.util as _ilu
import os
import sys
import types
from uuid import uuid4

# ──────────────────────────────────────────────────────────────────────────────
# 路径注入
# ──────────────────────────────────────────────────────────────────────────────
_SRC = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_ROOT = os.path.abspath(os.path.join(_SRC, "..", "..", "..", ".."))
sys.path.insert(0, _SRC)
sys.path.insert(0, _ROOT)

from unittest.mock import AsyncMock, MagicMock

# ──────────────────────────────────────────────────────────────────────────────
# 存根：structlog
# ──────────────────────────────────────────────────────────────────────────────
if "structlog" not in sys.modules:
    _slog = types.ModuleType("structlog")
    _slog.get_logger = lambda *a, **k: MagicMock()
    _slog.stdlib = types.SimpleNamespace(BoundLogger=object)
    sys.modules["structlog"] = _slog

# ──────────────────────────────────────────────────────────────────────────────
# 存根：shared.ontology.src.database
# ──────────────────────────────────────────────────────────────────────────────
_shared_pkg = types.ModuleType("shared")
_onto_pkg = types.ModuleType("shared.ontology")
_onto_src_pkg = types.ModuleType("shared.ontology.src")
_db_mod = types.ModuleType("shared.ontology.src.database")


async def _stub_get_db():
    yield MagicMock()


_db_mod.get_db = _stub_get_db
_db_mod.async_session_factory = MagicMock()
sys.modules.setdefault("shared", _shared_pkg)
sys.modules.setdefault("shared.ontology", _onto_pkg)
sys.modules.setdefault("shared.ontology.src", _onto_src_pkg)
sys.modules["shared.ontology.src.database"] = _db_mod

# ──────────────────────────────────────────────────────────────────────────────
# 构建根包链 tx_org2（独立命名，避免与 test_org_hr_ops 冲突）
# ──────────────────────────────────────────────────────────────────────────────
_ROOT_PKG = "tx_org2"  # 本测试文件专用命名空间

_tx_org2_pkg = types.ModuleType(_ROOT_PKG)
_tx_org2_pkg.__path__ = [_SRC]
_tx_org2_pkg.__package__ = _ROOT_PKG
sys.modules.setdefault(_ROOT_PKG, _tx_org2_pkg)

_tx_org2_api = types.ModuleType(f"{_ROOT_PKG}.api")
_tx_org2_api.__path__ = [os.path.join(_SRC, "api")]
_tx_org2_api.__package__ = f"{_ROOT_PKG}.api"
sys.modules.setdefault(f"{_ROOT_PKG}.api", _tx_org2_api)

_tx_org2_svc = types.ModuleType(f"{_ROOT_PKG}.services")
_tx_org2_svc.__path__ = [os.path.join(_SRC, "services")]
_tx_org2_svc.__package__ = f"{_ROOT_PKG}.services"
sys.modules.setdefault(f"{_ROOT_PKG}.services", _tx_org2_svc)

# ──────────────────────────────────────────────────────────────────────────────
# 存根：shared.events（unified_schedule_routes 依赖）
# ──────────────────────────────────────────────────────────────────────────────
_shared_events_pkg = types.ModuleType("shared.events")
sys.modules.setdefault("shared.events", _shared_events_pkg)

_org_events_mod = types.ModuleType("shared.events.org_events")


class _OrgEventType:
    SCHEDULE_CREATED = "org.schedule.created"
    SCHEDULE_BATCH_CREATED = "org.schedule.batch_created"
    SCHEDULE_CANCELLED = "org.schedule.cancelled"
    SCHEDULE_SWAP_APPROVED = "org.schedule.swap.approved"
    GAP_FILLED = "org.schedule.gap.filled"


_org_events_mod.OrgEventType = _OrgEventType
sys.modules["shared.events.org_events"] = _org_events_mod

_events_src_pkg = types.ModuleType("shared.events.src")
sys.modules.setdefault("shared.events.src", _events_src_pkg)

_emitter_mod = types.ModuleType("shared.events.src.emitter")
_emitter_mod.emit_event = AsyncMock(return_value=None)
sys.modules["shared.events.src.emitter"] = _emitter_mod

# ──────────────────────────────────────────────────────────────────────────────
# 存根：unified_schedule_service（unified_schedule_routes 依赖）
# ──────────────────────────────────────────────────────────────────────────────
_us_svc = types.ModuleType(f"{_ROOT_PKG}.services.unified_schedule_service")
_us_svc.auto_detect_gaps = AsyncMock(return_value={"detected": 0})
_us_svc.batch_create_schedules = AsyncMock(return_value={"inserted": 3, "skipped_conflicts": 0})
_us_svc.create_schedule = AsyncMock(return_value={"schedule_id": str(uuid4()), "status": "scheduled"})
_us_svc.detect_conflicts = AsyncMock(return_value=[])
_us_svc.get_fill_suggestions = AsyncMock(return_value=[])
_us_svc.get_week_schedule = AsyncMock(return_value={"employees": [], "dates": [], "total_shifts": 0})
_us_svc.swap_schedules = AsyncMock(return_value={"swap_request_id": str(uuid4())})
sys.modules[f"{_ROOT_PKG}.services.unified_schedule_service"] = _us_svc

# ──────────────────────────────────────────────────────────────────────────────
# 存根：store_ops_service（store_ops_routes 依赖）
# ──────────────────────────────────────────────────────────────────────────────
_so_svc = types.ModuleType(f"{_ROOT_PKG}.services.store_ops_service")
_so_svc.execute_fill_gap = AsyncMock(return_value={"status": "filled"})
_so_svc.execute_quick_action = AsyncMock(return_value={"success": True})
_so_svc.get_anomalies = AsyncMock(return_value=[])
_so_svc.get_fill_suggestions = AsyncMock(return_value=[])
_so_svc.get_labor_metrics = AsyncMock(
    return_value={
        "attendance_rate": 0.95,
        "avg_work_hours": 7.8,
        "labor_cost_ratio": 0.32,
    }
)
_so_svc.get_position_detail = AsyncMock(return_value=[])
_so_svc.get_today_dashboard = AsyncMock(
    return_value={
        "total_scheduled": 10,
        "present": 9,
        "absent": 1,
        "anomalies": [],
    }
)
_so_svc.get_weekly_summary = AsyncMock(return_value={"days": [], "avg_attendance_rate": 0.93})
sys.modules[f"{_ROOT_PKG}.services.store_ops_service"] = _so_svc


# ──────────────────────────────────────────────────────────────────────────────
# 辅助：用 importlib 加载路由文件
# ──────────────────────────────────────────────────────────────────────────────


def _load_router(filename: str, module_name: str, pkg: str = f"{_ROOT_PKG}.api"):
    """从 api/ 目录加载路由文件，强制设置 __package__。"""
    path = os.path.join(_SRC, "api", filename)
    spec = _ilu.spec_from_file_location(module_name, path)
    mod = _ilu.module_from_spec(spec)
    mod.__package__ = pkg
    sys.modules[module_name] = mod
    spec.loader.exec_module(mod)
    return mod


# ──────────────────────────────────────────────────────────────────────────────
# 加载被测路由
# ──────────────────────────────────────────────────────────────────────────────
_hr_mod = _load_router("hr_dashboard_routes.py", f"{_ROOT_PKG}.api.hr_dashboard_routes")
_sched_mod = _load_router("unified_schedule_routes.py", f"{_ROOT_PKG}.api.unified_schedule_routes")
_so_mod = _load_router("store_ops_routes.py", f"{_ROOT_PKG}.api.store_ops_routes")

# ──────────────────────────────────────────────────────────────────────────────
# 构建 FastAPI 应用
# ──────────────────────────────────────────────────────────────────────────────
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.exc import OperationalError

from shared.ontology.src.database import get_db

app_hr = FastAPI()
app_hr.include_router(_hr_mod.router)

app_sched = FastAPI()
app_sched.include_router(_sched_mod.router)

app_so = FastAPI()
app_so.include_router(_so_mod.router)

TENANT_ID = str(uuid4())
HEADERS = {"X-Tenant-ID": TENANT_ID}


# ──────────────────────────────────────────────────────────────────────────────
# 辅助函数
# ──────────────────────────────────────────────────────────────────────────────


def _mock_db() -> AsyncMock:
    return AsyncMock()


def _override_db(mock_session: AsyncMock):
    async def _inner():
        yield mock_session

    return _inner


def _mappings_result(rows: list) -> MagicMock:
    r = MagicMock()
    r.mappings = MagicMock(
        return_value=MagicMock(
            fetchall=MagicMock(return_value=rows),
            first=MagicMock(return_value=rows[0] if rows else None),
        )
    )
    return r


def _scalar_result(val) -> MagicMock:
    r = MagicMock()
    r.scalar_one = MagicMock(return_value=val)
    r.mappings = MagicMock(return_value=MagicMock(first=MagicMock(return_value={"total": val})))
    return r


# ══════════════════════════════════════════════════════════════════════════════
# Part 1 — hr_dashboard_routes.py
# ══════════════════════════════════════════════════════════════════════════════


def _make_mappings_first(data: dict) -> MagicMock:
    """构造 result.mappings().first() 返回指定 dict 的 mock。"""
    r = MagicMock()
    r.mappings = MagicMock(return_value=MagicMock(first=MagicMock(return_value=data)))
    return r


def _make_mappings_iter(rows: list) -> MagicMock:
    """构造 result.mappings() 可迭代的 mock。"""
    r = MagicMock()
    r.mappings = MagicMock(return_value=iter(rows))
    return r


@pytest.mark.anyio
async def test_hr_dashboard_ok():
    """[1] GET /api/v1/hr/dashboard/ — 正常返回聚合数据。

    hr_dashboard 执行顺序（所有带 try/except）：
    set_config → headcount_q → today_q → leave_q → conflict_q
    → alert_q → payroll_q → trend_q → agent_q
    """
    mock_db = _mock_db()

    set_cfg = MagicMock()

    headcount_r = _make_mappings_first({"total": 50})

    today_r = _make_mappings_first({"expected": 40, "present": 38, "absent": 2})

    leave_r = _make_mappings_first({"pending_leave": 3})

    conflict_r = _make_mappings_first({"conflicts": 1})

    alert_r = _make_mappings_first({"open_alerts": 2})

    payroll_r = _make_mappings_first({"pending_payroll": 4})

    from datetime import date as _date

    _trend_row = {"date": _date(2026, 4, 5), "rate": 0.95}
    trend_r = MagicMock()
    trend_r.mappings = MagicMock(return_value=iter([_trend_row]))

    agent_r = MagicMock()
    agent_r.mappings = MagicMock(return_value=iter([]))

    mock_db.execute = AsyncMock(
        side_effect=[
            set_cfg,
            headcount_r,
            today_r,
            leave_r,
            conflict_r,
            alert_r,
            payroll_r,
            trend_r,
            agent_r,
        ]
    )

    app_hr.dependency_overrides[get_db] = _override_db(mock_db)
    try:
        async with AsyncClient(transport=ASGITransport(app=app_hr), base_url="http://test") as ac:
            resp = await ac.get("/api/v1/hr/dashboard/", headers=HEADERS)
    finally:
        app_hr.dependency_overrides.pop(get_db, None)

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert "total_headcount" in body["data"]
    assert body["data"]["total_headcount"] == 50


@pytest.mark.anyio
async def test_hr_dashboard_db_error_graceful():
    """[2] GET /api/v1/hr/dashboard/ — DB OperationalError 降级，仍返回 200。

    hr_dashboard 每个子查询都有 try/except(OperationalError, ProgrammingError)，
    即使全部失败也返回包含默认值的 200 响应。
    """
    mock_db = _mock_db()

    # set_config 成功，后续 8 个子查询全部抛 OperationalError
    _err_calls = [OperationalError("stmt", {}, Exception("connection refused"))] * 8
    mock_db.execute = AsyncMock(
        side_effect=[MagicMock()] + _err_calls  # set_config + 8 个失败
    )

    app_hr.dependency_overrides[get_db] = _override_db(mock_db)
    try:
        async with AsyncClient(transport=ASGITransport(app=app_hr), base_url="http://test") as ac:
            resp = await ac.get("/api/v1/hr/dashboard/", headers=HEADERS)
    finally:
        app_hr.dependency_overrides.pop(get_db, None)

    # hr_dashboard 对每个子查询有 try/except，整体仍 200
    assert resp.status_code == 200
    assert resp.json()["ok"] is True


@pytest.mark.anyio
async def test_hr_dashboard_missing_tenant():
    """[3] GET /api/v1/hr/dashboard/ — 缺少 X-Tenant-ID → 400。"""
    async with AsyncClient(transport=ASGITransport(app=app_hr), base_url="http://test") as ac:
        resp = await ac.get("/api/v1/hr/dashboard/")

    assert resp.status_code == 400
    assert "X-Tenant-ID" in resp.json()["detail"]


# ══════════════════════════════════════════════════════════════════════════════
# Part 2 — unified_schedule_routes.py
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.anyio
async def test_schedule_get_week_ok():
    """[4] GET /api/v1/schedules/week — 正常返回周排班矩阵。

    from-import 绑定了 get_week_schedule 到 _sched_mod 命名空间，
    直接设置其 return_value 控制返回结果。
    """
    mock_db = _mock_db()
    mock_db.execute = AsyncMock(return_value=MagicMock())

    fake_week_data = {
        "employees": [
            {
                "employee_id": str(uuid4()),
                "emp_name": "王五",
                "shifts": [None, None, None, None, None, None, None],
            }
        ],
        "dates": [
            "2026-04-06",
            "2026-04-07",
            "2026-04-08",
            "2026-04-09",
            "2026-04-10",
            "2026-04-11",
            "2026-04-12",
        ],
        "total_shifts": 0,
    }

    _sched_mod.get_week_schedule.return_value = fake_week_data
    _sched_mod.get_week_schedule.side_effect = None

    app_sched.dependency_overrides[get_db] = _override_db(mock_db)
    try:
        async with AsyncClient(transport=ASGITransport(app=app_sched), base_url="http://test") as ac:
            resp = await ac.get(
                "/api/v1/schedules/week",
                headers=HEADERS,
                params={"store_id": str(uuid4()), "start_date": "2026-04-06"},
            )
    finally:
        app_sched.dependency_overrides.pop(get_db, None)

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert "employees" in body["data"]


@pytest.mark.anyio
async def test_schedule_create_ok():
    """[5] POST /api/v1/schedules — 正常创建单条排班。"""
    mock_db = _mock_db()
    mock_db.execute = AsyncMock(return_value=MagicMock())

    fake_result = {"schedule_id": str(uuid4()), "status": "scheduled"}
    _sched_mod.svc_create_schedule.return_value = fake_result
    _sched_mod.svc_create_schedule.side_effect = None

    app_sched.dependency_overrides[get_db] = _override_db(mock_db)
    try:
        async with AsyncClient(transport=ASGITransport(app=app_sched), base_url="http://test") as ac:
            resp = await ac.post(
                "/api/v1/schedules",
                headers=HEADERS,
                json={
                    "employee_id": str(uuid4()),
                    "store_id": str(uuid4()),
                    "schedule_date": "2026-04-10",
                    "shift_start": "09:00",
                    "shift_end": "17:00",
                },
            )
    finally:
        app_sched.dependency_overrides.pop(get_db, None)

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert "schedule_id" in body["data"]


@pytest.mark.anyio
async def test_schedule_batch_create_ok():
    """[6] POST /api/v1/schedules/batch — 批量创建排班。

    unified_schedule_routes 使用 from-import，函数引用已绑定到模块本地命名空间。
    通过直接设置 AsyncMock.return_value 而非 patch.object 来控制返回值。
    """
    mock_db = _mock_db()
    mock_db.execute = AsyncMock(return_value=MagicMock())

    # from-import 已将函数绑定到 _sched_mod 命名空间，直接设置其 return_value
    _sched_mod.batch_create_schedules.return_value = {"inserted": 5, "skipped_conflicts": 1}
    _sched_mod.batch_create_schedules.side_effect = None  # 清除可能的 side_effect

    app_sched.dependency_overrides[get_db] = _override_db(mock_db)
    try:
        async with AsyncClient(transport=ASGITransport(app=app_sched), base_url="http://test") as ac:
            resp = await ac.post(
                "/api/v1/schedules/batch",
                headers=HEADERS,
                json={
                    "store_id": str(uuid4()),
                    "template_id": str(uuid4()),
                    "employee_ids": [str(uuid4()), str(uuid4()), str(uuid4())],
                    "start_date": "2026-04-07",
                    "end_date": "2026-04-13",
                },
            )
    finally:
        app_sched.dependency_overrides.pop(get_db, None)

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["inserted"] == 5


@pytest.mark.anyio
async def test_schedule_update_invalid_status():
    """[7] PUT /api/v1/schedules/{id} — 非法 status 值 → 400。"""
    mock_db = _mock_db()
    mock_db.execute = AsyncMock(return_value=MagicMock())

    app_sched.dependency_overrides[get_db] = _override_db(mock_db)
    try:
        async with AsyncClient(transport=ASGITransport(app=app_sched), base_url="http://test") as ac:
            resp = await ac.put(
                f"/api/v1/schedules/{uuid4()}",
                headers=HEADERS,
                json={"status": "invalid_status"},
            )
    finally:
        app_sched.dependency_overrides.pop(get_db, None)

    assert resp.status_code == 400
    detail = resp.json()["detail"]
    assert "status" in detail or "scheduled" in detail


@pytest.mark.anyio
async def test_schedule_conflicts_ok():
    """[8] GET /api/v1/schedules/conflicts — 冲突检测返回列表。"""
    mock_db = _mock_db()
    mock_db.execute = AsyncMock(return_value=MagicMock())

    fake_conflicts = [
        {
            "employee_id": str(uuid4()),
            "conflict_date": "2026-04-10",
            "shift_a": "09:00-17:00",
            "shift_b": "15:00-23:00",
            "overlap_minutes": 120,
        }
    ]

    _sched_mod.detect_conflicts.return_value = fake_conflicts
    _sched_mod.detect_conflicts.side_effect = None

    app_sched.dependency_overrides[get_db] = _override_db(mock_db)
    try:
        async with AsyncClient(transport=ASGITransport(app=app_sched), base_url="http://test") as ac:
            # conflicts 端点需要三个必填参数：store_id/start_date/end_date
            resp = await ac.get(
                "/api/v1/schedules/conflicts",
                headers=HEADERS,
                params={
                    "store_id": str(uuid4()),
                    "start_date": "2026-04-07",
                    "end_date": "2026-04-13",
                },
            )
    finally:
        app_sched.dependency_overrides.pop(get_db, None)

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    # conflicts 端点返回 {"store_id": ..., "conflicts": [...], "conflict_count": ...}
    assert "conflicts" in body["data"]


# ══════════════════════════════════════════════════════════════════════════════
# Part 3 — store_ops_routes.py
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.anyio
async def test_store_ops_today_ok():
    """[9] GET /api/v1/store-ops/today — 正常返回今日作战台数据。

    store_ops_routes 使用 from-import，直接设置 _so_mod 命名空间里的函数 return_value。
    """
    mock_db = _mock_db()

    fake_data = {
        "total_scheduled": 12,
        "present": 10,
        "absent": 1,
        "leave": 1,
        "anomalies": [],
        "fill_gaps": [],
    }
    _so_mod.get_today_dashboard.return_value = fake_data
    _so_mod.get_today_dashboard.side_effect = None

    app_so.dependency_overrides[get_db] = _override_db(mock_db)
    try:
        async with AsyncClient(transport=ASGITransport(app=app_so), base_url="http://test") as ac:
            resp = await ac.get(
                "/api/v1/store-ops/today",
                headers=HEADERS,
                params={"store_id": str(uuid4())},
            )
    finally:
        app_so.dependency_overrides.pop(get_db, None)

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["total_scheduled"] == 12


@pytest.mark.anyio
async def test_store_ops_anomalies_ok():
    """[10] GET /api/v1/store-ops/anomalies — 考勤异常列表。"""
    mock_db = _mock_db()

    fake_anomalies = [
        {
            "employee_id": str(uuid4()),
            "emp_name": "赵六",
            "anomaly_type": "late",
            "diff_minutes": 15,
        }
    ]
    _so_mod.get_anomalies.return_value = fake_anomalies
    _so_mod.get_anomalies.side_effect = None

    app_so.dependency_overrides[get_db] = _override_db(mock_db)
    try:
        async with AsyncClient(transport=ASGITransport(app=app_so), base_url="http://test") as ac:
            resp = await ac.get(
                "/api/v1/store-ops/anomalies",
                headers=HEADERS,
                params={"store_id": str(uuid4())},
            )
    finally:
        app_so.dependency_overrides.pop(get_db, None)

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert len(body["data"]) == 1
    assert body["data"][0]["anomaly_type"] == "late"


@pytest.mark.anyio
async def test_store_ops_quick_action_ok():
    """[11] POST /api/v1/store-ops/quick-action — 正常快速操作（确认迟到）。"""
    mock_db = _mock_db()

    fake_result = {"success": True, "action_type": "acknowledge_late", "target_id": "rec-001"}
    _so_mod.execute_quick_action.return_value = fake_result
    _so_mod.execute_quick_action.side_effect = None

    app_so.dependency_overrides[get_db] = _override_db(mock_db)
    try:
        async with AsyncClient(transport=ASGITransport(app=app_so), base_url="http://test") as ac:
            resp = await ac.post(
                "/api/v1/store-ops/quick-action",
                headers=HEADERS,
                json={
                    "action_type": "acknowledge_late",
                    "target_id": "rec-001",
                    "operator_id": str(uuid4()),
                    "note": "已确认",
                },
            )
    finally:
        app_so.dependency_overrides.pop(get_db, None)

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["success"] is True


@pytest.mark.anyio
async def test_store_ops_quick_action_value_error():
    """[12] POST /api/v1/store-ops/quick-action — service ValueError → 400。"""
    mock_db = _mock_db()

    # 设置 side_effect 触发 ValueError
    _so_mod.execute_quick_action.side_effect = ValueError("不支持的操作类型")

    app_so.dependency_overrides[get_db] = _override_db(mock_db)
    try:
        async with AsyncClient(transport=ASGITransport(app=app_so), base_url="http://test") as ac:
            resp = await ac.post(
                "/api/v1/store-ops/quick-action",
                headers=HEADERS,
                json={
                    "action_type": "unknown_action",
                    "target_id": "rec-xyz",
                    "operator_id": str(uuid4()),
                },
            )
    finally:
        app_so.dependency_overrides.pop(get_db, None)
        # 恢复正常行为（清除 side_effect）
        _so_mod.execute_quick_action.side_effect = None
        _so_mod.execute_quick_action.return_value = {"success": True}

    assert resp.status_code == 400
    assert "不支持的操作类型" in resp.json()["detail"]


@pytest.mark.anyio
async def test_store_ops_labor_metrics_ok():
    """[13] GET /api/v1/store-ops/labor-metrics — 月度人力指标。"""
    mock_db = _mock_db()

    fake_metrics = {
        "attendance_rate": 0.94,
        "avg_work_hours": 7.6,
        "labor_cost_ratio": 0.28,
        "overtime_rate": 0.12,
        "absence_rate": 0.06,
    }
    _so_mod.get_labor_metrics.return_value = fake_metrics
    _so_mod.get_labor_metrics.side_effect = None

    app_so.dependency_overrides[get_db] = _override_db(mock_db)
    try:
        async with AsyncClient(transport=ASGITransport(app=app_so), base_url="http://test") as ac:
            resp = await ac.get(
                "/api/v1/store-ops/labor-metrics",
                headers=HEADERS,
                params={"store_id": str(uuid4()), "month": "2026-03"},
            )
    finally:
        app_so.dependency_overrides.pop(get_db, None)

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["attendance_rate"] == 0.94
