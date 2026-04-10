"""seafood_loss_routes.py + budget_v2_routes.py 路由测试

覆盖端点：
  POST /seafood-loss/record    - 录入活鲜死亡损耗
  GET  /seafood-loss           - 查询损耗记录
  GET  /seafood-loss/analysis  - 损耗趋势分析
  GET  /budget                 - 年度预算列表
  POST /budget                 - 创建月度预算
  GET  /budget/execution       - 预算执行情况

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
    def info(self, *a, **kw): pass
    def error(self, *a, **kw): pass
    def warning(self, *a, **kw): pass
    def debug(self, *a, **kw): pass

_structlog.get_logger = lambda *a, **kw: _FakeLogger()
sys.modules.setdefault("structlog", _structlog)

# ── Imports ─────────────────────────────────────────────────────────────────
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi import FastAPI
from fastapi.testclient import TestClient

STORE_ID = str(uuid.uuid4())
TENANT_ID = str(uuid.uuid4())
DISH_ID = str(uuid.uuid4())
COST_ITEM_ID = str(uuid.uuid4())
HEADERS = {"X-Tenant-ID": TENANT_ID}


# ───────────────────────────────────────────────────────────────────────────
# seafood_loss_routes tests
# ───────────────────────────────────────────────────────────────────────────

def _make_seafood_client(mock_db):
    """Build app with a mocked DB session injected via dependency override."""
    import importlib
    # Re-register the fake get_db_with_tenant each time
    _shared_ontology_src_database.get_db_with_tenant = _fake_get_db_with_tenant
    import services.tx_finance.src.api.seafood_loss_routes as sl_mod
    importlib.reload(sl_mod)

    app = FastAPI()
    app.include_router(sl_mod.router)

    async def _override_db():
        yield mock_db

    app.dependency_overrides[sl_mod._get_tenant_db] = _override_db
    return TestClient(app, raise_server_exceptions=False)


def _make_fake_db_for_record():
    """DB mock that returns a scalar UUID for INSERT RETURNING."""
    db = MagicMock()
    execute_result = MagicMock()
    execute_result.scalar_one.return_value = uuid.UUID(COST_ITEM_ID)
    db.execute = AsyncMock(return_value=execute_result)
    db.commit = AsyncMock()
    return db


def _make_fake_db_for_list(total=2, rows=None):
    """DB mock for GET /seafood-loss (count + items query)."""
    db = MagicMock()
    count_result = MagicMock()
    count_result.scalar.return_value = total

    if rows is None:
        fake_row = (
            uuid.UUID(COST_ITEM_ID),  # id
            "2026-04-01",             # cost_date
            "大黄鱼自然死亡",            # description
            3000,                     # amount_fen
            1.5,                      # quantity
            "kg",                     # unit
            2000,                     # unit_cost_fen
            uuid.UUID(DISH_ID),       # reference_id
            "2026-04-01T08:00:00",    # created_at
            "大黄鱼",                  # dish_name
        )
        rows = [fake_row]

    items_result = MagicMock()
    items_result.fetchall.return_value = rows

    db.execute = AsyncMock(side_effect=[count_result, items_result])
    return db


def _make_fake_db_for_analysis(daily_rows=None, dish_rows=None, ratio_rows=None):
    """DB mock for GET /seafood-loss/analysis (3 queries)."""
    db = MagicMock()

    if daily_rows is None:
        daily_rows = [("2026-04-01", 3000, 1)]
    if dish_rows is None:
        dish_rows = [(uuid.UUID(DISH_ID), "大黄鱼", 3000, 1.5, "kg", 1)]
    if ratio_rows is None:
        ratio_rows = [("2026-04-01", 50000, 3000)]

    def _make_result(rows):
        r = MagicMock()
        r.fetchall.return_value = rows
        return r

    db.execute = AsyncMock(
        side_effect=[
            _make_result(daily_rows),
            _make_result(dish_rows),
            _make_result(ratio_rows),
        ]
    )
    return db


# ── Test 1: POST /seafood-loss/record — happy path ───────────────────────────

def test_record_seafood_loss_happy_path():
    db = _make_fake_db_for_record()
    client = _make_seafood_client(db)

    resp = client.post(
        "/seafood-loss/record",
        json={
            "store_id": STORE_ID,
            "loss_date": "2026-04-01",
            "dish_id": DISH_ID,
            "description": "大黄鱼自然死亡3条",
            "amount_fen": 3000,
            "quantity": 1.5,
            "unit": "kg",
        },
        headers=HEADERS,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["amount_fen"] == 3000


# ── Test 2: POST /seafood-loss/record — invalid unit returns 422 ─────────────

def test_record_seafood_loss_invalid_unit():
    db = _make_fake_db_for_record()
    client = _make_seafood_client(db)

    resp = client.post(
        "/seafood-loss/record",
        json={
            "store_id": STORE_ID,
            "loss_date": "2026-04-01",
            "dish_id": DISH_ID,
            "description": "损耗记录",
            "amount_fen": 1000,
            "quantity": 1.0,
            "unit": "箱",  # not allowed
        },
        headers=HEADERS,
    )
    assert resp.status_code == 422


# ── Test 3: POST /seafood-loss/record — invalid store_id returns 400 ─────────

def test_record_seafood_loss_invalid_store_id():
    db = _make_fake_db_for_record()
    client = _make_seafood_client(db)

    resp = client.post(
        "/seafood-loss/record",
        json={
            "store_id": "not-a-uuid",
            "loss_date": "2026-04-01",
            "dish_id": DISH_ID,
            "description": "损耗",
            "amount_fen": 500,
            "quantity": 0.5,
            "unit": "kg",
        },
        headers=HEADERS,
    )
    assert resp.status_code == 400


# ── Test 4: POST /seafood-loss/record — with optional tank_zone_id ───────────

def test_record_seafood_loss_with_tank_zone():
    db = _make_fake_db_for_record()
    client = _make_seafood_client(db)

    tank_zone_id = str(uuid.uuid4())
    resp = client.post(
        "/seafood-loss/record",
        json={
            "store_id": STORE_ID,
            "loss_date": "2026-04-01",
            "dish_id": DISH_ID,
            "description": "水质事故批量死亡",
            "amount_fen": 8000,
            "quantity": 4.0,
            "unit": "kg",
            "unit_cost_fen": 2000,
            "tank_zone_id": tank_zone_id,
            "notes": "水温过高导致",
        },
        headers=HEADERS,
    )
    assert resp.status_code == 200
    assert resp.json()["ok"] is True


# ── Test 5: GET /seafood-loss — happy path ────────────────────────────────────

def test_get_seafood_loss_records_happy_path():
    db = _make_fake_db_for_list(total=1)
    client = _make_seafood_client(db)

    resp = client.get(
        f"/seafood-loss?store_id={STORE_ID}&date=2026-04-01",
        headers=HEADERS,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    data = body["data"]
    assert "items" in data
    assert data["total"] == 1


# ── Test 6: GET /seafood-loss — pagination parameters ────────────────────────

def test_get_seafood_loss_records_pagination():
    db = _make_fake_db_for_list(total=50, rows=[])
    client = _make_seafood_client(db)

    resp = client.get(
        f"/seafood-loss?store_id={STORE_ID}&date=2026-04-01&page=2&size=10",
        headers=HEADERS,
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["page"] == 2
    assert data["size"] == 10


# ── Test 7: GET /seafood-loss — "today" keyword ───────────────────────────────

def test_get_seafood_loss_records_today_keyword():
    db = _make_fake_db_for_list(total=0, rows=[])
    client = _make_seafood_client(db)

    resp = client.get(
        f"/seafood-loss?store_id={STORE_ID}",
        headers=HEADERS,
    )
    assert resp.status_code == 200
    assert resp.json()["ok"] is True


# ── Test 8: GET /seafood-loss/analysis — happy path ──────────────────────────

def test_get_seafood_loss_analysis_happy_path():
    db = _make_fake_db_for_analysis()
    client = _make_seafood_client(db)

    resp = client.get(
        f"/seafood-loss/analysis?store_id={STORE_ID}&days=30",
        headers=HEADERS,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    data = body["data"]
    assert "daily_trend" in data
    assert "top_dishes" in data
    assert "summary" in data


# ── Test 9: GET /seafood-loss/analysis — empty data ──────────────────────────

def test_get_seafood_loss_analysis_empty():
    db = _make_fake_db_for_analysis(daily_rows=[], dish_rows=[], ratio_rows=[])
    client = _make_seafood_client(db)

    resp = client.get(
        f"/seafood-loss/analysis?store_id={STORE_ID}&days=7",
        headers=HEADERS,
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["summary"]["total_loss_fen"] == 0
    assert data["summary"]["top_loss_dish"] is None


# ── Test 10: GET /seafood-loss/analysis — days param validation ───────────────

def test_get_seafood_loss_analysis_days_out_of_range():
    db = _make_fake_db_for_analysis()
    client = _make_seafood_client(db)

    # days < 7 should return 422
    resp = client.get(
        f"/seafood-loss/analysis?store_id={STORE_ID}&days=5",
        headers=HEADERS,
    )
    assert resp.status_code == 422


# ───────────────────────────────────────────────────────────────────────────
# budget_v2_routes tests
# ───────────────────────────────────────────────────────────────────────────

def _make_budget_client(mock_db):
    import importlib
    import services.tx_finance.src.api.budget_v2_routes as bv2_mod
    importlib.reload(bv2_mod)

    app = FastAPI()
    app.include_router(bv2_mod.router)

    async def _override_db():
        yield mock_db

    app.dependency_overrides[bv2_mod._get_tenant_db] = _override_db
    return TestClient(app, raise_server_exceptions=False)


def _make_fake_db_for_list_budgets(rows=None):
    """DB mock for GET /budget."""
    db = MagicMock()
    result = MagicMock()
    if rows is None:
        rows = [
            ("2026-01", 1000000, 300000, 200000, "draft"),
            ("2026-02", 1100000, 330000, 200000, "approved"),
        ]
    result.fetchall.return_value = rows
    db.execute = AsyncMock(return_value=result)
    return db


def _make_fake_db_for_create_budget():
    """DB mock for POST /budget (3 UPSERTs + commit)."""
    db = MagicMock()

    def _make_upsert_result(cat, fen):
        r = MagicMock()
        row = MagicMock()
        row.__getitem__ = lambda self, i: [uuid.uuid4(), cat, fen, "draft"][i]
        r.fetchone.return_value = row
        return r

    db.execute = AsyncMock(
        side_effect=[
            _make_upsert_result("revenue", 1200000),
            _make_upsert_result("ingredient_cost", 360000),
            _make_upsert_result("labor_cost", 240000),
        ]
    )
    db.commit = AsyncMock()
    return db


def _make_fake_db_for_execution(budget_rows=None, rev=500000, labor=200000, food=150000):
    """DB mock for GET /budget/execution (4 queries)."""
    db = MagicMock()

    if budget_rows is None:
        budget_rows = [
            ("revenue", 1000000),
            ("ingredient_cost", 300000),
            ("labor_cost", 200000),
        ]

    def _make_result(data, scalar_val=None):
        r = MagicMock()
        r.fetchall.return_value = data
        r.scalar.return_value = scalar_val
        return r

    budget_result = MagicMock()
    budget_result.fetchall.return_value = budget_rows

    rev_result = MagicMock()
    rev_result.scalar.return_value = rev

    labor_result = MagicMock()
    labor_result.scalar.return_value = labor

    food_result = MagicMock()
    food_result.scalar.return_value = food

    db.execute = AsyncMock(
        side_effect=[budget_result, rev_result, labor_result, food_result]
    )
    return db


# ── Test 11: GET /budget — happy path ────────────────────────────────────────

def test_list_annual_budgets_happy_path():
    db = _make_fake_db_for_list_budgets()
    client = _make_budget_client(db)

    resp = client.get(
        f"/budget?store_id={STORE_ID}&year=2026",
        headers=HEADERS,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["year"] == 2026
    assert len(body["data"]["items"]) == 2


# ── Test 12: GET /budget — empty result ──────────────────────────────────────

def test_list_annual_budgets_empty():
    db = _make_fake_db_for_list_budgets(rows=[])
    client = _make_budget_client(db)

    resp = client.get(
        f"/budget?store_id={STORE_ID}&year=2025",
        headers=HEADERS,
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["total"] == 0


# ── Test 13: POST /budget — happy path ───────────────────────────────────────

def test_create_monthly_budget_happy_path():
    db = _make_fake_db_for_create_budget()
    client = _make_budget_client(db)

    resp = client.post(
        "/budget",
        json={
            "store_id": STORE_ID,
            "year": 2026,
            "month": 5,
            "revenue_target_fen": 1200000,
            "cost_budget_fen": 360000,
            "labor_budget_fen": 240000,
        },
        headers=HEADERS,
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["period"] == "2026-05"
    assert body["data"]["revenue_target_fen"] == 1200000


# ── Test 14: POST /budget — invalid store_id returns 422 ─────────────────────

def test_create_monthly_budget_invalid_store_id():
    db = _make_fake_db_for_create_budget()
    client = _make_budget_client(db)

    resp = client.post(
        "/budget",
        json={
            "store_id": "not-a-uuid",
            "year": 2026,
            "month": 5,
            "revenue_target_fen": 1000000,
            "cost_budget_fen": 300000,
            "labor_budget_fen": 200000,
        },
        headers=HEADERS,
    )
    assert resp.status_code == 422


# ── Test 15: POST /budget — with optional note ───────────────────────────────

def test_create_monthly_budget_with_note():
    db = _make_fake_db_for_create_budget()
    client = _make_budget_client(db)

    resp = client.post(
        "/budget",
        json={
            "store_id": STORE_ID,
            "year": 2026,
            "month": 6,
            "revenue_target_fen": 1300000,
            "cost_budget_fen": 390000,
            "labor_budget_fen": 260000,
            "note": "旺季上调预算",
        },
        headers=HEADERS,
    )
    assert resp.status_code == 201
    assert resp.json()["ok"] is True


# ── Test 16: GET /budget/execution — happy path ───────────────────────────────

def test_get_budget_execution_happy_path():
    db = _make_fake_db_for_execution()
    client = _make_budget_client(db)

    resp = client.get(
        f"/budget/execution?store_id={STORE_ID}&year=2026&month=3",
        headers=HEADERS,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    data = body["data"]
    assert "budget" in data
    assert "actual" in data
    assert "variance" in data
    assert "execution_rate" in data


# ── Test 17: GET /budget/execution — execution_status logic ──────────────────

def test_get_budget_execution_status_on_track():
    # revenue_target=1000000, actual=980000 → rate=0.98 → on_track
    db = _make_fake_db_for_execution(
        budget_rows=[
            ("revenue", 1000000),
            ("ingredient_cost", 300000),
            ("labor_cost", 200000),
        ],
        rev=980000,
        labor=195000,
        food=290000,
    )
    client = _make_budget_client(db)

    resp = client.get(
        f"/budget/execution?store_id={STORE_ID}&year=2026&month=3",
        headers=HEADERS,
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["execution_status"] == "on_track"


# ── Test 18: GET /budget/execution — no budget → has_budget=False ─────────────

def test_get_budget_execution_no_budget():
    db = _make_fake_db_for_execution(budget_rows=[], rev=300000, labor=0, food=0)
    client = _make_budget_client(db)

    resp = client.get(
        f"/budget/execution?store_id={STORE_ID}&year=2026&month=3",
        headers=HEADERS,
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["has_budget"] is False
    assert data["execution_rate"] == 0.0


# ── Test 19: GET /budget/execution — month out of range returns 422 ───────────

def test_get_budget_execution_bad_month():
    db = _make_fake_db_for_execution()
    client = _make_budget_client(db)

    resp = client.get(
        f"/budget/execution?store_id={STORE_ID}&year=2026&month=13",
        headers=HEADERS,
    )
    assert resp.status_code == 422


# ── Test 20: GET /budget/execution — critical execution_status ───────────────

def test_get_budget_execution_status_critical():
    # rate = 400000 / 1000000 = 0.4 → critical
    db = _make_fake_db_for_execution(
        budget_rows=[
            ("revenue", 1000000),
            ("ingredient_cost", 300000),
            ("labor_cost", 200000),
        ],
        rev=400000,
        labor=200000,
        food=300000,
    )
    client = _make_budget_client(db)

    resp = client.get(
        f"/budget/execution?store_id={STORE_ID}&year=2026&month=3",
        headers=HEADERS,
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["execution_status"] == "critical"
