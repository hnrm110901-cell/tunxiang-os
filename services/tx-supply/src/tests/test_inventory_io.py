"""库存入库出库服务测试 -- inventory_io + expiry_monitor + stock_forecast

使用 SQLite 内存数据库模拟 PostgreSQL，测试核心业务逻辑。
"""
import uuid
from datetime import date, timedelta
from unittest.mock import MagicMock

import pytest
import pytest_asyncio
from services.tx_supply.src.services import expiry_monitor, inventory_io, stock_forecast
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from shared.ontology.src.base import TenantBase
from shared.ontology.src.entities import Ingredient
from shared.ontology.src.enums import InventoryStatus

# ─── Fixtures ───

TENANT_ID = str(uuid.uuid4())
STORE_ID = str(uuid.uuid4())


@pytest_asyncio.fixture
async def db_session():
    """创建内存 SQLite 异步会话"""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)

    async with engine.begin() as conn:
        await conn.run_sync(TenantBase.metadata.create_all)

    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with session_factory() as session:
        # Mock set_config（SQLite 无此函数）
        original_execute = session.execute

        async def patched_execute(stmt, *args, **kwargs):
            if hasattr(stmt, 'text') and 'set_config' in str(stmt):
                return MagicMock()
            if isinstance(stmt, text) and 'set_config' in str(stmt):
                return MagicMock()
            # Handle text objects
            stmt_str = str(stmt) if not isinstance(stmt, str) else stmt
            if 'set_config' in stmt_str:
                return MagicMock()
            return await original_execute(stmt, *args, **kwargs)

        session.execute = patched_execute
        yield session

    await engine.dispose()


@pytest_asyncio.fixture
async def sample_ingredient(db_session: AsyncSession):
    """创建测试原料"""
    ing = Ingredient(
        id=uuid.uuid4(),
        tenant_id=uuid.UUID(TENANT_ID),
        store_id=uuid.UUID(STORE_ID),
        ingredient_name="三文鱼",
        category="seafood",
        unit="kg",
        current_quantity=0,
        min_quantity=5.0,
        max_quantity=50.0,
        unit_price_fen=0,
        status=InventoryStatus.out_of_stock.value,
    )
    db_session.add(ing)
    await db_session.flush()
    return ing


# ─── Test: receive_stock ───


@pytest.mark.asyncio
async def test_receive_stock_basic(db_session, sample_ingredient):
    """入库基本流程：数量和成本正确更新"""
    result = await inventory_io.receive_stock(
        ingredient_id=str(sample_ingredient.id),
        quantity=10.0,
        unit_cost_fen=5000,
        batch_no="B20260327-001",
        expiry_date=date(2026, 4, 10),
        store_id=STORE_ID,
        tenant_id=TENANT_ID,
        db=db_session,
    )

    assert result["new_quantity"] == 10.0
    assert result["status"] == InventoryStatus.normal.value
    assert "transaction_id" in result

    # 验证原料记录已更新
    await db_session.refresh(sample_ingredient)
    assert sample_ingredient.current_quantity == 10.0
    assert sample_ingredient.unit_price_fen == 5000


@pytest.mark.asyncio
async def test_receive_stock_weighted_avg_cost(db_session, sample_ingredient):
    """两次入库后单价为加权平均"""
    await inventory_io.receive_stock(
        ingredient_id=str(sample_ingredient.id),
        quantity=10.0, unit_cost_fen=5000,
        batch_no="B001", expiry_date=None,
        store_id=STORE_ID, tenant_id=TENANT_ID, db=db_session,
    )
    await inventory_io.receive_stock(
        ingredient_id=str(sample_ingredient.id),
        quantity=10.0, unit_cost_fen=6000,
        batch_no="B002", expiry_date=None,
        store_id=STORE_ID, tenant_id=TENANT_ID, db=db_session,
    )

    await db_session.refresh(sample_ingredient)
    assert sample_ingredient.current_quantity == 20.0
    # 加权平均: (5000*10 + 6000*10) / 20 = 5500
    assert sample_ingredient.unit_price_fen == 5500


@pytest.mark.asyncio
async def test_receive_stock_rejects_zero_quantity(db_session, sample_ingredient):
    """入库数量 <= 0 应拒绝"""
    with pytest.raises(ValueError, match="入库数量必须大于0"):
        await inventory_io.receive_stock(
            ingredient_id=str(sample_ingredient.id),
            quantity=0, unit_cost_fen=5000,
            batch_no="B001", expiry_date=None,
            store_id=STORE_ID, tenant_id=TENANT_ID, db=db_session,
        )


# ─── Test: issue_stock (FIFO) ───


@pytest.mark.asyncio
async def test_issue_stock_fifo(db_session, sample_ingredient):
    """出库 FIFO：先进先出，优先扣最早批次"""
    # 入库两批
    await inventory_io.receive_stock(
        ingredient_id=str(sample_ingredient.id),
        quantity=5.0, unit_cost_fen=4000,
        batch_no="BATCH-OLD", expiry_date=date(2026, 4, 1),
        store_id=STORE_ID, tenant_id=TENANT_ID, db=db_session,
    )
    await inventory_io.receive_stock(
        ingredient_id=str(sample_ingredient.id),
        quantity=10.0, unit_cost_fen=5000,
        batch_no="BATCH-NEW", expiry_date=date(2026, 5, 1),
        store_id=STORE_ID, tenant_id=TENANT_ID, db=db_session,
    )

    # 出库 7kg — 应先扣 BATCH-OLD 5kg，再扣 BATCH-NEW 2kg
    result = await inventory_io.issue_stock(
        ingredient_id=str(sample_ingredient.id),
        quantity=7.0, reason="usage",
        store_id=STORE_ID, tenant_id=TENANT_ID, db=db_session,
    )

    assert result["new_quantity"] == pytest.approx(8.0, abs=0.01)
    assert len(result["transactions"]) == 2
    assert result["transactions"][0]["batch_no"] == "BATCH-OLD"
    assert result["transactions"][0]["deducted"] == pytest.approx(5.0, abs=0.01)
    assert result["transactions"][1]["batch_no"] == "BATCH-NEW"
    assert result["transactions"][1]["deducted"] == pytest.approx(2.0, abs=0.01)


@pytest.mark.asyncio
async def test_issue_stock_insufficient(db_session, sample_ingredient):
    """库存不足时拒绝出库"""
    await inventory_io.receive_stock(
        ingredient_id=str(sample_ingredient.id),
        quantity=3.0, unit_cost_fen=5000,
        batch_no="B001", expiry_date=None,
        store_id=STORE_ID, tenant_id=TENANT_ID, db=db_session,
    )

    with pytest.raises(ValueError, match="库存不足"):
        await inventory_io.issue_stock(
            ingredient_id=str(sample_ingredient.id),
            quantity=5.0, reason="usage",
            store_id=STORE_ID, tenant_id=TENANT_ID, db=db_session,
        )


# ─── Test: adjust_stock ───


@pytest.mark.asyncio
async def test_adjust_stock_gain(db_session, sample_ingredient):
    """盘盈调整"""
    await inventory_io.receive_stock(
        ingredient_id=str(sample_ingredient.id),
        quantity=10.0, unit_cost_fen=5000,
        batch_no="B001", expiry_date=None,
        store_id=STORE_ID, tenant_id=TENANT_ID, db=db_session,
    )

    result = await inventory_io.adjust_stock(
        ingredient_id=str(sample_ingredient.id),
        quantity=2.0, reason="盘盈-实际多2kg",
        store_id=STORE_ID, tenant_id=TENANT_ID, db=db_session,
    )

    assert result["new_quantity"] == 12.0


@pytest.mark.asyncio
async def test_adjust_stock_loss_negative_rejected(db_session, sample_ingredient):
    """盘亏导致负数应拒绝"""
    await inventory_io.receive_stock(
        ingredient_id=str(sample_ingredient.id),
        quantity=3.0, unit_cost_fen=5000,
        batch_no="B001", expiry_date=None,
        store_id=STORE_ID, tenant_id=TENANT_ID, db=db_session,
    )

    with pytest.raises(ValueError, match="调整后库存为负"):
        await inventory_io.adjust_stock(
            ingredient_id=str(sample_ingredient.id),
            quantity=-5.0, reason="盘亏",
            store_id=STORE_ID, tenant_id=TENANT_ID, db=db_session,
        )


# ─── Test: get_stock_balance ───


@pytest.mark.asyncio
async def test_get_stock_balance(db_session, sample_ingredient):
    """库存余额查询返回批次明细"""
    await inventory_io.receive_stock(
        ingredient_id=str(sample_ingredient.id),
        quantity=5.0, unit_cost_fen=4000,
        batch_no="B001", expiry_date=date(2026, 4, 15),
        store_id=STORE_ID, tenant_id=TENANT_ID, db=db_session,
    )
    await inventory_io.receive_stock(
        ingredient_id=str(sample_ingredient.id),
        quantity=8.0, unit_cost_fen=5000,
        batch_no="B002", expiry_date=date(2026, 5, 1),
        store_id=STORE_ID, tenant_id=TENANT_ID, db=db_session,
    )

    balance = await inventory_io.get_stock_balance(
        ingredient_id=str(sample_ingredient.id),
        store_id=STORE_ID, tenant_id=TENANT_ID, db=db_session,
    )

    assert balance["quantity"] == 13.0
    assert balance["unit"] == "kg"
    assert len(balance["batches"]) == 2
    assert balance["batches"][0]["batch_no"] == "B001"
    assert balance["batches"][0]["expiry"] == "2026-04-15"
    # 加权平均: (4000*5 + 5000*8) / 13 ≈ 4615
    assert balance["avg_cost_fen"] == round((4000 * 5 + 5000 * 8) / 13)


# ─── Test: expiry_monitor ───


@pytest.mark.asyncio
async def test_check_expiring_items(db_session, sample_ingredient):
    """临期检测：3天内到期的批次"""
    today = date.today()
    # 一个 2 天后到期的批次
    await inventory_io.receive_stock(
        ingredient_id=str(sample_ingredient.id),
        quantity=3.0, unit_cost_fen=5000,
        batch_no="EXPIRING", expiry_date=today + timedelta(days=2),
        store_id=STORE_ID, tenant_id=TENANT_ID, db=db_session,
    )
    # 一个 30 天后到期的批次
    await inventory_io.receive_stock(
        ingredient_id=str(sample_ingredient.id),
        quantity=5.0, unit_cost_fen=5000,
        batch_no="SAFE", expiry_date=today + timedelta(days=30),
        store_id=STORE_ID, tenant_id=TENANT_ID, db=db_session,
    )

    expiring = await expiry_monitor.check_expiring_items(
        store_id=STORE_ID, days_ahead=3,
        tenant_id=TENANT_ID, db=db_session,
    )

    assert len(expiring) == 1
    assert expiring[0]["batch_no"] == "EXPIRING"
    assert expiring[0]["remaining_days"] == 2
    assert expiring[0]["cost_fen"] == 15000  # 3kg * 5000


@pytest.mark.asyncio
async def test_check_expired_items(db_session, sample_ingredient):
    """过期检测：已过期但有库存"""
    await inventory_io.receive_stock(
        ingredient_id=str(sample_ingredient.id),
        quantity=2.0, unit_cost_fen=6000,
        batch_no="EXPIRED-001",
        expiry_date=date.today() - timedelta(days=3),
        store_id=STORE_ID, tenant_id=TENANT_ID, db=db_session,
    )

    expired = await expiry_monitor.check_expired_items(
        store_id=STORE_ID, tenant_id=TENANT_ID, db=db_session,
    )

    assert len(expired) == 1
    assert expired[0]["batch_no"] == "EXPIRED-001"
    assert expired[0]["days_overdue"] == 3


@pytest.mark.asyncio
async def test_generate_expiry_report(db_session, sample_ingredient):
    """效期综合报告"""
    today = date.today()
    # 过期
    await inventory_io.receive_stock(
        ingredient_id=str(sample_ingredient.id),
        quantity=1.0, unit_cost_fen=5000,
        batch_no="EXP", expiry_date=today - timedelta(days=1),
        store_id=STORE_ID, tenant_id=TENANT_ID, db=db_session,
    )
    # 3天内
    await inventory_io.receive_stock(
        ingredient_id=str(sample_ingredient.id),
        quantity=2.0, unit_cost_fen=5000,
        batch_no="SOON", expiry_date=today + timedelta(days=2),
        store_id=STORE_ID, tenant_id=TENANT_ID, db=db_session,
    )

    report = await expiry_monitor.generate_expiry_report(
        store_id=STORE_ID, tenant_id=TENANT_ID, db=db_session,
    )

    assert report["expired_count"] == 1
    assert report["expiring_3d_count"] == 1
    assert report["total_risk_cost_fen"] > 0


# ─── Test: stock_forecast ───


@pytest.mark.asyncio
async def test_predict_stockout_no_consumption(db_session, sample_ingredient):
    """无消耗记录时预测返回 None"""
    await inventory_io.receive_stock(
        ingredient_id=str(sample_ingredient.id),
        quantity=10.0, unit_cost_fen=5000,
        batch_no="B001", expiry_date=None,
        store_id=STORE_ID, tenant_id=TENANT_ID, db=db_session,
    )

    forecast = await stock_forecast.predict_stockout(
        store_id=STORE_ID, ingredient_id=str(sample_ingredient.id),
        tenant_id=TENANT_ID, db=db_session,
    )

    assert forecast["estimated_stockout_date"] is None
    assert forecast["days_remaining"] is None
    assert forecast["current_qty"] == 10.0
