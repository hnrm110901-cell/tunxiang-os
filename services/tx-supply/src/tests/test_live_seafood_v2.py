"""活鲜库存 V2 测试 -- track_live_status / calculate_live_loss / get_tank_inventory / price_by_weight / get_seafood_dashboard / warehouse / transfer

使用 SQLite 内存数据库模拟 PostgreSQL。
"""
import uuid
from datetime import date, datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker

from shared.ontology.src.base import TenantBase
from shared.ontology.src.entities import Ingredient, IngredientTransaction
from shared.ontology.src.enums import InventoryStatus, TransactionType
from services.tx_supply.src.services import live_seafood_v2


# ─── Fixtures ───

TENANT_ID = str(uuid.uuid4())
STORE_ID = str(uuid.uuid4())


@pytest_asyncio.fixture(autouse=True)
async def _clear_state():
    """每个测试前清空内存存储"""
    live_seafood_v2._live_status_records.clear()
    live_seafood_v2._tank_inventory.clear()
    live_seafood_v2._live_prices.clear()
    live_seafood_v2._warehouse_stock.clear()
    yield


@pytest_asyncio.fixture
async def db_session():
    """创建内存 SQLite 异步会话"""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)

    async with engine.begin() as conn:
        await conn.run_sync(TenantBase.metadata.create_all)

    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with session_factory() as session:
        original_execute = session.execute

        async def patched_execute(stmt, *args, **kwargs):
            stmt_str = str(stmt) if not isinstance(stmt, str) else stmt
            if "set_config" in stmt_str:
                return MagicMock()
            return await original_execute(stmt, *args, **kwargs)

        session.execute = patched_execute
        yield session

    await engine.dispose()


@pytest_asyncio.fixture
async def sample_seafood(db_session: AsyncSession):
    """创建活鲜测试原料"""
    ing = Ingredient(
        id=uuid.uuid4(),
        tenant_id=uuid.UUID(TENANT_ID),
        store_id=uuid.UUID(STORE_ID),
        ingredient_name="波士顿龙虾",
        category="seafood",
        unit="kg",
        current_quantity=10.0,
        min_quantity=3.0,
        max_quantity=30.0,
        unit_price_fen=28000,
        status=InventoryStatus.normal.value,
    )
    db_session.add(ing)
    await db_session.flush()
    return ing


# ─── Test: track_live_status ───


@pytest.mark.asyncio
async def test_track_live_status_alive(db_session, sample_seafood):
    """测试记录 alive 状态"""
    result = await live_seafood_v2.track_live_status(
        ingredient_id=str(sample_seafood.id),
        store_id=STORE_ID,
        status="alive",
        weight_g=1500.0,
        tenant_id=TENANT_ID,
        db=db_session,
    )
    assert result["status"] == "alive"
    assert result["weight_g"] == 1500.0
    assert result["previous_status"] is None
    assert result["record_id"]


@pytest.mark.asyncio
async def test_track_live_status_transition(db_session, sample_seafood):
    """测试状态流转 alive → weak → dead"""
    ing_id = str(sample_seafood.id)

    await live_seafood_v2.track_live_status(
        ing_id, STORE_ID, "alive", 1500.0, TENANT_ID, db_session,
    )

    result2 = await live_seafood_v2.track_live_status(
        ing_id, STORE_ID, "weak", 1480.0, TENANT_ID, db_session,
    )
    assert result2["status"] == "weak"
    assert result2["previous_status"] == "alive"

    result3 = await live_seafood_v2.track_live_status(
        ing_id, STORE_ID, "dead", 1460.0, TENANT_ID, db_session,
    )
    assert result3["status"] == "dead"
    assert result3["previous_status"] == "weak"


@pytest.mark.asyncio
async def test_track_live_status_irreversible(db_session, sample_seafood):
    """测试状态不可逆转"""
    ing_id = str(sample_seafood.id)

    await live_seafood_v2.track_live_status(
        ing_id, STORE_ID, "weak", 1500.0, TENANT_ID, db_session,
    )

    with pytest.raises(ValueError, match="不可逆转"):
        await live_seafood_v2.track_live_status(
            ing_id, STORE_ID, "alive", 1500.0, TENANT_ID, db_session,
        )


@pytest.mark.asyncio
async def test_track_live_status_invalid_status(db_session, sample_seafood):
    """测试无效状态"""
    with pytest.raises(ValueError, match="无效的活鲜状态"):
        await live_seafood_v2.track_live_status(
            str(sample_seafood.id), STORE_ID, "zombie", 1000.0, TENANT_ID, db_session,
        )


@pytest.mark.asyncio
async def test_track_live_status_negative_weight(db_session, sample_seafood):
    """测试负重量"""
    with pytest.raises(ValueError, match="重量不能为负数"):
        await live_seafood_v2.track_live_status(
            str(sample_seafood.id), STORE_ID, "alive", -100.0, TENANT_ID, db_session,
        )


# ─── Test: calculate_live_loss ───


@pytest.mark.asyncio
async def test_calculate_live_loss_with_dead(db_session, sample_seafood):
    """测试死亡损耗计算"""
    ing_id = str(sample_seafood.id)

    await live_seafood_v2.track_live_status(
        ing_id, STORE_ID, "alive", 1500.0, TENANT_ID, db_session,
    )
    await live_seafood_v2.track_live_status(
        ing_id, STORE_ID, "dead", 1500.0, TENANT_ID, db_session,
    )

    today = date.today()
    result = await live_seafood_v2.calculate_live_loss(
        STORE_ID, (today, today), TENANT_ID, db_session,
    )
    assert result["dead_loss_g"] == 1500.0
    assert result["total_loss_value_fen"] > 0
    assert len(result["details"]) >= 1


@pytest.mark.asyncio
async def test_calculate_live_loss_empty(db_session):
    """测试无损耗"""
    today = date.today()
    result = await live_seafood_v2.calculate_live_loss(
        STORE_ID, (today, today), TENANT_ID, db_session,
    )
    assert result["dead_loss_g"] == 0
    assert result["weak_loss_g"] == 0


# ─── Test: get_tank_inventory ───


@pytest.mark.asyncio
async def test_get_tank_inventory_empty(db_session):
    """测试空鱼缸库存"""
    result = await live_seafood_v2.get_tank_inventory(STORE_ID, TENANT_ID, db_session)
    assert result["tanks"] == []
    assert result["summary"]["tank_count"] == 0


@pytest.mark.asyncio
async def test_get_tank_inventory_with_data(db_session):
    """测试有数据的鱼缸库存"""
    live_seafood_v2.register_tank(
        store_id=STORE_ID, tank_id="TANK-A1", species="lobster",
        tenant_id=TENANT_ID, alive_count=5, alive_weight_g=7500.0,
        weak_count=1, weak_weight_g=1200.0, price_per_g_fen=28,
        temperature=15.0,
    )

    result = await live_seafood_v2.get_tank_inventory(STORE_ID, TENANT_ID, db_session)
    assert len(result["tanks"]) == 1
    assert result["tanks"][0]["tank_id"] == "TANK-A1"
    assert result["tanks"][0]["alive_weight_g"] == 7500.0
    assert result["summary"]["total_alive_weight_g"] == 7500.0


# ─── Test: price_by_weight ───


@pytest.mark.asyncio
async def test_price_by_weight_market_price(db_session, sample_seafood):
    """测试时价定价"""
    live_seafood_v2.set_market_price(
        str(sample_seafood.id), STORE_ID, TENANT_ID, 50,
    )

    result = await live_seafood_v2.price_by_weight(
        str(sample_seafood.id), 1200.0, TENANT_ID, db_session,
    )
    assert result["unit_price_fen_per_g"] == 50
    assert result["total_price_fen"] == 60000
    assert result["pricing_method"] == "market_price"


@pytest.mark.asyncio
async def test_price_by_weight_cost_fallback(db_session, sample_seafood):
    """测试成本加成定价回退"""
    result = await live_seafood_v2.price_by_weight(
        str(sample_seafood.id), 1000.0, TENANT_ID, db_session,
    )
    assert result["pricing_method"] == "cost_plus_margin"
    assert result["total_price_fen"] > 0


@pytest.mark.asyncio
async def test_price_by_weight_zero_weight(db_session, sample_seafood):
    """测试零重量"""
    with pytest.raises(ValueError, match="称重必须大于0"):
        await live_seafood_v2.price_by_weight(
            str(sample_seafood.id), 0, TENANT_ID, db_session,
        )


# ─── Test: get_seafood_dashboard ───


@pytest.mark.asyncio
async def test_get_seafood_dashboard(db_session, sample_seafood):
    """测试活鲜仪表盘"""
    result = await live_seafood_v2.get_seafood_dashboard(STORE_ID, TENANT_ID, db_session)
    assert result["store_id"] == STORE_ID
    assert "inventory" in result
    assert "loss_today" in result
    assert "alerts" in result
    assert result["total_inventory_value_fen"] >= 0


# ─── Test: warehouse stock & transfer ───


@pytest.mark.asyncio
async def test_get_warehouse_stock(db_session):
    """测试仓库库存查询"""
    live_seafood_v2.register_warehouse_item(
        STORE_ID, "store", TENANT_ID,
        "ing-001", "鲈鱼", 5000.0, 20000,
    )

    result = await live_seafood_v2.get_warehouse_stock(STORE_ID, "store", TENANT_ID, db_session)
    assert len(result["items"]) == 1
    assert result["items"][0]["ingredient_name"] == "鲈鱼"
    assert result["warehouse_type"] == "store"


@pytest.mark.asyncio
async def test_get_warehouse_stock_invalid_type(db_session):
    """测试无效仓库类型"""
    with pytest.raises(ValueError, match="无效仓库类型"):
        await live_seafood_v2.get_warehouse_stock(STORE_ID, "invalid", TENANT_ID, db_session)


@pytest.mark.asyncio
async def test_transfer_between_locations(db_session):
    """测试仓库到档口领料"""
    live_seafood_v2.register_warehouse_item(
        STORE_ID, "store", TENANT_ID,
        "ing-001", "鲈鱼", 5000.0, 20000,
    )

    result = await live_seafood_v2.transfer_between_locations(
        from_location={"store_id": STORE_ID, "warehouse_type": "store"},
        to_location={"store_id": STORE_ID, "warehouse_type": "dept"},
        items=[{"ingredient_id": "ing-001", "quantity_g": 2000.0}],
        tenant_id=TENANT_ID,
        db=db_session,
    )
    assert result["items_transferred"] == 1
    assert result["total_weight_g"] == 2000.0


@pytest.mark.asyncio
async def test_transfer_insufficient_stock(db_session):
    """测试调拨库存不足"""
    live_seafood_v2.register_warehouse_item(
        STORE_ID, "store", TENANT_ID,
        "ing-002", "石斑鱼", 1000.0, 30000,
    )

    with pytest.raises(ValueError, match="库存不足"):
        await live_seafood_v2.transfer_between_locations(
            from_location={"store_id": STORE_ID, "warehouse_type": "store"},
            to_location={"store_id": STORE_ID, "warehouse_type": "dept"},
            items=[{"ingredient_id": "ing-002", "quantity_g": 5000.0}],
            tenant_id=TENANT_ID,
            db=db_session,
        )
