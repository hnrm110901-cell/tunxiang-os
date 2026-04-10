"""BOM 管理 API 路由层测试 — TestClient + FastAPI dependency_overrides + Mock DB

覆盖路由 (bom_routes.py — 7 端点):
  GET  /api/v1/supply/boms                         — list_boms
  POST /api/v1/supply/boms                         — create_bom
  PUT  /api/v1/supply/boms/{bom_id}                — update_bom
  DELETE /api/v1/supply/boms/{bom_id}              — delete_bom
  POST /api/v1/supply/boms/{bom_id}/calculate-cost — calculate_bom_cost
  GET  /api/v1/supply/boms/{bom_id}/cost-breakdown — bom_cost_breakdown
  POST /api/v1/supply/dishes/{dish_id}/consume-stock — consume_stock_by_bom

测试数量: 23 个测试用例
"""
from __future__ import annotations

import sys
import types
import uuid

# ─── Stub: shared.ontology.src.database ───────────────────────────────────────
_shared = types.ModuleType("shared")
_shared_ont = types.ModuleType("shared.ontology")
_shared_ont_src = types.ModuleType("shared.ontology.src")
_shared_db = types.ModuleType("shared.ontology.src.database")

async def _placeholder_get_db():
    yield None  # will be overridden via dependency_overrides

_shared_db.get_db = _placeholder_get_db
sys.modules.setdefault("shared", _shared)
sys.modules.setdefault("shared.ontology", _shared_ont)
sys.modules.setdefault("shared.ontology.src", _shared_ont_src)
sys.modules.setdefault("shared.ontology.src.database", _shared_db)

# ─── Stub: structlog ──────────────────────────────────────────────────────────
_structlog = types.ModuleType("structlog")
_structlog.get_logger = lambda *a, **kw: types.SimpleNamespace(
    info=lambda *a, **kw: None,
    error=lambda *a, **kw: None,
    warning=lambda *a, **kw: None,
)
sys.modules.setdefault("structlog", _structlog)

import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi import FastAPI
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock, MagicMock
from sqlalchemy.exc import SQLAlchemyError

from api.bom_routes import router, get_db

TENANT_ID = str(uuid.uuid4())
BOM_ID = str(uuid.uuid4())
DISH_ID = str(uuid.uuid4())
HEADERS = {"X-Tenant-ID": TENANT_ID}


# ─── App factory with injectable DB mock ──────────────────────────────────────

def _make_app(db_mock):
    """Create FastAPI app with get_db overridden to yield db_mock."""
    app = FastAPI()
    app.include_router(router)

    async def _override():
        yield db_mock

    app.dependency_overrides[get_db] = _override
    return app


def _client(db_mock):
    return TestClient(_make_app(db_mock))


# ─── Helpers ───────────────────────────────────────────────────────────────────

def _mock_db():
    db = AsyncMock()
    db.execute = AsyncMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    return db


def _scalar_result(value):
    r = MagicMock()
    r.scalar.return_value = value
    return r


def _mapping_first(data: dict | None):
    if data is None:
        m = MagicMock()
        m.mappings.return_value.first.return_value = None
        return m
    row = MagicMock()
    row.__getitem__ = lambda s, k: data[k]
    row.get = lambda k, d=None: data.get(k, d)
    for k, v in data.items():
        setattr(row, k, v)
    m = MagicMock()
    m.mappings.return_value.first.return_value = row
    return m


def _mapping_all(rows: list[dict]):
    mock_rows = []
    for data in rows:
        row = MagicMock()
        row.__getitem__ = lambda s, k, d=data: d[k]
        row.get = lambda k, dft=None, d=data: d.get(k, dft)
        for k, v in data.items():
            setattr(row, k, v)
        mock_rows.append(row)
    m = MagicMock()
    m.mappings.return_value.all.return_value = mock_rows
    return m


def _fetchall_result(rows: list):
    m = MagicMock()
    m.fetchall.return_value = rows
    return m


# ═══════════════════════════════════════════════════════════════════════════════
# 1. GET /api/v1/supply/boms — list_boms
# ═══════════════════════════════════════════════════════════════════════════════


class TestListBoms:

    def test_list_boms_empty(self):
        """空列表：total=0, items=[]。"""
        db = _mock_db()
        db.execute.side_effect = [
            MagicMock(),           # set_config
            _scalar_result(0),    # COUNT
            _fetchall_result([]), # ids
        ]
        resp = _client(db).get("/api/v1/supply/boms", headers=HEADERS)
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["data"]["total"] == 0
        assert body["data"]["items"] == []

    def test_list_boms_with_pagination_params(self):
        """分页参数 page/size 可正常传递，返回对应字段。"""
        db = _mock_db()
        db.execute.side_effect = [
            MagicMock(),
            _scalar_result(0),
            _fetchall_result([]),
        ]
        resp = _client(db).get(
            "/api/v1/supply/boms?page=2&size=5",
            headers=HEADERS,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["data"]["page"] == 2
        assert body["data"]["size"] == 5

    def test_list_boms_with_dish_and_active_filter(self):
        """dish_id + is_active 过滤参数可正常传递。"""
        db = _mock_db()
        db.execute.side_effect = [
            MagicMock(),
            _scalar_result(0),
            _fetchall_result([]),
        ]
        resp = _client(db).get(
            f"/api/v1/supply/boms?dish_id={DISH_ID}&is_active=true",
            headers=HEADERS,
        )
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    def test_list_boms_db_error_500(self):
        """SQLAlchemyError → 500。"""
        db = _mock_db()
        db.execute.side_effect = SQLAlchemyError("db error")
        resp = _client(db).get("/api/v1/supply/boms", headers=HEADERS)
        assert resp.status_code == 500

    def test_list_boms_missing_tenant_422(self):
        """缺少 X-Tenant-ID → 422。"""
        db = _mock_db()
        resp = _client(db).get("/api/v1/supply/boms")
        assert resp.status_code == 422


# ═══════════════════════════════════════════════════════════════════════════════
# 2. POST /api/v1/supply/boms — create_bom
# ═══════════════════════════════════════════════════════════════════════════════


class TestCreateBom:

    def _valid_body(self):
        return {
            "dish_id": DISH_ID,
            "version": 1,
            "yield_qty": "1",
            "yield_unit": "份",
            "is_active": False,
            "items": [
                {
                    "ingredient_name": "猪肉",
                    "quantity": "0.5",
                    "unit": "kg",
                    "unit_cost_fen": 4000,
                    "loss_rate": "0.05",
                }
            ],
        }

    def test_create_bom_success_201(self):
        """正常创建 BOM → 201 + ok=True。"""
        new_bom_id = str(uuid.uuid4())
        db = _mock_db()

        dup_check = MagicMock()
        dup_check.first.return_value = None

        insert_bom = MagicMock()
        insert_bom.scalar.return_value = new_bom_id

        bom_data = {
            "id": new_bom_id, "tenant_id": TENANT_ID, "dish_id": DISH_ID,
            "version": 1, "total_cost_fen": 2100, "yield_qty": "1",
            "yield_unit": "份", "is_active": False, "notes": None,
            "created_at": None, "updated_at": None, "is_deleted": False,
        }

        db.execute.side_effect = [
            MagicMock(),   # set_config
            dup_check,     # dup check → None
            insert_bom,    # INSERT dish_boms RETURNING id
            MagicMock(),   # INSERT dish_bom_items
            _mapping_first(bom_data),   # _fetch_bom_with_items: bom
            _mapping_all([]),           # _fetch_bom_with_items: items
        ]

        resp = _client(db).post(
            "/api/v1/supply/boms",
            json=self._valid_body(),
            headers=HEADERS,
        )
        assert resp.status_code == 201
        assert resp.json()["ok"] is True

    def test_create_bom_duplicate_version_400(self):
        """同菜品同版本已存在 → 400。"""
        db = _mock_db()
        dup_check = MagicMock()
        dup_check.first.return_value = MagicMock()

        db.execute.side_effect = [
            MagicMock(),
            dup_check,
        ]

        resp = _client(db).post(
            "/api/v1/supply/boms",
            json=self._valid_body(),
            headers=HEADERS,
        )
        assert resp.status_code == 400

    def test_create_bom_missing_items_422(self):
        """items 为空列表 → Pydantic min_length 校验失败 → 422。"""
        body = dict(self._valid_body())
        body["items"] = []
        db = _mock_db()
        resp = _client(db).post("/api/v1/supply/boms", json=body, headers=HEADERS)
        assert resp.status_code == 422

    def test_create_bom_db_error_500(self):
        """SQLAlchemyError (set_config之后) → 500 + rollback。"""
        db = _mock_db()
        db.execute.side_effect = [
            MagicMock(),
            SQLAlchemyError("db fail"),
        ]
        resp = _client(db).post(
            "/api/v1/supply/boms",
            json=self._valid_body(),
            headers=HEADERS,
        )
        assert resp.status_code == 500


# ═══════════════════════════════════════════════════════════════════════════════
# 3. PUT /api/v1/supply/boms/{bom_id} — update_bom
# ═══════════════════════════════════════════════════════════════════════════════


class TestUpdateBom:

    def test_update_bom_not_found_404(self):
        """BOM 不存在 → 404。"""
        db = _mock_db()
        db.execute.side_effect = [
            MagicMock(),
            _mapping_first(None),
        ]
        resp = _client(db).put(
            f"/api/v1/supply/boms/{BOM_ID}",
            json={"notes": "test"},
            headers=HEADERS,
        )
        assert resp.status_code == 404

    def test_update_bom_notes_success(self):
        """更新 notes → 200 + ok=True。"""
        db = _mock_db()
        row_data = {"id": BOM_ID, "dish_id": DISH_ID, "is_active": False}

        bom_data = {
            "id": BOM_ID, "tenant_id": TENANT_ID, "dish_id": DISH_ID,
            "version": 1, "total_cost_fen": 0, "yield_qty": "1",
            "yield_unit": "份", "is_active": False, "notes": "updated note",
            "created_at": None, "updated_at": None, "is_deleted": False,
        }

        db.execute.side_effect = [
            MagicMock(),                  # set_config
            _mapping_first(row_data),     # SELECT existing
            MagicMock(),                  # UPDATE dish_boms
            _mapping_first(bom_data),     # _fetch_bom: bom
            _mapping_all([]),             # _fetch_bom: items
        ]

        resp = _client(db).put(
            f"/api/v1/supply/boms/{BOM_ID}",
            json={"notes": "updated note"},
            headers=HEADERS,
        )
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    def test_update_bom_db_error_500(self):
        """SQLAlchemyError → 500。"""
        db = _mock_db()
        db.execute.side_effect = SQLAlchemyError("db fail")
        resp = _client(db).put(
            f"/api/v1/supply/boms/{BOM_ID}",
            json={"notes": "test"},
            headers=HEADERS,
        )
        assert resp.status_code == 500


# ═══════════════════════════════════════════════════════════════════════════════
# 4. DELETE /api/v1/supply/boms/{bom_id} — delete_bom
# ═══════════════════════════════════════════════════════════════════════════════


class TestDeleteBom:

    def test_delete_bom_not_found_404(self):
        """BOM 不存在 → 404。"""
        db = _mock_db()
        db.execute.side_effect = [
            MagicMock(),
            _mapping_first(None),
        ]
        resp = _client(db).delete(f"/api/v1/supply/boms/{BOM_ID}", headers=HEADERS)
        assert resp.status_code == 404

    def test_delete_active_bom_400(self):
        """激活中的 BOM 不可删除 → 400。"""
        db = _mock_db()
        db.execute.side_effect = [
            MagicMock(),
            _mapping_first({"id": BOM_ID, "is_active": True}),
        ]
        resp = _client(db).delete(f"/api/v1/supply/boms/{BOM_ID}", headers=HEADERS)
        assert resp.status_code == 400

    def test_delete_bom_success(self):
        """正常软删除 → 200 + deleted=True。"""
        db = _mock_db()
        db.execute.side_effect = [
            MagicMock(),
            _mapping_first({"id": BOM_ID, "is_active": False}),
            MagicMock(),   # UPDATE is_deleted=true
        ]
        resp = _client(db).delete(f"/api/v1/supply/boms/{BOM_ID}", headers=HEADERS)
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["data"]["deleted"] is True
        assert body["data"]["bom_id"] == BOM_ID


# ═══════════════════════════════════════════════════════════════════════════════
# 5. POST /api/v1/supply/boms/{bom_id}/calculate-cost — calculate_bom_cost
# ═══════════════════════════════════════════════════════════════════════════════


class TestCalculateBomCost:

    def test_calculate_cost_not_found_404(self):
        """BOM 不存在 → 404。"""
        db = _mock_db()
        existing = MagicMock()
        existing.first.return_value = None
        db.execute.side_effect = [MagicMock(), existing]
        resp = _client(db).post(
            f"/api/v1/supply/boms/{BOM_ID}/calculate-cost",
            headers=HEADERS,
        )
        assert resp.status_code == 404

    def test_calculate_cost_no_items_400(self):
        """BOM 无明细行 → 400。"""
        db = _mock_db()
        existing = MagicMock()
        existing.first.return_value = MagicMock()
        db.execute.side_effect = [
            MagicMock(),
            existing,
            _mapping_all([]),   # items → empty
        ]
        resp = _client(db).post(
            f"/api/v1/supply/boms/{BOM_ID}/calculate-cost",
            headers=HEADERS,
        )
        assert resp.status_code == 400

    def test_calculate_cost_success(self):
        """有明细行 → 计算成本，返回 200 + total_cost_fen。"""
        db = _mock_db()
        item_id = str(uuid.uuid4())
        existing = MagicMock()
        existing.first.return_value = MagicMock()

        db.execute.side_effect = [
            MagicMock(),   # set_config
            existing,      # SELECT bom exists
            _mapping_all([{
                "id": item_id,
                "quantity": "0.5",
                "unit_cost_fen": 4000,
                "loss_rate": "0.05",
            }]),
            MagicMock(),   # UPDATE item cost
            MagicMock(),   # UPDATE bom total
        ]

        resp = _client(db).post(
            f"/api/v1/supply/boms/{BOM_ID}/calculate-cost",
            headers=HEADERS,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert "total_cost_fen" in body["data"]
        # 0.5 × 4000 × 1.05 = 2100, ceil → 2100
        assert body["data"]["total_cost_fen"] == 2100


# ═══════════════════════════════════════════════════════════════════════════════
# 6. GET /api/v1/supply/boms/{bom_id}/cost-breakdown — bom_cost_breakdown
# ═══════════════════════════════════════════════════════════════════════════════


class TestBomCostBreakdown:

    def test_breakdown_not_found_404(self):
        """BOM 不存在 → 404。"""
        db = _mock_db()
        db.execute.side_effect = [MagicMock(), _mapping_first(None)]
        resp = _client(db).get(
            f"/api/v1/supply/boms/{BOM_ID}/cost-breakdown",
            headers=HEADERS,
        )
        assert resp.status_code == 404

    def test_breakdown_empty_items(self):
        """BOM 存在但无明细行 → 200 + breakdown=[]。"""
        db = _mock_db()
        bom_data = {
            "id": BOM_ID, "total_cost_fen": 0,
            "yield_qty": "1", "yield_unit": "份", "dish_id": DISH_ID,
        }
        db.execute.side_effect = [
            MagicMock(),
            _mapping_first(bom_data),
            _mapping_all([]),
        ]
        resp = _client(db).get(
            f"/api/v1/supply/boms/{BOM_ID}/cost-breakdown",
            headers=HEADERS,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["data"]["breakdown"] == []

    def test_breakdown_with_items(self):
        """有明细行 → breakdown 含 cost_pct 字段。"""
        db = _mock_db()
        bom_data = {
            "id": BOM_ID, "total_cost_fen": 2100,
            "yield_qty": "1", "yield_unit": "份", "dish_id": DISH_ID,
        }
        db.execute.side_effect = [
            MagicMock(),
            _mapping_first(bom_data),
            _mapping_all([{
                "ingredient_name": "猪肉",
                "ingredient_code": "PK001",
                "quantity": "0.5",
                "unit": "kg",
                "unit_cost_fen": 4000,
                "total_cost_fen": 2100,
                "loss_rate": "0.05",
                "is_semi_product": False,
            }]),
        ]
        resp = _client(db).get(
            f"/api/v1/supply/boms/{BOM_ID}/cost-breakdown",
            headers=HEADERS,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        bd = body["data"]["breakdown"]
        assert len(bd) == 1
        assert bd[0]["ingredient_name"] == "猪肉"
        assert "cost_pct" in bd[0]
        assert bd[0]["cost_pct"] == 100.0


# ═══════════════════════════════════════════════════════════════════════════════
# 7. POST /api/v1/supply/dishes/{dish_id}/consume-stock — consume_stock_by_bom
# ═══════════════════════════════════════════════════════════════════════════════


class TestConsumeStockByBom:

    def _valid_body(self):
        return {
            "quantity": "2",
            "store_id": str(uuid.uuid4()),
        }

    def test_consume_no_active_bom_400(self):
        """无激活 BOM → 400。"""
        db = _mock_db()
        db.execute.side_effect = [
            MagicMock(),
            _mapping_first(None),
        ]
        resp = _client(db).post(
            f"/api/v1/supply/dishes/{DISH_ID}/consume-stock",
            json=self._valid_body(),
            headers=HEADERS,
        )
        assert resp.status_code == 400

    def test_consume_success_with_active_bom(self):
        """激活 BOM + 有明细行 → 消耗成功 → 200 + consumed 列表。"""
        db = _mock_db()
        bom_data = {"id": BOM_ID, "total_cost_fen": 2100}
        db.execute.side_effect = [
            MagicMock(),
            _mapping_first(bom_data),
            _mapping_all([{
                "ingredient_code": "PK001",
                "ingredient_name": "猪肉",
                "quantity": "0.5",
                "unit": "kg",
                "loss_rate": "0.05",
            }]),
            MagicMock(),   # UPDATE ingredients
        ]
        resp = _client(db).post(
            f"/api/v1/supply/dishes/{DISH_ID}/consume-stock",
            json=self._valid_body(),
            headers=HEADERS,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["data"]["dish_id"] == DISH_ID
        consumed = body["data"]["consumed"]
        assert len(consumed) == 1
        assert consumed[0]["ingredient_code"] == "PK001"

    def test_consume_missing_store_id_422(self):
        """缺少 store_id 字段 → 422。"""
        db = _mock_db()
        resp = _client(db).post(
            f"/api/v1/supply/dishes/{DISH_ID}/consume-stock",
            json={"quantity": "1"},
            headers=HEADERS,
        )
        assert resp.status_code == 422

    def test_consume_db_error_500(self):
        """SQLAlchemyError → 500 + rollback。"""
        db = _mock_db()
        db.execute.side_effect = SQLAlchemyError("db fail")
        resp = _client(db).post(
            f"/api/v1/supply/dishes/{DISH_ID}/consume-stock",
            json=self._valid_body(),
            headers=HEADERS,
        )
        assert resp.status_code == 500
