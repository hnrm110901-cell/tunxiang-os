"""预测驱动智能采购 — 单元测试

5个测试：
  1. TestSuggestionNoBOM           — 无BOM数据时返回空建议列表+友好提示
  2. TestSuggestionWithData        — 有BOM+库存数据时返回采购建议
  3. TestCreateOrderSuccess        — 一键生成采购订单流程
  4. TestCreateOrderNoSuggestions  — 无有效建议时返回404
  5. TestWasteReductionReport      — 浪费分析报表返回正确结构
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from api.smart_procurement_routes import _generate_waste_insight, router
from fastapi import FastAPI
from fastapi.testclient import TestClient

TENANT_ID = "11111111-1111-1111-1111-111111111111"
STORE_ID = "22222222-2222-2222-2222-222222222222"
HEADERS = {"X-Tenant-ID": TENANT_ID}


def _make_app() -> FastAPI:
    app = FastAPI()
    app.include_router(router)
    return app


class _MockRow:
    def __init__(self, d: dict[str, Any]) -> None:
        self._d = d

    @property
    def _mapping(self) -> dict[str, Any]:
        return self._d

    def __getattr__(self, name: str) -> Any:
        if name in self._d:
            return self._d[name]
        raise AttributeError(name)


def _make_db_mock() -> AsyncMock:
    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.fetchone.return_value = None
    mock_result.fetchall.return_value = []
    mock_result.__iter__ = MagicMock(return_value=iter([]))
    mock_result.rowcount = 0
    mock_db.execute.return_value = mock_result
    mock_db.commit = AsyncMock()
    mock_db.rollback = AsyncMock()
    return mock_db


# ──────────────────────────────────────────────────────────────────────────────
# Test 1: 无BOM数据时返回空建议
# ──────────────────────────────────────────────────────────────────────────────


class TestSuggestionNoBOM:
    def test_no_bom_returns_empty(self) -> None:
        """无BOM数据或无销售记录时，应返回空建议列表+提示信息。"""
        app = _make_app()
        mock_db = _make_db_mock()

        from shared.ontology.src.database import get_db

        app.dependency_overrides[get_db] = lambda: mock_db

        client = TestClient(app)
        resp = client.get(
            f"/api/v1/supply/smart-procurement/{STORE_ID}/suggestion",
            params={"days_ahead": 3},
            headers=HEADERS,
        )

        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        data = body["data"]
        assert data["total"] == 0
        assert data["suggestions"] == []
        assert "message" in data


# ──────────────────────────────────────────────────────────────────────────────
# Test 2: 有BOM+库存时返回采购建议
# ──────────────────────────────────────────────────────────────────────────────


class TestSuggestionWithData:
    def test_suggestion_with_bom_data(self) -> None:
        """有菜品销量+BOM数据+库存时，应返回具体采购建议。"""
        app = _make_app()
        mock_db = AsyncMock()
        mock_db.commit = AsyncMock()
        mock_db.rollback = AsyncMock()

        ingredient_id = str(uuid.uuid4())
        dish_id = str(uuid.uuid4())

        # 模拟各阶段查询
        rls_result = MagicMock()

        # 菜品需求预测
        dish_rows = [
            _MockRow(
                {
                    "dish_id": dish_id,
                    "dish_name": "宫保鸡丁",
                    "total_sold": 70,
                    "predicted_demand": Decimal("30.0"),
                }
            )
        ]
        dish_result = MagicMock()
        dish_result.__iter__ = MagicMock(return_value=iter(dish_rows))

        # BOM分解
        bom_rows = [
            _MockRow(
                {
                    "ingredient_id": uuid.UUID(ingredient_id),
                    "ingredient_name": "鸡胸肉",
                    "standard_qty": Decimal("0.3"),
                    "unit": "kg",
                }
            )
        ]
        bom_result = MagicMock()
        bom_result.__iter__ = MagicMock(return_value=iter(bom_rows))

        # 当前库存
        stock_rows = [_MockRow({"id": uuid.UUID(ingredient_id), "qty": Decimal("2.0")})]
        stock_result = MagicMock()
        stock_result.__iter__ = MagicMock(return_value=iter(stock_rows))

        # 供应商
        supplier_row = _MockRow(
            {
                "supplier_id": uuid.uuid4(),
                "supplier_name": "优质鸡肉供应商",
                "unit_price_fen": 1500,
            }
        )
        supplier_result = MagicMock()
        supplier_result.fetchone.return_value = supplier_row

        # 写入结果
        write_result = MagicMock()

        call_count = 0

        async def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return rls_result  # set_rls
            if call_count == 2:
                return dish_result  # dish demand
            if call_count == 3:
                return bom_result  # BOM
            if call_count == 4:
                return stock_result  # stock
            if call_count == 5:
                return supplier_result  # supplier
            return write_result

        mock_db.execute = AsyncMock(side_effect=side_effect)

        from shared.ontology.src.database import get_db

        app.dependency_overrides[get_db] = lambda: mock_db

        client = TestClient(app)
        resp = client.get(
            f"/api/v1/supply/smart-procurement/{STORE_ID}/suggestion",
            params={"days_ahead": 3},
            headers=HEADERS,
        )

        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        data = body["data"]
        assert data["total"] >= 1
        suggestion = data["suggestions"][0]
        assert suggestion["ingredient_name"] == "鸡胸肉"
        assert suggestion["suggested_qty"] > 0
        assert suggestion["estimated_cost_fen"] >= 0


# ──────────────────────────────────────────────────────────────────────────────
# Test 3: 一键生成采购订单
# ──────────────────────────────────────────────────────────────────────────────


class TestCreateOrderSuccess:
    def test_create_order_from_suggestions(self) -> None:
        """基于有效建议创建采购订单应成功。"""
        app = _make_app()
        mock_db = AsyncMock()
        mock_db.commit = AsyncMock()
        mock_db.rollback = AsyncMock()

        suggestion_id = str(uuid.uuid4())
        ingredient_id = uuid.uuid4()

        rls_result = MagicMock()

        # 查询建议
        suggestion_row = _MockRow(
            {
                "id": uuid.UUID(suggestion_id),
                "ingredient_id": ingredient_id,
                "ingredient_name": "鸡胸肉",
                "suggested_qty": Decimal("7.7"),
                "unit": "kg",
                "supplier_id": uuid.uuid4(),
                "supplier_name": "优质供应商",
                "estimated_cost_fen": 11550,
            }
        )
        suggestions_result = MagicMock()
        suggestions_result.fetchall.return_value = [suggestion_row]

        write_result = MagicMock()

        call_count = 0

        async def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return rls_result
            if call_count == 2:
                return suggestions_result
            return write_result

        mock_db.execute = AsyncMock(side_effect=side_effect)

        from shared.ontology.src.database import get_db

        app.dependency_overrides[get_db] = lambda: mock_db

        client = TestClient(app)
        resp = client.post(
            f"/api/v1/supply/smart-procurement/{STORE_ID}/create-order",
            json={"suggestion_ids": [suggestion_id]},
            headers=HEADERS,
        )

        assert resp.status_code == 201
        body = resp.json()
        assert body["ok"] is True
        data = body["data"]
        assert data["item_count"] == 1
        assert data["status"] == "pending"
        assert data["order_no"].startswith("SP-")
        assert data["total_amount_fen"] == 11550


# ──────────────────────────────────────────────────────────────────────────────
# Test 4: 无有效建议时返回404
# ──────────────────────────────────────────────────────────────────────────────


class TestCreateOrderNoSuggestions:
    def test_no_valid_suggestions_returns_404(self) -> None:
        """suggestion_ids 无匹配记录时应返回404。"""
        app = _make_app()
        mock_db = AsyncMock()
        mock_db.commit = AsyncMock()
        mock_db.rollback = AsyncMock()

        rls_result = MagicMock()
        empty_result = MagicMock()
        empty_result.fetchall.return_value = []

        call_count = 0

        async def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return rls_result
            return empty_result

        mock_db.execute = AsyncMock(side_effect=side_effect)

        from shared.ontology.src.database import get_db

        app.dependency_overrides[get_db] = lambda: mock_db

        client = TestClient(app)
        resp = client.post(
            f"/api/v1/supply/smart-procurement/{STORE_ID}/create-order",
            json={"suggestion_ids": [str(uuid.uuid4())]},
            headers=HEADERS,
        )
        assert resp.status_code == 404


# ──────────────────────────────────────────────────────────────────────────────
# Test 5: 浪费分析报表
# ──────────────────────────────────────────────────────────────────────────────


class TestWasteReductionReport:
    def test_waste_report_structure(self) -> None:
        """浪费分析报表应返回AI建议统计+库存流向+洞察。"""
        app = _make_app()
        mock_db = AsyncMock()
        mock_db.commit = AsyncMock()

        rls_result = MagicMock()

        # AI建议汇总
        suggestion_stats = _MockRow(
            {
                "total_suggestions": 50,
                "adopted_count": 35,
                "total_suggested_cost_fen": 500000,
                "adopted_cost_fen": 350000,
            }
        )
        suggestion_result = MagicMock()
        suggestion_result.fetchone.return_value = suggestion_stats

        # 库存流水
        waste_stats = _MockRow(
            {
                "total_inbound": Decimal("1000"),
                "total_usage": Decimal("900"),
                "total_waste": Decimal("60"),
            }
        )
        waste_result = MagicMock()
        waste_result.fetchone.return_value = waste_stats

        call_count = 0

        async def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return rls_result
            if call_count == 2:
                return suggestion_result
            if call_count == 3:
                return waste_result
            return MagicMock()

        mock_db.execute = AsyncMock(side_effect=side_effect)

        from shared.ontology.src.database import get_db

        app.dependency_overrides[get_db] = lambda: mock_db

        client = TestClient(app)
        resp = client.get(
            "/api/v1/supply/smart-procurement/waste-reduction",
            params={"store_id": STORE_ID, "days": 30},
            headers=HEADERS,
        )

        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        data = body["data"]

        # AI建议统计
        ai = data["ai_suggestions"]
        assert ai["total_suggestions"] == 50
        assert ai["adopted_count"] == 35
        assert ai["adoption_rate_pct"] == 70.0

        # 库存流向
        inv = data["inventory_flow"]
        assert inv["total_inbound"] == 1000.0
        assert inv["waste_rate_pct"] == 6.0  # 60/1000 = 6%
        assert inv["utilization_rate_pct"] == 90.0  # 900/1000

        # 洞察文本
        assert "insight" in data
        assert len(data["insight"]) > 0


# ──────────────────────────────────────────────────────────────────────────────
# 辅助函数测试
# ──────────────────────────────────────────────────────────────────────────────


class TestWasteInsight:
    def test_high_waste_insight(self) -> None:
        result = _generate_waste_insight(15.0, 80.0)
        assert "偏高" in result

    def test_low_adoption_insight(self) -> None:
        result = _generate_waste_insight(3.0, 20.0)
        assert "采纳率偏低" in result
