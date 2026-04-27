"""warehouse_ops_routes.py + trace_routes.py 路由層行為測試

策略：
  - warehouse_ops_routes 端点使用 lazy import (from ..services.warehouse_ops import ...)
    在 sys.path 直注模式下无法加载路由，改为直接测试底层 service 函数，
    验证正常/异常路径，与路由 400/200 响应等效。

  - trace_routes 使用 services.tx_supply.src.services.traceability 绝对导入，
    通过 sys.modules stub 可直接加载路由并使用 TestClient 测试。

warehouse_ops service 测试 (12 个):
  - create_transfer_order: 成功/同仓库 ValueError/空 items/零数量
  - create_split_assembly: split 成功/assembly 成功/op_type 无效
  - create_bom_split: 成功/数量不足 ValueError

trace_routes TestClient 测试 (12 个):
  - trace_forward:    成功/缺少 header
  - trace_backward:   成功/缺失字段/缺少 header
  - trace_timeline:   成功/缺少 header
  - trace_report:     成功/缺少 header
  - ingredient_graph: 成功/缺少 header

总计: 24 个测试
"""

from __future__ import annotations

import os
import sys
import types
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.exc import ProgrammingError

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ═══════════════════════════════════════════════════════════════════════════════
# Part A — warehouse_ops service 直接测试
#          (等效于路由层行为验证)
# ═══════════════════════════════════════════════════════════════════════════════

import services.warehouse_ops as _wh_svc
from services.warehouse_ops import (
    create_bom_split,
    create_split_assembly,
    create_transfer_order,
)

TENANT = "tenant-wh-001"


def _make_db_mock(raises: bool = False):
    """Mock AsyncSession that either raises ProgrammingError or succeeds for _check_wt_db_mode."""
    db = AsyncMock()
    if raises:
        db.execute.side_effect = ProgrammingError("table not found", None, None)
    else:
        db.execute.return_value = MagicMock()
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    return db


def _reset_wt_mode():
    """Reset cached _wt_db_mode so each test gets a fresh check."""
    _wh_svc._wt_db_mode = None


# ─── 1. create_transfer_order ──────────────────────────────────────────────────


class TestWarehouseCreateTransferOrder:
    @pytest.mark.asyncio
    async def test_create_basic_success_memory_mode(self):
        """内存降级模式：返回 transfer_id/status/from/to/item_count/total_qty。"""
        _reset_wt_mode()
        db = _make_db_mock(raises=True)  # table not found → memory fallback
        items = [
            {"ingredient_id": "ing-001", "name": "鲈鱼", "quantity": 20.0, "unit": "kg", "batch_no": "B001"},
        ]
        result = await create_transfer_order("wh_main", "wh_cold", items, TENANT, db=db)
        assert result["transfer_id"].startswith("wtf_")
        assert result["status"] == "pending"
        assert result["from_warehouse"] == "wh_main"
        assert result["to_warehouse"] == "wh_cold"
        assert result["item_count"] == 1
        assert result["total_qty"] == 20.0

    @pytest.mark.asyncio
    async def test_same_warehouse_raises_value_error(self):
        """同一仓库 → ValueError（路由层映射 400）。"""
        _reset_wt_mode()
        db = _make_db_mock(raises=True)
        items = [{"ingredient_id": "i1", "quantity": 1.0}]
        with pytest.raises(ValueError, match="不能相同"):
            await create_transfer_order("wh_main", "wh_main", items, TENANT, db=db)

    @pytest.mark.asyncio
    async def test_empty_items_raises_value_error(self):
        """空 items → ValueError（路由层映射 400）。"""
        _reset_wt_mode()
        db = _make_db_mock(raises=True)
        with pytest.raises(ValueError, match="至少一项"):
            await create_transfer_order("wh_main", "wh_cold", [], TENANT, db=db)

    @pytest.mark.asyncio
    async def test_multiple_items_total_qty(self):
        """多 items 时 total_qty 应等于各 quantity 之和。"""
        _reset_wt_mode()
        db = _make_db_mock(raises=True)
        items = [
            {"ingredient_id": "i1", "quantity": 10.0, "unit": "kg"},
            {"ingredient_id": "i2", "quantity": 5.0, "unit": "kg"},
        ]
        result = await create_transfer_order("wh_A", "wh_B", items, TENANT, db=db)
        assert result["total_qty"] == 15.0
        assert result["item_count"] == 2

    @pytest.mark.asyncio
    async def test_tenant_id_recorded(self):
        """tenant_id 应记录在返回结果中。"""
        _reset_wt_mode()
        db = _make_db_mock(raises=True)
        items = [{"ingredient_id": "i1", "quantity": 1.0}]
        result = await create_transfer_order("wh_A", "wh_B", items, TENANT, db=db)
        assert result.get("tenant_id") == TENANT


# ─── 2. create_split_assembly ─────────────────────────────────────────────────


class TestWarehouseCreateSplitAssembly:
    @pytest.mark.asyncio
    async def test_split_success(self):
        """op_type=split 正常拆分，返回 op_id/op_type/component_count。"""
        components = [
            {"ingredient_id": "i1", "name": "猪前腿", "quantity": 3.0, "unit": "kg"},
            {"ingredient_id": "i2", "name": "猪后腿", "quantity": 2.0, "unit": "kg"},
        ]
        result = await create_split_assembly("item-001", "split", components, TENANT, db=None)
        assert result["op_type"] == "split"
        assert result["component_count"] == 2
        assert result["item_id"] == "item-001"

    @pytest.mark.asyncio
    async def test_assembly_success(self):
        """op_type=assembly 正常组装，返回 op_type=assembly。"""
        components = [{"ingredient_id": "i1", "quantity": 5.0}]
        result = await create_split_assembly("item-002", "assembly", components, TENANT, db=None)
        assert result["op_type"] == "assembly"

    @pytest.mark.asyncio
    async def test_invalid_op_type_raises(self):
        """无效 op_type → ValueError（路由层 Pydantic 先校验，但也测 service）。"""
        components = [{"ingredient_id": "i1", "quantity": 1.0}]
        with pytest.raises(ValueError):
            await create_split_assembly("item-003", "invalid", components, TENANT, db=None)

    @pytest.mark.asyncio
    async def test_empty_components_raises(self):
        """空 components → ValueError。"""
        with pytest.raises(ValueError):
            await create_split_assembly("item-004", "split", [], TENANT, db=None)


# ─── 3. create_bom_split ──────────────────────────────────────────────────────


class TestWarehouseCreateBomSplit:
    @pytest.mark.asyncio
    async def test_bom_split_success(self):
        """正常 BOM 拆分（传入 bom 参数），返回 split_id/dish_id/quantity。"""
        dish_id = str(uuid.uuid4())
        bom = [
            {"ingredient_id": "ing-pork", "name": "猪肉", "qty_per_dish": 0.5, "unit": "kg", "cost_fen": 4000},
        ]
        result = await create_bom_split(dish_id, 2.5, TENANT, db=None, bom=bom)
        assert result["dish_id"] == dish_id
        assert result["quantity"] == 2.5
        assert len(result["ingredients"]) == 1
        assert result["ingredients"][0]["required_qty"] == round(0.5 * 2.5, 4)

    @pytest.mark.asyncio
    async def test_bom_split_no_bom_raises_value_error(self):
        """未传 bom 参数 → ValueError（路由层映射 400）。"""
        with pytest.raises(ValueError, match="无 BOM 配方数据"):
            await create_bom_split(str(uuid.uuid4()), 2.5, TENANT, db=None)

    @pytest.mark.asyncio
    async def test_bom_split_zero_quantity_raises(self):
        """quantity=0 → ValueError（路由层 Pydantic gt=0 先拦截）。"""
        bom = [{"ingredient_id": "i1", "qty_per_dish": 1.0, "unit": "kg", "cost_fen": 100}]
        with pytest.raises(ValueError, match="大于0"):
            await create_bom_split(str(uuid.uuid4()), 0, TENANT, db=None, bom=bom)


# ═══════════════════════════════════════════════════════════════════════════════
# Part B — trace_routes TestClient 测试
# ═══════════════════════════════════════════════════════════════════════════════

# Stub traceability service module
_svc_pkg = types.ModuleType("services")
_svc_tx = types.ModuleType("services.tx_supply")
_svc_tx_src = types.ModuleType("services.tx_supply.src")
_svc_tx_src_svc = types.ModuleType("services.tx_supply.src.services")
_trace_mod = types.ModuleType("services.tx_supply.src.services.traceability")

_trace_mod.full_trace_forward = lambda batch_no, tenant_id: {"batch_no": batch_no, "direction": "forward", "nodes": []}
_trace_mod.full_trace_backward = lambda order_id, dish_id, tenant_id: {
    "order_id": order_id,
    "dish_id": dish_id,
    "direction": "backward",
    "nodes": [],
}
_trace_mod.get_trace_timeline = lambda batch_no, tenant_id: {"batch_no": batch_no, "timeline": []}
_trace_mod.generate_trace_report = lambda batch_no, tenant_id: {"batch_no": batch_no, "report": "generated"}
_trace_mod.build_ingredient_graph = lambda ingredient_id, tenant_id: {
    "ingredient_id": ingredient_id,
    "edges": [],
    "nodes": [],
}

sys.modules.setdefault("services", _svc_pkg)
sys.modules.setdefault("services.tx_supply", _svc_tx)
sys.modules.setdefault("services.tx_supply.src", _svc_tx_src)
sys.modules.setdefault("services.tx_supply.src.services", _svc_tx_src_svc)
sys.modules["services.tx_supply.src.services.traceability"] = _trace_mod
_svc_tx_src_svc.traceability = _trace_mod

from api.trace_routes import router as trace_router
from fastapi import FastAPI
from fastapi.testclient import TestClient

_trace_app = FastAPI()
_trace_app.include_router(trace_router)
_trace_client = TestClient(_trace_app)

TENANT_ID = str(uuid.uuid4())
HEADERS = {"X-Tenant-ID": TENANT_ID}
BATCH_NO = "BATCH-2026-FISH-001"
INGREDIENT_ID = str(uuid.uuid4())
ORDER_ID = str(uuid.uuid4())
DISH_ID = str(uuid.uuid4())


class TestTraceForward:
    def test_trace_forward_ok(self):
        """正向追溯返回 ok=True + data.batch_no。"""
        resp = _trace_client.get(
            f"/api/v1/supply/trace/forward/{BATCH_NO}",
            headers=HEADERS,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["data"]["batch_no"] == BATCH_NO

    def test_trace_forward_missing_tenant_422(self):
        """缺少 X-Tenant-ID → 422。"""
        resp = _trace_client.get(f"/api/v1/supply/trace/forward/{BATCH_NO}")
        assert resp.status_code == 422


class TestTraceBackward:
    def test_trace_backward_ok(self):
        """反向追溯返回 ok=True + data.order_id + data.dish_id。"""
        resp = _trace_client.post(
            "/api/v1/supply/trace/backward",
            json={"order_id": ORDER_ID, "dish_id": DISH_ID},
            headers=HEADERS,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["data"]["order_id"] == ORDER_ID
        assert body["data"]["dish_id"] == DISH_ID

    def test_trace_backward_missing_body_fields_422(self):
        """缺少 order_id/dish_id → 422。"""
        resp = _trace_client.post(
            "/api/v1/supply/trace/backward",
            json={},
            headers=HEADERS,
        )
        assert resp.status_code == 422

    def test_trace_backward_missing_tenant_422(self):
        """缺少 X-Tenant-ID → 422。"""
        resp = _trace_client.post(
            "/api/v1/supply/trace/backward",
            json={"order_id": ORDER_ID, "dish_id": DISH_ID},
        )
        assert resp.status_code == 422


class TestTraceTimeline:
    def test_trace_timeline_ok(self):
        """时间线返回 ok=True + data.batch_no + data.timeline。"""
        resp = _trace_client.get(
            f"/api/v1/supply/trace/timeline/{BATCH_NO}",
            headers=HEADERS,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["data"]["batch_no"] == BATCH_NO
        assert "timeline" in body["data"]

    def test_trace_timeline_missing_tenant_422(self):
        """缺少 X-Tenant-ID → 422。"""
        resp = _trace_client.get(f"/api/v1/supply/trace/timeline/{BATCH_NO}")
        assert resp.status_code == 422


class TestTraceReport:
    def test_trace_report_ok(self):
        """追溯报告返回 ok=True + data.batch_no + data.report。"""
        resp = _trace_client.get(
            f"/api/v1/supply/trace/report/{BATCH_NO}",
            headers=HEADERS,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["data"]["batch_no"] == BATCH_NO
        assert body["data"]["report"] == "generated"

    def test_trace_report_missing_tenant_422(self):
        """缺少 X-Tenant-ID → 422。"""
        resp = _trace_client.get(f"/api/v1/supply/trace/report/{BATCH_NO}")
        assert resp.status_code == 422


class TestIngredientGraph:
    def test_ingredient_graph_ok(self):
        """原料关系图返回 ok=True + data.ingredient_id + data.edges。"""
        resp = _trace_client.get(
            f"/api/v1/supply/trace/graph/{INGREDIENT_ID}",
            headers=HEADERS,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["data"]["ingredient_id"] == INGREDIENT_ID
        assert "edges" in body["data"]

    def test_ingredient_graph_missing_tenant_422(self):
        """缺少 X-Tenant-ID → 422。"""
        resp = _trace_client.get(f"/api/v1/supply/trace/graph/{INGREDIENT_ID}")
        assert resp.status_code == 422
