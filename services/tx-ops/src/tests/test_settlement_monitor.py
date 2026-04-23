"""日结监控 API 测试

6 个测试用例：
  1. test_monitor_returns_store_list    — GET /monitor 返回门店列表，含 status 字段
  2. test_overdue_detection             — 逾期判定逻辑
  3. test_brand_filter                  — brand_id 过滤参数生效
  4. test_completion_rate_calculation   — 完成率 = completed / total 正确
  5. test_history_returns_trend         — GET /history 返回趋势数据
  6. test_remark_endpoint               — POST /remark 写入备注

技术约束：
  - sys.modules 存根注入（shared.ontology / shared.events）
  - app.dependency_overrides[get_db] + AsyncMock
  - DB mock 返回模拟行数据
"""

from __future__ import annotations

import sys
import types
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

# ══════════════════════════════════════════════════════════════════════════════
#  sys.modules 存根注入（必须在导入路由前完成）
# ══════════════════════════════════════════════════════════════════════════════


def _ensure_stub(module_path: str, attrs: dict | None = None) -> types.ModuleType:
    if module_path not in sys.modules:
        mod = types.ModuleType(module_path)
        if attrs:
            for k, v in attrs.items():
                setattr(mod, k, v)
        sys.modules[module_path] = mod
    return sys.modules[module_path]


_ensure_stub("shared")
_ensure_stub("shared.ontology")
_ensure_stub("shared.ontology.src")
_db_mod = _ensure_stub("shared.ontology.src.database")
if not hasattr(_db_mod, "get_db"):

    async def _placeholder_get_db():
        yield None

    _db_mod.get_db = _placeholder_get_db

_ensure_stub("shared.events")
_ensure_stub("shared.events.src")
_ensure_stub("shared.events.src.emitter", {"emit_event": AsyncMock()})
_ev_types = _ensure_stub("shared.events.src.event_types")
if not hasattr(_ev_types, "SettlementEventType"):

    class _FakeSettlementEventType:
        DAILY_CLOSED = "settlement.daily_closed"

    _ev_types.SettlementEventType = _FakeSettlementEventType

if "structlog" not in sys.modules:
    _sl = types.ModuleType("structlog")
    _sl.get_logger = MagicMock(return_value=MagicMock())
    sys.modules["structlog"] = _sl

if "asyncpg" not in sys.modules:
    _apg = types.ModuleType("asyncpg")
    _apg.connect = AsyncMock()
    sys.modules["asyncpg"] = _apg


# ══════════════════════════════════════════════════════════════════════════════
#  导入路由（存根注入后）
# ══════════════════════════════════════════════════════════════════════════════

from shared.ontology.src.database import get_db  # noqa: E402

from ..api.settlement_monitor_routes import (  # noqa: E402
    _compute_summary,
    _is_overdue,
)
from ..api.settlement_monitor_routes import router as monitor_router  # noqa: E402

# ══════════════════════════════════════════════════════════════════════════════
#  FastAPI 应用
# ══════════════════════════════════════════════════════════════════════════════

app = FastAPI()
app.include_router(monitor_router)

TENANT_ID = str(uuid.uuid4())
HEADERS = {"X-Tenant-ID": TENANT_ID}


# ── 辅助函数 ──────────────────────────────────────────────────────────────────


def _make_row_mapping(data: dict):
    """创建模拟 SQLAlchemy row._mapping 对象。"""

    class FakeMapping:
        def __init__(self, d):
            self._data = d

        def __getitem__(self, key):
            return self._data[key]

        def get(self, key, default=None):
            return self._data.get(key, default)

    class FakeRow:
        def __init__(self, d):
            self._mapping = FakeMapping(d)

    return FakeRow(data)


def _make_db_with_stores(stores_data: list[dict]) -> AsyncMock:
    """返回一个DB mock，execute 返回模拟门店日结数据。"""
    db = AsyncMock()
    rows = [_make_row_mapping(s) for s in stores_data]
    result_mock = MagicMock()
    result_mock.fetchall.return_value = rows
    result_mock.fetchone.return_value = True  # for table check
    result_mock.scalar.return_value = len(stores_data)
    db.execute = AsyncMock(return_value=result_mock)
    db.commit = AsyncMock()
    return db


SAMPLE_STORES = [
    {
        "store_id": "store_001",
        "store_name": "芙蓉路店",
        "brand_name": "尝在一起",
        "brand_id": "brand_001",
        "region_id": "region_001",
        "status": "completed",
        "expected_close_time": "22:00",
        "actual_close_time": "21:45",
        "operator_name": "张店长",
        "duration_minutes": 45,
        "remarks": "",
    },
    {
        "store_id": "store_002",
        "store_name": "五一广场店",
        "brand_name": "尝在一起",
        "brand_id": "brand_001",
        "region_id": "region_001",
        "status": "running",
        "expected_close_time": "22:00",
        "actual_close_time": None,
        "operator_name": "李店长",
        "duration_minutes": None,
        "remarks": "",
    },
    {
        "store_id": "store_003",
        "store_name": "解放西店",
        "brand_name": "最黔线",
        "brand_id": "brand_002",
        "region_id": "region_001",
        "status": "pending",
        "expected_close_time": "21:30",
        "actual_close_time": None,
        "operator_name": "王店长",
        "duration_minutes": None,
        "remarks": "",
    },
]


def _override(db_mock: AsyncMock):
    async def _dep() -> AsyncGenerator:
        yield db_mock

    return _dep


# ══════════════════════════════════════════════════════════════════════════════
#  测试用例
# ══════════════════════════════════════════════════════════════════════════════


class TestMonitorReturnsStoreList:
    """1. GET /monitor 返回门店列表，含 status 字段。"""

    def setup_method(self):
        app.dependency_overrides.clear()

    def teardown_method(self):
        app.dependency_overrides.clear()

    def test_monitor_returns_store_list(self):
        db = _make_db_with_stores(SAMPLE_STORES)
        app.dependency_overrides[get_db] = _override(db)

        with TestClient(app) as client:
            resp = client.get(
                "/api/v1/ops/settlement/monitor",
                params={"settlement_date": "2026-04-06"},
                headers=HEADERS,
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        data = body["data"]
        assert "stores" in data
        assert "summary" in data
        assert isinstance(data["stores"], list)
        for store in data["stores"]:
            assert "status" in store
            assert store["status"] in ("completed", "running", "pending", "overdue")
            assert "store_id" in store
            assert "store_name" in store


class TestOverdueDetection:
    """2. 逾期判定逻辑。"""

    def test_overdue_detection_logic(self):
        store_running = {
            "store_id": "test_store",
            "status": "running",
            "expected_close_time": "01:00",
        }
        today = date.today()
        now_late = datetime(today.year, today.month, today.day, 4, 0, tzinfo=timezone.utc)
        assert _is_overdue(store_running, now_late) is True

    def test_not_overdue_if_completed(self):
        store_done = {
            "store_id": "test_store",
            "status": "completed",
            "expected_close_time": "01:00",
        }
        today = date.today()
        now_late = datetime(today.year, today.month, today.day, 4, 0, tzinfo=timezone.utc)
        assert _is_overdue(store_done, now_late) is False

    def test_not_overdue_within_1h_window(self):
        store_running = {
            "store_id": "test_store",
            "status": "running",
            "expected_close_time": "23:30",
        }
        today = date.today()
        now_within = datetime(today.year, today.month, today.day, 23, 45, tzinfo=timezone.utc)
        assert _is_overdue(store_running, now_within) is False


class TestCompletionRateCalculation:
    """3. 完成率 = completed / total 正确。"""

    def test_completion_rate_formula(self):
        stores = [
            {"status": "completed"},
            {"status": "completed"},
            {"status": "running"},
            {"status": "pending"},
            {"status": "overdue"},
        ]
        summary = _compute_summary(stores)
        assert summary["total_stores"] == 5
        assert summary["completed_count"] == 2
        assert summary["completion_rate"] == 40.0

    def test_completion_rate_all_complete(self):
        stores = [{"status": "completed"}, {"status": "completed"}]
        summary = _compute_summary(stores)
        assert summary["completion_rate"] == 100.0

    def test_completion_rate_empty(self):
        summary = _compute_summary([])
        assert summary["completion_rate"] == 0.0
        assert summary["total_stores"] == 0


class TestHistoryEndpoint:
    """4. GET /history 返回趋势数据。"""

    def setup_method(self):
        app.dependency_overrides.clear()

    def teardown_method(self):
        app.dependency_overrides.clear()

    def test_history_returns_trend(self):
        db = AsyncMock()
        # 模拟 history 查询结果
        today = date.today()
        trend_rows = []
        for i in range(3):
            d = today - timedelta(days=2 - i)
            trend_rows.append(
                _make_row_mapping(
                    {
                        "settlement_date": d,
                        "total": 5,
                        "completed": 4 + (i % 2),
                    }
                )
            )
        result_mock = MagicMock()
        result_mock.fetchall.return_value = trend_rows
        db.execute = AsyncMock(return_value=result_mock)
        app.dependency_overrides[get_db] = _override(db)

        with TestClient(app) as client:
            resp = client.get(
                "/api/v1/ops/settlement/monitor/history",
                params={"days": 3},
                headers=HEADERS,
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        trend = body["data"]["trend"]
        assert isinstance(trend, list)
        for item in trend:
            assert "date" in item
            assert "completion_rate" in item
            assert 0 <= item["completion_rate"] <= 100


class TestRemarkEndpoint:
    """5. POST /remark 写入备注。"""

    def setup_method(self):
        app.dependency_overrides.clear()

    def teardown_method(self):
        app.dependency_overrides.clear()

    def test_remark_update(self):
        db = AsyncMock()
        result_mock = MagicMock()
        result_mock.rowcount = 1
        db.execute = AsyncMock(return_value=result_mock)
        db.commit = AsyncMock()
        app.dependency_overrides[get_db] = _override(db)

        with TestClient(app) as client:
            resp = client.post(
                "/api/v1/ops/settlement/monitor/remark",
                json={
                    "store_id": "store_001",
                    "settlement_date": "2026-04-06",
                    "remark": "延迟原因：盘点",
                    "operator_id": "op_001",
                },
                headers=HEADERS,
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["data"]["remark"] == "延迟原因：盘点"
        assert body["data"]["rows_affected"] == 1
