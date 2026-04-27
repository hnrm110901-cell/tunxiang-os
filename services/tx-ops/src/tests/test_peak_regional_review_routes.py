"""高峰值守 / 区域追踪 / D8复盘 路由层测试（共 21 个测试）

覆盖范围：
  peak_routes.py   (prefix=/api/v1/peak)     — 5 端点
  regional_routes.py (prefix=/api/v1/regional) — 7 端点
  review_routes.py   (prefix=/api/v1/review)   — 10 端点（选 9）

技术约束：
  - sys.modules 存根注入，隔离 shared.ontology + sqlalchemy + 各服务模块
  - app.dependency_overrides[get_db] 覆盖数据库依赖
  - X-Tenant-ID header 必须传递（Header(...)）
"""

from __future__ import annotations

import sys
import types
import uuid
from typing import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  sys.modules 存根注入
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def _ensure_stub(module_path: str, attrs: dict | None = None) -> types.ModuleType:
    if module_path not in sys.modules:
        mod = types.ModuleType(module_path)
        if attrs:
            for k, v in attrs.items():
                setattr(mod, k, v)
        sys.modules[module_path] = mod
    return sys.modules[module_path]


# shared.ontology
_ensure_stub("shared")
_ensure_stub("shared.ontology")
_ensure_stub("shared.ontology.src")
_db_mod = _ensure_stub("shared.ontology.src.database")
if not hasattr(_db_mod, "get_db"):

    async def _placeholder_get_db():  # pragma: no cover
        yield None

    _db_mod.get_db = _placeholder_get_db

# sqlalchemy 存根（路由文件有 AsyncSession type hint）
_ensure_stub("sqlalchemy")
_ensure_stub("sqlalchemy.ext")
_ensure_stub("sqlalchemy.ext.asyncio")
if not hasattr(sys.modules["sqlalchemy.ext.asyncio"], "AsyncSession"):
    sys.modules["sqlalchemy.ext.asyncio"].AsyncSession = MagicMock  # type: ignore[attr-defined]

# structlog
if "structlog" not in sys.modules:
    _sl = types.ModuleType("structlog")
    _sl.get_logger = MagicMock(return_value=MagicMock())  # type: ignore[attr-defined]
    sys.modules["structlog"] = _sl

# pydantic（如已安装则跳过）
if "pydantic" not in sys.modules:
    _pydantic = types.ModuleType("pydantic")
    _pydantic.BaseModel = object  # type: ignore[attr-defined]
    _pydantic.Field = MagicMock(return_value=None)  # type: ignore[attr-defined]
    sys.modules["pydantic"] = _pydantic

# ── 服务层存根（内联 import 预占位）─────────────────────────────────────────────
_ensure_stub("src")
_ensure_stub("src.services")

# peak_management
_peak_svc = _ensure_stub("src.services.peak_management")
_peak_svc.detect_peak = AsyncMock(return_value={"is_peak": True, "occupancy_rate": 0.85})
_peak_svc.get_dept_load_monitor = AsyncMock(return_value={"depts": []})
_peak_svc.suggest_staff_dispatch = AsyncMock(return_value={"suggestions": []})
_peak_svc.get_queue_pressure = AsyncMock(return_value={"queue_count": 5, "pressure": "medium"})
_peak_svc.handle_peak_event = AsyncMock(return_value={"event_id": "evt-001", "status": "handled"})

# regional_management
_regional_svc = _ensure_stub("src.services.regional_management")
_regional_svc.dispatch_rectification = AsyncMock(return_value={"rectification_id": "rect-001"})
_regional_svc.track_rectification = AsyncMock(return_value={"rectification_id": "rect-001", "status": "in_progress"})
_regional_svc.submit_review = AsyncMock(return_value={"review_id": "rev-001", "result": "pass"})
_regional_svc.get_regional_scorecard = AsyncMock(return_value={"scorecard": []})
_regional_svc.cross_store_benchmark = AsyncMock(return_value={"benchmark": []})
_regional_svc.generate_regional_report = AsyncMock(return_value={"report_id": "rpt-001"})
_regional_svc.get_rectification_archive = AsyncMock(return_value={"items": []})

# review services
_issue_tracker = _ensure_stub("src.services.issue_tracker")
_issue_tracker.create_issue = AsyncMock(return_value={"issue_id": "iss-001"})
_issue_tracker.assign_issue = AsyncMock(return_value={"issue_id": "iss-001", "assignee_id": "u-001"})
_issue_tracker.update_issue_status = AsyncMock(return_value={"issue_id": "iss-001", "status": "resolved"})
_issue_tracker.get_store_issue_board = AsyncMock(return_value={"red": [], "yellow": [], "green": []})

_knowledge_base = _ensure_stub("src.services.knowledge_base")
_knowledge_base.save_case = AsyncMock(return_value={"case_id": "case-001"})
_knowledge_base.search_cases = AsyncMock(return_value={"cases": []})
_knowledge_base.get_sop_suggestions = AsyncMock(return_value={"suggestions": []})

_weekly_review = _ensure_stub("src.services.weekly_review")
_weekly_review.generate_weekly_review = AsyncMock(return_value={"report_id": "wr-001"})

_monthly_review = _ensure_stub("src.services.monthly_review")
_monthly_review.generate_monthly_review = AsyncMock(return_value={"report_id": "mr-001"})
_monthly_review.generate_regional_review = AsyncMock(return_value={"report_id": "rr-001"})

# ── 导入路由 ────────────────────────────────────────────────────────────────────
from shared.ontology.src.database import get_db  # noqa: E402

from ..api.peak_routes import router as peak_router  # noqa: E402
from ..api.regional_routes import router as regional_router  # noqa: E402
from ..api.review_routes import router as review_router  # noqa: E402

# ── FastAPI 应用 ─────────────────────────────────────────────────────────────────
app = FastAPI()
app.include_router(peak_router)
app.include_router(regional_router)
app.include_router(review_router)

# ── 常量 ──────────────────────────────────────────────────────────────────────────
TENANT = str(uuid.uuid4())
STORE = str(uuid.uuid4())
REGION = str(uuid.uuid4())
HEADERS = {"X-Tenant-ID": TENANT}


# ── 辅助 ─────────────────────────────────────────────────────────────────────────


def _override_db(db_mock: AsyncMock):
    async def _dep() -> AsyncGenerator:
        yield db_mock

    return _dep


def _make_db() -> AsyncMock:
    db = AsyncMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    db.execute = AsyncMock(return_value=MagicMock())
    return db


# ══════════════════════════════════════════════════════════════════════════════════
#  peak_routes.py — 高峰值守
# ══════════════════════════════════════════════════════════════════════════════════


class TestPeakDetect:
    """GET /api/v1/peak/stores/{store_id}/detect"""

    def setup_method(self):
        app.dependency_overrides.clear()

    def teardown_method(self):
        app.dependency_overrides.clear()

    def test_detect_peak_success(self):
        """正常检测高峰，返回 ok=True + is_peak 字段。"""
        db = _make_db()
        app.dependency_overrides[get_db] = _override_db(db)
        _peak_svc.detect_peak = AsyncMock(return_value={"is_peak": True, "occupancy_rate": 0.9})

        resp = client_for(app).get(f"/api/v1/peak/stores/{STORE}/detect", headers=HEADERS)
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert "is_peak" in body["data"]

    def test_detect_peak_missing_tenant_header(self):
        """缺少 X-Tenant-ID header → 422 Unprocessable Entity。"""
        db = _make_db()
        app.dependency_overrides[get_db] = _override_db(db)
        resp = client_for(app).get(f"/api/v1/peak/stores/{STORE}/detect")
        assert resp.status_code == 422

    def test_detect_peak_value_error_returns_400(self):
        """服务层抛出 ValueError → 400。"""
        db = _make_db()
        app.dependency_overrides[get_db] = _override_db(db)
        _peak_svc.detect_peak = AsyncMock(side_effect=ValueError("store not found"))
        resp = client_for(app).get(f"/api/v1/peak/stores/{STORE}/detect", headers=HEADERS)
        assert resp.status_code == 400


class TestDeptLoadMonitor:
    """GET /api/v1/peak/stores/{store_id}/dept-load"""

    def setup_method(self):
        app.dependency_overrides.clear()

    def teardown_method(self):
        app.dependency_overrides.clear()

    def test_dept_load_success(self):
        """正常返回档口负载数据。"""
        db = _make_db()
        app.dependency_overrides[get_db] = _override_db(db)
        _peak_svc.get_dept_load_monitor = AsyncMock(return_value={"depts": [{"id": "d1", "load": 0.7}]})
        resp = client_for(app).get(f"/api/v1/peak/stores/{STORE}/dept-load", headers=HEADERS)
        assert resp.status_code == 200
        assert resp.json()["ok"] is True


class TestStaffDispatch:
    """GET /api/v1/peak/stores/{store_id}/staff-dispatch"""

    def setup_method(self):
        app.dependency_overrides.clear()

    def teardown_method(self):
        app.dependency_overrides.clear()

    def test_staff_dispatch_success(self):
        """正常返回加派建议。"""
        db = _make_db()
        app.dependency_overrides[get_db] = _override_db(db)
        _peak_svc.suggest_staff_dispatch = AsyncMock(return_value={"suggestions": [{"role": "服务员", "count": 2}]})
        resp = client_for(app).get(f"/api/v1/peak/stores/{STORE}/staff-dispatch", headers=HEADERS)
        assert resp.status_code == 200
        assert resp.json()["ok"] is True


class TestHandlePeakEvent:
    """POST /api/v1/peak/stores/{store_id}/events"""

    def setup_method(self):
        app.dependency_overrides.clear()

    def teardown_method(self):
        app.dependency_overrides.clear()

    def test_handle_peak_event_success(self):
        """正常处理高峰事件（temp_menu_switch），返回 ok=True。"""
        db = _make_db()
        app.dependency_overrides[get_db] = _override_db(db)
        _peak_svc.handle_peak_event = AsyncMock(return_value={"event_id": "evt-123", "status": "handled"})
        payload = {"event_type": "temp_menu_switch", "params": {"menu_id": "m-001"}}
        resp = client_for(app).post(f"/api/v1/peak/stores/{STORE}/events", json=payload, headers=HEADERS)
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["data"]["event_id"] == "evt-123"

    def test_handle_peak_event_value_error_returns_400(self):
        """服务层抛出 ValueError → 400。"""
        db = _make_db()
        app.dependency_overrides[get_db] = _override_db(db)
        _peak_svc.handle_peak_event = AsyncMock(side_effect=ValueError("invalid event type"))
        payload = {"event_type": "unknown_event"}
        resp = client_for(app).post(f"/api/v1/peak/stores/{STORE}/events", json=payload, headers=HEADERS)
        assert resp.status_code == 400


# ══════════════════════════════════════════════════════════════════════════════════
#  regional_routes.py — 区域追踪与整改
# ══════════════════════════════════════════════════════════════════════════════════


class TestDispatchRectification:
    """POST /api/v1/regional/regions/{region_id}/rectifications"""

    def setup_method(self):
        app.dependency_overrides.clear()

    def teardown_method(self):
        app.dependency_overrides.clear()

    def test_dispatch_rectification_success(self):
        """正常派发整改，返回 rectification_id。"""
        db = _make_db()
        app.dependency_overrides[get_db] = _override_db(db)
        _regional_svc.dispatch_rectification = AsyncMock(return_value={"rectification_id": "rect-001"})
        payload = {
            "store_id": STORE,
            "issue_id": "iss-001",
            "assignee_id": "u-001",
            "deadline": "2026-04-30",
        }
        resp = client_for(app).post(
            f"/api/v1/regional/regions/{REGION}/rectifications",
            json=payload,
            headers=HEADERS,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["data"]["rectification_id"] == "rect-001"

    def test_dispatch_rectification_value_error_returns_400(self):
        """服务层 ValueError → 400。"""
        db = _make_db()
        app.dependency_overrides[get_db] = _override_db(db)
        _regional_svc.dispatch_rectification = AsyncMock(side_effect=ValueError("region not found"))
        payload = {
            "store_id": STORE,
            "issue_id": "iss-bad",
            "assignee_id": "u-001",
            "deadline": "2026-04-30",
        }
        resp = client_for(app).post(
            f"/api/v1/regional/regions/{REGION}/rectifications",
            json=payload,
            headers=HEADERS,
        )
        assert resp.status_code == 400


class TestTrackRectification:
    """PUT /api/v1/regional/rectifications/{rectification_id}/track"""

    def setup_method(self):
        app.dependency_overrides.clear()

    def teardown_method(self):
        app.dependency_overrides.clear()

    def test_track_rectification_success(self):
        """正常更新整改进度。"""
        db = _make_db()
        app.dependency_overrides[get_db] = _override_db(db)
        _regional_svc.track_rectification = AsyncMock(
            return_value={"rectification_id": "rect-001", "status": "in_progress"}
        )
        payload = {"new_status": "in_progress", "note": "已开始处理"}
        resp = client_for(app).put(
            "/api/v1/regional/rectifications/rect-001/track",
            json=payload,
            headers=HEADERS,
        )
        assert resp.status_code == 200
        assert resp.json()["ok"] is True


class TestRegionalScorecard:
    """GET /api/v1/regional/regions/{region_id}/scorecard"""

    def setup_method(self):
        app.dependency_overrides.clear()

    def teardown_method(self):
        app.dependency_overrides.clear()

    def test_get_regional_scorecard_success(self):
        """正常返回区域评分卡。"""
        db = _make_db()
        app.dependency_overrides[get_db] = _override_db(db)
        _regional_svc.get_regional_scorecard = AsyncMock(
            return_value={"scorecard": [{"store_id": STORE, "grade": "green"}]}
        )
        resp = client_for(app).get(f"/api/v1/regional/regions/{REGION}/scorecard", headers=HEADERS)
        assert resp.status_code == 200
        assert resp.json()["ok"] is True


class TestCrossStoreBenchmark:
    """GET /api/v1/regional/regions/{region_id}/benchmark"""

    def setup_method(self):
        app.dependency_overrides.clear()

    def teardown_method(self):
        app.dependency_overrides.clear()

    def test_cross_store_benchmark_success(self):
        """正常返回跨店对标数据，需要 metric 查询参数。"""
        db = _make_db()
        app.dependency_overrides[get_db] = _override_db(db)
        _regional_svc.cross_store_benchmark = AsyncMock(return_value={"benchmark": []})
        resp = client_for(app).get(
            f"/api/v1/regional/regions/{REGION}/benchmark?metric=revenue",
            headers=HEADERS,
        )
        assert resp.status_code == 200
        assert resp.json()["ok"] is True


# ══════════════════════════════════════════════════════════════════════════════════
#  review_routes.py — D8 复盘经营改进
# ══════════════════════════════════════════════════════════════════════════════════


class TestWeeklyReview:
    """POST /api/v1/review/weekly"""

    def setup_method(self):
        app.dependency_overrides.clear()

    def teardown_method(self):
        app.dependency_overrides.clear()

    def test_create_weekly_review_success(self):
        """正常生成周复盘报告。"""
        db = _make_db()
        app.dependency_overrides[get_db] = _override_db(db)
        _weekly_review.generate_weekly_review = AsyncMock(return_value={"report_id": "wr-001"})
        payload = {"store_id": STORE, "week_start": "2026-03-30"}
        resp = client_for(app).post("/api/v1/review/weekly", json=payload, headers=HEADERS)
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True

    def test_create_weekly_review_invalid_date(self):
        """week_start 格式错误 → 400。"""
        db = _make_db()
        app.dependency_overrides[get_db] = _override_db(db)
        payload = {"store_id": STORE, "week_start": "not-a-date"}
        resp = client_for(app).post("/api/v1/review/weekly", json=payload, headers=HEADERS)
        assert resp.status_code == 400


class TestMonthlyReview:
    """POST /api/v1/review/monthly"""

    def setup_method(self):
        app.dependency_overrides.clear()

    def teardown_method(self):
        app.dependency_overrides.clear()

    def test_create_monthly_review_success(self):
        """正常生成月复盘报告。"""
        db = _make_db()
        app.dependency_overrides[get_db] = _override_db(db)
        _monthly_review.generate_monthly_review = AsyncMock(return_value={"report_id": "mr-001"})
        payload = {"store_id": STORE, "month": "2026-03"}
        resp = client_for(app).post("/api/v1/review/monthly", json=payload, headers=HEADERS)
        assert resp.status_code == 200
        assert resp.json()["ok"] is True


class TestCreateIssue:
    """POST /api/v1/review/issues"""

    def setup_method(self):
        app.dependency_overrides.clear()

    def teardown_method(self):
        app.dependency_overrides.clear()

    def test_create_issue_success(self):
        """正常创建问题，返回 issue_id。"""
        db = _make_db()
        app.dependency_overrides[get_db] = _override_db(db)
        _issue_tracker.create_issue = AsyncMock(return_value={"issue_id": "iss-001"})
        payload = {
            "store_id": STORE,
            "type": "service",
            "description": "服务不及时",
            "reporter_id": "u-001",
            "priority": "high",
        }
        resp = client_for(app).post("/api/v1/review/issues", json=payload, headers=HEADERS)
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["data"]["issue_id"] == "iss-001"


class TestGetIssueBoard:
    """GET /api/v1/review/issues/board/{store_id}"""

    def setup_method(self):
        app.dependency_overrides.clear()

    def teardown_method(self):
        app.dependency_overrides.clear()

    def test_get_issue_board_success(self):
        """正常返回门店问题看板（红黄绿）。"""
        db = _make_db()
        app.dependency_overrides[get_db] = _override_db(db)
        _issue_tracker.get_store_issue_board = AsyncMock(return_value={"red": [], "yellow": ["iss-002"], "green": []})
        resp = client_for(app).get(f"/api/v1/review/issues/board/{STORE}", headers=HEADERS)
        assert resp.status_code == 200
        assert resp.json()["ok"] is True


class TestSopSuggestions:
    """GET /api/v1/review/sop/{store_id}/{issue_type}"""

    def setup_method(self):
        app.dependency_overrides.clear()

    def teardown_method(self):
        app.dependency_overrides.clear()

    def test_get_sop_suggestions_success(self):
        """正常返回 SOP 优化建议。"""
        db = _make_db()
        app.dependency_overrides[get_db] = _override_db(db)
        _knowledge_base.get_sop_suggestions = AsyncMock(
            return_value={"suggestions": [{"sop_id": "s-001", "title": "卫生标准SOP"}]}
        )
        resp = client_for(app).get(f"/api/v1/review/sop/{STORE}/hygiene", headers=HEADERS)
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert "suggestions" in body["data"]


# ── 辅助：每次测试隔离 dependency_overrides ─────────────────────────────────────


def client_for(application: FastAPI) -> TestClient:
    """返回 TestClient，raise_server_exceptions=True（默认）。"""
    return TestClient(application, raise_server_exceptions=True)
