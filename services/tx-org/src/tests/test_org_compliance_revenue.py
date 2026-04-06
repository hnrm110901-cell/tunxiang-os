"""tx-org 合规预警 / 营收排班 / 员工贡献度 路由测试

覆盖三个路由文件：
  1. compliance_alert_routes.py  (7 端点) — 直接 SQL + get_db 依赖
  2. revenue_schedule_routes.py  (5 端点) — RevenueScheduleService 封装层
  3. contribution_routes.py      (5 端点) — ContributionScoreService 封装层

测试矩阵（每文件 ≥ 4 个，共 17 个）：

  compliance_alert_routes [1-7]:
    [1]  GET  /alerts              — 正常列表返回 ok=True
    [2]  GET  /alerts/{id}         — 无记录 → 404
    [3]  POST /alerts/{id}/acknowledge — 正常确认 → acknowledged
    [4]  POST /alerts/{id}/resolve     — alert 不存在 → 404
    [5]  GET  /dashboard           — 正常统计返回
    [6]  POST /scan                — 无效 scan_type → 400
    [7]  GET  /alerts/export       — 正常导出 ok=True

  revenue_schedule_routes [8-12]:
    [8]  GET  /analysis            — 正常返回 ok=True
    [9]  GET  /optimal-plan        — ValueError → 400
    [10] POST /apply-plan          — 正常写入 draft ok=True
    [11] GET  /comparison          — 正常返回 differences
    [12] GET  /savings-estimate    — 正常返回 ok=True

  contribution_routes [13-17]:
    [13] GET  /score/{emp_id}      — 正常返回 ok=True
    [14] GET  /rankings            — 缺 X-Tenant-ID → 400
    [15] POST /recalculate         — 正常触发重算 ok=True
    [16] GET  /store-comparison    — 正常跨店对比 ok=True
    [17] GET  /trend/{emp_id}      — 正常趋势 ok=True

技术说明：
  compliance_alert_routes 使用绝对导入，可直接 from api.xxx import。
  revenue_schedule_routes 和 contribution_routes 使用相对导入（from ..services）。
  通过虚拟父包 txorg 绕过相对导入限制，用 importlib.util 手动加载。
"""

from __future__ import annotations

import importlib.util
import os
import sys
import types

# ──────────────────────────────────────────────────────────────────────────────
# 路径注入
# ──────────────────────────────────────────────────────────────────────────────
_SRC = os.path.join(os.path.dirname(__file__), "..")
_ROOT = os.path.join(_SRC, "..", "..", "..", "..")
sys.path.insert(0, _SRC)
sys.path.insert(0, _ROOT)

from unittest.mock import AsyncMock, MagicMock, patch

# ──────────────────────────────────────────────────────────────────────────────
# structlog 存根
# ──────────────────────────────────────────────────────────────────────────────
if "structlog" not in sys.modules:
    _slog = types.ModuleType("structlog")
    _slog.get_logger = lambda *a, **k: MagicMock()
    _slog.stdlib = types.SimpleNamespace(BoundLogger=object)
    sys.modules["structlog"] = _slog

# ──────────────────────────────────────────────────────────────────────────────
# shared.ontology.src.database 存根
# ──────────────────────────────────────────────────────────────────────────────
for _key in ("shared", "shared.ontology", "shared.ontology.src"):
    sys.modules.setdefault(_key, types.ModuleType(_key))

_db_mod = types.ModuleType("shared.ontology.src.database")


async def _stub_get_db():
    yield MagicMock()


_db_mod.get_db = _stub_get_db
_db_mod.async_session_factory = MagicMock()
sys.modules["shared.ontology.src.database"] = _db_mod

# ──────────────────────────────────────────────────────────────────────────────
# 虚拟父包 txorg — 让相对导入 from ..services.xxx 正常解析
#   txorg.api.revenue_schedule_routes  →  ..services  →  txorg.services
#   txorg.api.contribution_routes      →  ..services  →  txorg.services
# ──────────────────────────────────────────────────────────────────────────────
_txorg = types.ModuleType("txorg")
_txorg.__path__ = [_SRC]
_txorg.__package__ = "txorg"
sys.modules["txorg"] = _txorg

_txorg_api = types.ModuleType("txorg.api")
_txorg_api.__path__ = [os.path.join(_SRC, "api")]
_txorg_api.__package__ = "txorg.api"
sys.modules["txorg.api"] = _txorg_api

_txorg_svc = types.ModuleType("txorg.services")
_txorg_svc.__path__ = [os.path.join(_SRC, "services")]
sys.modules["txorg.services"] = _txorg_svc


# ── RevenueScheduleService 存根 ───────────────────────────────────────────────
class _FakeRevSvc:
    async def analyze_revenue_pattern(self, db, tenant_id, store_id, weeks):
        return {"store_id": store_id, "patterns": [], "weeks": weeks}

    async def generate_weekly_plan(self, db, tenant_id, store_id, week_start):
        return {
            "store_id": store_id,
            "week_start": str(week_start),
            "daily_plans": [],
            "summary": {"total_slots": 0, "optimized_slots": 0},
        }

    async def apply_plan_as_draft(self, db, tenant_id, store_id, week_start, operator_id):
        return {
            "store_id": store_id,
            "week_start": str(week_start),
            "status": "draft",
            "created": 0,
        }

    async def estimate_monthly_savings(self, db, tenant_id, store_id, month):
        return {"store_id": store_id, "month": month, "estimated_savings_fen": 0}


_rev_svc_stub = types.ModuleType("txorg.services.revenue_schedule_service")
_rev_svc_stub.RevenueScheduleService = _FakeRevSvc
sys.modules["txorg.services.revenue_schedule_service"] = _rev_svc_stub


# ── ContributionScoreService 存根 ──────────────────────────────────────────────
class _FakeContribSvc:
    async def calculate_score(self, db, tenant_id, employee_id, period_start, period_end):
        return {
            "employee_id": employee_id,
            "score": 85.0,
            "rank": 1,
            "dimensions": {},
        }

    async def calculate_store_rankings(self, db, tenant_id, store_id, period_start, period_end):
        return {
            "store_id": store_id,
            "rankings": [{"employee_id": "emp-1", "score": 90.0}],
            "stats": {"total_employees": 1, "avg": 90.0},
        }

    async def get_employee_trend(self, db, tenant_id, employee_id, periods):
        return {
            "employee_id": employee_id,
            "periods": periods,
            "trend": [],
        }


_contrib_svc_stub = types.ModuleType("txorg.services.contribution_score_service")
_contrib_svc_stub.ContributionScoreService = _FakeContribSvc
sys.modules["txorg.services.contribution_score_service"] = _contrib_svc_stub


# ──────────────────────────────────────────────────────────────────────────────
# 用 importlib 将两个相对导入路由文件以 txorg.api.* 身份加载
# ──────────────────────────────────────────────────────────────────────────────
def _load_route_module(name: str, filepath: str, package: str = "txorg.api"):
    spec = importlib.util.spec_from_file_location(name, filepath)
    mod = importlib.util.module_from_spec(spec)
    mod.__package__ = package
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


_rev_route_mod = _load_route_module(
    "txorg.api.revenue_schedule_routes",
    os.path.join(_SRC, "api", "revenue_schedule_routes.py"),
)

_contrib_route_mod = _load_route_module(
    "txorg.api.contribution_routes",
    os.path.join(_SRC, "api", "contribution_routes.py"),
)

# ──────────────────────────────────────────────────────────────────────────────
# 普通绝对导入（compliance_alert_routes 无相对 service 导入）
# ──────────────────────────────────────────────────────────────────────────────
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from uuid import uuid4

from api.compliance_alert_routes import router as compliance_router
import api.compliance_alert_routes as _ca_mod

# 从路由模块本身获取 get_db 引用，确保 dependency_overrides key 与路由实际使用的一致
get_db = _ca_mod.get_db

# 获取动态加载的 router 和 _service 单例
rev_sched_router = _rev_route_mod.router
_rev_service = _rev_route_mod._service
# 从路由模块获取它们实际使用的 get_db 引用（避免 dependency_overrides key 不匹配）
_rev_get_db = _rev_route_mod.get_db

contrib_router = _contrib_route_mod.router
_contrib_service = _contrib_route_mod._service
_contrib_get_db = _contrib_route_mod.get_db

# ──────────────────────────────────────────────────────────────────────────────
# 三个独立 FastAPI 应用
# ──────────────────────────────────────────────────────────────────────────────
app_compliance = FastAPI()
app_compliance.include_router(compliance_router)

app_rev = FastAPI()
app_rev.include_router(rev_sched_router)

app_contrib = FastAPI()
app_contrib.include_router(contrib_router)

TENANT_ID = str(uuid4())
HEADERS = {"X-Tenant-ID": TENANT_ID}
EMP_ID = str(uuid4())
STORE_ID = str(uuid4())
ALERT_ID = str(uuid4())


# ──────────────────────────────────────────────────────────────────────────────
# 工具函数
# ──────────────────────────────────────────────────────────────────────────────

def _make_row(data: dict) -> MagicMock:
    row = MagicMock()
    row._mapping = data
    for k, v in data.items():
        setattr(row, k, v)
    return row


_UNSET = object()


def _make_sync_result(
    *,
    fetchone=_UNSET,
    fetchall=_UNSET,
    scalar=_UNSET,
) -> MagicMock:
    """构造同步 execute 结果对象（fetchall/fetchone/scalar 均为同步调用）。

    传入 None 表示返回 None；不传表示使用 MagicMock 默认值。
    """
    r = MagicMock()
    if fetchone is not _UNSET:
        r.fetchone = MagicMock(return_value=fetchone)
    if fetchall is not _UNSET:
        r.fetchall = MagicMock(return_value=fetchall)
    if scalar is not _UNSET:
        r.scalar = MagicMock(return_value=scalar)
    return r


def _mock_db() -> AsyncMock:
    """DB session mock：execute 是 async，但返回值的子方法是同步 MagicMock。"""
    return AsyncMock()


def _override_db(mock_session: AsyncMock):
    async def _inner():
        yield mock_session
    return _inner


# ══════════════════════════════════════════════════════════════════════════════
# Part 1 — compliance_alert_routes.py  [1-7]
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.anyio
async def test_compliance_list_alerts_ok():
    """[1] GET /api/v1/compliance/alerts — 正常列表返回 ok=True。"""
    db = _mock_db()

    count_result = _make_sync_result(scalar=2)

    row1 = _make_row({
        "alert_id": ALERT_ID, "employee_id": EMP_ID, "store_id": STORE_ID,
        "alert_type": "health_cert_expiry", "severity": "high",
        "title": "健康证将在5天后到期", "description": "到期: 2026-04-10",
        "status": "pending", "acknowledged_by": None, "acknowledged_at": None,
        "resolved_by": None, "resolved_at": None, "resolution_note": None,
        "created_at": None, "employee_name": "张三", "employee_phone": "13800138000",
    })
    list_result = _make_sync_result(fetchall=[row1])

    # set_config + count + list
    set_result = MagicMock()
    db.execute = AsyncMock(side_effect=[set_result, count_result, list_result])
    app_compliance.dependency_overrides[get_db] = _override_db(db)

    try:
        async with AsyncClient(
            transport=ASGITransport(app=app_compliance), base_url="http://test"
        ) as ac:
            resp = await ac.get("/api/v1/compliance/alerts", headers=HEADERS)
    finally:
        app_compliance.dependency_overrides.clear()

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["total"] == 2
    assert len(body["data"]["items"]) == 1


@pytest.mark.anyio
async def test_compliance_get_alert_detail_not_found():
    """[2] GET /api/v1/compliance/alerts/{id} — 无记录 → 404。"""
    db = _mock_db()

    set_result = MagicMock()
    detail_result = _make_sync_result(fetchone=None)
    db.execute = AsyncMock(side_effect=[set_result, detail_result])
    app_compliance.dependency_overrides[get_db] = _override_db(db)

    try:
        async with AsyncClient(
            transport=ASGITransport(app=app_compliance), base_url="http://test"
        ) as ac:
            resp = await ac.get(f"/api/v1/compliance/alerts/{ALERT_ID}", headers=HEADERS)
    finally:
        app_compliance.dependency_overrides.clear()

    assert resp.status_code == 404
    assert "预警不存在" in resp.json()["detail"]


@pytest.mark.anyio
async def test_compliance_acknowledge_alert_ok():
    """[3] POST /api/v1/compliance/alerts/{id}/acknowledge — 正常确认。"""
    db = _mock_db()

    set_result = MagicMock()
    ack_row = _make_row({"alert_id": ALERT_ID})
    ack_result = _make_sync_result(fetchone=ack_row)
    db.execute = AsyncMock(side_effect=[set_result, ack_result])
    db.commit = AsyncMock()
    app_compliance.dependency_overrides[get_db] = _override_db(db)

    try:
        async with AsyncClient(
            transport=ASGITransport(app=app_compliance), base_url="http://test"
        ) as ac:
            resp = await ac.post(
                f"/api/v1/compliance/alerts/{ALERT_ID}/acknowledge",
                headers=HEADERS,
                json={"acknowledged_by": "manager-001", "note": "已知晓"},
            )
    finally:
        app_compliance.dependency_overrides.clear()

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["status"] == "acknowledged"


@pytest.mark.anyio
async def test_compliance_resolve_alert_not_found():
    """[4] POST /api/v1/compliance/alerts/{id}/resolve — alert 不存在 → 404。"""
    db = _mock_db()

    set_result = MagicMock()
    update_result = _make_sync_result(fetchone=None)
    check_result = _make_sync_result(fetchone=None)

    db.execute = AsyncMock(side_effect=[set_result, update_result, check_result])
    db.commit = AsyncMock()
    app_compliance.dependency_overrides[get_db] = _override_db(db)

    try:
        async with AsyncClient(
            transport=ASGITransport(app=app_compliance), base_url="http://test"
        ) as ac:
            resp = await ac.post(
                f"/api/v1/compliance/alerts/{ALERT_ID}/resolve",
                headers=HEADERS,
                json={"resolved_by": "manager-001", "resolution_note": "已处理"},
            )
    finally:
        app_compliance.dependency_overrides.clear()

    assert resp.status_code == 404
    assert "预警不存在" in resp.json()["detail"]


@pytest.mark.anyio
async def test_compliance_dashboard_ok():
    """[5] GET /api/v1/compliance/dashboard — 正常统计返回 ok=True。"""
    db = _mock_db()

    set_result = MagicMock()

    overview_row = _make_row({
        "total": 10, "pending_count": 3, "acknowledged_count": 4, "resolved_count": 3,
        "critical_count": 1, "high_count": 2, "medium_count": 4, "low_count": 3,
    })
    overview_result = _make_sync_result(fetchone=overview_row)
    type_result = _make_sync_result(fetchall=[])
    store_result = _make_sync_result(fetchall=[])
    trend_result = _make_sync_result(fetchall=[])

    db.execute = AsyncMock(
        side_effect=[set_result, overview_result, type_result, store_result, trend_result]
    )
    app_compliance.dependency_overrides[get_db] = _override_db(db)

    try:
        async with AsyncClient(
            transport=ASGITransport(app=app_compliance), base_url="http://test"
        ) as ac:
            resp = await ac.get("/api/v1/compliance/dashboard", headers=HEADERS)
    finally:
        app_compliance.dependency_overrides.clear()

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["overview"]["total"] == 10
    assert body["data"]["overview"]["by_status"]["pending"] == 3


@pytest.mark.anyio
async def test_compliance_scan_invalid_type():
    """[6] POST /api/v1/compliance/scan — 无效 scan_type → 400。"""
    db = _mock_db()
    set_result = MagicMock()
    db.execute = AsyncMock(return_value=set_result)
    app_compliance.dependency_overrides[get_db] = _override_db(db)

    try:
        async with AsyncClient(
            transport=ASGITransport(app=app_compliance), base_url="http://test"
        ) as ac:
            resp = await ac.post(
                "/api/v1/compliance/scan",
                headers=HEADERS,
                json={"scan_type": "invalid_type"},
            )
    finally:
        app_compliance.dependency_overrides.clear()

    assert resp.status_code == 400
    assert "scan_type" in resp.json()["detail"]


@pytest.mark.anyio
async def test_compliance_export_alerts_ok():
    """[7] GET /api/v1/compliance/alerts/export — 正常导出 ok=True。"""
    db = _mock_db()

    set_result = MagicMock()
    export_row = _make_row({
        "alert_id": ALERT_ID, "alert_type": "contract_expiry",
        "severity": "medium", "title": "合同将到期", "description": "30天内",
        "status": "pending", "resolution_note": None,
        "created_at": None, "resolved_at": None,
        "employee_name": "李四", "employee_phone": "13900139000",
        "store_id": STORE_ID, "department_name": "前厅",
    })
    export_result = _make_sync_result(fetchall=[export_row])

    db.execute = AsyncMock(side_effect=[set_result, export_result])
    app_compliance.dependency_overrides[get_db] = _override_db(db)

    try:
        async with AsyncClient(
            transport=ASGITransport(app=app_compliance), base_url="http://test"
        ) as ac:
            resp = await ac.get(
                "/api/v1/compliance/alerts/export",
                headers=HEADERS,
                params={"severity": "medium"},
            )
    finally:
        app_compliance.dependency_overrides.clear()

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["total"] == 1


# ══════════════════════════════════════════════════════════════════════════════
# Part 2 — revenue_schedule_routes.py  [8-12]
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.anyio
async def test_rev_sched_analysis_ok():
    """[8] GET /api/v1/revenue-schedule/analysis — 正常返回 ok=True。"""
    db = _mock_db()
    app_rev.dependency_overrides[get_db] = _override_db(db)

    with patch.object(
        _rev_service,
        "analyze_revenue_pattern",
        new=AsyncMock(return_value={
            "store_id": STORE_ID,
            "patterns": [{"slot": "lunch", "avg_revenue_fen": 50000}],
            "weeks": 4,
        }),
    ):
        try:
            async with AsyncClient(
                transport=ASGITransport(app=app_rev), base_url="http://test"
            ) as ac:
                resp = await ac.get(
                    "/api/v1/revenue-schedule/analysis",
                    headers=HEADERS,
                    params={"store_id": STORE_ID, "weeks": "4"},
                )
        finally:
            app_rev.dependency_overrides.clear()

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["store_id"] == STORE_ID


@pytest.mark.anyio
async def test_rev_sched_optimal_plan_value_error():
    """[9] GET /api/v1/revenue-schedule/optimal-plan — ValueError → 400。"""
    db = _mock_db()
    app_rev.dependency_overrides[get_db] = _override_db(db)

    with patch.object(
        _rev_service,
        "generate_weekly_plan",
        new=AsyncMock(side_effect=ValueError("门店数据不足，无法生成方案")),
    ):
        try:
            async with AsyncClient(
                transport=ASGITransport(app=app_rev), base_url="http://test"
            ) as ac:
                resp = await ac.get(
                    "/api/v1/revenue-schedule/optimal-plan",
                    headers=HEADERS,
                    params={"store_id": STORE_ID},
                )
        finally:
            app_rev.dependency_overrides.clear()

    assert resp.status_code == 400
    assert "门店数据不足" in resp.json()["detail"]


@pytest.mark.anyio
async def test_rev_sched_apply_plan_ok():
    """[10] POST /api/v1/revenue-schedule/apply-plan — 正常写入 draft ok=True。"""
    db = _mock_db()
    app_rev.dependency_overrides[get_db] = _override_db(db)

    with patch.object(
        _rev_service,
        "apply_plan_as_draft",
        new=AsyncMock(return_value={
            "store_id": STORE_ID,
            "week_start": "2026-04-06",
            "status": "draft",
            "created": 7,
        }),
    ):
        try:
            async with AsyncClient(
                transport=ASGITransport(app=app_rev), base_url="http://test"
            ) as ac:
                resp = await ac.post(
                    "/api/v1/revenue-schedule/apply-plan",
                    headers=HEADERS,
                    json={
                        "store_id": STORE_ID,
                        "week_start": "2026-04-06",
                        "operator_id": "mgr-001",
                    },
                )
        finally:
            app_rev.dependency_overrides.clear()

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["status"] == "draft"
    assert body["data"]["created"] == 7


@pytest.mark.anyio
async def test_rev_sched_comparison_ok():
    """[11] GET /api/v1/revenue-schedule/comparison — 正常返回 differences 字段。"""
    db = _mock_db()
    app_rev.dependency_overrides[get_db] = _override_db(db)

    plan_with_delta = {
        "store_id": STORE_ID,
        "week_start": "2026-04-06",
        "daily_plans": [
            {
                "date": "2026-04-06",
                "weekday_name": "周一",
                "slots": [
                    {
                        "slot_name": "午餐", "start_time": "11:00", "end_time": "14:00",
                        "predicted_revenue_fen": 120000, "optimal_staff": 5,
                        "current_staff": 3, "delta": 2,
                    }
                ],
            }
        ],
        "summary": {"total_slots": 42, "optimized_slots": 1},
    }

    with patch.object(
        _rev_service,
        "generate_weekly_plan",
        new=AsyncMock(return_value=plan_with_delta),
    ):
        try:
            async with AsyncClient(
                transport=ASGITransport(app=app_rev), base_url="http://test"
            ) as ac:
                resp = await ac.get(
                    "/api/v1/revenue-schedule/comparison",
                    headers=HEADERS,
                    params={"store_id": STORE_ID, "week_start": "2026-04-06"},
                )
        finally:
            app_rev.dependency_overrides.clear()

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["total_differences"] == 1
    assert body["data"]["differences"][0]["delta"] == 2


@pytest.mark.anyio
async def test_rev_sched_savings_estimate_ok():
    """[12] GET /api/v1/revenue-schedule/savings-estimate — 正常返回 ok=True。"""
    db = _mock_db()
    app_rev.dependency_overrides[get_db] = _override_db(db)

    with patch.object(
        _rev_service,
        "estimate_monthly_savings",
        new=AsyncMock(return_value={
            "store_id": STORE_ID,
            "month": "2026-04",
            "estimated_savings_fen": 48000,
        }),
    ):
        try:
            async with AsyncClient(
                transport=ASGITransport(app=app_rev), base_url="http://test"
            ) as ac:
                resp = await ac.get(
                    "/api/v1/revenue-schedule/savings-estimate",
                    headers=HEADERS,
                    params={"store_id": STORE_ID, "month": "2026-04"},
                )
        finally:
            app_rev.dependency_overrides.clear()

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["estimated_savings_fen"] == 48000


# ══════════════════════════════════════════════════════════════════════════════
# Part 3 — contribution_routes.py  [13-17]
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.anyio
async def test_contrib_score_ok():
    """[13] GET /api/v1/contribution/score/{emp_id} — 正常返回 ok=True。"""
    db = _mock_db()
    app_contrib.dependency_overrides[get_db] = _override_db(db)

    with patch.object(
        _contrib_service,
        "calculate_score",
        new=AsyncMock(return_value={
            "employee_id": EMP_ID,
            "score": 88.5,
            "rank": 2,
            "dimensions": {"sales": 90, "attendance": 87},
        }),
    ):
        try:
            async with AsyncClient(
                transport=ASGITransport(app=app_contrib), base_url="http://test"
            ) as ac:
                resp = await ac.get(
                    f"/api/v1/contribution/score/{EMP_ID}",
                    headers=HEADERS,
                )
        finally:
            app_contrib.dependency_overrides.clear()

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["score"] == 88.5


@pytest.mark.anyio
async def test_contrib_rankings_missing_tenant():
    """[14] GET /api/v1/contribution/rankings — 缺 X-Tenant-ID → 400。"""
    db = _mock_db()
    app_contrib.dependency_overrides[get_db] = _override_db(db)

    try:
        async with AsyncClient(
            transport=ASGITransport(app=app_contrib), base_url="http://test"
        ) as ac:
            resp = await ac.get(
                "/api/v1/contribution/rankings",
                params={"store_id": STORE_ID},
                # 故意不传 X-Tenant-ID
            )
    finally:
        app_contrib.dependency_overrides.clear()

    assert resp.status_code == 400
    assert "X-Tenant-ID" in resp.json()["detail"]


@pytest.mark.anyio
async def test_contrib_recalculate_ok():
    """[15] POST /api/v1/contribution/recalculate — 正常触发重算 ok=True。"""
    db = _mock_db()
    app_contrib.dependency_overrides[get_db] = _override_db(db)

    expected = {
        "store_id": STORE_ID,
        "rankings": [{"employee_id": EMP_ID, "score": 91.0}],
        "stats": {"total_employees": 1, "avg": 91.0},
    }

    with patch.object(
        _contrib_service,
        "calculate_store_rankings",
        new=AsyncMock(return_value=expected),
    ):
        try:
            async with AsyncClient(
                transport=ASGITransport(app=app_contrib), base_url="http://test"
            ) as ac:
                resp = await ac.post(
                    "/api/v1/contribution/recalculate",
                    headers=HEADERS,
                    json={"store_id": STORE_ID},
                )
        finally:
            app_contrib.dependency_overrides.clear()

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["stats"]["total_employees"] == 1


@pytest.mark.anyio
async def test_contrib_store_comparison_ok():
    """[16] GET /api/v1/contribution/store-comparison — 正常跨店对比 ok=True。"""
    db = _mock_db()
    app_contrib.dependency_overrides[get_db] = _override_db(db)

    store2 = str(uuid4())
    side_effects = [
        {
            "store_id": STORE_ID,
            "rankings": [{"employee_id": EMP_ID, "score": 85.0}],
            "stats": {"total_employees": 1, "avg": 85.0},
        },
        {
            "store_id": store2,
            "rankings": [],
            "stats": {"total_employees": 0, "avg": 0.0},
        },
    ]

    with patch.object(
        _contrib_service,
        "calculate_store_rankings",
        new=AsyncMock(side_effect=side_effects),
    ):
        try:
            async with AsyncClient(
                transport=ASGITransport(app=app_contrib), base_url="http://test"
            ) as ac:
                resp = await ac.get(
                    "/api/v1/contribution/store-comparison",
                    headers=HEADERS,
                    params={"store_ids": f"{STORE_ID},{store2}"},
                )
        finally:
            app_contrib.dependency_overrides.clear()

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert len(body["data"]["stores"]) == 2


@pytest.mark.anyio
async def test_contrib_trend_ok():
    """[17] GET /api/v1/contribution/trend/{emp_id} — 正常趋势 ok=True。"""
    db = _mock_db()
    app_contrib.dependency_overrides[get_db] = _override_db(db)

    trend_data = {
        "employee_id": EMP_ID,
        "periods": 6,
        "trend": [
            {"period": "2025-10", "score": 80.0},
            {"period": "2025-11", "score": 83.0},
        ],
    }

    with patch.object(
        _contrib_service,
        "get_employee_trend",
        new=AsyncMock(return_value=trend_data),
    ):
        try:
            async with AsyncClient(
                transport=ASGITransport(app=app_contrib), base_url="http://test"
            ) as ac:
                resp = await ac.get(
                    f"/api/v1/contribution/trend/{EMP_ID}",
                    headers=HEADERS,
                    params={"periods": "6"},
                )
        finally:
            app_contrib.dependency_overrides.clear()

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert len(body["data"]["trend"]) == 2
