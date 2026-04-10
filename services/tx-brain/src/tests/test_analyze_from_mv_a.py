"""Team A: discount_guardian 和 inventory_sentinel 的 analyze_from_mv 测试"""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from ..agents.discount_guardian import DiscountGuardianAgent
from ..agents.inventory_sentinel import InventorySentinelAgent


# ─── discount_guardian ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_discount_guardian_mv_normal():
    """正常路径：返回 mv_discount_health 数据"""
    agent = DiscountGuardianAgent()

    mock_row = MagicMock()
    mock_row._mapping = {
        "store_id": "store-1",
        "stat_date": "2026-04-04",
        "total_orders": 100,
        "discounted_orders": 20,
        "discount_rate": 0.15,
        "total_discount_fen": 5000,
        "unauthorized_count": 0,
        "leak_types": {},
        "top_operators": [],
        "threshold_breaches": 0,
    }

    mock_result = MagicMock()
    mock_result.mappings.return_value.one_or_none.return_value = mock_row

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=mock_result)

    async def mock_get_db():
        yield mock_db

    with patch("shared.ontology.src.database.get_db", mock_get_db):
        result = await agent.analyze_from_mv("tenant-1", "store-1")

    assert result["inference_layer"] == "mv_fast_path"
    assert result["data"]["total_orders"] == 100
    assert result["data"]["discount_rate"] == 0.15
    assert result["risk_signal"] == "normal"


@pytest.mark.asyncio
async def test_discount_guardian_mv_high_risk():
    """unauthorized_count > 0 时 risk_signal = high"""
    agent = DiscountGuardianAgent()

    mock_row = MagicMock()
    mock_row._mapping = {
        "store_id": "store-1",
        "stat_date": "2026-04-04",
        "total_orders": 80,
        "discounted_orders": 30,
        "discount_rate": 0.25,
        "total_discount_fen": 12000,
        "unauthorized_count": 3,
        "leak_types": {"over_limit": 3},
        "top_operators": [],
        "threshold_breaches": 2,
    }

    mock_result = MagicMock()
    mock_result.mappings.return_value.one_or_none.return_value = mock_row

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=mock_result)

    async def mock_get_db():
        yield mock_db

    with patch("shared.ontology.src.database.get_db", mock_get_db):
        result = await agent.analyze_from_mv("tenant-1", "store-1")

    assert result["risk_signal"] == "high"
    assert result["data"]["unauthorized_count"] == 3


@pytest.mark.asyncio
async def test_discount_guardian_mv_empty():
    """无数据时返回空 data + note"""
    agent = DiscountGuardianAgent()

    mock_result = MagicMock()
    mock_result.mappings.return_value.one_or_none.return_value = None

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=mock_result)

    async def mock_get_db():
        yield mock_db

    with patch("shared.ontology.src.database.get_db", mock_get_db):
        result = await agent.analyze_from_mv("tenant-1")

    assert result["inference_layer"] == "mv_fast_path"
    assert result["data"] == {}
    assert "note" in result


@pytest.mark.asyncio
async def test_discount_guardian_mv_db_error():
    """DB 异常时返回 error 字段"""
    from sqlalchemy.exc import SQLAlchemyError
    agent = DiscountGuardianAgent()

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(side_effect=SQLAlchemyError("DB down"))

    async def mock_get_db():
        yield mock_db

    with patch("shared.ontology.src.database.get_db", mock_get_db):
        result = await agent.analyze_from_mv("tenant-1", "store-1")

    assert result["inference_layer"] == "mv_fast_path_error"
    assert "error" in result


# ─── inventory_sentinel ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_inventory_sentinel_mv_normal():
    """正常路径：返回 mv_inventory_bom 数据"""
    agent = InventorySentinelAgent()

    rows = []
    for i in range(3):
        row = MagicMock()
        row._mapping = {
            "ingredient_id": f"ing-{i}",
            "ingredient_name": f"食材{i}",
            "theoretical_usage_g": 100.0,
            "actual_usage_g": 120.0 if i == 0 else 105.0,
            "waste_g": 5.0,
            "unexplained_loss_g": 15.0 if i == 0 else 0.0,
            "loss_rate": 0.15 if i == 0 else 0.05,
            "stat_date": "2026-04-04",
        }
        rows.append(row)

    mock_result = MagicMock()
    mock_result.mappings.return_value.all.return_value = rows

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=mock_result)

    async def mock_get_db():
        yield mock_db

    with patch("shared.ontology.src.database.get_db", mock_get_db):
        result = await agent.analyze_from_mv("tenant-1", "store-1")

    assert result["inference_layer"] == "mv_fast_path"
    assert result["data"]["total_ingredients"] == 3
    assert result["data"]["high_loss_count"] == 1  # loss_rate=0.15 > 10%


@pytest.mark.asyncio
async def test_inventory_sentinel_mv_high_risk():
    """4个高损耗食材 → risk_signal = high"""
    agent = InventorySentinelAgent()

    rows = []
    for i in range(5):
        row = MagicMock()
        row._mapping = {
            "ingredient_id": f"ing-{i}",
            "ingredient_name": f"食材{i}",
            "theoretical_usage_g": 100.0,
            "actual_usage_g": 125.0,
            "waste_g": 5.0,
            "unexplained_loss_g": 20.0,
            "loss_rate": 0.20,
            "stat_date": "2026-04-04",
        }
        rows.append(row)

    mock_result = MagicMock()
    mock_result.mappings.return_value.all.return_value = rows

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=mock_result)

    async def mock_get_db():
        yield mock_db

    with patch("shared.ontology.src.database.get_db", mock_get_db):
        result = await agent.analyze_from_mv("tenant-1", "store-1")

    assert result["risk_signal"] == "high"
    assert result["data"]["high_loss_count"] == 5


@pytest.mark.asyncio
async def test_inventory_sentinel_mv_empty():
    """无数据时返回空"""
    agent = InventorySentinelAgent()

    mock_result = MagicMock()
    mock_result.mappings.return_value.all.return_value = []

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=mock_result)

    async def mock_get_db():
        yield mock_db

    with patch("shared.ontology.src.database.get_db", mock_get_db):
        result = await agent.analyze_from_mv("tenant-1")

    assert result["inference_layer"] == "mv_fast_path"
    assert result["data"]["total_ingredients"] == 0
    assert result["data"]["high_loss_count"] == 0
    assert result["risk_signal"] == "normal"


@pytest.mark.asyncio
async def test_inventory_sentinel_mv_db_error():
    """DB 异常时返回 error 字段"""
    from sqlalchemy.exc import SQLAlchemyError
    agent = InventorySentinelAgent()

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(side_effect=SQLAlchemyError("timeout"))

    async def mock_get_db():
        yield mock_db

    with patch("shared.ontology.src.database.get_db", mock_get_db):
        result = await agent.analyze_from_mv("tenant-1", "store-1")

    assert result["inference_layer"] == "mv_fast_path_error"
    assert "error" in result
