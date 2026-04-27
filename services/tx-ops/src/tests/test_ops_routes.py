"""tx-ops 路由层测试 — 覆盖 ops_routes.py（主路由，之前零测试）

覆盖范围（共 18 个测试）：
  ops_routes.py（/api/v1/daily-ops）— 15 个端点，全覆盖：
    E1 开店准备：
      POST /stores/{id}/opening/checklist      — 正常创建 / ValueError → 400
      PUT  /stores/{id}/opening/checklist/{id}/items/{id} — 正常打勾 / ValueError → 400
      GET  /stores/{id}/opening/status         — 正常返回
      POST /stores/{id}/opening/approve        — 正常放行 / 缺 header → 422
    E2 营业巡航：
      GET  /stores/{id}/cruise/dashboard       — 正常返回
      POST /stores/{id}/cruise/patrol          — 正常记录
    E4 异常处置：
      POST /stores/{id}/exceptions             — 正常上报 / ValueError → 400
      POST /exceptions/{id}/escalate           — 正常升级
      POST /exceptions/{id}/resolve            — 正常关闭
      GET  /stores/{id}/exceptions             — 正常列表
    E5 闭店盘点：
      POST /stores/{id}/closing/checklist      — 正常创建
      POST /stores/{id}/closing/stocktake      — 正常盘点
      POST /stores/{id}/closing/waste          — 正常损耗
      POST /stores/{id}/closing/finalize       — 正常放行 / ValueError → 400
    E7 店长复盘：
      GET  /stores/{id}/review/{date}          — 正常生成
      POST /stores/{id}/review/{date}/actions  — 正常提交
      GET  /stores/{id}/review/history         — 正常列表
      POST /stores/{id}/review/{date}/sign-off — 正常签发

技术约束：
  - sys.modules 存根注入隔离 shared.ontology / 内联服务模块
  - TestClient + app.dependency_overrides[get_db] + AsyncMock side_effect
  - 全部 mock，不需要真实 DB
"""

from __future__ import annotations

import sys
import types
import uuid
from typing import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  sys.modules 存根注入（必须在导入路由前完成）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def _ensure_stub(module_path: str, attrs: dict | None = None) -> types.ModuleType:
    """确保 module_path 在 sys.modules 中存在，返回模块对象。"""
    if module_path not in sys.modules:
        mod = types.ModuleType(module_path)
        if attrs:
            for k, v in attrs.items():
                setattr(mod, k, v)
        sys.modules[module_path] = mod
    return sys.modules[module_path]


# shared.ontology 层
_ensure_stub("shared")
_ensure_stub("shared.ontology")
_ensure_stub("shared.ontology.src")
_db_mod = _ensure_stub("shared.ontology.src.database")
if not hasattr(_db_mod, "get_db"):

    async def _placeholder_get_db():  # pragma: no cover
        yield None

    _db_mod.get_db = _placeholder_get_db

# structlog 存根
if "structlog" not in sys.modules:
    _sl = types.ModuleType("structlog")
    _sl.get_logger = MagicMock(return_value=MagicMock())  # type: ignore[attr-defined]
    sys.modules["structlog"] = _sl

# ── 内联服务模块存根（ops_routes 在函数体内 import，需预占位） ──────────────────
# store_opening
_pkg = _ensure_stub("src")
_ensure_stub("src.services")
_store_opening = _ensure_stub("src.services.store_opening")
_store_opening.create_opening_checklist = AsyncMock()
_store_opening.check_item = AsyncMock()
_store_opening.get_opening_status = MagicMock()
_store_opening.approve_opening = AsyncMock()

# cruise_monitor
_cruise = _ensure_stub("src.services.cruise_monitor")
_cruise.get_realtime_dashboard = AsyncMock()
_cruise.record_patrol = AsyncMock()

# exception_workflow
_exc_wf = _ensure_stub("src.services.exception_workflow")
_exc_wf.report_exception = AsyncMock()
_exc_wf.escalate_exception = AsyncMock()
_exc_wf.resolve_exception = AsyncMock()
_exc_wf.get_open_exceptions = AsyncMock()

# store_closing
_closing = _ensure_stub("src.services.store_closing")
_closing.create_closing_checklist = AsyncMock()
_closing.record_closing_stocktake = AsyncMock()
_closing.record_waste_report = AsyncMock()
_closing.finalize_closing = AsyncMock()

# daily_review
_review = _ensure_stub("src.services.daily_review")
_review.generate_daily_review = AsyncMock()
_review.submit_action_items = AsyncMock()
_review.get_review_history = AsyncMock()
_review.sign_off_review = AsyncMock()

# ── 导入路由 ────────────────────────────────────────────────────────────────────
from shared.ontology.src.database import get_db  # noqa: E402

from ..api.ops_routes import router as ops_router  # noqa: E402

# ── FastAPI 应用 ─────────────────────────────────────────────────────────────────
app = FastAPI()
app.include_router(ops_router)

# ── 常量 ──────────────────────────────────────────────────────────────────────────
TENANT = str(uuid.uuid4())
STORE = str(uuid.uuid4())
HEADERS = {"X-Tenant-ID": TENANT}


# ── 辅助 ─────────────────────────────────────────────────────────────────────────


def _override(db_mock: AsyncMock):
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
#  E1 — 开店准备
# ══════════════════════════════════════════════════════════════════════════════════


class TestOpeningChecklist:
    """POST /api/v1/daily-ops/stores/{store_id}/opening/checklist"""

    def setup_method(self):
        app.dependency_overrides.clear()

    def teardown_method(self):
        app.dependency_overrides.clear()

    def test_create_opening_checklist_success(self):
        """正常创建开店检查单 → 200，ok=True，含 checklist_id。"""
        db = _make_db()
        app.dependency_overrides[get_db] = _override(db)

        expected = {"checklist_id": "cl-001", "store_id": STORE, "items": []}

        with patch(
            "src.services.store_opening.create_opening_checklist",
            new=AsyncMock(return_value=expected),
        ):
            # ops_routes 做内联 import：需 patch 在函数体的命名空间下
            import src.api.ops_routes as _mod

            with patch.object(_mod, "__builtins__", __builtins__):
                # 改为 patch 整个服务模块引用
                pass

        # 直接 patch sys.modules 中已注入的存根
        _store_opening.create_opening_checklist = AsyncMock(return_value=expected)

        with TestClient(app) as client:
            resp = client.post(
                f"/api/v1/daily-ops/stores/{STORE}/opening/checklist",
                headers=HEADERS,
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["data"]["checklist_id"] == "cl-001"

    def test_create_opening_checklist_value_error_returns_400(self):
        """服务层抛出 ValueError → 400。"""
        db = _make_db()
        app.dependency_overrides[get_db] = _override(db)

        _store_opening.create_opening_checklist = AsyncMock(side_effect=ValueError("今日检查单已存在"))

        with TestClient(app) as client:
            resp = client.post(
                f"/api/v1/daily-ops/stores/{STORE}/opening/checklist",
                headers=HEADERS,
            )

        assert resp.status_code == 400
        assert "今日检查单已存在" in resp.json()["detail"]


class TestCheckOpeningItem:
    """PUT /api/v1/daily-ops/stores/{store_id}/opening/checklist/{cl_id}/items/{item_id}"""

    def setup_method(self):
        app.dependency_overrides.clear()

    def teardown_method(self):
        app.dependency_overrides.clear()

    def test_check_item_success(self):
        """正常打勾 → 200，ok=True。"""
        db = _make_db()
        app.dependency_overrides[get_db] = _override(db)

        expected = {"item_id": "item-1", "status": "checked", "result": "pass"}
        _store_opening.check_item = AsyncMock(return_value=expected)

        with TestClient(app) as client:
            resp = client.put(
                f"/api/v1/daily-ops/stores/{STORE}/opening/checklist/cl-001/items/item-1",
                json={"item_id": "item-1", "status": "checked", "result": "pass"},
                headers=HEADERS,
            )

        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    def test_check_item_invalid_status_422(self):
        """非法 status 字段（非 checked/skipped）→ 422 校验失败。"""
        db = _make_db()
        app.dependency_overrides[get_db] = _override(db)

        with TestClient(app) as client:
            resp = client.put(
                f"/api/v1/daily-ops/stores/{STORE}/opening/checklist/cl-001/items/item-1",
                json={"item_id": "item-1", "status": "unknown", "result": "pass"},
                headers=HEADERS,
            )

        assert resp.status_code == 422


class TestOpeningStatus:
    """GET /api/v1/daily-ops/stores/{store_id}/opening/status"""

    def setup_method(self):
        app.dependency_overrides.clear()

    def teardown_method(self):
        app.dependency_overrides.clear()

    def test_get_opening_status_success(self):
        """正常返回开店进度 → 200，ok=True。"""
        db = _make_db()
        app.dependency_overrides[get_db] = _override(db)

        expected = {"store_id": STORE, "can_open": True, "completion_rate": 1.0}
        _store_opening.get_opening_status = MagicMock(return_value=expected)

        with TestClient(app) as client:
            resp = client.get(
                f"/api/v1/daily-ops/stores/{STORE}/opening/status",
                headers=HEADERS,
            )

        assert resp.status_code == 200
        assert resp.json()["ok"] is True
        assert resp.json()["data"]["can_open"] is True


class TestApproveOpening:
    """POST /api/v1/daily-ops/stores/{store_id}/opening/approve"""

    def setup_method(self):
        app.dependency_overrides.clear()

    def teardown_method(self):
        app.dependency_overrides.clear()

    def test_approve_opening_success(self):
        """店长放行 → 200，ok=True。"""
        db = _make_db()
        app.dependency_overrides[get_db] = _override(db)

        expected = {"store_id": STORE, "approved_by": "mgr-001", "status": "open"}
        _store_opening.approve_opening = AsyncMock(return_value=expected)

        with TestClient(app) as client:
            resp = client.post(
                f"/api/v1/daily-ops/stores/{STORE}/opening/approve",
                json={"manager_id": "mgr-001"},
                headers=HEADERS,
            )

        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    def test_approve_opening_missing_header_422(self):
        """缺少 X-Tenant-ID header → 422。"""
        with TestClient(app) as client:
            resp = client.post(
                f"/api/v1/daily-ops/stores/{STORE}/opening/approve",
                json={"manager_id": "mgr-001"},
            )

        assert resp.status_code == 422


# ══════════════════════════════════════════════════════════════════════════════════
#  E2 — 营业巡航
# ══════════════════════════════════════════════════════════════════════════════════


class TestCruiseDashboard:
    """GET /api/v1/daily-ops/stores/{store_id}/cruise/dashboard"""

    def setup_method(self):
        app.dependency_overrides.clear()

    def teardown_method(self):
        app.dependency_overrides.clear()

    def test_get_cruise_dashboard_success(self):
        """实时经营看板正常返回 → 200。"""
        db = _make_db()
        app.dependency_overrides[get_db] = _override(db)

        expected = {"store_id": STORE, "table_occupancy": 0.85, "alerts": []}
        _cruise.get_realtime_dashboard = AsyncMock(return_value=expected)

        with TestClient(app) as client:
            resp = client.get(
                f"/api/v1/daily-ops/stores/{STORE}/cruise/dashboard",
                headers=HEADERS,
            )

        assert resp.status_code == 200
        assert resp.json()["ok"] is True
        assert resp.json()["data"]["table_occupancy"] == 0.85


class TestRecordPatrol:
    """POST /api/v1/daily-ops/stores/{store_id}/cruise/patrol"""

    def setup_method(self):
        app.dependency_overrides.clear()

    def teardown_method(self):
        app.dependency_overrides.clear()

    def test_record_patrol_success(self):
        """记录巡台发现 → 200，ok=True。"""
        db = _make_db()
        app.dependency_overrides[get_db] = _override(db)

        expected = {"patrol_id": "pt-001", "findings_count": 2}
        _cruise.record_patrol = AsyncMock(return_value=expected)

        with TestClient(app) as client:
            resp = client.post(
                f"/api/v1/daily-ops/stores/{STORE}/cruise/patrol",
                json={
                    "operator_id": "emp-001",
                    "findings": [
                        {"table": "T01", "issue": "empty_cup"},
                        {"table": "T03", "issue": "dirty_menu"},
                    ],
                },
                headers=HEADERS,
            )

        assert resp.status_code == 200
        assert resp.json()["ok"] is True


# ══════════════════════════════════════════════════════════════════════════════════
#  E4 — 异常处置
# ══════════════════════════════════════════════════════════════════════════════════


class TestReportException:
    """POST /api/v1/daily-ops/stores/{store_id}/exceptions"""

    def setup_method(self):
        app.dependency_overrides.clear()

    def teardown_method(self):
        app.dependency_overrides.clear()

    def test_report_exception_success(self):
        """正常上报异常 → 200，含 exception_id。"""
        db = _make_db()
        app.dependency_overrides[get_db] = _override(db)

        expected = {"exception_id": "exc-001", "status": "open"}
        _exc_wf.report_exception = AsyncMock(return_value=expected)

        with TestClient(app) as client:
            resp = client.post(
                f"/api/v1/daily-ops/stores/{STORE}/exceptions",
                json={
                    "type": "equipment_failure",
                    "detail": {"device": "dishwasher"},
                    "reporter_id": "emp-010",
                },
                headers=HEADERS,
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["data"]["exception_id"] == "exc-001"

    def test_report_exception_value_error_400(self):
        """服务层抛 ValueError（如类型不合法）→ 400。"""
        db = _make_db()
        app.dependency_overrides[get_db] = _override(db)

        _exc_wf.report_exception = AsyncMock(side_effect=ValueError("未知异常类型"))

        with TestClient(app) as client:
            resp = client.post(
                f"/api/v1/daily-ops/stores/{STORE}/exceptions",
                json={"type": "bad_type", "reporter_id": "emp-010"},
                headers=HEADERS,
            )

        assert resp.status_code == 400
        assert "未知异常类型" in resp.json()["detail"]


class TestGetOpenExceptions:
    """GET /api/v1/daily-ops/stores/{store_id}/exceptions"""

    def setup_method(self):
        app.dependency_overrides.clear()

    def teardown_method(self):
        app.dependency_overrides.clear()

    def test_get_open_exceptions_returns_list(self):
        """未关闭异常列表 → 200，data 为 list。"""
        db = _make_db()
        app.dependency_overrides[get_db] = _override(db)

        expected = [{"exception_id": "exc-001"}, {"exception_id": "exc-002"}]
        _exc_wf.get_open_exceptions = AsyncMock(return_value=expected)

        with TestClient(app) as client:
            resp = client.get(
                f"/api/v1/daily-ops/stores/{STORE}/exceptions",
                headers=HEADERS,
            )

        assert resp.status_code == 200
        assert resp.json()["ok"] is True
        assert len(resp.json()["data"]) == 2


class TestEscalateException:
    """POST /api/v1/daily-ops/exceptions/{exception_id}/escalate"""

    def setup_method(self):
        app.dependency_overrides.clear()

    def teardown_method(self):
        app.dependency_overrides.clear()

    def test_escalate_success(self):
        """升级异常到指定级别 → 200。"""
        db = _make_db()
        app.dependency_overrides[get_db] = _override(db)

        expected = {"exception_id": "exc-001", "level": 2}
        _exc_wf.escalate_exception = AsyncMock(return_value=expected)

        with TestClient(app) as client:
            resp = client.post(
                "/api/v1/daily-ops/exceptions/exc-001/escalate",
                json={"to_level": 2},
                headers=HEADERS,
            )

        assert resp.status_code == 200
        assert resp.json()["data"]["level"] == 2


class TestResolveException:
    """POST /api/v1/daily-ops/exceptions/{exception_id}/resolve"""

    def setup_method(self):
        app.dependency_overrides.clear()

    def teardown_method(self):
        app.dependency_overrides.clear()

    def test_resolve_success(self):
        """关闭异常 → 200，status=resolved。"""
        db = _make_db()
        app.dependency_overrides[get_db] = _override(db)

        expected = {"exception_id": "exc-001", "status": "resolved"}
        _exc_wf.resolve_exception = AsyncMock(return_value=expected)

        with TestClient(app) as client:
            resp = client.post(
                "/api/v1/daily-ops/exceptions/exc-001/resolve",
                json={
                    "resolution": {"action": "repaired"},
                    "resolver_id": "mgr-001",
                },
                headers=HEADERS,
            )

        assert resp.status_code == 200
        assert resp.json()["data"]["status"] == "resolved"


# ══════════════════════════════════════════════════════════════════════════════════
#  E5 — 闭店盘点
# ══════════════════════════════════════════════════════════════════════════════════


class TestClosingChecklist:
    """POST /api/v1/daily-ops/stores/{store_id}/closing/checklist"""

    def setup_method(self):
        app.dependency_overrides.clear()

    def teardown_method(self):
        app.dependency_overrides.clear()

    def test_create_closing_checklist_success(self):
        """生成闭店检查单 → 200，含 checklist_id。"""
        db = _make_db()
        app.dependency_overrides[get_db] = _override(db)

        expected = {"checklist_id": "cl-closing-001", "items": []}
        _closing.create_closing_checklist = AsyncMock(return_value=expected)

        with TestClient(app) as client:
            resp = client.post(
                f"/api/v1/daily-ops/stores/{STORE}/closing/checklist",
                headers=HEADERS,
            )

        assert resp.status_code == 200
        assert resp.json()["data"]["checklist_id"] == "cl-closing-001"


class TestRecordStocktake:
    """POST /api/v1/daily-ops/stores/{store_id}/closing/stocktake"""

    def setup_method(self):
        app.dependency_overrides.clear()

    def teardown_method(self):
        app.dependency_overrides.clear()

    def test_stocktake_success(self):
        """原料盘点正常提交 → 200。"""
        db = _make_db()
        app.dependency_overrides[get_db] = _override(db)

        expected = {"variance_count": 1, "total_items": 3}
        _closing.record_closing_stocktake = AsyncMock(return_value=expected)

        items = [
            {"ingredient_id": "ing-1", "name": "鸡腿", "expected_qty": 10.0, "actual_qty": 9.5, "unit": "kg"},
            {"ingredient_id": "ing-2", "name": "生菜", "expected_qty": 5.0, "actual_qty": 5.0, "unit": "kg"},
            {"ingredient_id": "ing-3", "name": "豆腐", "expected_qty": 8.0, "actual_qty": 7.0, "unit": "kg"},
        ]

        with TestClient(app) as client:
            resp = client.post(
                f"/api/v1/daily-ops/stores/{STORE}/closing/stocktake",
                json=items,
                headers=HEADERS,
            )

        assert resp.status_code == 200
        assert resp.json()["ok"] is True


class TestRecordWaste:
    """POST /api/v1/daily-ops/stores/{store_id}/closing/waste"""

    def setup_method(self):
        app.dependency_overrides.clear()

    def teardown_method(self):
        app.dependency_overrides.clear()

    def test_waste_report_success(self):
        """损耗上报正常提交 → 200。"""
        db = _make_db()
        app.dependency_overrides[get_db] = _override(db)

        expected = {"waste_id": "waste-001", "total_cost_fen": 3500}
        _closing.record_waste_report = AsyncMock(return_value=expected)

        items = [
            {"ingredient_id": "ing-1", "name": "猪肉", "qty": 0.5, "unit": "kg", "reason": "过期", "cost_fen": 3500}
        ]

        with TestClient(app) as client:
            resp = client.post(
                f"/api/v1/daily-ops/stores/{STORE}/closing/waste",
                json=items,
                headers=HEADERS,
            )

        assert resp.status_code == 200
        assert resp.json()["data"]["waste_id"] == "waste-001"


class TestFinalizeClosing:
    """POST /api/v1/daily-ops/stores/{store_id}/closing/finalize"""

    def setup_method(self):
        app.dependency_overrides.clear()

    def teardown_method(self):
        app.dependency_overrides.clear()

    def test_finalize_closing_success(self):
        """闭店放行 → 200，status=closed。"""
        db = _make_db()
        app.dependency_overrides[get_db] = _override(db)

        expected = {"store_id": STORE, "status": "closed", "closed_by": "mgr-001"}
        _closing.finalize_closing = AsyncMock(return_value=expected)

        with TestClient(app) as client:
            resp = client.post(
                f"/api/v1/daily-ops/stores/{STORE}/closing/finalize",
                json={"manager_id": "mgr-001"},
                headers=HEADERS,
            )

        assert resp.status_code == 200
        assert resp.json()["data"]["status"] == "closed"

    def test_finalize_closing_error_400(self):
        """检查项未完成时抛 ValueError → 400。"""
        db = _make_db()
        app.dependency_overrides[get_db] = _override(db)

        _closing.finalize_closing = AsyncMock(side_effect=ValueError("闭店检查单未完成"))

        with TestClient(app) as client:
            resp = client.post(
                f"/api/v1/daily-ops/stores/{STORE}/closing/finalize",
                json={"manager_id": "mgr-001"},
                headers=HEADERS,
            )

        assert resp.status_code == 400
        assert "闭店检查单未完成" in resp.json()["detail"]


# ══════════════════════════════════════════════════════════════════════════════════
#  E7 — 店长复盘
# ══════════════════════════════════════════════════════════════════════════════════


class TestDailyReview:
    """GET /api/v1/daily-ops/stores/{store_id}/review/{review_date}"""

    def setup_method(self):
        app.dependency_overrides.clear()

    def teardown_method(self):
        app.dependency_overrides.clear()

    def test_get_daily_review_success(self):
        """正常生成日度复盘 → 200，含 review_date。"""
        db = _make_db()
        app.dependency_overrides[get_db] = _override(db)

        expected = {
            "store_id": STORE,
            "review_date": "2026-04-04",
            "revenue_fen": 580000,
            "issues": [],
        }
        _review.generate_daily_review = AsyncMock(return_value=expected)

        with TestClient(app) as client:
            resp = client.get(
                f"/api/v1/daily-ops/stores/{STORE}/review/2026-04-04",
                headers=HEADERS,
            )

        assert resp.status_code == 200
        assert resp.json()["data"]["review_date"] == "2026-04-04"


class TestSubmitActionItems:
    """POST /api/v1/daily-ops/stores/{store_id}/review/{review_date}/actions"""

    def setup_method(self):
        app.dependency_overrides.clear()

    def teardown_method(self):
        app.dependency_overrides.clear()

    def test_submit_action_items_success(self):
        """提交次日行动项 → 200，含 action_count。"""
        db = _make_db()
        app.dependency_overrides[get_db] = _override(db)

        expected = {"action_count": 2, "manager_id": "mgr-001"}
        _review.submit_action_items = AsyncMock(return_value=expected)

        payload = {
            "items": [
                {
                    "title": "增加备货",
                    "description": "周末客流预计增加20%",
                    "assignee_id": "emp-002",
                    "priority": "high",
                    "due_date": "2026-04-05",
                },
                {
                    "title": "维修洗碗机",
                    "description": "故障待修",
                    "assignee_id": "emp-003",
                    "priority": "medium",
                    "due_date": "2026-04-05",
                },
            ],
            "manager_id": "mgr-001",
        }

        with TestClient(app) as client:
            resp = client.post(
                f"/api/v1/daily-ops/stores/{STORE}/review/2026-04-04/actions",
                json=payload,
                headers=HEADERS,
            )

        assert resp.status_code == 200
        assert resp.json()["data"]["action_count"] == 2


class TestReviewHistory:
    """GET /api/v1/daily-ops/stores/{store_id}/review/history"""

    def setup_method(self):
        app.dependency_overrides.clear()

    def teardown_method(self):
        app.dependency_overrides.clear()

    def test_review_history_default_days(self):
        """默认 days=7 返回历史复盘列表 → 200。"""
        db = _make_db()
        app.dependency_overrides[get_db] = _override(db)

        expected = [{"review_date": "2026-04-04"}, {"review_date": "2026-04-03"}]
        _review.get_review_history = AsyncMock(return_value=expected)

        with TestClient(app) as client:
            resp = client.get(
                f"/api/v1/daily-ops/stores/{STORE}/review/history",
                headers=HEADERS,
            )

        assert resp.status_code == 200
        assert len(resp.json()["data"]) == 2

    def test_review_history_custom_days(self):
        """自定义 days=30 → 200，ok=True。"""
        db = _make_db()
        app.dependency_overrides[get_db] = _override(db)

        _review.get_review_history = AsyncMock(return_value=[])

        with TestClient(app) as client:
            resp = client.get(
                f"/api/v1/daily-ops/stores/{STORE}/review/history",
                params={"days": 30},
                headers=HEADERS,
            )

        assert resp.status_code == 200
        assert resp.json()["ok"] is True


class TestSignOffReview:
    """POST /api/v1/daily-ops/stores/{store_id}/review/{review_date}/sign-off"""

    def setup_method(self):
        app.dependency_overrides.clear()

    def teardown_method(self):
        app.dependency_overrides.clear()

    def test_sign_off_success(self):
        """店长签发复盘 → 200，signed=True。"""
        db = _make_db()
        app.dependency_overrides[get_db] = _override(db)

        expected = {"review_date": "2026-04-04", "signed": True, "manager_id": "mgr-001"}
        _review.sign_off_review = AsyncMock(return_value=expected)

        with TestClient(app) as client:
            resp = client.post(
                f"/api/v1/daily-ops/stores/{STORE}/review/2026-04-04/sign-off",
                json={"manager_id": "mgr-001"},
                headers=HEADERS,
            )

        assert resp.status_code == 200
        assert resp.json()["data"]["signed"] is True
