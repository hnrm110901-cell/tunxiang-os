"""供应链核心路由单元测试

覆盖文件（各 5 个测试，共 10 个）：
  1. api/purchase_order_routes.py — 采购单管理（7 个端点）
     - GET  /api/v1/supply/purchase-orders           — 列表查询
     - POST /api/v1/supply/purchase-orders           — 创建采购单
     - GET  /api/v1/supply/purchase-orders/{po_id}   — 采购单详情（含 404）
     - POST /api/v1/supply/purchase-orders/{id}/submit — 提交审批
     - DB 错误 → TABLE_NOT_READY

  2. api/ck_production_routes.py — 中央厨房生产/配送工单（7 个端点）
     - POST /api/v1/supply/ck/production-orders              — 创建生产工单
     - GET  /api/v1/supply/ck/production-orders              — 查询工单列表
     - PATCH /api/v1/supply/ck/production-orders/{id}/status — 推进状态（含 404）
     - GET  /api/v1/supply/ck/distribution-orders            — 查询配送单列表
     - DB 错误 → 500

技术说明：
  - shared.* 模块用 sys.modules 注入存根，避免循环导入
  - DB 依赖通过 app.dependency_overrides[_get_db] 注入 mock AsyncSession
  - ck_production_routes 的 services.supplier_scoring_engine 也注入存根
  - mock execute 使用 side_effect 列表按顺序排列多次调用结果
"""
from __future__ import annotations

import os
import sys
import types
import uuid
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.exc import ProgrammingError, SQLAlchemyError

# ─── 路径设置 ──────────────────────────────────────────────────────────────────

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# ─── shared.* 存根注入（必须在导入路由模块前完成） ──────────────────────────────


def _make_shared_stubs():
    """把 shared.ontology / shared.events 等模块注入 sys.modules 存根。"""
    # shared
    shared_mod = types.ModuleType("shared")
    sys.modules.setdefault("shared", shared_mod)

    # shared.ontology
    ont = types.ModuleType("shared.ontology")
    sys.modules.setdefault("shared.ontology", ont)

    # shared.ontology.src
    ont_src = types.ModuleType("shared.ontology.src")
    sys.modules.setdefault("shared.ontology.src", ont_src)

    # shared.ontology.src.database — 暴露 get_db（占位，测试中会 override）
    db_mod = types.ModuleType("shared.ontology.src.database")
    # get_db 是个异步生成器依赖；存根只要是可调用对象即可
    db_mod.get_db = lambda: None  # type: ignore[attr-defined]
    sys.modules.setdefault("shared.ontology.src.database", db_mod)

    # shared.events
    ev = types.ModuleType("shared.events")
    sys.modules.setdefault("shared.events", ev)

    # shared.events.src
    ev_src = types.ModuleType("shared.events.src")
    sys.modules.setdefault("shared.events.src", ev_src)

    # shared.events.src.emitter
    emitter_mod = types.ModuleType("shared.events.src.emitter")
    emitter_mod.emit_event = AsyncMock(return_value=None)  # type: ignore[attr-defined]
    sys.modules.setdefault("shared.events.src.emitter", emitter_mod)

    # shared.events.src.event_types
    et_mod = types.ModuleType("shared.events.src.event_types")
    for name in ["InventoryEventType", "OrderEventType"]:
        mock_enum = MagicMock()
        mock_enum.RECEIVED = "RECEIVED"
        mock_enum.CONSUMED = "CONSUMED"
        mock_enum.WASTED = "WASTED"
        mock_enum.ADJUSTED = "ADJUSTED"
        setattr(et_mod, name, mock_enum)
    sys.modules.setdefault("shared.events.src.event_types", et_mod)

    # shared.core
    core_mod = types.ModuleType("shared.core")
    sys.modules.setdefault("shared.core", core_mod)

    # shared.core.model_router
    mr_mod = types.ModuleType("shared.core.model_router")
    mr_mod.ModelRouter = MagicMock  # type: ignore[attr-defined]
    sys.modules.setdefault("shared.core.model_router", mr_mod)


_make_shared_stubs()

# ─── 导入路由模块 ──────────────────────────────────────────────────────────────

from api.purchase_order_routes import router as po_router  # noqa: E402
from api.purchase_order_routes import _get_db as po_get_db  # noqa: E402

# ck_production_routes 使用顶层 `from shared.ontology.src.database import get_db`
# 以及内部服务注入（services.supplier_scoring_engine 等），注入存根
_ck_services_pkg = types.ModuleType("services")
sys.modules.setdefault("services", _ck_services_pkg)

from api.ck_production_routes import router as ck_router  # noqa: E402
from api.ck_production_routes import get_db as ck_get_db  # noqa: E402

# ─── 公共常量 ──────────────────────────────────────────────────────────────────

TENANT_ID = str(uuid.uuid4())
STORE_ID = str(uuid.uuid4())
SUPPLIER_ID = str(uuid.uuid4())
INGREDIENT_ID = str(uuid.uuid4())
PO_ID = str(uuid.uuid4())
ORDER_ID = str(uuid.uuid4())
DIST_ID = str(uuid.uuid4())
HEADERS = {"X-Tenant-ID": TENANT_ID}


# ─── Mock DB 工厂 ──────────────────────────────────────────────────────────────


def _mock_db():
    """返回一个 mock AsyncSession，execute / commit / rollback 均为 AsyncMock。"""
    db = AsyncMock()
    db.execute = AsyncMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    return db


def _scalar_result(value):
    """包装 scalar_one() / scalar() 返回的 mock 结果。"""
    r = MagicMock()
    r.scalar_one = MagicMock(return_value=value)
    r.scalar = MagicMock(return_value=value)
    return r


def _rows_result(rows: list):
    """包装 fetchall / iteration 返回多行的 mock 结果。"""
    r = MagicMock()
    mapping_rows = []
    for row_data in rows:
        m = MagicMock()
        m._mapping = row_data
        mapping_rows.append(m)
    r.__iter__ = MagicMock(return_value=iter(mapping_rows))
    r.mappings = MagicMock(return_value=MagicMock(
        all=MagicMock(return_value=mapping_rows),
        first=MagicMock(return_value=mapping_rows[0] if mapping_rows else None),
    ))
    r.fetchall = MagicMock(return_value=mapping_rows)
    r.fetchone = MagicMock(return_value=mapping_rows[0] if mapping_rows else None)
    return r


def _none_result():
    """包装 fetchone() 返回 None 的 mock（用于"不存在"场景）。"""
    r = MagicMock()
    r.fetchone = MagicMock(return_value=None)
    r.scalar_one = MagicMock(return_value=0)
    r.scalar = MagicMock(return_value=0)
    r.mappings = MagicMock(return_value=MagicMock(
        first=MagicMock(return_value=None),
        all=MagicMock(return_value=[]),
    ))
    return r


# ══════════════════════════════════════════════════════════════════════════════
# 一、采购单路由测试（purchase_order_routes.py）
# ══════════════════════════════════════════════════════════════════════════════


class TestPurchaseOrderRoutes:
    """针对 api/purchase_order_routes.py 的路由级测试（使用 dependency_overrides）。"""

    def _make_app(self, db):
        """每个测试用例创建独立的 FastAPI 实例，注入 mock DB。"""
        app = FastAPI()
        app.include_router(po_router)

        async def override_get_db():
            yield db

        app.dependency_overrides[po_get_db] = override_get_db
        return TestClient(app)

    # ── 1. 列表查询（正常：返回分页数据） ───────────────────────────────────────

    def test_list_purchase_orders_ok(self):
        """GET /api/v1/supply/purchase-orders — 正常返回分页数据。"""
        db = _mock_db()
        po_row = {
            "id": PO_ID, "store_id": STORE_ID, "supplier_id": SUPPLIER_ID,
            "po_number": "PO-20260404-ABCDEF", "status": "draft",
            "total_amount_fen": 10000, "expected_delivery_date": None,
            "actual_delivery_date": None, "approved_by": None,
            "approved_at": None, "received_at": None, "notes": None,
            "created_at": "2026-04-04T00:00:00Z", "updated_at": "2026-04-04T00:00:00Z",
        }
        # side_effect 顺序：
        #   1. _set_tenant → set_config 执行（忽略返回值）
        #   2. COUNT(*) → scalar_one()=1
        #   3. SELECT 列表 → 迭代结果
        set_tenant_result = MagicMock()
        count_result = _scalar_result(1)
        list_result = _rows_result([po_row])
        db.execute.side_effect = [set_tenant_result, count_result, list_result]

        client = self._make_app(db)
        resp = client.get("/api/v1/supply/purchase-orders", headers=HEADERS)

        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["data"]["total"] == 1
        assert body["data"]["page"] == 1
        assert len(body["data"]["items"]) == 1
        assert body["data"]["items"][0]["po_number"] == "PO-20260404-ABCDEF"

    # ── 2. 创建采购单（正常） ────────────────────────────────────────────────────

    def test_create_purchase_order_ok(self):
        """POST /api/v1/supply/purchase-orders — 正常创建，返回 po_id 和 status=draft。"""
        db = _mock_db()
        set_tenant_result = MagicMock()
        insert_po_result = MagicMock()
        insert_item_result = MagicMock()
        # 顺序：set_tenant, INSERT purchase_orders, INSERT purchase_order_items（1 行）
        db.execute.side_effect = [set_tenant_result, insert_po_result, insert_item_result]

        client = self._make_app(db)
        body = {
            "store_id": STORE_ID,
            "supplier_id": SUPPLIER_ID,
            "items": [
                {
                    "ingredient_id": INGREDIENT_ID,
                    "ingredient_name": "鲈鱼",
                    "quantity": "2.0",
                    "unit": "kg",
                    "unit_price_fen": 5000,
                }
            ],
        }
        resp = client.post("/api/v1/supply/purchase-orders", json=body, headers=HEADERS)

        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["status"] == "draft"
        assert "po_id" in data
        assert "po_number" in data
        assert data["po_number"].startswith("PO-")
        assert data["total_amount_fen"] == 10000  # 2.0 * 5000
        db.commit.assert_awaited_once()

    # ── 3. 采购单详情（正常） ────────────────────────────────────────────────────

    def test_get_purchase_order_ok(self):
        """GET /api/v1/supply/purchase-orders/{po_id} — 正常返回详情含 items 列表。"""
        db = _mock_db()
        set_tenant_result = MagicMock()

        po_data = {
            "id": PO_ID, "store_id": STORE_ID, "supplier_id": SUPPLIER_ID,
            "po_number": "PO-20260404-XYZABC", "status": "approved",
            "total_amount_fen": 20000, "expected_delivery_date": None,
            "actual_delivery_date": None, "approved_by": None,
            "approved_at": None, "received_at": None, "notes": None,
            "created_at": "2026-04-04T00:00:00Z", "updated_at": "2026-04-04T00:00:00Z",
        }
        item_data = {
            "id": str(uuid.uuid4()), "ingredient_id": INGREDIENT_ID,
            "ingredient_name": "猪肉", "quantity": "5.0", "unit": "kg",
            "unit_price_fen": 4000, "subtotal_fen": 20000,
            "received_quantity": "0.0", "notes": None,
        }
        po_result = _rows_result([po_data])
        items_result = _rows_result([item_data])
        # 顺序：set_tenant, SELECT po, SELECT items
        db.execute.side_effect = [set_tenant_result, po_result, items_result]

        client = self._make_app(db)
        resp = client.get(f"/api/v1/supply/purchase-orders/{PO_ID}", headers=HEADERS)

        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["po_number"] == "PO-20260404-XYZABC"
        assert data["status"] == "approved"
        assert len(data["items"]) == 1
        assert data["items"][0]["ingredient_name"] == "猪肉"

    # ── 4. 采购单详情（404）────────────────────────────────────────────────────

    def test_get_purchase_order_not_found_404(self):
        """GET /api/v1/supply/purchase-orders/{po_id} — 采购单不存在 → 404。"""
        db = _mock_db()
        set_tenant_result = MagicMock()
        not_found_result = _none_result()
        # 顺序：set_tenant, SELECT po → fetchone()=None
        db.execute.side_effect = [set_tenant_result, not_found_result]

        client = self._make_app(db)
        fake_id = str(uuid.uuid4())
        resp = client.get(f"/api/v1/supply/purchase-orders/{fake_id}", headers=HEADERS)

        assert resp.status_code == 404
        assert "采购单不存在" in resp.json()["detail"]

    # ── 5. DB 表不存在（ProgrammingError → TABLE_NOT_READY） ──────────────────

    def test_list_purchase_orders_table_not_ready(self):
        """GET /api/v1/supply/purchase-orders — 表不存在时返回 TABLE_NOT_READY（非 5xx）。"""
        db = _mock_db()
        # ProgrammingError 要求 orig 参数
        prog_err = ProgrammingError(
            statement="SELECT",
            params={},
            orig=Exception("relation 'purchase_orders' does not exist"),
        )
        set_tenant_result = MagicMock()
        # 顺序：set_tenant 成功，COUNT 抛出 ProgrammingError
        db.execute.side_effect = [set_tenant_result, prog_err]

        client = self._make_app(db)
        resp = client.get("/api/v1/supply/purchase-orders", headers=HEADERS)

        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is False
        assert body["error"]["code"] == "TABLE_NOT_READY"


# ══════════════════════════════════════════════════════════════════════════════
# 二、中央厨房生产工单路由测试（ck_production_routes.py）
# ══════════════════════════════════════════════════════════════════════════════


class TestCKProductionRoutes:
    """针对 api/ck_production_routes.py 的路由级测试（使用 dependency_overrides）。"""

    def _make_app(self, db):
        """每个测试用例创建独立的 FastAPI 实例，注入 mock DB。"""
        app = FastAPI()
        app.include_router(ck_router)

        async def override_get_db():
            yield db

        app.dependency_overrides[ck_get_db] = override_get_db
        return TestClient(app)

    # ── 1. 创建生产工单（正常） ──────────────────────────────────────────────────

    def test_create_production_order_ok(self):
        """POST /api/v1/supply/ck/production-orders — 正常创建，返回 ok=True 及工单数据。"""
        db = _mock_db()

        set_tenant_result = MagicMock()

        # INSERT 返回新工单 ID
        insert_result = MagicMock()
        insert_result.scalar = MagicMock(return_value=ORDER_ID)

        # 查询 BOM（无 BOM 返回 None）
        bom_result = MagicMock()
        bom_result.mappings = MagicMock(return_value=MagicMock(
            first=MagicMock(return_value=None)
        ))

        # INSERT production_item（1 个菜品）
        insert_item_result = MagicMock()

        # _fetch_production_order → SELECT main + SELECT items
        order_row_data = MagicMock()
        order_row_data.__iter__ = MagicMock(return_value=iter([
            ("id", ORDER_ID), ("tenant_id", TENANT_ID),
            ("order_no", "CK-20260404-ABC123"), ("store_id", STORE_ID),
            ("production_date", "2026-04-04"), ("status", "draft"),
            ("total_items", 1), ("completed_items", 0), ("notes", None),
            ("created_at", "2026-04-04T00:00:00"), ("updated_at", "2026-04-04T00:00:00"),
        ]))

        main_mapping = MagicMock()
        main_mapping.first = MagicMock(return_value=order_row_data)
        fetch_main_result = MagicMock()
        fetch_main_result.mappings = MagicMock(return_value=main_mapping)

        items_mapping = MagicMock()
        items_mapping.all = MagicMock(return_value=[])
        fetch_items_result = MagicMock()
        fetch_items_result.mappings = MagicMock(return_value=items_mapping)

        # 顺序：set_tenant, INSERT order, SELECT bom, INSERT item,
        #        (fetch_order) SELECT main, SELECT items
        db.execute.side_effect = [
            set_tenant_result,
            insert_result,
            bom_result,
            insert_item_result,
            fetch_main_result,
            fetch_items_result,
        ]

        client = self._make_app(db)
        body = {
            "store_id": STORE_ID,
            "production_date": "2026-04-04",
            "items": [
                {
                    "dish_id": str(uuid.uuid4()),
                    "dish_name": "红烧肉",
                    "quantity": "10.0",
                    "unit": "份",
                    "estimated_cost_fen": 3000,
                }
            ],
        }
        resp = client.post("/api/v1/supply/ck/production-orders", json=body, headers=HEADERS)

        assert resp.status_code == 201
        assert resp.json()["ok"] is True
        db.commit.assert_awaited_once()

    # ── 2. 查询生产工单列表（正常） ──────────────────────────────────────────────

    def test_list_production_orders_ok(self):
        """GET /api/v1/supply/ck/production-orders — 正常返回分页列表。"""
        db = _mock_db()

        set_tenant_result = MagicMock()

        # COUNT
        count_result = MagicMock()
        count_result.scalar = MagicMock(return_value=1)

        # 列表行数据
        row_data = MagicMock()
        row_data.__iter__ = MagicMock(return_value=iter([
            ("id", ORDER_ID), ("order_no", "CK-20260404-AABBCC"),
            ("store_id", STORE_ID), ("production_date", "2026-04-04"),
            ("status", "draft"), ("total_items", 2),
            ("completed_items", 0), ("notes", None),
            ("created_at", "2026-04-04T00:00:00"),
            ("updated_at", "2026-04-04T00:00:00"),
        ]))
        list_mapping = MagicMock()
        list_mapping.all = MagicMock(return_value=[row_data])
        list_result = MagicMock()
        list_result.mappings = MagicMock(return_value=list_mapping)

        # 顺序：set_tenant, COUNT, SELECT 列表
        db.execute.side_effect = [set_tenant_result, count_result, list_result]

        client = self._make_app(db)
        resp = client.get("/api/v1/supply/ck/production-orders", headers=HEADERS)

        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["total"] == 1
        assert data["page"] == 1
        assert len(data["items"]) == 1

    # ── 3. 推进状态（404：工单不存在） ─────────────────────────────────────────

    def test_update_production_order_status_not_found(self):
        """PATCH /ck/production-orders/{id}/status — 工单不存在 → 404。"""
        db = _mock_db()

        set_tenant_result = MagicMock()

        # SELECT 返回 None（工单不存在）
        not_found_mapping = MagicMock()
        not_found_mapping.first = MagicMock(return_value=None)
        not_found_result = MagicMock()
        not_found_result.mappings = MagicMock(return_value=not_found_mapping)

        db.execute.side_effect = [set_tenant_result, not_found_result]

        client = self._make_app(db)
        fake_order_id = str(uuid.uuid4())
        resp = client.patch(
            f"/api/v1/supply/ck/production-orders/{fake_order_id}/status",
            json={"status": "confirmed"},
            headers=HEADERS,
        )

        assert resp.status_code == 404
        assert "生产工单不存在" in resp.json()["detail"]

    # ── 4. 查询配送单列表（正常，空列表） ───────────────────────────────────────

    def test_list_distribution_orders_empty(self):
        """GET /api/v1/supply/ck/distribution-orders — 无数据时返回空列表。"""
        db = _mock_db()

        set_tenant_result = MagicMock()

        # COUNT → 0
        count_result = MagicMock()
        count_result.scalar = MagicMock(return_value=0)

        # 空列表
        empty_mapping = MagicMock()
        empty_mapping.all = MagicMock(return_value=[])
        empty_result = MagicMock()
        empty_result.mappings = MagicMock(return_value=empty_mapping)

        db.execute.side_effect = [set_tenant_result, count_result, empty_result]

        client = self._make_app(db)
        resp = client.get("/api/v1/supply/ck/distribution-orders", headers=HEADERS)

        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["total"] == 0
        assert data["items"] == []

    # ── 5. DB 错误 → 500 ────────────────────────────────────────────────────────

    def test_list_production_orders_db_error_500(self):
        """GET /api/v1/supply/ck/production-orders — SQLAlchemyError → 500。"""
        db = _mock_db()

        set_tenant_result = MagicMock()
        db_error = SQLAlchemyError("connection refused")
        # 顺序：set_tenant 成功，COUNT 抛 SQLAlchemyError
        db.execute.side_effect = [set_tenant_result, db_error]

        client = self._make_app(db)
        resp = client.get("/api/v1/supply/ck/production-orders", headers=HEADERS)

        assert resp.status_code == 500
        assert "查询失败" in resp.json()["detail"]
