"""库存成本深度分析单元测试 — 使用 mock AsyncSession

覆盖:
  - 库存周转率（正常 / 无消耗）
  - 损耗排行
  - 盘点差异分析
  - 采购偏差
  - 活鲜损耗专项（三分类）
  - 食安风险图谱
"""

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

TENANT_ID = str(uuid.uuid4())
STORE_ID = str(uuid.uuid4())
DATE_RANGE = {"start": "2026-03-01", "end": "2026-03-27"}
INGREDIENT_1 = str(uuid.uuid4())
INGREDIENT_2 = str(uuid.uuid4())


def _mock_session():
    session = AsyncMock()
    session.execute = AsyncMock()
    session.flush = AsyncMock()
    return session


def _make_mapping(data: dict):
    m = MagicMock()
    m.__getitem__ = lambda self, key: data[key]
    m.get = lambda key, default=None: data.get(key, default)
    return m


# ─── 库存周转率 — 正常 ───


@pytest.mark.asyncio
async def test_inventory_turnover_normal():
    """inventory_turnover: 有消耗时计算正确的周转天数"""
    from services.inventory_analysis import inventory_turnover

    session = _mock_session()

    # set_config
    set_config = MagicMock()
    # consumption query: 500000 分 (5000元)
    consumption = MagicMock()
    consumption.scalar.return_value = 500000
    # inventory snapshots: start=200000, end=300000 => avg=250000
    inv_result = MagicMock()
    inv_mappings = MagicMock()
    inv_mappings.first.return_value = _make_mapping(
        {
            "start_cost_fen": 200000,
            "end_cost_fen": 300000,
        }
    )
    inv_result.mappings.return_value = inv_mappings

    session.execute.side_effect = [set_config, consumption, inv_result]

    result = await inventory_turnover(
        store_id=STORE_ID,
        date_range=DATE_RANGE,
        tenant_id=TENANT_ID,
        db=session,
    )

    # 26天, avg_inv=250000, consumption=500000
    # turnover_days = 250000 * 26 / 500000 = 13.0
    assert result["turnover_days"] == 13.0
    assert result["avg_inventory_fen"] == 250000
    assert result["total_consumption_fen"] == 500000
    assert result["days"] == 26


# ─── 库存周转率 — 无消耗 ───


@pytest.mark.asyncio
async def test_inventory_turnover_no_consumption():
    """inventory_turnover: 无消耗时 turnover_days 为 None"""
    from services.inventory_analysis import inventory_turnover

    session = _mock_session()

    set_config = MagicMock()
    consumption = MagicMock()
    consumption.scalar.return_value = 0
    inv_result = MagicMock()
    inv_mappings = MagicMock()
    inv_mappings.first.return_value = _make_mapping(
        {
            "start_cost_fen": 100000,
            "end_cost_fen": 100000,
        }
    )
    inv_result.mappings.return_value = inv_mappings

    session.execute.side_effect = [set_config, consumption, inv_result]

    result = await inventory_turnover(
        store_id=STORE_ID,
        date_range=DATE_RANGE,
        tenant_id=TENANT_ID,
        db=session,
    )

    assert result["turnover_days"] is None
    assert result["total_consumption_fen"] == 0


# ─── 损耗排行 ───


@pytest.mark.asyncio
async def test_waste_ranking():
    """waste_ranking: 返回按金额排序的损耗列表"""
    from services.inventory_analysis import waste_ranking

    session = _mock_session()

    set_config = MagicMock()
    query_result = MagicMock()
    query_mappings = MagicMock()
    query_mappings.all.return_value = [
        _make_mapping(
            {
                "ingredient_id": uuid.UUID(INGREDIENT_1),
                "ingredient_name": "鲍鱼",
                "total_cost_fen": 50000,
                "total_qty": 5.0,
                "frequency": 3,
                "unit": "只",
            }
        ),
        _make_mapping(
            {
                "ingredient_id": uuid.UUID(INGREDIENT_2),
                "ingredient_name": "生菜",
                "total_cost_fen": 2000,
                "total_qty": 10.0,
                "frequency": 7,
                "unit": "kg",
            }
        ),
    ]
    query_result.mappings.return_value = query_mappings

    session.execute.side_effect = [set_config, query_result]

    result = await waste_ranking(
        store_id=STORE_ID,
        date_range=DATE_RANGE,
        tenant_id=TENANT_ID,
        db=session,
    )

    assert result["total_waste_fen"] == 52000
    assert len(result["items"]) == 2
    assert result["items"][0]["rank"] == 1
    assert result["items"][0]["ingredient_name"] == "鲍鱼"


# ─── 盘点差异分析 ───


@pytest.mark.asyncio
async def test_stocktake_variance_analysis():
    """stocktake_variance_analysis: 正确汇总盘盈盘亏"""
    from services.inventory_analysis import stocktake_variance_analysis

    session = _mock_session()

    set_config = MagicMock()
    query_result = MagicMock()
    query_mappings = MagicMock()
    query_mappings.all.return_value = [
        _make_mapping(
            {
                "ingredient_id": uuid.UUID(INGREDIENT_1),
                "ingredient_name": "虾仁",
                "unit": "kg",
                "total_expected": 20.0,
                "total_actual": 18.0,
                "total_variance_qty": -2.0,
                "total_variance_cost_fen": -6000,
                "stocktake_count": 2,
            }
        ),
        _make_mapping(
            {
                "ingredient_id": uuid.UUID(INGREDIENT_2),
                "ingredient_name": "酱油",
                "unit": "瓶",
                "total_expected": 10.0,
                "total_actual": 11.0,
                "total_variance_qty": 1.0,
                "total_variance_cost_fen": 500,
                "stocktake_count": 1,
            }
        ),
    ]
    query_result.mappings.return_value = query_mappings

    session.execute.side_effect = [set_config, query_result]

    result = await stocktake_variance_analysis(
        store_id=STORE_ID,
        date_range=DATE_RANGE,
        tenant_id=TENANT_ID,
        db=session,
    )

    assert result["net_variance_fen"] == -5500
    assert result["shortage_count"] == 1
    assert result["surplus_count"] == 1
    assert len(result["items"]) == 2


# ─── 采购偏差 ───


@pytest.mark.asyncio
async def test_procurement_variance():
    """procurement_variance: 正确计算计划vs实际偏差"""
    from services.inventory_analysis import procurement_variance

    session = _mock_session()

    set_config = MagicMock()
    query_result = MagicMock()
    query_mappings = MagicMock()
    query_mappings.all.return_value = [
        _make_mapping(
            {
                "ingredient_id": uuid.UUID(INGREDIENT_1),
                "ingredient_name": "猪肉",
                "unit": "kg",
                "total_planned": 100.0,
                "total_actual": 110.0,
                "total_planned_cost": 300000,
                "total_actual_cost": 345000,
                "order_count": 5,
            }
        ),
    ]
    query_result.mappings.return_value = query_mappings

    session.execute.side_effect = [set_config, query_result]

    result = await procurement_variance(
        store_id=STORE_ID,
        date_range=DATE_RANGE,
        tenant_id=TENANT_ID,
        db=session,
    )

    assert result["total_variance_fen"] == 45000
    assert len(result["items"]) == 1
    assert result["items"][0]["variance_pct"] == 15.0  # (45000/300000)*100


# ─── 活鲜损耗专项 ───


@pytest.mark.asyncio
async def test_seafood_waste_analysis():
    """seafood_waste_analysis: 按 death/quality_downgrade/alive_loss 三分类"""
    from services.inventory_analysis import seafood_waste_analysis

    session = _mock_session()

    set_config = MagicMock()
    query_result = MagicMock()
    query_mappings = MagicMock()
    query_mappings.all.return_value = [
        _make_mapping(
            {
                "ingredient_id": uuid.UUID(INGREDIENT_1),
                "ingredient_name": "帝王蟹",
                "waste_category": "death",
                "total_qty": 2.0,
                "total_cost_fen": 80000,
                "unit": "只",
                "occurrence_count": 2,
            }
        ),
        _make_mapping(
            {
                "ingredient_id": uuid.UUID(INGREDIENT_2),
                "ingredient_name": "石斑鱼",
                "waste_category": "quality_downgrade",
                "total_qty": 3.0,
                "total_cost_fen": 15000,
                "unit": "条",
                "occurrence_count": 3,
            }
        ),
    ]
    query_result.mappings.return_value = query_mappings

    session.execute.side_effect = [set_config, query_result]

    result = await seafood_waste_analysis(
        store_id=STORE_ID,
        date_range=DATE_RANGE,
        tenant_id=TENANT_ID,
        db=session,
    )

    assert result["grand_total_cost_fen"] == 95000
    assert result["by_category"]["death"]["total_cost_fen"] == 80000
    assert len(result["by_category"]["death"]["items"]) == 1
    assert result["by_category"]["quality_downgrade"]["total_cost_fen"] == 15000
    assert result["by_category"]["alive_loss"]["total_cost_fen"] == 0


# ─── 食安风险图谱 ───


@pytest.mark.asyncio
async def test_food_safety_risk_graph():
    """food_safety_risk_graph: 汇总临期/过期/温度异常/高风险原料"""
    from services.inventory_analysis import food_safety_risk_graph

    session = _mock_session()
    now = datetime.now(timezone.utc)

    set_config = MagicMock()

    # 临期/过期查询
    expiry_result = MagicMock()
    expiry_mappings = MagicMock()
    expiry_mappings.all.return_value = [
        _make_mapping(
            {
                "ingredient_id": uuid.UUID(INGREDIENT_1),
                "ingredient_name": "三文鱼",
                "batch_no": "B202603001",
                "expiry_date": now,
                "qty_on_hand": 5.0,
                "unit": "kg",
                "expiry_status": "expired",
            }
        ),
    ]
    expiry_result.mappings.return_value = expiry_mappings

    # 温度异常查询
    temp_result = MagicMock()
    temp_mappings = MagicMock()
    temp_mappings.all.return_value = []
    temp_result.mappings.return_value = temp_mappings

    # 高风险原料查询
    risk_result = MagicMock()
    risk_mappings = MagicMock()
    risk_mappings.all.return_value = []
    risk_result.mappings.return_value = risk_mappings

    session.execute.side_effect = [set_config, expiry_result, temp_result, risk_result]

    result = await food_safety_risk_graph(
        store_id=STORE_ID,
        tenant_id=TENANT_ID,
        db=session,
    )

    assert result["expiry_risks"]["expired_count"] == 1
    assert result["risk_score"] >= 20  # 1 expired * 20 = 20
    assert "store_id" in result
