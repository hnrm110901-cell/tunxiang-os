"""CostEngine 单元测试

测试覆盖：
1. 单笔订单成本追溯：order_id → 各菜品成本 → 毛利率
2. BOM层级成本归集（套餐含多种配料）
3. 损耗率应用（库存成本 × 产出率）
4. 无BOM数据时fallback到菜品标准成本
5. tenant_id隔离
"""
import uuid
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from services.tx_finance.src.services.cost_engine import (
    CostEngine,
    OrderCostResult,
)

# ─── Fixtures ────────────────────────────────────────────────────────────────

TENANT_A = uuid.uuid4()
TENANT_B = uuid.uuid4()
ORDER_ID = uuid.uuid4()
DISH_ID_1 = uuid.uuid4()
DISH_ID_2 = uuid.uuid4()
ORDER_ITEM_ID_1 = uuid.uuid4()
ORDER_ITEM_ID_2 = uuid.uuid4()
BOM_ID = uuid.uuid4()


def _make_order_item(item_id, dish_id, qty, price_fen, std_cost_fen=None):
    """构造模拟 OrderItem 行"""
    item = MagicMock()
    item.id = item_id
    item.dish_id = dish_id
    item.quantity = qty
    item.unit_price_fen = price_fen
    item.cost_fen = std_cost_fen or (price_fen // 3)
    return item


def _make_bom(bom_id, dish_id, yield_rate, ingredients):
    """构造模拟 BOM 模板，ingredients = [(ingredient_id, qty, unit_cost_fen)]"""
    bom = MagicMock()
    bom.id = bom_id
    bom.dish_id = dish_id
    bom.yield_rate = yield_rate

    items = []
    for ing_id, qty, unit_cost_fen in ingredients:
        item = MagicMock()
        item.ingredient_id = ing_id
        item.standard_qty = qty
        item.unit_cost_fen = unit_cost_fen
        items.append(item)

    bom.items = items
    return bom


# ─── Test 1: 单笔订单成本追溯 ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_compute_order_cost_basic():
    """单笔订单：1道菜，有BOM，验证成本与毛利率计算正确"""
    engine = CostEngine()
    db = AsyncMock()

    ingredient_id = uuid.uuid4()
    bom = _make_bom(
        bom_id=BOM_ID,
        dish_id=DISH_ID_1,
        yield_rate=1.0,
        ingredients=[(ingredient_id, 0.5, 2000)],  # 0.5kg × 20元/kg = 10元
    )
    order_items = [
        _make_order_item(ORDER_ITEM_ID_1, DISH_ID_1, qty=1, price_fen=5000),  # 卖价 50元
    ]

    with patch.object(engine, "_fetch_order_items", new=AsyncMock(return_value=order_items)), \
         patch.object(engine, "_fetch_active_bom", new=AsyncMock(return_value=bom)), \
         patch.object(engine, "_save_cost_snapshots", new=AsyncMock()):

        result = await engine.compute_order_cost(
            order_id=ORDER_ID,
            tenant_id=TENANT_A,
            db=db,
        )

    assert isinstance(result, OrderCostResult)
    assert result.order_id == ORDER_ID
    assert len(result.items) == 1

    dish_cost = result.items[0]
    # 配料成本 = 0.5 × 2000 / 1.0 = 1000 fen
    assert dish_cost.raw_material_cost == Decimal("1000")
    # 毛利率 = (5000 - 1000) / 5000 = 0.8
    assert dish_cost.gross_margin_rate == pytest.approx(Decimal("0.8"))
    assert result.total_cost > 0


# ─── Test 2: BOM层级成本归集（套餐含多种配料）────────────────────────────────

@pytest.mark.asyncio
async def test_bom_multi_ingredient_aggregation():
    """套餐含3种配料，验证总成本 = sum(各配料成本)"""
    engine = CostEngine()
    db = AsyncMock()

    ing_a, ing_b, ing_c = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    # 配料成本：1000 + 500 + 300 = 1800 fen
    bom = _make_bom(
        bom_id=BOM_ID,
        dish_id=DISH_ID_1,
        yield_rate=1.0,
        ingredients=[
            (ing_a, 1.0, 1000),
            (ing_b, 0.5, 1000),   # 0.5 × 1000 = 500
            (ing_c, 0.3, 1000),   # 0.3 × 1000 = 300
        ],
    )
    order_items = [
        _make_order_item(ORDER_ITEM_ID_1, DISH_ID_1, qty=1, price_fen=8000),
    ]

    with patch.object(engine, "_fetch_order_items", new=AsyncMock(return_value=order_items)), \
         patch.object(engine, "_fetch_active_bom", new=AsyncMock(return_value=bom)), \
         patch.object(engine, "_save_cost_snapshots", new=AsyncMock()):

        result = await engine.compute_order_cost(ORDER_ID, TENANT_A, db)

    dish_cost = result.items[0]
    assert dish_cost.raw_material_cost == Decimal("1800")


# ─── Test 3: 损耗率应用（库存成本 × 产出率）──────────────────────────────────

@pytest.mark.asyncio
async def test_yield_rate_applied():
    """yield_rate=0.8 时，成本 = qty × unit_cost / yield_rate（损耗放大成本）"""
    engine = CostEngine()
    db = AsyncMock()

    ingredient_id = uuid.uuid4()
    # yield_rate=0.8 表示原料有20%损耗
    bom = _make_bom(
        bom_id=BOM_ID,
        dish_id=DISH_ID_1,
        yield_rate=0.8,
        ingredients=[(ingredient_id, 1.0, 1000)],  # 需要1kg，但要买1.25kg
    )
    order_items = [
        _make_order_item(ORDER_ITEM_ID_1, DISH_ID_1, qty=1, price_fen=5000),
    ]

    with patch.object(engine, "_fetch_order_items", new=AsyncMock(return_value=order_items)), \
         patch.object(engine, "_fetch_active_bom", new=AsyncMock(return_value=bom)), \
         patch.object(engine, "_save_cost_snapshots", new=AsyncMock()):

        result = await engine.compute_order_cost(ORDER_ID, TENANT_A, db)

    dish_cost = result.items[0]
    # 成本 = 1.0 × 1000 / 0.8 = 1250 fen
    assert dish_cost.raw_material_cost == pytest.approx(Decimal("1250"), abs=Decimal("1"))


# ─── Test 4: 无BOM时fallback到菜品标准成本 ───────────────────────────────────

@pytest.mark.asyncio
async def test_fallback_to_standard_cost_when_no_bom():
    """无激活BOM时，fallback使用 OrderItem.cost_fen 作为标准成本"""
    engine = CostEngine()
    db = AsyncMock()

    std_cost_fen = 1500
    order_items = [
        _make_order_item(ORDER_ITEM_ID_1, DISH_ID_1, qty=1,
                         price_fen=5000, std_cost_fen=std_cost_fen),
    ]

    with patch.object(engine, "_fetch_order_items", new=AsyncMock(return_value=order_items)), \
         patch.object(engine, "_fetch_active_bom", new=AsyncMock(return_value=None)), \
         patch.object(engine, "_save_cost_snapshots", new=AsyncMock()):

        result = await engine.compute_order_cost(ORDER_ID, TENANT_A, db)

    dish_cost = result.items[0]
    # fallback：raw_material_cost = cost_fen（分）转换为 Decimal
    assert dish_cost.raw_material_cost == Decimal(str(std_cost_fen))
    assert dish_cost.bom_version_id is None


# ─── Test 5: tenant_id 隔离 ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_tenant_isolation():
    """不同 tenant_id 的成本快照不能混用，_fetch_order_items 必须携带 tenant_id"""
    engine = CostEngine()
    db_a = AsyncMock()
    db_b = AsyncMock()

    calls_a = []
    calls_b = []

    async def mock_fetch_a(order_id, tenant_id, db):
        calls_a.append(tenant_id)
        return []

    async def mock_fetch_b(order_id, tenant_id, db):
        calls_b.append(tenant_id)
        return []

    with patch.object(engine, "_fetch_order_items", new=mock_fetch_a):
        await engine.compute_order_cost(ORDER_ID, TENANT_A, db_a)

    with patch.object(engine, "_fetch_order_items", new=mock_fetch_b):
        await engine.compute_order_cost(ORDER_ID, TENANT_B, db_b)

    assert calls_a[0] == TENANT_A
    assert calls_b[0] == TENANT_B
    assert calls_a[0] != calls_b[0]


# ─── Test 6: get_order_margin 从快照查询 ─────────────────────────────────────

@pytest.mark.asyncio
async def test_get_order_margin_from_snapshot():
    """get_order_margin 优先从 cost_snapshots 返回缓存结果"""
    engine = CostEngine()
    db = AsyncMock()

    snapshot_data = {
        "order_id": str(ORDER_ID),
        "total_cost": Decimal("1800"),
        "selling_price": Decimal("5000"),
        "gross_margin_rate": Decimal("0.64"),
        "computed_at": "2026-03-30T10:00:00Z",
    }

    with patch.object(engine, "_fetch_cost_snapshot", new=AsyncMock(return_value=snapshot_data)):
        result = await engine.get_order_margin(ORDER_ID, TENANT_A, db)

    assert result["order_id"] == str(ORDER_ID)
    assert result["gross_margin_rate"] == Decimal("0.64")


# ─── Test 7: 多菜品订单汇总 ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_multi_dish_order_total():
    """2道菜的订单，total_cost = 各菜成本之和"""
    engine = CostEngine()
    db = AsyncMock()

    ing1, ing2 = uuid.uuid4(), uuid.uuid4()
    bom1 = _make_bom(BOM_ID, DISH_ID_1, 1.0, [(ing1, 1.0, 1000)])
    bom2 = _make_bom(uuid.uuid4(), DISH_ID_2, 1.0, [(ing2, 2.0, 500)])  # 2 × 500 = 1000

    order_items = [
        _make_order_item(ORDER_ITEM_ID_1, DISH_ID_1, qty=1, price_fen=4000),
        _make_order_item(ORDER_ITEM_ID_2, DISH_ID_2, qty=2, price_fen=3000),
    ]

    bom_map = {DISH_ID_1: bom1, DISH_ID_2: bom2}

    async def mock_fetch_bom(dish_id, tenant_id, db):
        return bom_map.get(dish_id)

    with patch.object(engine, "_fetch_order_items", new=AsyncMock(return_value=order_items)), \
         patch.object(engine, "_fetch_active_bom", new=mock_fetch_bom), \
         patch.object(engine, "_save_cost_snapshots", new=AsyncMock()):

        result = await engine.compute_order_cost(ORDER_ID, TENANT_A, db)

    # dish1: 1000, dish2: 1.0×2qty×1000 = 2000 => total=3000
    assert result.total_cost == Decimal("3000")
    assert len(result.items) == 2


# ─── Test 8: batch_recompute_date 调用次数 ───────────────────────────────────

@pytest.mark.asyncio
async def test_batch_recompute_date():
    """batch_recompute_date 对每笔订单都调用一次 compute_order_cost"""
    from datetime import date

    engine = CostEngine()
    db = AsyncMock()
    store_id = uuid.uuid4()
    biz_date = date(2026, 3, 30)

    order_ids = [uuid.uuid4(), uuid.uuid4(), uuid.uuid4()]

    with patch.object(engine, "_fetch_order_ids_by_date",
                      new=AsyncMock(return_value=order_ids)), \
         patch.object(engine, "compute_order_cost",
                      new=AsyncMock(return_value=MagicMock())) as mock_compute:

        await engine.batch_recompute_date(store_id, biz_date, TENANT_A, db)

    assert mock_compute.call_count == len(order_ids)
