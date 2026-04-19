"""组织 HR 运营路由测试 — test_org_hr_ops.py

覆盖四个路由文件：
  1. attendance_routes.py          — 考勤打卡 API
  2. device_routes.py              — 设备管理 API
  3. employee_document_routes.py   — 员工证照管理 API
  4. governance_routes.py          — 总部人力治理台 API

测试矩阵（每文件 ≥ 3 个，共 14 个）：
  attendance（4 个）：
    [1]  POST /api/v1/attendance/clock-in       — 正常打卡上班
    [2]  POST /api/v1/attendance/clock-in       — 非法打卡方式 → 400
    [3]  GET  /api/v1/attendance/daily          — 正常查询日打卡状态
    [4]  GET  /api/v1/attendance/anomalies      — 缺少 X-Tenant-ID → 400

  device（3 个）：
    [5]  GET  /api/v1/org/devices               — 正常分页列表
    [6]  GET  /api/v1/org/devices/offline       — 返回离线设备列表
    [7]  GET  /api/v1/org/devices/stats         — 设备在线率统计

  employee_document（4 个）：
    [8]  GET  /api/v1/employee-documents/expiring    — 正常返回到期列表
    [9]  GET  /api/v1/employee-documents/statistics  — 证照统计
    [10] GET  /api/v1/employee-documents/{emp_id}    — 查询员工证照
    [11] PUT  /api/v1/employee-documents/{emp_id}    — 员工不存在 → 404

  governance（3 个）：
    [12] GET  /api/v1/hr/governance/dashboard   — 正常返回聚合数据
    [13] GET  /api/v1/hr/governance/risk-stores — 高风险门店列表
    [14] GET  /api/v1/hr/governance/benchmark   — 缺少 X-Tenant-ID → 400
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

from unittest.mock import AsyncMock, MagicMock, patch

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
# 构建根包链 tx_org（解决相对导入 from ..services.xxx import）
# ──────────────────────────────────────────────────────────────────────────────
_tx_org_pkg = types.ModuleType("tx_org")
_tx_org_pkg.__path__ = [_SRC]
_tx_org_pkg.__package__ = "tx_org"
sys.modules.setdefault("tx_org", _tx_org_pkg)

_tx_org_api_pkg = types.ModuleType("tx_org.api")
_tx_org_api_pkg.__path__ = [os.path.join(_SRC, "api")]
_tx_org_api_pkg.__package__ = "tx_org.api"
sys.modules.setdefault("tx_org.api", _tx_org_api_pkg)

_tx_org_svc_pkg = types.ModuleType("tx_org.services")
_tx_org_svc_pkg.__path__ = [os.path.join(_SRC, "services")]
_tx_org_svc_pkg.__package__ = "tx_org.services"
sys.modules.setdefault("tx_org.services", _tx_org_svc_pkg)

# ──────────────────────────────────────────────────────────────────────────────
# 存根：attendance_engine + attendance_repository
# ──────────────────────────────────────────────────────────────────────────────
_att_engine = types.ModuleType("tx_org.services.attendance_engine")
_att_engine.CLOCK_METHODS = {"device", "face", "app", "manual"}
sys.modules["tx_org.services.attendance_engine"] = _att_engine

_att_repo = types.ModuleType("tx_org.services.attendance_repository")
_att_repo.create_clock_record = AsyncMock(return_value={"id": str(uuid4())})
_att_repo.get_attendance_anomalies = AsyncMock(return_value=[])
_att_repo.get_attendance_rule = AsyncMock(return_value=None)
_att_repo.get_daily_attendance_for_store = AsyncMock(return_value=[])
_att_repo.get_employee_schedule = AsyncMock(return_value=None)
_att_repo.get_open_clock_in = AsyncMock(return_value=None)
_att_repo.get_payroll_attendance_data = AsyncMock(return_value=[])
_att_repo.mark_absent_employees = AsyncMock(return_value=0)
_att_repo.update_clock_out_pair = AsyncMock(return_value=None)
_att_repo.upsert_daily_attendance = AsyncMock(return_value=None)
sys.modules["tx_org.services.attendance_repository"] = _att_repo


# ──────────────────────────────────────────────────────────────────────────────
# 辅助：用 importlib 加载路由文件（指定 __package__ = 'tx_org.api'）
# ──────────────────────────────────────────────────────────────────────────────


def _load_router(filename: str, module_name: str):
    """从 api/ 目录加载路由文件，强制设置 __package__ = 'tx_org.api'。"""
    path = os.path.join(_SRC, "api", filename)
    spec = _ilu.spec_from_file_location(module_name, path)
    mod = _ilu.module_from_spec(spec)
    mod.__package__ = "tx_org.api"
    sys.modules[module_name] = mod
    spec.loader.exec_module(mod)
    return mod


# ──────────────────────────────────────────────────────────────────────────────
# 加载被测路由
# ──────────────────────────────────────────────────────────────────────────────
_att_mod = _load_router("attendance_routes.py", "tx_org.api.attendance_routes")
_dev_mod = _load_router("device_routes.py", "tx_org.api.device_routes")
_doc_mod = _load_router("employee_document_routes.py", "tx_org.api.employee_document_routes")
_gov_mod = _load_router("governance_routes.py", "tx_org.api.governance_routes")

# ──────────────────────────────────────────────────────────────────────────────
# 构建 FastAPI 应用
# ──────────────────────────────────────────────────────────────────────────────
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from shared.ontology.src.database import get_db

app_att = FastAPI()
app_att.include_router(_att_mod.router)

app_dev = FastAPI()
app_dev.include_router(_dev_mod.router)

app_doc = FastAPI()
app_doc.include_router(_doc_mod.router)

app_gov = FastAPI()
app_gov.include_router(_gov_mod.router)

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


# ══════════════════════════════════════════════════════════════════════════════
# Part 1 — attendance_routes.py
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.anyio
async def test_attendance_clock_in_ok():
    """[1] POST /api/v1/attendance/clock-in — 正常打卡上班，返回 ok=True。"""
    mock_db = _mock_db()
    mock_db.execute = AsyncMock(return_value=MagicMock())

    fake_record_id = str(uuid4())
    with (
        patch.object(_att_repo, "get_open_clock_in", new=AsyncMock(return_value=None)),
        patch.object(_att_repo, "get_employee_schedule", new=AsyncMock(return_value=None)),
        patch.object(_att_repo, "get_attendance_rule", new=AsyncMock(return_value=None)),
        patch.object(
            _att_repo,
            "create_clock_record",
            new=AsyncMock(return_value={"id": fake_record_id}),
        ),
        patch.object(_att_repo, "upsert_daily_attendance", new=AsyncMock(return_value=None)),
    ):
        app_att.dependency_overrides[get_db] = _override_db(mock_db)
        try:
            async with AsyncClient(transport=ASGITransport(app=app_att), base_url="http://test") as ac:
                resp = await ac.post(
                    "/api/v1/attendance/clock-in",
                    headers=HEADERS,
                    json={
                        "employee_id": str(uuid4()),
                        "store_id": str(uuid4()),
                        "method": "device",
                    },
                )
        finally:
            app_att.dependency_overrides.pop(get_db, None)

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert "clock_record_id" in body["data"]


@pytest.mark.anyio
async def test_attendance_clock_in_invalid_method():
    """[2] POST /api/v1/attendance/clock-in — 非法打卡方式 → 400。"""
    mock_db = _mock_db()
    mock_db.execute = AsyncMock(return_value=MagicMock())

    app_att.dependency_overrides[get_db] = _override_db(mock_db)
    try:
        async with AsyncClient(transport=ASGITransport(app=app_att), base_url="http://test") as ac:
            resp = await ac.post(
                "/api/v1/attendance/clock-in",
                headers=HEADERS,
                json={
                    "employee_id": str(uuid4()),
                    "store_id": str(uuid4()),
                    "method": "quantum_teleport",
                },
            )
    finally:
        app_att.dependency_overrides.pop(get_db, None)

    assert resp.status_code == 400
    assert "打卡方式" in resp.json()["detail"]


@pytest.mark.anyio
async def test_attendance_daily_ok():
    """[3] GET /api/v1/attendance/daily — 正常查询日打卡状态。"""
    mock_db = _mock_db()

    set_cfg = MagicMock()
    rows_result = _mappings_result([{"employee_id": str(uuid4()), "status": "normal", "work_hours": 8.0}])
    mock_db.execute = AsyncMock(side_effect=[set_cfg, rows_result])

    app_att.dependency_overrides[get_db] = _override_db(mock_db)
    try:
        async with AsyncClient(transport=ASGITransport(app=app_att), base_url="http://test") as ac:
            resp = await ac.get(
                "/api/v1/attendance/daily",
                headers=HEADERS,
                params={"store_id": str(uuid4()), "date": "2026-04-05"},
            )
    finally:
        app_att.dependency_overrides.pop(get_db, None)

    assert resp.status_code == 200
    assert resp.json()["ok"] is True


@pytest.mark.anyio
async def test_attendance_anomalies_missing_tenant():
    """[4] GET /api/v1/attendance/anomalies — 缺少 X-Tenant-ID → 400。

    anomalies 端点有三个必填 query 参数（store_id/start_date/end_date），
    但 X-Tenant-ID 的检查在路由内部，缺少必填参数会先 422。
    改用：带齐参数但不带 tenant header，期望路由返回 400。
    """
    mock_db = _mock_db()
    mock_db.execute = AsyncMock(return_value=MagicMock())

    app_att.dependency_overrides[get_db] = _override_db(mock_db)
    try:
        async with AsyncClient(transport=ASGITransport(app=app_att), base_url="http://test") as ac:
            resp = await ac.get(
                "/api/v1/attendance/anomalies",
                # 不带 X-Tenant-ID，但带齐必填参数
                params={
                    "store_id": str(uuid4()),
                    "start_date": "2026-04-01",
                    "end_date": "2026-04-05",
                },
            )
    finally:
        app_att.dependency_overrides.pop(get_db, None)

    assert resp.status_code == 400
    assert "X-Tenant-ID" in resp.json()["detail"]


# ══════════════════════════════════════════════════════════════════════════════
# Part 2 — device_routes.py
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.anyio
async def test_device_list_ok():
    """[5] GET /api/v1/org/devices — 正常分页设备列表。

    device_routes 先查 rows（mappings().all()），再查 count（scalar_one()）。
    """
    mock_db = _mock_db()

    # 第一次 execute：数据行（mappings().all()）
    device_rows = MagicMock()
    device_rows.mappings = MagicMock(
        return_value=MagicMock(
            all=MagicMock(
                return_value=[
                    {"device_id": str(uuid4()), "store_id": str(uuid4()), "device_type": "pos", "status": "online"},
                    {"device_id": str(uuid4()), "store_id": str(uuid4()), "device_type": "kds", "status": "online"},
                ]
            )
        )
    )

    # 第二次 execute：count
    count_result = MagicMock()
    count_result.scalar_one.return_value = 2

    mock_db.execute = AsyncMock(side_effect=[device_rows, count_result])

    app_dev.dependency_overrides[get_db] = _override_db(mock_db)
    try:
        async with AsyncClient(transport=ASGITransport(app=app_dev), base_url="http://test") as ac:
            resp = await ac.get(
                "/api/v1/org/devices",
                headers=HEADERS,
                params={"page": 1, "size": 20},
            )
    finally:
        app_dev.dependency_overrides.pop(get_db, None)

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["total"] == 2
    assert len(body["data"]["items"]) == 2


@pytest.mark.anyio
async def test_device_offline_list_ok():
    """[6] GET /api/v1/org/devices/offline — 离线设备告警列表（返回 items/total 结构）。"""
    mock_db = _mock_db()

    # offline 端点也是先查 rows，再查 count
    offline_rows = MagicMock()
    offline_rows.mappings = MagicMock(
        return_value=MagicMock(
            all=MagicMock(
                return_value=[
                    {
                        "device_id": str(uuid4()),
                        "store_id": str(uuid4()),
                        "device_type": "pos",
                        "last_heartbeat_at": "2026-04-05T08:00:00Z",
                        "offline_seconds": 600,
                    }
                ]
            )
        )
    )
    count_r = MagicMock()
    count_r.scalar_one.return_value = 1

    mock_db.execute = AsyncMock(side_effect=[offline_rows, count_r])

    app_dev.dependency_overrides[get_db] = _override_db(mock_db)
    try:
        async with AsyncClient(transport=ASGITransport(app=app_dev), base_url="http://test") as ac:
            resp = await ac.get("/api/v1/org/devices/offline", headers=HEADERS)
    finally:
        app_dev.dependency_overrides.pop(get_db, None)

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    # offline 端点返回 {"items": [...], "total": ..., "page": ..., "size": ...}
    assert "items" in body["data"]
    assert body["data"]["total"] == 1


@pytest.mark.anyio
async def test_device_stats_ok():
    """[7] GET /api/v1/org/devices/stats — 设备在线率统计。"""
    mock_db = _mock_db()

    overall_r = MagicMock()
    overall_r.mappings = MagicMock(
        return_value=MagicMock(first=MagicMock(return_value={"total": 10, "online": 8, "offline": 2, "maintenance": 0}))
    )
    empty_rows = _mappings_result([])

    mock_db.execute = AsyncMock(side_effect=[overall_r, empty_rows, empty_rows, empty_rows])

    app_dev.dependency_overrides[get_db] = _override_db(mock_db)
    try:
        async with AsyncClient(transport=ASGITransport(app=app_dev), base_url="http://test") as ac:
            resp = await ac.get("/api/v1/org/devices/stats", headers=HEADERS)
    finally:
        app_dev.dependency_overrides.pop(get_db, None)

    assert resp.status_code == 200
    assert resp.json()["ok"] is True


# ══════════════════════════════════════════════════════════════════════════════
# Part 3 — employee_document_routes.py
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.anyio
async def test_doc_expiring_ok():
    """[8] GET /api/v1/employee-documents/expiring — 正常返回到期证照列表。

    expiring 端点使用 result.fetchall()，每行通过 row._mapping 读取。
    """
    from datetime import date as _date

    mock_db = _mock_db()

    set_cfg = MagicMock()

    # 构造带 _mapping 的行
    _row_data = {
        "employee_id": str(uuid4()),
        "emp_name": "张三",
        "cert_type": "health_cert",
        "cert_type_name": "健康证",
        "cert_number": "HC20230101",
        "expiry_date": _date(2026, 4, 20),
        "days_remaining": 15,
        "store_id": str(uuid4()),
        "department_id": None,
    }
    _cert_row = MagicMock()
    _cert_row._mapping = _row_data

    cert_r = MagicMock()
    cert_r.fetchall = MagicMock(return_value=[_cert_row])
    mock_db.execute = AsyncMock(side_effect=[set_cfg, cert_r])

    app_doc.dependency_overrides[get_db] = _override_db(mock_db)
    try:
        async with AsyncClient(transport=ASGITransport(app=app_doc), base_url="http://test") as ac:
            resp = await ac.get(
                "/api/v1/employee-documents/expiring",
                headers=HEADERS,
                params={"threshold_days": 30},
            )
    finally:
        app_doc.dependency_overrides.pop(get_db, None)

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["total"] == 1


@pytest.mark.anyio
async def test_doc_statistics_ok():
    """[9] GET /api/v1/employee-documents/statistics — 证照统计数据。

    statistics 端点使用 result.fetchone()._mapping 获取第一行。
    """
    mock_db = _mock_db()

    set_cfg = MagicMock()

    # 构造带 _mapping 的 fetchone() 返回
    _stats_data = {
        "health_cert_total": 50,
        "health_cert_valid": 45,
        "health_cert_expiring": 3,
        "health_cert_expired": 2,
        "food_cert_total": 50,
        "food_cert_valid": 48,
        "food_cert_expiring": 1,
        "food_cert_expired": 1,
        "contract_total": 50,
        "contract_valid": 47,
        "contract_expiring": 2,
        "contract_expired": 1,
        "no_health_cert": 5,
        "no_food_cert": 2,
    }
    _fake_row = MagicMock()
    _fake_row._mapping = _stats_data

    stats_r = MagicMock()
    stats_r.fetchone = MagicMock(return_value=_fake_row)
    mock_db.execute = AsyncMock(side_effect=[set_cfg, stats_r])

    app_doc.dependency_overrides[get_db] = _override_db(mock_db)
    try:
        async with AsyncClient(transport=ASGITransport(app=app_doc), base_url="http://test") as ac:
            resp = await ac.get("/api/v1/employee-documents/statistics", headers=HEADERS)
    finally:
        app_doc.dependency_overrides.pop(get_db, None)

    assert resp.status_code == 200
    assert resp.json()["ok"] is True


@pytest.mark.anyio
async def test_doc_get_employee_docs_ok():
    """[10] GET /api/v1/employee-documents/{employee_id} — 查询某员工所有证照。

    /{employee_id} 端点使用 result.fetchone() 获取原始行，再通过 row._mapping 读取数据。
    """
    from datetime import date as _date

    mock_db = _mock_db()
    emp_id = str(uuid4())

    set_cfg = MagicMock()

    _emp_data = {
        "employee_id": emp_id,
        "emp_name": "李四",
        "store_id": str(uuid4()),
        "department_id": None,
        "health_cert_number": "HC2024001",
        "health_cert_expiry": _date(2027, 1, 1),
        "food_safety_cert": "FS2024001",
        "food_safety_cert_expiry": _date(2027, 6, 1),
        "contract_start_date": _date(2024, 1, 1),
        "contract_end_date": _date(2026, 12, 31),
    }
    _emp_row = MagicMock()
    _emp_row._mapping = _emp_data
    for k, v in _emp_data.items():
        setattr(_emp_row, k, v)

    emp_r = MagicMock()
    emp_r.fetchone = MagicMock(return_value=_emp_row)
    mock_db.execute = AsyncMock(side_effect=[set_cfg, emp_r])

    app_doc.dependency_overrides[get_db] = _override_db(mock_db)
    try:
        async with AsyncClient(transport=ASGITransport(app=app_doc), base_url="http://test") as ac:
            resp = await ac.get(
                f"/api/v1/employee-documents/{emp_id}",
                headers=HEADERS,
            )
    finally:
        app_doc.dependency_overrides.pop(get_db, None)

    assert resp.status_code == 200
    assert resp.json()["ok"] is True


@pytest.mark.anyio
async def test_doc_update_employee_not_found():
    """[11] PUT /api/v1/employee-documents/{emp_id} — 员工不存在 → 404。

    PUT 端点先查员工（fetchone()），找不到返回 404。
    """
    mock_db = _mock_db()

    set_cfg = MagicMock()
    # fetchone() 返回 None 表示找不到员工
    not_found_r = MagicMock()
    not_found_r.fetchone = MagicMock(return_value=None)
    mock_db.execute = AsyncMock(side_effect=[set_cfg, not_found_r])

    app_doc.dependency_overrides[get_db] = _override_db(mock_db)
    try:
        async with AsyncClient(transport=ASGITransport(app=app_doc), base_url="http://test") as ac:
            resp = await ac.put(
                f"/api/v1/employee-documents/{uuid4()}",
                headers=HEADERS,
                json={"health_cert_number": "HC9999"},
            )
    finally:
        app_doc.dependency_overrides.pop(get_db, None)

    assert resp.status_code == 404


# ══════════════════════════════════════════════════════════════════════════════
# Part 4 — governance_routes.py
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.anyio
async def test_governance_dashboard_ok():
    """[12] GET /api/v1/hr/governance/dashboard — 正常返回人力驾驶舱聚合数据。

    dashboard 执行顺序：set_config + headcount_q + attendance_q + productivity_q
    每个查询都有 try/except(OperationalError, ProgrammingError)。
    """
    mock_db = _mock_db()

    # set_config
    set_cfg = MagicMock()

    # headcount_q: mappings() 迭代返回品牌/区域/人数
    headcount_r = MagicMock()
    headcount_r.mappings = MagicMock(
        return_value=iter(
            [
                {"brand": "品牌A", "region": "长沙", "headcount": 30},
                {"brand": "品牌B", "region": "北京", "headcount": 20},
            ]
        )
    )

    # attendance_q: mappings().first() 返回出勤率
    att_r = MagicMock()
    att_r.mappings = MagicMock(return_value=MagicMock(first=MagicMock(return_value={"avg_attendance_rate": 0.95})))

    # productivity_q: mappings().first() 返回收入和人数
    prod_r = MagicMock()
    prod_r.mappings = MagicMock(
        return_value=MagicMock(first=MagicMock(return_value={"total_revenue_fen": 2000000, "active_employees": 50}))
    )

    mock_db.execute = AsyncMock(side_effect=[set_cfg, headcount_r, att_r, prod_r])

    app_gov.dependency_overrides[get_db] = _override_db(mock_db)
    try:
        async with AsyncClient(transport=ASGITransport(app=app_gov), base_url="http://test") as ac:
            resp = await ac.get("/api/v1/hr/governance/dashboard", headers=HEADERS)
    finally:
        app_gov.dependency_overrides.pop(get_db, None)

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert "total_headcount" in body["data"]


@pytest.mark.anyio
async def test_governance_risk_stores_ok():
    """[13] GET /api/v1/hr/governance/risk-stores — 高风险门店列表。

    risk-stores 执行顺序：set_config + att_q（出勤率+迟到率）+ alert_q（合规预警率）。
    两个查询都有 try/except(OperationalError, ProgrammingError)。
    """
    mock_db = _mock_db()

    set_cfg = MagicMock()

    store_id_val = str(uuid4())

    # att_q: mappings() 可迭代
    att_rows = MagicMock()
    att_rows.mappings = MagicMock(
        return_value=iter(
            [
                {
                    "store_id": store_id_val,
                    "store_name": "危险门店1",
                    "total_records": 100,
                    "attendance_rate": 0.75,
                    "late_rate": 0.15,
                }
            ]
        )
    )

    # alert_q: mappings() 可迭代
    alert_rows = MagicMock()
    alert_rows.mappings = MagicMock(return_value=iter([{"store_id": store_id_val, "alert_rate": 0.20}]))

    mock_db.execute = AsyncMock(side_effect=[set_cfg, att_rows, alert_rows])

    app_gov.dependency_overrides[get_db] = _override_db(mock_db)
    try:
        async with AsyncClient(transport=ASGITransport(app=app_gov), base_url="http://test") as ac:
            resp = await ac.get("/api/v1/hr/governance/risk-stores", headers=HEADERS)
    finally:
        app_gov.dependency_overrides.pop(get_db, None)

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    # risk-stores 返回带评分的门店列表
    assert "stores" in body["data"]


@pytest.mark.anyio
async def test_governance_benchmark_missing_tenant():
    """[14] GET /api/v1/hr/governance/benchmark — 缺少 X-Tenant-ID → 400。"""
    async with AsyncClient(transport=ASGITransport(app=app_gov), base_url="http://test") as ac:
        resp = await ac.get("/api/v1/hr/governance/benchmark")

    assert resp.status_code == 400
    assert "X-Tenant-ID" in resp.json()["detail"]
