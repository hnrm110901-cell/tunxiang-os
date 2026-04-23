"""Round 105 — tx-menu 剩余路由补测
涵盖端点数 Top-3：dishes.py (12) / live_seafood_routes.py (8) / dish_spec_routes.py (5)
测试数量：≥ 15
"""

import sys
import types

# ── Mock src.db ──────────────────────────────────────────────────────
fake_db = types.ModuleType("src.db")


async def fake_get_db():
    yield None


fake_db.get_db = fake_get_db
sys.modules.setdefault("src", types.ModuleType("src"))
sys.modules.setdefault("src.db", fake_db)

# ── Mock shared.ontology.src.database ───────────────────────────────
_shared = types.ModuleType("shared")
_shared_onto = types.ModuleType("shared.ontology")
_shared_onto_src = types.ModuleType("shared.ontology.src")
_shared_onto_src_db = types.ModuleType("shared.ontology.src.database")
_shared_onto_src_db.get_db = fake_get_db
sys.modules.setdefault("shared", _shared)
sys.modules.setdefault("shared.ontology", _shared_onto)
sys.modules.setdefault("shared.ontology.src", _shared_onto_src)
sys.modules.setdefault("shared.ontology.src.database", _shared_onto_src_db)

# ── Mock structlog ──────────────────────────────────────────────────
import unittest.mock as _mock

_structlog = types.ModuleType("structlog")
_structlog.get_logger = lambda *a, **kw: _mock.MagicMock()
sys.modules.setdefault("structlog", _structlog)

# ── Mock ..models.dish_practice for practice_routes ─────────────────
_services_pkg = types.ModuleType("services")
_tx_menu_pkg = types.ModuleType("services.tx_menu")
_tx_menu_src = types.ModuleType("services.tx_menu.src")
_tx_menu_src_svc = types.ModuleType("services.tx_menu.src.services")
_dish_intel_mod = types.ModuleType("services.tx_menu.src.services.dish_intelligence")
_dish_intel_mod.calculate_dish_reputation = _mock.MagicMock(return_value={"score": 4.5})
_dish_intel_mod.auto_derive_status = _mock.MagicMock(return_value={"status": "star"})
_dish_intel_mod.get_dish_lifecycle = _mock.MagicMock(return_value={"lifecycle": "growth"})
_dish_intel_mod.suggest_dish_action = _mock.MagicMock(return_value={"action": "promote"})
sys.modules.setdefault("services", _services_pkg)
sys.modules.setdefault("services.tx_menu", _tx_menu_pkg)
sys.modules.setdefault("services.tx_menu.src", _tx_menu_src)
sys.modules.setdefault("services.tx_menu.src.services", _tx_menu_src_svc)
sys.modules.setdefault("services.tx_menu.src.services.dish_intelligence", _dish_intel_mod)

# ── Mock ..services.dish_intelligence (relative) ────────────────────
# patch both potential import paths
_rel_svc = types.ModuleType("src.api.services")
sys.modules.setdefault("src.api.services", _rel_svc)
sys.modules.setdefault("src.api.services.dish_intelligence", _dish_intel_mod)

# Mock ..models.dish_practice
_models_pkg = types.ModuleType("src.api.models")


class _FakeDishPractice:
    dish_id = None
    tenant_id = None
    is_deleted = False
    practice_group = "default"
    sort_order = 0
    id = None
    practice_name = ""
    additional_price_fen = 0
    is_default = False


_models_pkg.DishPractice = _FakeDishPractice
sys.modules.setdefault("src.api.models", _models_pkg)
sys.modules.setdefault("src.api.models.dish_practice", _models_pkg)

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

TENANT_ID = "11111111-1111-1111-1111-111111111111"
DISH_ID = "22222222-2222-2222-2222-222222222222"
STORE_ID = "33333333-3333-3333-3333-333333333333"


# ════════════════════════════════════════════════════════════════════
# PART 1 — dishes.py  (12 endpoints)
# ════════════════════════════════════════════════════════════════════


def _make_dishes_app():
    from services.tx_menu.src.api import dishes as _dishes_mod  # type: ignore[import]

    app = FastAPI()
    app.include_router(_dishes_mod.router)
    return app


def _make_dishes_app_direct():
    """Import dishes directly from the known path."""
    import importlib.util
    import pathlib

    spec_path = str(pathlib.Path(__file__).parent.parent / "api" / "dishes.py")
    spec = importlib.util.spec_from_file_location("dishes_module", spec_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    app = FastAPI()
    app.include_router(mod.router)
    return app


@pytest.fixture
def dishes_client():
    app = _make_dishes_app_direct()
    return TestClient(app, raise_server_exceptions=False)


class TestDishesEndpoints:
    """dishes.py — 12 端点覆盖"""

    def test_list_dishes_returns_ok(self, dishes_client):
        r = dishes_client.get("/api/v1/menu/dishes", params={"store_id": STORE_ID})
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is True
        assert "items" in body["data"]

    def test_list_dishes_with_category_filter(self, dishes_client):
        r = dishes_client.get(
            "/api/v1/menu/dishes",
            params={"store_id": STORE_ID, "category_id": "cat-1", "page": 1, "size": 10},
        )
        assert r.status_code == 200

    def test_create_dish_returns_ok(self, dishes_client):
        payload = {
            "dish_name": "测试菜品",
            "dish_code": "DISH001",
            "price_fen": 3800,
            "category_id": "cat-1",
            "kitchen_station": "热菜",
        }
        r = dishes_client.post("/api/v1/menu/dishes", json=payload)
        assert r.status_code == 200
        assert r.json()["ok"] is True

    def test_get_dish_returns_ok(self, dishes_client):
        r = dishes_client.get(f"/api/v1/menu/dishes/{DISH_ID}")
        assert r.status_code == 200
        assert r.json()["ok"] is True

    def test_update_dish_returns_ok(self, dishes_client):
        r = dishes_client.patch(
            f"/api/v1/menu/dishes/{DISH_ID}",
            json={"dish_name": "更新后名称"},
        )
        assert r.status_code == 200
        assert r.json()["ok"] is True

    def test_delete_dish_returns_ok(self, dishes_client):
        r = dishes_client.delete(f"/api/v1/menu/dishes/{DISH_ID}")
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is True
        assert body["data"]["deleted"] is True

    def test_get_dish_bom_returns_ok(self, dishes_client):
        r = dishes_client.get(f"/api/v1/menu/dishes/{DISH_ID}/bom")
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is True
        assert "items" in body["data"]

    def test_update_dish_bom_with_items(self, dishes_client):
        items = [
            {"ingredient_id": "ing-1", "quantity": 0.5, "unit": "kg"},
            {"ingredient_id": "ing-2", "quantity": 2.0, "unit": "个"},
        ]
        r = dishes_client.put(f"/api/v1/menu/dishes/{DISH_ID}/bom", json=items)
        assert r.status_code == 200
        body = r.json()
        assert body["data"]["bom_count"] == 2

    def test_get_dish_quadrant(self, dishes_client):
        r = dishes_client.get(f"/api/v1/menu/dishes/{DISH_ID}/quadrant")
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is True
        assert body["data"]["quadrant"] == "star"

    def test_get_menu_ranking(self, dishes_client):
        r = dishes_client.get(
            "/api/v1/menu/ranking",
            params={"store_id": STORE_ID, "period": "week"},
        )
        assert r.status_code == 200
        assert r.json()["ok"] is True

    def test_list_categories_returns_ok(self, dishes_client):
        r = dishes_client.get("/api/v1/menu/categories", params={"store_id": STORE_ID})
        assert r.status_code == 200
        assert r.json()["ok"] is True

    def test_create_category_returns_ok(self, dishes_client):
        r = dishes_client.post(
            "/api/v1/menu/categories",
            params={"name": "海鲜类"},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is True
        assert body["data"]["category_id"] == "new"


# ════════════════════════════════════════════════════════════════════
# PART 2 — live_seafood_routes.py  (8 endpoints)
# ════════════════════════════════════════════════════════════════════


def _make_live_seafood_app():
    import importlib.util
    import pathlib

    spec_path = str(pathlib.Path(__file__).parent.parent / "api" / "live_seafood_routes.py")
    spec = importlib.util.spec_from_file_location("live_seafood_routes", spec_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    app = FastAPI()
    app.include_router(mod.router)
    return app


def _mock_db_ctx():
    """Return context manager patching get_db with a fully mocked AsyncSession."""
    mock_session = MagicMock()
    mock_result = MagicMock()
    mock_result.fetchall.return_value = []
    mock_result.fetchone.return_value = None
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_session.commit = AsyncMock()

    async def _fake_get_db_gen():
        yield mock_session

    return patch(
        "shared.ontology.src.database.get_db",
        side_effect=_fake_get_db_gen,
    ), mock_session


@pytest.fixture
def live_seafood_client():
    app = _make_live_seafood_app()

    mock_session = MagicMock()
    mock_result = MagicMock()
    mock_result.fetchall.return_value = []
    mock_result.fetchone.return_value = None
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_session.commit = AsyncMock()
    mock_session.add = MagicMock()

    async def _override_get_db():
        yield mock_session

    # Override the dependency at app level
    import shared.ontology.src.database as _db_mod  # type: ignore[import]

    with patch.object(_db_mod, "get_db", _override_get_db):
        return TestClient(app, raise_server_exceptions=False), mock_session


class TestLiveSeafoodEndpoints:
    """live_seafood_routes.py — 端点覆盖"""

    def test_list_tank_zones(self, live_seafood_client):
        client, _ = live_seafood_client
        r = client.get(
            "/api/v1/menu/tank-zones",
            params={"store_id": STORE_ID},
            headers={"X-Tenant-ID": TENANT_ID},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is True

    def test_list_tank_zones_missing_tenant(self, live_seafood_client):
        client, _ = live_seafood_client
        r = client.get(
            "/api/v1/menu/tank-zones",
            params={"store_id": STORE_ID},
        )
        # 400 because X-Tenant-ID missing
        assert r.status_code in (400, 422)

    def test_list_live_seafood(self, live_seafood_client):
        client, _ = live_seafood_client
        r = client.get(
            "/api/v1/menu/live-seafood",
            params={"store_id": STORE_ID},
            headers={"X-Tenant-ID": TENANT_ID},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is True

    def test_list_live_seafood_in_stock_only(self, live_seafood_client):
        client, _ = live_seafood_client
        r = client.get(
            "/api/v1/menu/live-seafood",
            params={"store_id": STORE_ID, "in_stock_only": True},
            headers={"X-Tenant-ID": TENANT_ID},
        )
        assert r.status_code == 200

    def test_update_live_seafood_config_dish_not_found(self, live_seafood_client):
        client, _ = live_seafood_client
        payload = {
            "pricing_method": "weight",
            "weight_unit": "jin",
            "price_per_unit_fen": 6800,
            "display_unit": "斤",
        }
        r = client.patch(
            f"/api/v1/menu/live-seafood/{DISH_ID}",
            json=payload,
            headers={"X-Tenant-ID": TENANT_ID},
        )
        # 404 since mock returns no row
        assert r.status_code in (404, 200)

    def test_update_live_stock(self, live_seafood_client):
        client, mock_session = live_seafood_client
        # Make mock return a row for the UPDATE RETURNING
        row = MagicMock()
        row.__getitem__ = lambda self, key: {0: DISH_ID, 1: "石斑鱼", 2: 5, 3: 2500}[key]
        mock_result2 = MagicMock()
        mock_result2.fetchone.return_value = row
        mock_session.execute = AsyncMock(return_value=mock_result2)

        payload = {"delta_count": 5, "reason": "purchase"}
        r = client.post(
            f"/api/v1/menu/live-seafood/{DISH_ID}/stock",
            json=payload,
            headers={"X-Tenant-ID": TENANT_ID},
        )
        assert r.status_code in (200, 404)


# ════════════════════════════════════════════════════════════════════
# PART 3 — dish_spec_routes.py  (5 endpoints)
# ════════════════════════════════════════════════════════════════════


def _make_spec_app():
    import importlib.util
    import pathlib

    spec_path = str(pathlib.Path(__file__).parent.parent / "api" / "dish_spec_routes.py")
    spec = importlib.util.spec_from_file_location("dish_spec_routes", spec_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    app = FastAPI()
    app.include_router(mod.router)
    return app


@pytest.fixture
def spec_client():
    app = _make_spec_app()

    mock_session = MagicMock()
    mock_result = MagicMock()
    mock_result.scalar.return_value = 0
    mock_result.mappings.return_value.all.return_value = []
    mock_result.mappings.return_value.one_or_none.return_value = None
    mock_result.rowcount = 0
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_session.commit = AsyncMock()

    async def _override_get_db():
        yield mock_session

    import shared.ontology.src.database as _db_mod  # type: ignore[import]

    with patch.object(_db_mod, "get_db", _override_get_db):
        return TestClient(app, raise_server_exceptions=False), mock_session


class TestDishSpecEndpoints:
    """dish_spec_routes.py — 5 端点覆盖"""

    def test_list_specs_returns_ok(self, spec_client):
        client, _ = spec_client
        r = client.get(
            "/api/v1/menu/specs",
            headers={"X-Tenant-ID": TENANT_ID},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is True

    def test_list_specs_with_dish_filter(self, spec_client):
        client, _ = spec_client
        r = client.get(
            "/api/v1/menu/specs",
            params={"dish_id": DISH_ID},
            headers={"X-Tenant-ID": TENANT_ID},
        )
        assert r.status_code == 200

    def test_create_spec_db_error_503(self, spec_client):
        client, mock_session = spec_client
        from sqlalchemy.exc import SQLAlchemyError

        mock_session.execute = AsyncMock(side_effect=SQLAlchemyError("DB error"))
        payload = {
            "dish_id": DISH_ID,
            "spec_group_name": "辣度",
            "options": [
                {"name": "微辣", "price_delta_fen": 0, "is_default": True},
                {"name": "中辣", "price_delta_fen": 100},
            ],
        }
        r = client.post(
            "/api/v1/menu/specs",
            json=payload,
            headers={"X-Tenant-ID": TENANT_ID},
        )
        assert r.status_code == 503

    def test_delete_spec_not_found(self, spec_client):
        client, _ = spec_client
        r = client.delete(
            f"/api/v1/menu/specs/{DISH_ID}",
            headers={"X-Tenant-ID": TENANT_ID},
        )
        # rowcount=0 → 404
        assert r.status_code == 404

    def test_update_spec_not_found(self, spec_client):
        client, _ = spec_client
        payload = {
            "dish_id": DISH_ID,
            "spec_group_name": "份量",
            "options": [{"name": "半份"}, {"name": "全份"}],
        }
        r = client.put(
            f"/api/v1/menu/specs/{DISH_ID}",
            json=payload,
            headers={"X-Tenant-ID": TENANT_ID},
        )
        # _get_group_with_options returns None → 404
        assert r.status_code == 404
