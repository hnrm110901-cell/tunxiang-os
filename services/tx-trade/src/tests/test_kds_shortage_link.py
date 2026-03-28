"""KDS 缺料联动测试 -- on_shortage_reported / get_production_rhythm / optimize_production_sequence

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
from services.tx_trade.src.services import kds_shortage_link


# ─── Fixtures ───

TENANT_ID = str(uuid.uuid4())
STORE_ID = str(uuid.uuid4())


@pytest_asyncio.fixture(autouse=True)
async def _clear_state():
    """每个测试前清空内存存储"""
    kds_shortage_link._sellout_map.clear()
    kds_shortage_link._notifications.clear()
    kds_shortage_link._purchase_suggestions.clear()
    kds_shortage_link._production_records.clear()
    kds_shortage_link._ingredient_dish_map.clear()
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
async def low_stock_ingredient(db_session: AsyncSession):
    """创建低库存原料"""
    ing = Ingredient(
        id=uuid.uuid4(),
        tenant_id=uuid.UUID(TENANT_ID),
        store_id=uuid.UUID(STORE_ID),
        ingredient_name="三文鱼",
        category="seafood",
        unit="kg",
        current_quantity=0.5,
        min_quantity=5.0,
        max_quantity=30.0,
        unit_price_fen=18000,
        status=InventoryStatus.low.value,
        supplier_name="海鲜供应商A",
    )
    db_session.add(ing)
    await db_session.flush()
    return ing


@pytest_asyncio.fixture
async def normal_stock_ingredient(db_session: AsyncSession):
    """创建正常库存原料"""
    ing = Ingredient(
        id=uuid.uuid4(),
        tenant_id=uuid.UUID(TENANT_ID),
        store_id=uuid.UUID(STORE_ID),
        ingredient_name="大米",
        category="grain",
        unit="kg",
        current_quantity=50.0,
        min_quantity=10.0,
        max_quantity=100.0,
        unit_price_fen=500,
        status=InventoryStatus.normal.value,
    )
    db_session.add(ing)
    await db_session.flush()
    return ing


# ─── Test: on_shortage_reported ───


@pytest.mark.asyncio
async def test_shortage_verified_auto_sellout(db_session, low_stock_ingredient):
    """测试缺料确认后自动沽清"""
    ing_id = str(low_stock_ingredient.id)

    # 注册原料-菜品映射
    kds_shortage_link.register_ingredient_dishes(ing_id, ["dish-001", "dish-002"])

    result = await kds_shortage_link.on_shortage_reported(
        task_id="task-001",
        ingredient_id=ing_id,
        store_id=STORE_ID,
        tenant_id=TENANT_ID,
        db=db_session,
    )

    assert result["stock_verified"] is True
    assert result["actual_quantity"] == 0.5
    assert len(result["dishes_sold_out"]) == 2
    assert "dish-001" in result["dishes_sold_out"]
    assert result["notification_sent"] is True

    # 验证沽清状态
    status = kds_shortage_link.get_sellout_status(STORE_ID, "dish-001", TENANT_ID)
    assert status == "sold_out"


@pytest.mark.asyncio
async def test_shortage_not_verified_normal_stock(db_session, normal_stock_ingredient):
    """测试库存充足时不自动沽清"""
    ing_id = str(normal_stock_ingredient.id)
    kds_shortage_link.register_ingredient_dishes(ing_id, ["dish-003"])

    result = await kds_shortage_link.on_shortage_reported(
        task_id="task-002",
        ingredient_id=ing_id,
        store_id=STORE_ID,
        tenant_id=TENANT_ID,
        db=db_session,
    )

    assert result["stock_verified"] is False
    assert result["actual_quantity"] == 50.0
    assert len(result["dishes_sold_out"]) == 0
    # 通知仍然发送（但标记为 warning）
    assert result["notification_sent"] is True


@pytest.mark.asyncio
async def test_shortage_generates_purchase_suggestion(db_session, low_stock_ingredient):
    """测试缺料后生成采购建议"""
    ing_id = str(low_stock_ingredient.id)

    result = await kds_shortage_link.on_shortage_reported(
        task_id="task-003",
        ingredient_id=ing_id,
        store_id=STORE_ID,
        tenant_id=TENANT_ID,
        db=db_session,
    )

    assert result["purchase_suggestion"] is not None
    suggestion = result["purchase_suggestion"]
    assert suggestion["urgency"] == "urgent"
    assert suggestion["suggested_quantity"] > 0
    assert suggestion["supplier_name"] == "海鲜供应商A"


@pytest.mark.asyncio
async def test_shortage_nonexistent_ingredient(db_session):
    """测试不存在的原料上报缺料"""
    fake_id = str(uuid.uuid4())

    result = await kds_shortage_link.on_shortage_reported(
        task_id="task-004",
        ingredient_id=fake_id,
        store_id=STORE_ID,
        tenant_id=TENANT_ID,
        db=db_session,
    )

    # 原料不存在，视为缺料确认
    assert result["stock_verified"] is True
    assert result["actual_quantity"] == 0.0


@pytest.mark.asyncio
async def test_shortage_notifications_stored(db_session, low_stock_ingredient):
    """测试通知存储"""
    ing_id = str(low_stock_ingredient.id)

    await kds_shortage_link.on_shortage_reported(
        task_id="task-005",
        ingredient_id=ing_id,
        store_id=STORE_ID,
        tenant_id=TENANT_ID,
        db=db_session,
    )

    notifications = kds_shortage_link.get_pending_notifications(STORE_ID, TENANT_ID)
    assert len(notifications) == 1
    assert notifications[0]["type"] == "shortage_alert"
    assert notifications[0]["severity"] == "critical"


# ─── Test: get_production_rhythm ───


@pytest.mark.asyncio
async def test_production_rhythm_empty(db_session):
    """测试无出品数据"""
    today = date.today()
    result = await kds_shortage_link.get_production_rhythm(
        STORE_ID, (today, today), TENANT_ID, db_session,
    )
    assert result["departments"] == []
    assert result["bottleneck_dept"] is None
    assert result["avg_speed_sec"] == 0


@pytest.mark.asyncio
async def test_production_rhythm_with_data(db_session):
    """测试出品节拍分析"""
    now = datetime.now(timezone.utc)

    # 添加两个档口的出品记录
    for i in range(5):
        kds_shortage_link.add_production_record(
            STORE_ID, "hot-kitchen", TENANT_ID,
            f"task-hot-{i}", "宫保鸡丁",
            (now - timedelta(minutes=10 * i + 8)).isoformat(),
            (now - timedelta(minutes=10 * i)).isoformat(),
            duration_sec=480,
        )

    for i in range(3):
        kds_shortage_link.add_production_record(
            STORE_ID, "cold-kitchen", TENANT_ID,
            f"task-cold-{i}", "凉拌黄瓜",
            (now - timedelta(minutes=5 * i + 3)).isoformat(),
            (now - timedelta(minutes=5 * i)).isoformat(),
            duration_sec=180,
        )

    today = date.today()
    result = await kds_shortage_link.get_production_rhythm(
        STORE_ID, (today - timedelta(days=1), today), TENANT_ID, db_session,
    )

    assert len(result["departments"]) == 2
    assert result["bottleneck_dept"] == "hot-kitchen"

    # 热菜档口平均 480 秒
    hot = next(d for d in result["departments"] if d["dept_id"] == "hot-kitchen")
    assert hot["avg_duration_sec"] == 480.0
    assert hot["total_tasks"] == 5


@pytest.mark.asyncio
async def test_production_rhythm_date_filter(db_session):
    """测试日期过滤"""
    old_time = datetime.now(timezone.utc) - timedelta(days=30)

    kds_shortage_link.add_production_record(
        STORE_ID, "hot-kitchen", TENANT_ID,
        "task-old", "红烧肉",
        old_time.isoformat(),
        (old_time + timedelta(minutes=10)).isoformat(),
        duration_sec=600,
    )

    today = date.today()
    result = await kds_shortage_link.get_production_rhythm(
        STORE_ID, (today, today), TENANT_ID, db_session,
    )
    # 30天前的记录应被过滤掉
    assert result["departments"] == []


# ─── Test: optimize_production_sequence ───


@pytest.mark.asyncio
async def test_optimize_sequence_empty(db_session):
    """测试无数据优化"""
    result = await kds_shortage_link.optimize_production_sequence(
        "hot-kitchen", TENANT_ID, db_session,
    )
    assert result["optimized_sequence"] == []
    assert result["strategy"] == "shortest_job_first"


@pytest.mark.asyncio
async def test_optimize_sequence_sjf(db_session):
    """测试SJF排序"""
    now = datetime.now(timezone.utc)

    # 添加不同耗时的菜品记录
    kds_shortage_link.add_production_record(
        STORE_ID, "hot-kitchen", TENANT_ID,
        "task-1", "宫保鸡丁", now.isoformat(), now.isoformat(), duration_sec=480,
    )
    kds_shortage_link.add_production_record(
        STORE_ID, "hot-kitchen", TENANT_ID,
        "task-2", "蒜蓉蒸虾", now.isoformat(), now.isoformat(), duration_sec=120,
    )
    kds_shortage_link.add_production_record(
        STORE_ID, "hot-kitchen", TENANT_ID,
        "task-3", "红烧肉", now.isoformat(), now.isoformat(), duration_sec=900,
    )

    result = await kds_shortage_link.optimize_production_sequence(
        "hot-kitchen", TENANT_ID, db_session,
    )

    seq = result["optimized_sequence"]
    assert len(seq) == 3
    # SJF: 蒜蓉蒸虾(120) < 宫保鸡丁(480) < 红烧肉(900)
    assert seq[0]["dish_name"] == "蒜蓉蒸虾"
    assert seq[1]["dish_name"] == "宫保鸡丁"
    assert seq[2]["dish_name"] == "红烧肉"
    assert result["estimated_savings_sec"] > 0
