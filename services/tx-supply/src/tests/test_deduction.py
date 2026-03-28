"""自动扣料引擎 + 盘点服务 + 损耗归因 测试

测试策略：
- 扣料引擎核心逻辑：BOM查找、库存扣减、不足告警、回滚
- 盘点服务：创建/录入/完成/差异报告
- 损耗归因：多维度分析
- 使用 Mock 代替真实 DB
"""
import sys
import os
import uuid
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Fixtures / Helpers
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

TENANT_ID = str(uuid.uuid4())
STORE_ID = str(uuid.uuid4())
DISH_ID = str(uuid.uuid4())
ORDER_ID = str(uuid.uuid4())
ING_ID_1 = str(uuid.uuid4())
ING_ID_2 = str(uuid.uuid4())


def _make_ingredient(ing_id: str, name: str, qty: float, unit_price_fen: int = 1000):
    """创建模拟 Ingredient 对象"""
    ing = MagicMock()
    ing.id = uuid.UUID(ing_id)
    ing.ingredient_name = name
    ing.category = "meat"
    ing.unit = "kg"
    ing.current_quantity = qty
    ing.min_quantity = 1.0
    ing.max_quantity = 100.0
    ing.unit_price_fen = unit_price_fen
    ing.status = "normal"
    ing.is_deleted = False
    return ing


def _make_bom_line(ing_id: str, quantity: float, unit: str = "kg"):
    """创建模拟 DishIngredient 对象"""
    line = MagicMock()
    line.ingredient_id = ing_id
    line.quantity = quantity
    line.unit = unit
    line.is_deleted = False
    line.tenant_id = uuid.UUID(TENANT_ID)
    line.dish_id = uuid.UUID(DISH_ID)
    return line


def _make_consume_txn(ing_id: str, qty: float, order_id: str):
    """创建模拟 consume 类型流水"""
    txn = MagicMock()
    txn.id = uuid.uuid4()
    txn.ingredient_id = uuid.UUID(ing_id)
    txn.store_id = uuid.UUID(STORE_ID)
    txn.transaction_type = "consume"
    txn.quantity = -qty  # consume 为负数
    txn.unit_cost_fen = 1000
    txn.reference_id = order_id
    txn.notes = f"BOM扣料: dish={DISH_ID}, qty=1"
    txn.is_deleted = False
    return txn


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Test: auto_deduction._calc_status
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestCalcStatus:
    """库存状态计算纯函数测试"""

    def test_normal_stock(self):
        from services.auto_deduction import _calc_status
        assert _calc_status(10.0, 5.0) == "normal"

    def test_low_stock(self):
        from services.auto_deduction import _calc_status
        assert _calc_status(4.0, 5.0) == "low"

    def test_critical_stock(self):
        from services.auto_deduction import _calc_status
        # min_qty=10, 0.3*10=3, current=2 < 3 → critical
        assert _calc_status(2.0, 10.0) == "critical"

    def test_out_of_stock(self):
        from services.auto_deduction import _calc_status
        assert _calc_status(0.0, 5.0) == "out_of_stock"

    def test_negative_stock(self):
        from services.auto_deduction import _calc_status
        assert _calc_status(-1.0, 5.0) == "out_of_stock"

    def test_exact_min_boundary(self):
        from services.auto_deduction import _calc_status
        # current == min_qty → low
        assert _calc_status(5.0, 5.0) == "low"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Test: auto_deduction._get_bom_for_dish
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestGetBomForDish:
    """BOM 查找逻辑测试"""

    @pytest.mark.asyncio
    async def test_returns_bom_lines(self):
        from services.auto_deduction import _get_bom_for_dish

        bom_line = _make_bom_line(ING_ID_1, 0.5)

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [bom_line]

        db = AsyncMock()
        db.execute.return_value = mock_result

        result = await _get_bom_for_dish(db, uuid.UUID(DISH_ID), uuid.UUID(TENANT_ID))

        assert len(result) == 1
        assert result[0]["ingredient_id"] == ING_ID_1
        assert result[0]["quantity"] == 0.5

    @pytest.mark.asyncio
    async def test_empty_bom(self):
        from services.auto_deduction import _get_bom_for_dish

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []

        db = AsyncMock()
        db.execute.return_value = mock_result

        result = await _get_bom_for_dish(db, uuid.UUID(DISH_ID), uuid.UUID(TENANT_ID))
        assert result == []


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Test: stocktake_service (in-memory)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestStocktakeService:
    """盘点服务完整流程测试（使用内存缓存）"""

    @pytest.mark.asyncio
    async def test_create_stocktake(self):
        from services.stocktake_service import create_stocktake, _stocktakes

        # 清理内存
        _stocktakes.clear()

        ing = _make_ingredient(ING_ID_1, "猪肉", 10.0, 4000)

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [ing]

        db = AsyncMock()
        db.execute.return_value = mock_result

        result = await create_stocktake(STORE_ID, TENANT_ID, db)

        assert result["ok"] is True
        assert result["status"] == "open"
        assert result["item_count"] == 1
        assert len(_stocktakes) == 1

    @pytest.mark.asyncio
    async def test_record_count(self):
        from services.stocktake_service import (
            create_stocktake, record_count, _stocktakes,
        )

        _stocktakes.clear()

        ing = _make_ingredient(ING_ID_1, "猪肉", 10.0, 4000)

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [ing]

        db = AsyncMock()
        db.execute.return_value = mock_result

        create_result = await create_stocktake(STORE_ID, TENANT_ID, db)
        st_id = create_result["stocktake_id"]

        count_result = await record_count(st_id, ING_ID_1, 8.5, TENANT_ID, db)

        assert count_result["ok"] is True
        assert count_result["actual_qty"] == 8.5
        assert count_result["variance"] == -1.5  # 8.5 - 10.0

    @pytest.mark.asyncio
    async def test_record_count_wrong_tenant(self):
        from services.stocktake_service import (
            create_stocktake, record_count, _stocktakes,
        )

        _stocktakes.clear()

        ing = _make_ingredient(ING_ID_1, "猪肉", 10.0, 4000)
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [ing]

        db = AsyncMock()
        db.execute.return_value = mock_result

        create_result = await create_stocktake(STORE_ID, TENANT_ID, db)
        st_id = create_result["stocktake_id"]

        wrong_tenant = str(uuid.uuid4())
        count_result = await record_count(st_id, ING_ID_1, 8.5, wrong_tenant, db)

        assert count_result["ok"] is False
        assert "Tenant" in count_result["error"]

    @pytest.mark.asyncio
    async def test_record_count_not_found(self):
        from services.stocktake_service import record_count

        result = await record_count("nonexistent", ING_ID_1, 8.5, TENANT_ID, AsyncMock())

        assert result["ok"] is False
        assert "not found" in result["error"]


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Test: API routes (FastAPI TestClient)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestDeductionRoutes:
    """API 路由基础测试"""

    def _get_client(self):
        from fastapi.testclient import TestClient
        from fastapi import FastAPI
        from api.deduction_routes import router

        app = FastAPI()
        app.include_router(router)
        return TestClient(app)

    def test_deduct_order_endpoint(self):
        client = self._get_client()
        response = client.post(
            f"/api/v1/supply/deduction/order/{ORDER_ID}",
            json={
                "store_id": STORE_ID,
                "order_items": [
                    {"dish_id": DISH_ID, "quantity": 2, "item_name": "宫保鸡丁"},
                ],
            },
            headers={"X-Tenant-ID": TENANT_ID},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True
        assert data["data"]["order_id"] == ORDER_ID

    def test_rollback_endpoint(self):
        client = self._get_client()
        response = client.post(
            f"/api/v1/supply/deduction/rollback/{ORDER_ID}",
            headers={"X-Tenant-ID": TENANT_ID},
        )
        assert response.status_code == 200
        assert response.json()["ok"] is True

    def test_stocktake_create_endpoint(self):
        client = self._get_client()
        response = client.post(
            f"/api/v1/supply/stocktake?store_id={STORE_ID}",
            headers={"X-Tenant-ID": TENANT_ID},
        )
        assert response.status_code == 200
        assert response.json()["ok"] is True

    def test_waste_analysis_endpoint(self):
        client = self._get_client()
        response = client.get(
            "/api/v1/supply/waste/analysis",
            params={
                "store_id": STORE_ID,
                "date_from": "2026-03-01",
                "date_to": "2026-03-27",
            },
            headers={"X-Tenant-ID": TENANT_ID},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True
        assert "by_type" in data["data"]
        assert "by_ingredient" in data["data"]

    def test_waste_top_items_endpoint(self):
        client = self._get_client()
        response = client.get(
            "/api/v1/supply/waste/top-items",
            params={"store_id": STORE_ID, "limit": 5, "days": 30},
            headers={"X-Tenant-ID": TENANT_ID},
        )
        assert response.status_code == 200
        assert response.json()["ok"] is True

    def test_missing_tenant_header(self):
        """缺少 X-Tenant-ID 应报 422"""
        client = self._get_client()
        response = client.post(
            f"/api/v1/supply/deduction/order/{ORDER_ID}",
            json={
                "store_id": STORE_ID,
                "order_items": [],
            },
        )
        assert response.status_code == 422
