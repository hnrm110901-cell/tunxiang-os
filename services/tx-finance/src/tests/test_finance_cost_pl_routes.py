"""finance_cost_routes.py + finance_pl_routes.py 路由测试

覆盖端点：
  GET  /cost/daily              - 日成本快报
  GET  /cost/breakdown          - 成本明细（菜品占比）
  GET  /health/cost-rate        - 成本健康指数
  GET  /store-cost-config       - 门店固定成本配置读取
  PUT  /store-cost-config       - 门店固定成本配置写入
  GET  /pl/store                - 门店 P&L 损益表
  GET  /pl/brand                - 品牌级 P&L

Mock 路径：shared.ontology.src.database.get_db_with_tenant
"""

import sys
import types
import uuid

# ── Mock shared.ontology.src.database ──────────────────────────────────────
_shared = types.ModuleType("shared")
_shared_ontology = types.ModuleType("shared.ontology")
_shared_ontology_src = types.ModuleType("shared.ontology.src")
_shared_ontology_src_database = types.ModuleType("shared.ontology.src.database")


async def _fake_get_db_with_tenant(tenant_id):
    yield None


_shared_ontology_src_database.get_db_with_tenant = _fake_get_db_with_tenant

sys.modules.setdefault("shared", _shared)
sys.modules.setdefault("shared.ontology", _shared_ontology)
sys.modules.setdefault("shared.ontology.src", _shared_ontology_src)
sys.modules.setdefault("shared.ontology.src.database", _shared_ontology_src_database)

# ── Mock structlog ──────────────────────────────────────────────────────────
_structlog = types.ModuleType("structlog")


class _FakeLogger:
    def info(self, *a, **kw):
        pass

    def error(self, *a, **kw):
        pass

    def warning(self, *a, **kw):
        pass

    def debug(self, *a, **kw):
        pass


_structlog.get_logger = lambda *a, **kw: _FakeLogger()
sys.modules.setdefault("structlog", _structlog)

# ── Mock services.tx_finance.src.services.cost_engine_service ──────────────
_services = types.ModuleType("services")
_services_txf = types.ModuleType("services.tx_finance")
_services_txf_src = types.ModuleType("services.tx_finance.src")
_services_txf_src_services = types.ModuleType("services.tx_finance.src.services")
_services_txf_src_services_ces = types.ModuleType("services.tx_finance.src.services.cost_engine_service")
_services_txf_src_services_pls = types.ModuleType("services.tx_finance.src.services.pl_service")

sys.modules.setdefault("services", _services)
sys.modules.setdefault("services.tx_finance", _services_txf)
sys.modules.setdefault("services.tx_finance.src", _services_txf_src)
sys.modules.setdefault("services.tx_finance.src.services", _services_txf_src_services)
sys.modules.setdefault(
    "services.tx_finance.src.services.cost_engine_service",
    _services_txf_src_services_ces,
)
sys.modules.setdefault(
    "services.tx_finance.src.services.pl_service",
    _services_txf_src_services_pls,
)

# ── Now import route modules with patched stubs ─────────────────────────────
from unittest.mock import AsyncMock, MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

STORE_ID = str(uuid.uuid4())
TENANT_ID = str(uuid.uuid4())
BRAND_ID = str(uuid.uuid4())
HEADERS = {"X-Tenant-ID": TENANT_ID}

# ───────────────────────────────────────────────────────────────────────────
# finance_cost_routes tests
# ───────────────────────────────────────────────────────────────────────────


def _make_cost_client(mock_svc):
    """Build a TestClient with a fresh FastAPI app that uses the mocked service."""
    _services_txf_src_services_ces.CostEngineService = lambda: mock_svc
    import importlib

    import services.tx_finance.src.api.finance_cost_routes as cost_mod

    importlib.reload(cost_mod)
    app = FastAPI()
    app.include_router(cost_mod.router)
    return TestClient(app, raise_server_exceptions=False)


def _fake_health():
    h = MagicMock()
    h.to_dict.return_value = {"signal": "green", "score": 95, "cost_rate": 0.27}
    return h


def _fake_daily_report():
    rpt = MagicMock()
    rpt.revenue_fen = 100000
    rpt.food_cost_fen = 28000
    rpt.is_estimated = False
    rpt.health = _fake_health()
    rpt.to_dict.return_value = {
        "food_cost_fen": 28000,
        "food_cost_rate": 0.28,
        "gross_profit_fen": 72000,
        "gross_margin_rate": 0.72,
        "is_estimated": False,
        "health": {"signal": "green"},
    }
    return rpt


def _fake_breakdown_report():
    rpt = MagicMock()
    rpt.to_dict.return_value = {"items": [{"dish_name": "大黄鱼", "cost_ratio": 0.15, "total_cost_fen": 4200}]}
    return rpt


# ── Test 1: GET /cost/daily — happy path ────────────────────────────────────


def test_get_daily_cost_happy_path():
    svc = MagicMock()
    svc.get_daily_cost_report = AsyncMock(return_value=_fake_daily_report())
    client = _make_cost_client(svc)

    resp = client.get(
        f"/cost/daily?store_id={STORE_ID}&date=2026-04-01",
        headers=HEADERS,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert "data" in body


# ── Test 2: GET /cost/daily — invalid store_id returns 400 ──────────────────


def test_get_daily_cost_invalid_store_id():
    svc = MagicMock()
    svc.get_daily_cost_report = AsyncMock(return_value=_fake_daily_report())
    client = _make_cost_client(svc)

    resp = client.get(
        "/cost/daily?store_id=not-a-uuid&date=2026-04-01",
        headers=HEADERS,
    )
    assert resp.status_code == 400


# ── Test 3: GET /cost/daily — "today" keyword works ─────────────────────────


def test_get_daily_cost_today_keyword():
    svc = MagicMock()
    svc.get_daily_cost_report = AsyncMock(return_value=_fake_daily_report())
    client = _make_cost_client(svc)

    resp = client.get(
        f"/cost/daily?store_id={STORE_ID}&date=today",
        headers=HEADERS,
    )
    assert resp.status_code == 200


# ── Test 4: GET /cost/breakdown — happy path ────────────────────────────────


def test_get_cost_breakdown_happy_path():
    svc = MagicMock()
    svc.get_cost_breakdown = AsyncMock(return_value=_fake_breakdown_report())
    client = _make_cost_client(svc)

    resp = client.get(
        f"/cost/breakdown?store_id={STORE_ID}&start_date=2026-03-01&end_date=2026-03-31",
        headers=HEADERS,
    )
    assert resp.status_code == 200
    assert resp.json()["ok"] is True


# ── Test 5: GET /cost/breakdown — start > end returns 400 ───────────────────


def test_get_cost_breakdown_date_order_error():
    svc = MagicMock()
    svc.get_cost_breakdown = AsyncMock(return_value=_fake_breakdown_report())
    client = _make_cost_client(svc)

    resp = client.get(
        f"/cost/breakdown?store_id={STORE_ID}&start_date=2026-04-01&end_date=2026-03-01",
        headers=HEADERS,
    )
    assert resp.status_code == 400
    assert "start_date" in resp.json()["detail"]


# ── Test 6: GET /health/cost-rate — happy path ──────────────────────────────


def test_get_cost_health_happy_path():
    svc = MagicMock()
    svc.get_daily_cost_report = AsyncMock(return_value=_fake_daily_report())
    client = _make_cost_client(svc)

    resp = client.get(
        f"/health/cost-rate?store_id={STORE_ID}&date=2026-04-01",
        headers=HEADERS,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    data = body["data"]
    assert "store_id" in data
    assert "food_cost_fen" in data


# ── Test 7: GET /store-cost-config — happy path ─────────────────────────────


def test_get_store_cost_config_happy_path():
    svc = MagicMock()
    svc.get_store_cost_config = AsyncMock(
        return_value={
            "monthly_rent_fen": 500000,
            "monthly_utility_fen": 80000,
            "monthly_other_fixed_fen": 20000,
        }
    )
    client = _make_cost_client(svc)

    resp = client.get(
        f"/store-cost-config?store_id={STORE_ID}",
        headers=HEADERS,
    )
    assert resp.status_code == 200
    assert resp.json()["ok"] is True


# ── Test 8: PUT /store-cost-config — happy path ─────────────────────────────


def test_update_store_cost_config_happy_path():
    svc = MagicMock()
    svc.update_store_cost_config = AsyncMock(
        return_value={
            "monthly_rent_fen": 600000,
            "monthly_utility_fen": 90000,
            "monthly_other_fixed_fen": 15000,
        }
    )
    client = _make_cost_client(svc)

    resp = client.put(
        "/store-cost-config",
        json={
            "store_id": STORE_ID,
            "monthly_rent_fen": 600000,
            "monthly_utility_fen": 90000,
            "monthly_other_fixed_fen": 15000,
        },
        headers=HEADERS,
    )
    assert resp.status_code == 200
    assert resp.json()["ok"] is True


# ── Test 9: PUT /store-cost-config — invalid body returns 422 ───────────────


def test_update_store_cost_config_missing_fields():
    svc = MagicMock()
    client = _make_cost_client(svc)

    resp = client.put(
        "/store-cost-config",
        json={"store_id": STORE_ID},  # missing required fields
        headers=HEADERS,
    )
    assert resp.status_code == 422


# ── Test 10: GET /cost/daily — bad date format returns 400 ──────────────────


def test_get_daily_cost_bad_date_format():
    svc = MagicMock()
    svc.get_daily_cost_report = AsyncMock(return_value=_fake_daily_report())
    client = _make_cost_client(svc)

    resp = client.get(
        f"/cost/daily?store_id={STORE_ID}&date=not-a-date",
        headers=HEADERS,
    )
    assert resp.status_code == 400


# ───────────────────────────────────────────────────────────────────────────
# finance_pl_routes tests
# ───────────────────────────────────────────────────────────────────────────


def _make_pl_client(mock_svc):
    _services_txf_src_services_pls.PLService = lambda: mock_svc
    import importlib

    import services.tx_finance.src.api.finance_pl_routes as pl_mod

    importlib.reload(pl_mod)
    app = FastAPI()
    app.include_router(pl_mod.router)
    return TestClient(app, raise_server_exceptions=False)


def _fake_store_pl():
    pl = MagicMock()
    pl.to_dict.return_value = {
        "revenue_fen": 200000,
        "gross_profit_fen": 140000,
        "gross_margin_rate": 0.70,
        "operating_profit_fen": 80000,
    }
    return pl


def _fake_brand_pl():
    bpl = MagicMock()
    bpl.to_dict.return_value = {
        "summary": {"total_revenue_fen": 1000000},
        "store_details": [],
    }
    return bpl


# ── Test 11: GET /pl/store — happy path ─────────────────────────────────────


def test_get_store_pl_happy_path():
    svc = MagicMock()
    svc.get_store_pl = AsyncMock(return_value=_fake_store_pl())
    client = _make_pl_client(svc)

    resp = client.get(
        f"/pl/store?store_id={STORE_ID}&start_date=2026-03-01&end_date=2026-03-31",
        headers=HEADERS,
    )
    assert resp.status_code == 200
    assert resp.json()["ok"] is True


# ── Test 12: GET /pl/store — start_date > end_date returns 400 ──────────────


def test_get_store_pl_date_order_error():
    svc = MagicMock()
    client = _make_pl_client(svc)

    resp = client.get(
        f"/pl/store?store_id={STORE_ID}&start_date=2026-04-01&end_date=2026-03-01",
        headers=HEADERS,
    )
    assert resp.status_code == 400


# ── Test 13: GET /pl/store — date range > 366 days returns 400 ──────────────


def test_get_store_pl_range_too_large():
    svc = MagicMock()
    client = _make_pl_client(svc)

    resp = client.get(
        f"/pl/store?store_id={STORE_ID}&start_date=2024-01-01&end_date=2026-04-01",
        headers=HEADERS,
    )
    assert resp.status_code == 400


# ── Test 14: GET /pl/store — invalid store_id returns 400 ───────────────────


def test_get_store_pl_invalid_store_id():
    svc = MagicMock()
    client = _make_pl_client(svc)

    resp = client.get(
        "/pl/store?store_id=bad-id&start_date=2026-03-01&end_date=2026-03-31",
        headers=HEADERS,
    )
    assert resp.status_code == 400


# ── Test 15: GET /pl/brand — happy path ─────────────────────────────────────


def test_get_brand_pl_happy_path():
    svc = MagicMock()
    svc.get_brand_pl = AsyncMock(return_value=_fake_brand_pl())
    client = _make_pl_client(svc)

    resp = client.get(
        f"/pl/brand?brand_id={BRAND_ID}&month=2026-03",
        headers=HEADERS,
    )
    assert resp.status_code == 200
    assert resp.json()["ok"] is True


# ── Test 16: GET /pl/brand — bad month format returns 400 ───────────────────


def test_get_brand_pl_bad_month_format():
    svc = MagicMock()
    client = _make_pl_client(svc)

    resp = client.get(
        f"/pl/brand?brand_id={BRAND_ID}&month=202603",
        headers=HEADERS,
    )
    assert resp.status_code == 400
