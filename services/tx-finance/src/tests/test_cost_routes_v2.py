"""cost_routes_v2.py 路由测试

覆盖端点（5个）：
  POST /api/v1/finance/costs                  — 录入成本记录
  GET  /api/v1/finance/costs                  — 查询成本明细
  GET  /api/v1/finance/costs/summary          — 成本结构汇总（饼图数据）
  POST /api/v1/finance/configs                — 设置财务配置
  GET  /api/v1/finance/configs/{store_id}     — 查询门店财务配置

注：cost_routes_v2.py 与 cost_routes.py 差异显著：
- v2 直接执行 SQL（text() + db.execute），无 CostEngine 服务层
- 新增 /costs/summary 和 /configs 端点
- 全部端点使用 get_db_with_tenant（RLS 路径）

测试用例总计：16个
"""

import sys
import types
import uuid
from unittest.mock import AsyncMock, MagicMock

# ── Mock shared.ontology.src.database ──────────────────────────────────────
_shared = types.ModuleType("shared")
_shared_ont = types.ModuleType("shared.ontology")
_shared_ont_src = types.ModuleType("shared.ontology.src")
_shared_ont_src_db = types.ModuleType("shared.ontology.src.database")


async def _fake_get_db_with_tenant(tenant_id):
    yield None


_shared_ont_src_db.get_db_with_tenant = _fake_get_db_with_tenant
sys.modules.setdefault("shared", _shared)
sys.modules.setdefault("shared.ontology", _shared_ont)
sys.modules.setdefault("shared.ontology.src", _shared_ont_src)
sys.modules.setdefault("shared.ontology.src.database", _shared_ont_src_db)

# ── Mock structlog ──────────────────────────────────────────────────────────
_structlog = types.ModuleType("structlog")


class _FakeLogger:
    def info(self, *a, **kw):
        pass

    def error(self, *a, **kw):
        pass

    def warning(self, *a, **kw):
        pass


_structlog.get_logger = lambda *a, **kw: _FakeLogger()
sys.modules.setdefault("structlog", _structlog)

# ── Load cost_routes_v2 ─────────────────────────────────────────────────────
import importlib.util
import pathlib

_api_base = pathlib.Path(__file__).parent.parent / "api"
_spec = importlib.util.spec_from_file_location("cost_routes_v2", _api_base / "cost_routes_v2.py")
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

from fastapi import FastAPI
from fastapi.testclient import TestClient

# ── Constants ────────────────────────────────────────────────────────────────
_TENANT_ID = str(uuid.uuid4())
_STORE_ID = str(uuid.uuid4())
_HEADERS = {"X-Tenant-ID": _TENANT_ID}


def _make_db_with_scalar(scalar_val):
    """DB mock: execute() returns result with scalar_one() = scalar_val"""
    db = MagicMock()
    mock_result = MagicMock()
    mock_result.scalar_one.return_value = scalar_val
    mock_result.scalar.return_value = scalar_val
    mock_result.fetchall.return_value = []
    db.execute = AsyncMock(return_value=mock_result)
    db.commit = AsyncMock()
    return db


def _make_client(db=None):
    app = FastAPI()
    # cost_routes_v2 doesn't have a prefix, add /api/v1/finance prefix for testing
    app.include_router(_mod.router, prefix="/api/v1/finance")
    override_db = db if db is not None else _make_db_with_scalar(uuid.uuid4())
    app.dependency_overrides[_mod._get_tenant_db] = lambda: override_db
    return TestClient(app, raise_server_exceptions=False)


# ══════════════════════════════════════════════════════════════════════════════
# POST /api/v1/finance/costs
# ══════════════════════════════════════════════════════════════════════════════


class TestCreateCostItem:
    def test_create_rent_cost_returns_200(self):
        db = _make_db_with_scalar(uuid.uuid4())
        client = _make_client(db)
        resp = client.post(
            "/api/v1/finance/costs",
            json={
                "store_id": _STORE_ID,
                "cost_date": "2026-04-06",
                "cost_type": "rent",
                "amount_fen": 500000,
                "description": "4月房租",
            },
            headers=_HEADERS,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["data"]["cost_type"] == "rent"
        assert body["data"]["amount_fen"] == 500000

    def test_invalid_cost_type_returns_422(self):
        client = _make_client()
        resp = client.post(
            "/api/v1/finance/costs",
            json={
                "store_id": _STORE_ID,
                "cost_date": "2026-04-06",
                "cost_type": "invalid_type",
                "amount_fen": 1000,
            },
            headers=_HEADERS,
        )
        assert resp.status_code == 422

    def test_invalid_store_uuid_returns_400(self):
        client = _make_client()
        resp = client.post(
            "/api/v1/finance/costs",
            json={
                "store_id": "bad-uuid",
                "cost_date": "2026-04-06",
                "cost_type": "labor",
                "amount_fen": 20000,
            },
            headers=_HEADERS,
        )
        assert resp.status_code == 400

    def test_today_keyword_in_cost_date_accepted(self):
        db = _make_db_with_scalar(uuid.uuid4())
        client = _make_client(db)
        resp = client.post(
            "/api/v1/finance/costs",
            json={
                "store_id": _STORE_ID,
                "cost_date": "today",
                "cost_type": "utilities",
                "amount_fen": 8000,
            },
            headers=_HEADERS,
        )
        assert resp.status_code == 200

    def test_negative_amount_rejected_by_schema(self):
        client = _make_client()
        resp = client.post(
            "/api/v1/finance/costs",
            json={
                "store_id": _STORE_ID,
                "cost_date": "2026-04-06",
                "cost_type": "purchase",
                "amount_fen": -100,
            },
            headers=_HEADERS,
        )
        assert resp.status_code == 422

    def test_missing_tenant_header_returns_422(self):
        client = _make_client()
        resp = client.post(
            "/api/v1/finance/costs",
            json={
                "store_id": _STORE_ID,
                "cost_date": "2026-04-06",
                "cost_type": "rent",
                "amount_fen": 100000,
            },
        )
        assert resp.status_code == 422


# ══════════════════════════════════════════════════════════════════════════════
# GET /api/v1/finance/costs
# ══════════════════════════════════════════════════════════════════════════════


class TestGetCostItems:
    def _db_with_rows(self, rows=None):
        if rows is None:
            rows = []
        db = MagicMock()
        count_result = MagicMock()
        count_result.scalar.return_value = len(rows)
        items_result = MagicMock()
        items_result.fetchall.return_value = rows
        db.execute = AsyncMock(side_effect=[count_result, items_result])
        db.commit = AsyncMock()
        return db

    def test_returns_paginated_list(self):
        client = _make_client(self._db_with_rows([]))
        resp = client.get(
            "/api/v1/finance/costs",
            params={"store_id": _STORE_ID, "date": "2026-04-06"},
            headers=_HEADERS,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert "items" in body["data"]
        assert body["data"]["total"] == 0

    def test_invalid_cost_type_filter_returns_400(self):
        client = _make_client(self._db_with_rows())
        resp = client.get(
            "/api/v1/finance/costs",
            params={"store_id": _STORE_ID, "date": "2026-04-06", "cost_type": "bad_type"},
            headers=_HEADERS,
        )
        assert resp.status_code == 400

    def test_missing_store_id_returns_422(self):
        client = _make_client(self._db_with_rows())
        resp = client.get(
            "/api/v1/finance/costs",
            params={"date": "2026-04-06"},
            headers=_HEADERS,
        )
        assert resp.status_code == 422


# ══════════════════════════════════════════════════════════════════════════════
# GET /api/v1/finance/costs/summary
# ══════════════════════════════════════════════════════════════════════════════


class TestGetCostSummary:
    def test_valid_request_returns_200(self):
        db = MagicMock()
        mock_result = MagicMock()
        mock_result.fetchall.return_value = [("rent", 300000), ("utilities", 50000)]
        db.execute = AsyncMock(return_value=mock_result)
        client = _make_client(db)
        resp = client.get(
            "/api/v1/finance/costs/summary",
            params={"store_id": _STORE_ID, "start_date": "2026-04-01", "end_date": "2026-04-06"},
            headers=_HEADERS,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["data"]["total_cost_fen"] == 350000
        assert len(body["data"]["breakdown"]) == 2

    def test_start_after_end_returns_400(self):
        client = _make_client()
        resp = client.get(
            "/api/v1/finance/costs/summary",
            params={"store_id": _STORE_ID, "start_date": "2026-04-10", "end_date": "2026-04-01"},
            headers=_HEADERS,
        )
        assert resp.status_code == 400

    def test_range_over_366_days_returns_400(self):
        client = _make_client()
        resp = client.get(
            "/api/v1/finance/costs/summary",
            params={"store_id": _STORE_ID, "start_date": "2025-01-01", "end_date": "2026-04-06"},
            headers=_HEADERS,
        )
        assert resp.status_code == 400
        assert "366" in resp.json()["detail"]


# ══════════════════════════════════════════════════════════════════════════════
# POST /api/v1/finance/configs
# ══════════════════════════════════════════════════════════════════════════════


class TestSetFinanceConfig:
    def test_set_pct_config_returns_200(self):
        db = _make_db_with_scalar(uuid.uuid4())
        client = _make_client(db)
        resp = client.post(
            "/api/v1/finance/configs",
            json={
                "store_id": _STORE_ID,
                "config_type": "labor_cost_pct",
                "value_pct": 25.0,
            },
            headers=_HEADERS,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["data"]["config_type"] == "labor_cost_pct"

    def test_invalid_config_type_returns_422(self):
        client = _make_client()
        resp = client.post(
            "/api/v1/finance/configs",
            json={
                "store_id": _STORE_ID,
                "config_type": "invalid_config",
                "value_fen": 10000,
            },
            headers=_HEADERS,
        )
        assert resp.status_code == 422

    def test_pct_config_without_value_returns_400(self):
        client = _make_client()
        resp = client.post(
            "/api/v1/finance/configs",
            json={
                "store_id": _STORE_ID,
                "config_type": "labor_cost_pct",
                # Neither value_pct nor value_fen provided
            },
            headers=_HEADERS,
        )
        assert resp.status_code == 400


# ══════════════════════════════════════════════════════════════════════════════
# GET /api/v1/finance/configs/{store_id}
# ══════════════════════════════════════════════════════════════════════════════


class TestGetFinanceConfigs:
    def test_returns_config_list(self):
        db = MagicMock()
        mock_result = MagicMock()
        # Row: (id, config_type, value_fen, value_pct, effective_from, effective_until, store_id)
        fake_id = uuid.uuid4()
        mock_result.fetchall.return_value = [
            (fake_id, "rent_monthly_fen", 300000, None, None, None, uuid.UUID(_STORE_ID))
        ]
        db.execute = AsyncMock(return_value=mock_result)
        client = _make_client(db)
        resp = client.get(
            f"/api/v1/finance/configs/{_STORE_ID}",
            params={"date": "2026-04-06"},
            headers=_HEADERS,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert len(body["data"]["configs"]) == 1
        assert body["data"]["configs"][0]["config_type"] == "rent_monthly_fen"

    def test_invalid_store_id_returns_400(self):
        client = _make_client()
        resp = client.get(
            "/api/v1/finance/configs/bad-uuid",
            headers=_HEADERS,
        )
        assert resp.status_code == 400
