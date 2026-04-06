"""revenue_aggregation_routes.py + approval_callback_routes.py 路由测试

覆盖端点（revenue_aggregation_routes.py — 3个）：
  GET /api/v1/finance/revenue/daily-fast
  GET /api/v1/finance/revenue/range
  GET /api/v1/finance/revenue/payment-reconcile

覆盖端点（approval_callback_routes.py — 1个）：
  POST /api/v1/credit/agreements/{id}/approval-callback

测试用例总计：19个
"""
import sys
import types
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

# ── Mock shared.ontology.src.database ──────────────────────────────────────
_shared = types.ModuleType("shared")
_shared_ontology = types.ModuleType("shared.ontology")
_shared_ontology_src = types.ModuleType("shared.ontology.src")
_shared_ontology_src_db = types.ModuleType("shared.ontology.src.database")

async def _fake_get_db_with_tenant(tenant_id):
    yield None

_shared_ontology_src_db.get_db_with_tenant = _fake_get_db_with_tenant

sys.modules.setdefault("shared", _shared)
sys.modules.setdefault("shared.ontology", _shared_ontology)
sys.modules.setdefault("shared.ontology.src", _shared_ontology_src)
sys.modules.setdefault("shared.ontology.src.database", _shared_ontology_src_db)

# ── Mock structlog ──────────────────────────────────────────────────────────
_structlog = types.ModuleType("structlog")

class _FakeLogger:
    def info(self, *a, **kw): pass
    def error(self, *a, **kw): pass
    def warning(self, *a, **kw): pass
    def debug(self, *a, **kw): pass

_structlog.get_logger = lambda *a, **kw: _FakeLogger()
sys.modules.setdefault("structlog", _structlog)

# ── Mock services.revenue_aggregation_service ───────────────────────────────
_svc_mod = types.ModuleType("services")
_svc_ra_mod = types.ModuleType("services.revenue_aggregation_service")

class _FakeDailyReport:
    def to_dict(self):
        return {
            "gross_revenue_fen": 100000,
            "net_revenue_fen": 95000,
            "discount_fen": 5000,
            "refund_fen": 0,
            "transaction_count": 42,
            "avg_order_fen": 2261,
            "payment_breakdown": {},
            "hourly_distribution": {},
        }

class _FakeRangeReport:
    def to_dict(self):
        return {
            "summary": {"total_net_fen": 500000},
            "series": [],
        }

class _FakePaymentReport:
    def to_dict(self):
        return {
            "payment_methods": [],
            "total_orders": 100,
            "total_net_fen": 250000,
        }

class _FakeRevenueService:
    async def get_daily_revenue_fast(self, tenant_id, store_id, query_date, db):
        return _FakeDailyReport()

    async def get_revenue_range_report(self, tenant_id, store_id, s_date, e_date, granularity, db):
        return _FakeRangeReport()

    async def get_payment_reconciliation(self, tenant_id, store_id, s_date, e_date, db):
        return _FakePaymentReport()

_svc_ra_mod.RevenueAggregationService = _FakeRevenueService
sys.modules.setdefault("services", _svc_mod)
sys.modules.setdefault("services.revenue_aggregation_service", _svc_ra_mod)

# ── Mock shared.events.src.emitter ──────────────────────────────────────────
_shared_events = types.ModuleType("shared.events")
_shared_events_src = types.ModuleType("shared.events.src")
_shared_events_src_emitter = types.ModuleType("shared.events.src.emitter")

async def _fake_emit_event(**kwargs):
    pass

_shared_events_src_emitter.emit_event = _fake_emit_event
sys.modules.setdefault("shared.events", _shared_events)
sys.modules.setdefault("shared.events.src", _shared_events_src)
sys.modules.setdefault("shared.events.src.emitter", _shared_events_src_emitter)

# ── Now import the route modules ─────────────────────────────────────────────
import importlib.util
import pathlib

_api_base = pathlib.Path(__file__).parent.parent / "api"

# Load revenue_aggregation_routes
_rev_spec = importlib.util.spec_from_file_location(
    "revenue_aggregation_routes", _api_base / "revenue_aggregation_routes.py"
)
_rev_mod = importlib.util.module_from_spec(_rev_spec)
_rev_spec.loader.exec_module(_rev_mod)

# Load approval_callback_routes
_cb_spec = importlib.util.spec_from_file_location(
    "approval_callback_routes", _api_base / "approval_callback_routes.py"
)
_cb_mod = importlib.util.module_from_spec(_cb_spec)
_cb_spec.loader.exec_module(_cb_mod)

from fastapi import FastAPI
from fastapi.testclient import TestClient

# ── Helpers ──────────────────────────────────────────────────────────────────
_TENANT_ID = str(uuid.uuid4())
_STORE_ID = str(uuid.uuid4())
_AGREEMENT_ID = str(uuid.uuid4())
_APPROVER_ID = str(uuid.uuid4())
_HEADERS = {"X-Tenant-ID": _TENANT_ID}

def _make_rev_client(svc_override=None):
    app = FastAPI()
    app.include_router(_rev_mod.router)
    # Override dependency
    svc = svc_override if svc_override else _FakeRevenueService()
    app.dependency_overrides[_rev_mod._get_tenant_db] = lambda: None
    # patch _service on the module
    return TestClient(app, raise_server_exceptions=False)

def _make_cb_client(db_override=None):
    app = FastAPI()
    app.include_router(_cb_mod.router)
    if db_override is not None:
        app.dependency_overrides[_cb_mod._get_tenant_db] = lambda: db_override
    return TestClient(app, raise_server_exceptions=False)


# ══════════════════════════════════════════════════════════════════════════════
# revenue_aggregation_routes 测试
# ══════════════════════════════════════════════════════════════════════════════

class TestDailyRevenueFast:
    """GET /api/v1/finance/revenue/daily-fast"""

    def test_valid_request_returns_200(self):
        client = _make_rev_client()
        with patch.object(_rev_mod, "_service", _FakeRevenueService()):
            resp = client.get(
                "/api/v1/finance/revenue/daily-fast",
                params={"store_id": _STORE_ID, "biz_date": "2026-04-06"},
                headers=_HEADERS,
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert "data" in data

    def test_today_keyword_accepted(self):
        client = _make_rev_client()
        with patch.object(_rev_mod, "_service", _FakeRevenueService()):
            resp = client.get(
                "/api/v1/finance/revenue/daily-fast",
                params={"store_id": _STORE_ID, "biz_date": "today"},
                headers=_HEADERS,
            )
        assert resp.status_code == 200

    def test_invalid_store_uuid_returns_400(self):
        client = _make_rev_client()
        with patch.object(_rev_mod, "_service", _FakeRevenueService()):
            resp = client.get(
                "/api/v1/finance/revenue/daily-fast",
                params={"store_id": "not-a-uuid", "biz_date": "2026-04-06"},
                headers=_HEADERS,
            )
        assert resp.status_code == 400

    def test_invalid_biz_date_returns_400(self):
        client = _make_rev_client()
        with patch.object(_rev_mod, "_service", _FakeRevenueService()):
            resp = client.get(
                "/api/v1/finance/revenue/daily-fast",
                params={"store_id": _STORE_ID, "biz_date": "not-a-date"},
                headers=_HEADERS,
            )
        assert resp.status_code == 400

    def test_missing_tenant_header_returns_422(self):
        client = _make_rev_client()
        with patch.object(_rev_mod, "_service", _FakeRevenueService()):
            resp = client.get(
                "/api/v1/finance/revenue/daily-fast",
                params={"store_id": _STORE_ID},
            )
        assert resp.status_code == 422

    def test_service_db_error_returns_500(self):
        from sqlalchemy.exc import SQLAlchemyError

        class _ErrService:
            async def get_daily_revenue_fast(self, *a, **kw):
                raise SQLAlchemyError("db down")

        client = _make_rev_client()
        with patch.object(_rev_mod, "_service", _ErrService()):
            resp = client.get(
                "/api/v1/finance/revenue/daily-fast",
                params={"store_id": _STORE_ID, "biz_date": "2026-04-06"},
                headers=_HEADERS,
            )
        assert resp.status_code == 500


class TestRevenueRange:
    """GET /api/v1/finance/revenue/range"""

    def test_valid_range_returns_200(self):
        client = _make_rev_client()
        with patch.object(_rev_mod, "_service", _FakeRevenueService()):
            resp = client.get(
                "/api/v1/finance/revenue/range",
                params={
                    "store_id": _STORE_ID,
                    "start_date": "2026-04-01",
                    "end_date": "2026-04-06",
                    "granularity": "day",
                },
                headers=_HEADERS,
            )
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    def test_start_after_end_returns_400(self):
        client = _make_rev_client()
        with patch.object(_rev_mod, "_service", _FakeRevenueService()):
            resp = client.get(
                "/api/v1/finance/revenue/range",
                params={
                    "store_id": _STORE_ID,
                    "start_date": "2026-04-10",
                    "end_date": "2026-04-01",
                },
                headers=_HEADERS,
            )
        assert resp.status_code == 400
        assert "start_date" in resp.json()["detail"].lower() or "不能晚于" in resp.json()["detail"]

    def test_range_exceeds_366_days_returns_400(self):
        client = _make_rev_client()
        with patch.object(_rev_mod, "_service", _FakeRevenueService()):
            resp = client.get(
                "/api/v1/finance/revenue/range",
                params={
                    "store_id": _STORE_ID,
                    "start_date": "2025-01-01",
                    "end_date": "2026-04-06",
                },
                headers=_HEADERS,
            )
        assert resp.status_code == 400
        assert "366" in resp.json()["detail"]

    def test_week_granularity_accepted(self):
        client = _make_rev_client()
        with patch.object(_rev_mod, "_service", _FakeRevenueService()):
            resp = client.get(
                "/api/v1/finance/revenue/range",
                params={
                    "store_id": _STORE_ID,
                    "start_date": "2026-03-01",
                    "end_date": "2026-04-06",
                    "granularity": "week",
                },
                headers=_HEADERS,
            )
        assert resp.status_code == 200


class TestPaymentReconciliation:
    """GET /api/v1/finance/revenue/payment-reconcile"""

    def test_valid_request_returns_200(self):
        client = _make_rev_client()
        with patch.object(_rev_mod, "_service", _FakeRevenueService()):
            resp = client.get(
                "/api/v1/finance/revenue/payment-reconcile",
                params={
                    "store_id": _STORE_ID,
                    "start_date": "2026-04-01",
                    "end_date": "2026-04-06",
                },
                headers=_HEADERS,
            )
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    def test_range_exceeds_93_days_returns_400(self):
        client = _make_rev_client()
        with patch.object(_rev_mod, "_service", _FakeRevenueService()):
            resp = client.get(
                "/api/v1/finance/revenue/payment-reconcile",
                params={
                    "store_id": _STORE_ID,
                    "start_date": "2026-01-01",
                    "end_date": "2026-04-06",
                },
                headers=_HEADERS,
            )
        assert resp.status_code == 400
        assert "93" in resp.json()["detail"]

    def test_start_after_end_returns_400(self):
        client = _make_rev_client()
        with patch.object(_rev_mod, "_service", _FakeRevenueService()):
            resp = client.get(
                "/api/v1/finance/revenue/payment-reconcile",
                params={
                    "store_id": _STORE_ID,
                    "start_date": "2026-04-06",
                    "end_date": "2026-04-01",
                },
                headers=_HEADERS,
            )
        assert resp.status_code == 400


# ══════════════════════════════════════════════════════════════════════════════
# approval_callback_routes 测试
# ══════════════════════════════════════════════════════════════════════════════

def _make_mock_db_with_row(status="pending_approval"):
    """创建带有 row 的 mock db session"""
    db = MagicMock()
    row = {"status": status, "company_name": "测试公司", "credit_limit_fen": 100000}
    mock_result = MagicMock()
    mock_result.mappings.return_value.first.return_value = row
    db.execute = AsyncMock(return_value=mock_result)
    db.commit = AsyncMock()
    return db


class TestApprovalCallback:
    """POST /api/v1/credit/agreements/{id}/approval-callback"""

    def _client_with_db(self, db):
        app = FastAPI()
        app.include_router(_cb_mod.router)
        app.dependency_overrides[_cb_mod._get_tenant_db] = lambda: db
        return TestClient(app, raise_server_exceptions=False)

    def test_approved_callback_returns_200(self):
        db = _make_mock_db_with_row("pending_approval")
        client = self._client_with_db(db)
        with patch.object(_cb_mod, "emit_event", AsyncMock()):
            resp = client.post(
                f"/api/v1/credit/agreements/{_AGREEMENT_ID}/approval-callback",
                json={"decision": "approved", "approver_id": _APPROVER_ID, "comment": "LGTM"},
                headers=_HEADERS,
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["data"]["decision"] == "approved"
        assert body["data"]["new_status"] == "active"

    def test_rejected_callback_returns_200(self):
        db = _make_mock_db_with_row("pending_approval")
        client = self._client_with_db(db)
        with patch.object(_cb_mod, "emit_event", AsyncMock()):
            resp = client.post(
                f"/api/v1/credit/agreements/{_AGREEMENT_ID}/approval-callback",
                json={"decision": "rejected", "approver_id": _APPROVER_ID},
                headers=_HEADERS,
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["data"]["new_status"] == "terminated"

    def test_invalid_decision_returns_400(self):
        db = _make_mock_db_with_row("pending_approval")
        client = self._client_with_db(db)
        resp = client.post(
            f"/api/v1/credit/agreements/{_AGREEMENT_ID}/approval-callback",
            json={"decision": "unknown", "approver_id": _APPROVER_ID},
            headers=_HEADERS,
        )
        assert resp.status_code == 400
        assert "decision" in resp.json()["detail"]

    def test_agreement_not_found_returns_404(self):
        db = MagicMock()
        mock_result = MagicMock()
        mock_result.mappings.return_value.first.return_value = None
        db.execute = AsyncMock(return_value=mock_result)
        client = self._client_with_db(db)
        resp = client.post(
            f"/api/v1/credit/agreements/{_AGREEMENT_ID}/approval-callback",
            json={"decision": "approved", "approver_id": _APPROVER_ID},
            headers=_HEADERS,
        )
        assert resp.status_code == 404

    def test_non_pending_status_returns_409(self):
        db = _make_mock_db_with_row("active")
        client = self._client_with_db(db)
        resp = client.post(
            f"/api/v1/credit/agreements/{_AGREEMENT_ID}/approval-callback",
            json={"decision": "approved", "approver_id": _APPROVER_ID},
            headers=_HEADERS,
        )
        assert resp.status_code == 409
        assert "pending_approval" in resp.json()["detail"]

    def test_invalid_agreement_id_returns_422(self):
        db = _make_mock_db_with_row("pending_approval")
        client = self._client_with_db(db)
        resp = client.post(
            "/api/v1/credit/agreements/not-a-uuid/approval-callback",
            json={"decision": "approved", "approver_id": _APPROVER_ID},
            headers=_HEADERS,
        )
        assert resp.status_code == 422

    def test_missing_tenant_header_returns_422(self):
        db = _make_mock_db_with_row("pending_approval")
        client = self._client_with_db(db)
        resp = client.post(
            f"/api/v1/credit/agreements/{_AGREEMENT_ID}/approval-callback",
            json={"decision": "approved", "approver_id": _APPROVER_ID},
        )
        assert resp.status_code == 422

    def test_invalid_approver_id_returns_400(self):
        db = _make_mock_db_with_row("pending_approval")
        client = self._client_with_db(db)
        resp = client.post(
            f"/api/v1/credit/agreements/{_AGREEMENT_ID}/approval-callback",
            json={"decision": "approved", "approver_id": "not-a-uuid"},
            headers=_HEADERS,
        )
        assert resp.status_code == 400
        assert "approver_id" in resp.json()["detail"]

    def test_db_query_error_returns_500(self):
        db = MagicMock()
        db.execute = AsyncMock(side_effect=Exception("DB connection failed"))
        client = self._client_with_db(db)
        resp = client.post(
            f"/api/v1/credit/agreements/{_AGREEMENT_ID}/approval-callback",
            json={"decision": "approved", "approver_id": _APPROVER_ID},
            headers=_HEADERS,
        )
        assert resp.status_code == 500
