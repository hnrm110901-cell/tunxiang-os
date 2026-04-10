"""班次交班 & 班次报表路由测试
shift_routes.py + shift_report_routes.py

覆盖场景（共 10 个）：

shift_routes.py — 5 个
1. POST /api/v1/shifts/handover                  — 正常开始交班，返回 handover_id
2. POST /api/v1/shifts/handover                  — 缺少 X-Tenant-ID → 400
3. POST /api/v1/shifts/handover/{id}/cash-count  — 现金清点正常，返回 cash_actual_fen
4. POST /api/v1/shifts/handover/{id}/finalize    — 完成交班，返回 variance_fen
5. POST /api/v1/shifts/handover                  — ShiftHandoverService 抛 ValueError → 400

shift_report_routes.py — 5 个
6. GET  /api/v1/shifts/{store_id}/config          — 正常返回班次配置列表
7. POST /api/v1/shifts/{store_id}/config          — 创建班次配置成功
8. GET  /api/v1/shifts/{store_id}/report          — 正常返回报表摘要
9. GET  /api/v1/shifts/{store_id}/report          — date 参数格式非法 → 422
10. GET /api/v1/shifts/{store_id}/operators       — 正常返回厨师绩效列表
"""
from __future__ import annotations

import os
import sys
import types
import uuid
from datetime import date, time
from unittest.mock import AsyncMock, MagicMock, patch

# ─── sys.path 设置 ─────────────────────────────────────────────────────────────

_TESTS_DIR = os.path.dirname(__file__)
_SRC_DIR   = os.path.abspath(os.path.join(_TESTS_DIR, ".."))
_ROOT_DIR  = os.path.abspath(os.path.join(_TESTS_DIR, "..", "..", "..", ".."))

for _p in [_SRC_DIR, _ROOT_DIR]:
    if _p not in sys.path:
        sys.path.insert(0, _p)


# ─── 包层级注册（解决相对导入 from ..services.X 问题） ──────────────────────────

def _stub(name: str, **attrs) -> types.ModuleType:
    """注入一个空模块存根（仅当尚未存在时）。"""
    if name not in sys.modules:
        mod = types.ModuleType(name)
        sys.modules[name] = mod
    mod = sys.modules[name]
    for k, v in attrs.items():
        setattr(mod, k, v)
    return mod


def _ensure_pkg(name: str, path: str) -> types.ModuleType:
    if name not in sys.modules:
        mod = types.ModuleType(name)
        mod.__path__ = [path]
        mod.__package__ = name
        sys.modules[name] = mod
    return sys.modules[name]


# 注册 src 包层级（让相对导入能够解析 ..services）
_ensure_pkg("src",          _SRC_DIR)
_ensure_pkg("src.api",      os.path.join(_SRC_DIR, "api"))
_ensure_pkg("src.services", os.path.join(_SRC_DIR, "services"))
_ensure_pkg("src.models",   os.path.join(_SRC_DIR, "models"))

# ─── shared.* 存根 ─────────────────────────────────────────────────────────────

_stub("shared")
_stub("shared.events")
_stub("shared.events.src")

async def _fake_emit_event(*_args, **_kwargs):  # pragma: no cover
    pass

_stub("shared.events.src.emitter", emit_event=_fake_emit_event)

import enum as _enum  # noqa: E402

class _TradeEventType(_enum.Enum):
    PAID = "ORDER.PAID"

_stub("shared.events.src.event_types", TradeEventType=_TradeEventType, OrderEventType=_TradeEventType)

# shared.ontology
_stub("shared.ontology")
_stub("shared.ontology.src")
_stub("shared.ontology.src.entities", Order=object)
_stub("shared.ontology.src.enums", OrderStatus=None)

# shared.ontology.src.database — 注入 get_db / get_db_with_tenant 占位符
_db_mod = types.ModuleType("shared.ontology.src.database")

async def _get_db_placeholder():  # pragma: no cover
    yield None

_db_mod.get_db             = _get_db_placeholder
_db_mod.get_db_with_tenant = _get_db_placeholder
_db_mod.get_db_no_rls      = _get_db_placeholder
sys.modules["shared.ontology.src.database"] = _db_mod

# ─── src.models 存根（避免 SQLAlchemy 模型导入链爆炸） ───────────────────────────

_stub("src.models.enums", PaymentStatus=None)
_stub("src.models.payment", Payment=object, Refund=object)
_stub("src.models.settlement", ShiftHandover=object)
_stub("src.models.shift_config", ShiftConfig=object)

# ─── src.services 存根（让路由相对导入时找到服务类）────────────────────────────────

class _StubShiftHandoverService:
    def __init__(self, db, tenant_id): ...
    async def start_handover(self, **kw): ...
    async def record_cash_count(self, **kw): ...
    async def finalize_handover(self, **kw): ...
    async def get_shift_summary(self, **kw): ...


class _StubShiftReportService:
    def __init__(self, db, tenant_id): ...
    async def list_shift_configs(self, *a, **kw): ...
    async def create_shift_config(self, *a, **kw): ...
    async def get_shift_summary(self, *a, **kw): ...
    async def get_shift_trend(self, *a, **kw): ...
    async def get_operator_performance(self, *a, **kw): ...


_stub("src.services.shift_handover_service",
      ShiftHandoverService=_StubShiftHandoverService)
_stub("src.services.shift_report",
      ShiftReportService=_StubShiftReportService)

# ─── 导入被测路由 ──────────────────────────────────────────────────────────────

import pytest                                                      # noqa: E402
from fastapi import FastAPI                                        # noqa: E402
from fastapi.testclient import TestClient                          # noqa: E402

from src.api.shift_routes import router as shift_router            # type: ignore[import]  # noqa: E402
from src.api.shift_routes import _get_db_session as _shift_db_dep  # type: ignore[import]  # noqa: E402

from src.api.shift_report_routes import router as report_router               # type: ignore[import]  # noqa: E402
from src.api.shift_report_routes import _get_db_session as _report_db_dep     # type: ignore[import]  # noqa: E402

from shared.ontology.src.database import get_db                    # noqa: E402  # noqa: F401

# ─── 常量 ──────────────────────────────────────────────────────────────────────

TENANT_ID   = str(uuid.uuid4())
STORE_ID    = str(uuid.uuid4())
CASHIER_ID  = str(uuid.uuid4())
HANDOVER_ID = str(uuid.uuid4())
SHIFT_ID    = str(uuid.uuid4())

SHIFT_HEADERS = {"X-Tenant-ID": TENANT_ID}


# ─── 辅助工厂 ──────────────────────────────────────────────────────────────────

def _make_db() -> AsyncMock:
    db = AsyncMock()
    db.commit   = AsyncMock()
    db.rollback = AsyncMock()
    db.execute  = AsyncMock()
    return db


def _db_override(db: AsyncMock):
    """生成 async generator 覆盖函数，注入 mock DB session"""
    async def _dep():
        yield db
    return _dep


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# shift_routes — 5 个测试
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# 场景 1: POST /handover — 正常开始交班 ─────────────────────────────────────────

def test_start_handover_ok():
    """ShiftHandoverService.start_handover 成功时返回 ok=True 和 handover_id"""
    db = _make_db()

    app = FastAPI()
    app.include_router(shift_router)
    app.dependency_overrides[_shift_db_dep] = _db_override(db)

    expected = {
        "handover_id": HANDOVER_ID,
        "cashier_id": CASHIER_ID,
        "store_id": STORE_ID,
        "status": "pending",
    }

    with patch("src.api.shift_routes.ShiftHandoverService") as MockSvc:
        instance = MagicMock()
        instance.start_handover = AsyncMock(return_value=expected)
        MockSvc.return_value = instance

        client = TestClient(app)
        resp = client.post(
            "/api/v1/shifts/handover",
            json={"cashier_id": CASHIER_ID, "store_id": STORE_ID},
            headers=SHIFT_HEADERS,
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["handover_id"] == HANDOVER_ID
    assert body["data"]["status"] == "pending"


# 场景 2: POST /handover — 缺少 X-Tenant-ID → 400 ──────────────────────────────

def test_start_handover_missing_tenant():
    """不提供 X-Tenant-ID header 时路由返回 400"""
    db = _make_db()

    app = FastAPI()
    app.include_router(shift_router)
    app.dependency_overrides[_shift_db_dep] = _db_override(db)

    with patch("src.api.shift_routes.ShiftHandoverService"):
        client = TestClient(app)
        resp = client.post(
            "/api/v1/shifts/handover",
            json={"cashier_id": CASHIER_ID, "store_id": STORE_ID},
            # 故意不传 X-Tenant-ID
        )

    assert resp.status_code == 400
    assert "X-Tenant-ID" in resp.json()["detail"]


# 场景 3: POST /handover/{id}/cash-count — 现金清点正常 ─────────────────────────

def test_record_cash_count_ok():
    """record_cash_count 返回 cash_actual_fen，ok=True"""
    db = _make_db()

    app = FastAPI()
    app.include_router(shift_router)
    app.dependency_overrides[_shift_db_dep] = _db_override(db)

    denominations = {"100": 5, "50": 3, "20": 2, "10": 5, "1": 8}
    expected = {
        "handover_id": HANDOVER_ID,
        "cash_actual_fen": 158000,
        "denominations": denominations,
    }

    with patch("src.api.shift_routes.ShiftHandoverService") as MockSvc:
        instance = MagicMock()
        instance.record_cash_count = AsyncMock(return_value=expected)
        MockSvc.return_value = instance

        client = TestClient(app)
        resp = client.post(
            f"/api/v1/shifts/handover/{HANDOVER_ID}/cash-count",
            json={"denominations": denominations},
            headers=SHIFT_HEADERS,
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["cash_actual_fen"] == 158000
    assert body["data"]["handover_id"] == HANDOVER_ID


# 场景 4: POST /handover/{id}/finalize — 完成交班 ──────────────────────────────

def test_finalize_handover_ok():
    """finalize_handover 成功返回 variance_fen 和 variance_alert 字段"""
    db = _make_db()

    app = FastAPI()
    app.include_router(shift_router)
    app.dependency_overrides[_shift_db_dep] = _db_override(db)

    expected = {
        "handover_id": HANDOVER_ID,
        "variance_fen": -500,
        "variance_alert": False,
        "status": "completed",
    }

    with patch("src.api.shift_routes.ShiftHandoverService") as MockSvc:
        instance = MagicMock()
        instance.finalize_handover = AsyncMock(return_value=expected)
        MockSvc.return_value = instance

        client = TestClient(app)
        resp = client.post(
            f"/api/v1/shifts/handover/{HANDOVER_ID}/finalize",
            headers=SHIFT_HEADERS,
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["variance_fen"] == -500
    assert body["data"]["variance_alert"] is False
    assert body["data"]["status"] == "completed"


# 场景 5: POST /handover — 业务校验失败（ValueError → 400） ─────────────────────

def test_start_handover_service_value_error():
    """ShiftHandoverService.start_handover 抛 ValueError 时返回 400"""
    db = _make_db()

    app = FastAPI()
    app.include_router(shift_router)
    app.dependency_overrides[_shift_db_dep] = _db_override(db)

    with patch("src.api.shift_routes.ShiftHandoverService") as MockSvc:
        instance = MagicMock()
        instance.start_handover = AsyncMock(
            side_effect=ValueError("当前已有未完成交班，请先完成")
        )
        MockSvc.return_value = instance

        client = TestClient(app)
        resp = client.post(
            "/api/v1/shifts/handover",
            json={"cashier_id": CASHIER_ID, "store_id": STORE_ID},
            headers=SHIFT_HEADERS,
        )

    assert resp.status_code == 400
    assert "当前已有未完成交班" in resp.json()["detail"]


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# shift_report_routes — 5 个测试
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# 场景 6: GET /{store_id}/config — 正常返回班次配置列表 ──────────────────────────

def test_list_shift_configs_ok():
    """list_shift_configs 有数据时返回 ok=True，data 为配置列表"""
    db = _make_db()

    app = FastAPI()
    app.include_router(report_router)
    app.dependency_overrides[_report_db_dep] = _db_override(db)

    fake_config = MagicMock()
    fake_config.id         = uuid.uuid4()
    fake_config.store_id   = uuid.UUID(STORE_ID)
    fake_config.shift_name = "午班"
    fake_config.start_time = time(11, 0)
    fake_config.end_time   = time(14, 0)
    fake_config.color      = "#FF6B35"
    fake_config.is_active  = True
    fake_config.created_at = None

    with patch("src.api.shift_report_routes.ShiftReportService") as MockSvc:
        instance = MagicMock()
        instance.list_shift_configs = AsyncMock(return_value=[fake_config])
        MockSvc.return_value = instance

        client = TestClient(app)
        resp = client.get(
            f"/api/v1/shifts/{STORE_ID}/config",
            headers=SHIFT_HEADERS,
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert isinstance(body["data"], list)
    assert len(body["data"]) == 1
    assert body["data"][0]["shift_name"] == "午班"
    assert body["data"][0]["start_time"] == "11:00"


# 场景 7: POST /{store_id}/config — 创建班次配置成功 ────────────────────────────

def test_create_shift_config_ok():
    """create_shift_config 成功时返回新建配置，ok=True"""
    db = _make_db()

    app = FastAPI()
    app.include_router(report_router)
    app.dependency_overrides[_report_db_dep] = _db_override(db)

    new_config = MagicMock()
    new_config.id         = uuid.uuid4()
    new_config.store_id   = uuid.UUID(STORE_ID)
    new_config.shift_name = "晚班"
    new_config.start_time = time(17, 0)
    new_config.end_time   = time(21, 0)
    new_config.color      = "#2196F3"
    new_config.is_active  = True
    new_config.created_at = None

    with patch("src.api.shift_report_routes.ShiftReportService") as MockSvc:
        instance = MagicMock()
        instance.create_shift_config = AsyncMock(return_value=new_config)
        MockSvc.return_value = instance

        client = TestClient(app)
        resp = client.post(
            f"/api/v1/shifts/{STORE_ID}/config",
            json={
                "shift_name": "晚班",
                "start_time": "17:00",
                "end_time":   "21:00",
                "color":      "#2196F3",
            },
            headers=SHIFT_HEADERS,
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["shift_name"] == "晚班"
    assert body["data"]["start_time"] == "17:00"
    assert body["data"]["end_time"]   == "21:00"


# 场景 8: GET /{store_id}/report — 正常返回报表摘要 ─────────────────────────────

def test_get_shift_report_ok():
    """get_shift_summary 成功时返回含 total_tasks/timeout_rate 的报表摘要"""
    db = _make_db()

    app = FastAPI()
    app.include_router(report_router)
    app.dependency_overrides[_report_db_dep] = _db_override(db)

    fake_dept = MagicMock()
    fake_dept.dept_id              = "dept-01"
    fake_dept.dept_name            = "炒菜档"
    fake_dept.total_tasks          = 50
    fake_dept.finished_tasks       = 48
    fake_dept.avg_duration_seconds = 95.3
    fake_dept.timeout_count        = 3
    fake_dept.remake_count         = 1
    fake_dept.timeout_rate         = 0.0625
    fake_dept.remake_rate          = 0.0208

    fake_op = MagicMock()
    fake_op.operator_id            = "op-001"
    fake_op.operator_name          = "张三"
    fake_op.total_tasks            = 30
    fake_op.finished_tasks         = 29
    fake_op.avg_duration_seconds   = 88.0
    fake_op.remake_count           = 0
    fake_op.remake_rate            = 0.0

    fake_summary = MagicMock()
    fake_summary.shift_id              = SHIFT_ID
    fake_summary.shift_name            = "午班"
    fake_summary.date                  = "2026-04-04"
    fake_summary.total_tasks           = 80
    fake_summary.finished_tasks        = 77
    fake_summary.avg_duration_seconds  = 92.5
    fake_summary.timeout_count         = 5
    fake_summary.remake_count          = 2
    fake_summary.timeout_rate          = 0.065
    fake_summary.remake_rate           = 0.026
    fake_summary.dept_stats            = [fake_dept]
    fake_summary.operator_stats        = [fake_op]

    with patch("src.api.shift_report_routes.ShiftReportService") as MockSvc:
        instance = MagicMock()
        instance.get_shift_summary = AsyncMock(return_value=fake_summary)
        MockSvc.return_value = instance

        client = TestClient(app)
        resp = client.get(
            f"/api/v1/shifts/{STORE_ID}/report",
            params={"date": "2026-04-04", "shift_id": SHIFT_ID},
            headers=SHIFT_HEADERS,
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    data = body["data"]
    assert data["total_tasks"] == 80
    assert data["finished_tasks"] == 77
    assert data["shift_name"] == "午班"
    assert len(data["dept_stats"]) == 1
    assert data["dept_stats"][0]["dept_name"] == "炒菜档"
    assert len(data["operator_stats"]) == 1
    assert data["operator_stats"][0]["operator_name"] == "张三"


# 场景 9: GET /{store_id}/report — 日期格式非法 → 422 ──────────────────────────
# shift_report_routes.get_shift_report 仅捕获 date.fromisoformat() 的 ValueError
# 并转为 422，这是该路由的唯一业务校验失败路径。

def test_get_shift_report_invalid_date():
    """date 参数格式非法（非 YYYY-MM-DD）时路由返回 422"""
    db = _make_db()

    app = FastAPI()
    app.include_router(report_router)
    app.dependency_overrides[_report_db_dep] = _db_override(db)

    with patch("src.api.shift_report_routes.ShiftReportService") as MockSvc:
        instance = MagicMock()
        instance.get_shift_summary = AsyncMock(return_value=MagicMock())
        MockSvc.return_value = instance

        client = TestClient(app)
        resp = client.get(
            f"/api/v1/shifts/{STORE_ID}/report",
            params={"date": "not-a-date", "shift_id": SHIFT_ID},
            headers=SHIFT_HEADERS,
        )

    assert resp.status_code == 422
    assert "日期格式错误" in resp.json()["detail"]


# 场景 10: GET /{store_id}/operators — 正常返回厨师绩效列表 ────────────────────────

def test_get_operator_performance_ok():
    """get_operator_performance 成功时返回厨师绩效列表，ok=True"""
    db = _make_db()

    app = FastAPI()
    app.include_router(report_router)
    app.dependency_overrides[_report_db_dep] = _db_override(db)

    op1 = MagicMock()
    op1.operator_id            = "op-001"
    op1.operator_name          = "李四"
    op1.total_tasks            = 40
    op1.finished_tasks         = 39
    op1.avg_duration_seconds   = 85.2
    op1.remake_count           = 1
    op1.remake_rate            = 0.0256

    op2 = MagicMock()
    op2.operator_id            = "op-002"
    op2.operator_name          = "王五"
    op2.total_tasks            = 35
    op2.finished_tasks         = 35
    op2.avg_duration_seconds   = 78.0
    op2.remake_count           = 0
    op2.remake_rate            = 0.0

    with patch("src.api.shift_report_routes.ShiftReportService") as MockSvc:
        instance = MagicMock()
        instance.get_operator_performance = AsyncMock(return_value=[op1, op2])
        MockSvc.return_value = instance

        client = TestClient(app)
        resp = client.get(
            f"/api/v1/shifts/{STORE_ID}/operators",
            params={"date": "2026-04-04"},
            headers=SHIFT_HEADERS,
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    items = body["data"]
    assert len(items) == 2
    assert items[0]["operator_name"] == "李四"
    assert items[0]["total_tasks"] == 40
    assert items[1]["operator_name"] == "王五"
    assert items[1]["remake_count"] == 0
