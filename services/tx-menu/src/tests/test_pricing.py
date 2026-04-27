"""定价中心测试 — 覆盖全部8个核心场景

使用 mock DB 模拟 SQLAlchemy AsyncSession，验证 PricingEngine 逻辑。
"""

import uuid
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from ..services.pricing_engine import DEFAULT_MIN_MARGIN_RATE, PricingEngine

# ─── Fixtures ───

TENANT_ID = str(uuid.uuid4())
DISH_ID = str(uuid.uuid4())


def _make_engine(db_mock: AsyncMock) -> PricingEngine:
    return PricingEngine(db=db_mock, tenant_id=TENANT_ID)


def _mock_db() -> AsyncMock:
    """创建一个模拟的 AsyncSession"""
    db = AsyncMock()
    db.execute = AsyncMock()
    db.flush = AsyncMock()
    return db


def _mapping_result(rows: list[dict]):
    """模拟 result.mappings().first() 或 .all()"""
    mock_result = MagicMock()
    mock_mappings = MagicMock()
    mock_mappings.first.return_value = rows[0] if rows else None
    mock_mappings.all.return_value = rows
    mock_result.mappings.return_value = mock_mappings
    mock_result.scalar_one_or_none.return_value = rows[0].get("_scalar") if rows else None
    return mock_result


def _scalar_result(value):
    """模拟 result.scalar_one_or_none()"""
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = value
    mock_result.mappings.return_value = MagicMock(first=MagicMock(return_value=None))
    return mock_result


# ─── 1. 标准定价 — 返回基础售价 ───


@pytest.mark.asyncio
async def test_get_standard_price_base():
    """无时价/渠道价/促销价时，返回基础售价"""
    db = _mock_db()
    engine = _make_engine(db)

    # 四次查询: set_tenant, market_price(空), channel(空), promo(空), base_price
    db.execute.side_effect = [
        AsyncMock(),  # set_tenant
        _mapping_result([]),  # market_price -> 空
        _scalar_result(None),  # channel_price -> 空
        _scalar_result(None),  # promo_price -> 空
        _scalar_result(5800),  # base_price -> 5800 分
    ]

    result = await engine.get_standard_price(DISH_ID, "dine_in")

    assert result["dish_id"] == DISH_ID
    assert result["price_fen"] == 5800
    assert result["price_type"] == "base"
    assert result["channel"] == "dine_in"


# ─── 2. 时价查询 — 海鲜时价优先 ───


@pytest.mark.asyncio
async def test_get_standard_price_market():
    """有生效中的时价时，优先返回时价"""
    db = _mock_db()
    engine = _make_engine(db)

    db.execute.side_effect = [
        AsyncMock(),  # set_tenant
        _mapping_result(
            [
                {  # market_price -> 有效
                    "price_fen": 12800,
                    "effective_from": datetime.utcnow(),
                }
            ]
        ),
    ]

    result = await engine.get_standard_price(DISH_ID, "dine_in")

    assert result["price_fen"] == 12800
    assert result["price_type"] == "market"


# ─── 3. 设置时价 ───


@pytest.mark.asyncio
async def test_set_market_price():
    """设置海鲜时价"""
    db = _mock_db()
    engine = _make_engine(db)

    db.execute.side_effect = [
        AsyncMock(),  # set_tenant
        AsyncMock(),  # INSERT
    ]

    effective = datetime(2026, 3, 27, 8, 0, 0)
    result = await engine.set_market_price(DISH_ID, 15000, effective)

    assert result["dish_id"] == DISH_ID
    assert result["price_fen"] == 15000
    assert "id" in result


@pytest.mark.asyncio
async def test_set_market_price_invalid():
    """时价不能为负"""
    db = _mock_db()
    engine = _make_engine(db)

    with pytest.raises(ValueError, match="price_fen must be positive"):
        await engine.set_market_price(DISH_ID, -100, datetime.utcnow())


# ─── 4. 称重计价 ───


@pytest.mark.asyncio
async def test_calculate_weighing_price():
    """称重计价：单价 6800分/500g，重量 750g -> 10200分"""
    db = _mock_db()
    engine = _make_engine(db)

    db.execute.side_effect = [
        AsyncMock(),  # set_tenant
        _mapping_result(
            [
                {  # dish info
                    "price_fen": 6800,
                    "unit": "斤",
                }
            ]
        ),
    ]

    result = await engine.calculate_weighing_price(DISH_ID, 750)

    assert result["dish_id"] == DISH_ID
    assert result["weight_g"] == 750
    assert result["unit_price_fen_per_500g"] == 6800
    # 6800 * 750 / 500 = 10200
    assert result["total_price_fen"] == 10200


@pytest.mark.asyncio
async def test_calculate_weighing_price_invalid_weight():
    """重量不能为 0 或负数"""
    db = _mock_db()
    engine = _make_engine(db)

    with pytest.raises(ValueError, match="weight_g must be positive"):
        await engine.calculate_weighing_price(DISH_ID, 0)


# ─── 5. 套餐组合定价 ───


@pytest.mark.asyncio
async def test_create_combo_price():
    """套餐定价：两道菜合计 10000 分，85 折 = 8500 分"""
    db = _mock_db()
    engine = _make_engine(db)

    dish_a = str(uuid.uuid4())
    dish_b = str(uuid.uuid4())

    db.execute.side_effect = [
        AsyncMock(),  # set_tenant
        _mapping_result(
            [
                {  # dish_a
                    "price_fen": 5800,
                    "dish_name": "宫保鸡丁",
                }
            ]
        ),
        _mapping_result(
            [
                {  # dish_b
                    "price_fen": 4200,
                    "dish_name": "麻婆豆腐",
                }
            ]
        ),
    ]

    result = await engine.create_combo_price(
        dishes_with_qty=[
            {"dish_id": dish_a, "quantity": 1},
            {"dish_id": dish_b, "quantity": 1},
        ],
        discount_rate=0.85,
    )

    assert result["original_total_fen"] == 10000
    assert result["discount_rate"] == 0.85
    assert result["combo_price_fen"] == 8500
    assert result["saving_fen"] == 1500
    assert len(result["items"]) == 2


# ─── 6. 毛利校验通过 ───


@pytest.mark.asyncio
async def test_validate_margin_passed():
    """售价 10000 分，成本 5000 分，毛利率 50% >= 30%，通过"""
    db = _mock_db()
    engine = _make_engine(db)

    # set_tenant + BOM查询(无BOM) + 回退到 dishes.cost_fen
    db.execute.side_effect = [
        AsyncMock(),  # set_tenant (validate_margin)
        AsyncMock(),  # set_tenant (_get_dish_cost)
        _mapping_result([]),  # BOM -> 空
        _scalar_result(5000),  # dishes.cost_fen -> 5000
    ]

    result = await engine.validate_margin(DISH_ID, 10000)

    assert result["passed"] is True
    assert result["theoretical_cost_fen"] == 5000
    assert result["margin_rate"] == 0.5
    assert result["min_margin_rate"] == DEFAULT_MIN_MARGIN_RATE


# ─── 7. 毛利校验不通过 ───


@pytest.mark.asyncio
async def test_validate_margin_failed():
    """售价 6000 分，成本 5000 分，毛利率 16.7% < 30%，不通过"""
    db = _mock_db()
    engine = _make_engine(db)

    db.execute.side_effect = [
        AsyncMock(),  # set_tenant (validate_margin)
        AsyncMock(),  # set_tenant (_get_dish_cost)
        _mapping_result([]),  # BOM -> 空
        _scalar_result(5000),  # dishes.cost_fen -> 5000
    ]

    result = await engine.validate_margin(DISH_ID, 6000)

    assert result["passed"] is False
    assert result["theoretical_cost_fen"] == 5000
    # 毛利率: (6000-5000)/6000 = 0.1667
    assert result["margin_rate"] == round((6000 - 5000) / 6000, 4)
    # 最低售价: 5000 / (1 - 0.30) = 7143
    assert result["min_price_fen"] == 7143


# ─── 8. 促销价设置 ───


@pytest.mark.asyncio
async def test_set_promotion_price():
    """设置限时促销价"""
    db = _mock_db()
    engine = _make_engine(db)

    db.execute.side_effect = [
        AsyncMock(),  # set_tenant
        AsyncMock(),  # INSERT
    ]

    start = datetime(2026, 4, 1, 0, 0, 0)
    end = datetime(2026, 4, 7, 23, 59, 59)
    result = await engine.set_promotion_price(DISH_ID, 3900, start, end)

    assert result["dish_id"] == DISH_ID
    assert result["promo_price_fen"] == 3900
    assert "id" in result


@pytest.mark.asyncio
async def test_set_promotion_price_invalid_time():
    """促销结束时间不能早于开始时间"""
    db = _mock_db()
    engine = _make_engine(db)

    start = datetime(2026, 4, 7)
    end = datetime(2026, 4, 1)

    with pytest.raises(ValueError, match="end must be after start"):
        await engine.set_promotion_price(DISH_ID, 3900, start, end)


# ─── 9. 多渠道差异价 ───


@pytest.mark.asyncio
async def test_set_channel_price():
    """设置多渠道差异价"""
    db = _mock_db()
    engine = _make_engine(db)

    db.execute.side_effect = [
        AsyncMock(),  # set_tenant
        AsyncMock(),  # UPSERT dine_in
        AsyncMock(),  # UPSERT takeaway
        AsyncMock(),  # UPSERT delivery
    ]

    channel_prices = {"dine_in": 5800, "takeaway": 5500, "delivery": 6200}
    result = await engine.set_channel_price(DISH_ID, channel_prices)

    assert result["dish_id"] == DISH_ID
    assert result["channels"] == channel_prices


# ─── 10. 称重计价 — 精确到分 ───


@pytest.mark.asyncio
async def test_weighing_price_rounding():
    """称重计价四舍五入：6800分/500g * 333g / 500 = 4528.8 -> 4529分"""
    db = _mock_db()
    engine = _make_engine(db)

    db.execute.side_effect = [
        AsyncMock(),
        _mapping_result([{"price_fen": 6800, "unit": "斤"}]),
    ]

    result = await engine.calculate_weighing_price(DISH_ID, 333)

    # 6800 * 333 / 500 = 4528.8 -> 4529
    assert result["total_price_fen"] == 4529
