"""收货验收流程 V2 测试

覆盖：
- 创建收货单
- 单项验收（全验收/部分验收/拒收）
- 完成验收后库存正确增加
- 部分拒收后只入库验收通过数量
- 全部拒收
- 多租户隔离
"""
from __future__ import annotations

import os

# Import services via absolute path pattern used in the project
import sys
import uuid
from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from shared.ontology.src.base import TenantBase
from shared.ontology.src.entities import (
    Ingredient,
    IngredientTransaction,
)
from shared.ontology.src.enums import ReceivingItemStatus, ReceivingOrderStatus, TransactionType

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../../.."))

from services.tx_supply.src.services.receiving_v2_service import (
    complete_receiving,
    create_receiving_order,
    get_receiving_order,
    inspect_item,
    reject_all,
)

# ─── Fixtures ─────────────────────────────────────────────


TENANT_ID = str(uuid.uuid4())
STORE_ID = str(uuid.uuid4())
INGREDIENT_ID = str(uuid.uuid4())
INGREDIENT_ID_2 = str(uuid.uuid4())


@pytest_asyncio.fixture
async def db_session():
    """SQLite 内存数据库异步会话"""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)

    async with engine.begin() as conn:
        await conn.run_sync(TenantBase.metadata.create_all)

    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with session_factory() as session:
        # Patch set_config（SQLite 无此函数）
        original_execute = session.execute

        async def patched_execute(stmt, *args, **kwargs):
            stmt_str = str(stmt) if not isinstance(stmt, str) else stmt
            if "set_config" in stmt_str:
                return MagicMock()
            return await original_execute(stmt, *args, **kwargs)

        session.execute = patched_execute

        # 创建测试门店（stores 表依赖）
        await session.execute(
            text("""
                INSERT INTO stores (id, tenant_id, store_name, address,
                    created_at, updated_at, is_deleted)
                VALUES (:id, :tenant_id, :name, :addr,
                    CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, 0)
            """),
            {
                "id": STORE_ID,
                "tenant_id": TENANT_ID,
                "name": "测试门店",
                "addr": "测试地址",
            },
        )

        # 创建测试食材台账
        ing1 = Ingredient(
            id=uuid.UUID(INGREDIENT_ID),
            tenant_id=uuid.UUID(TENANT_ID),
            store_id=uuid.UUID(STORE_ID),
            ingredient_name="鲈鱼",
            unit="kg",
            current_quantity=10.0,
            min_quantity=5.0,
            unit_price_fen=3000,
            status="normal",
        )
        ing2 = Ingredient(
            id=uuid.UUID(INGREDIENT_ID_2),
            tenant_id=uuid.UUID(TENANT_ID),
            store_id=uuid.UUID(STORE_ID),
            ingredient_name="虾",
            unit="kg",
            current_quantity=3.0,
            min_quantity=2.0,
            unit_price_fen=5000,
            status="normal",
        )
        session.add(ing1)
        session.add(ing2)
        await session.flush()

        yield session
        await session.rollback()

    await engine.dispose()


# ─── 创建收货单 ───────────────────────────────────────────


class TestCreateReceivingOrder:
    @pytest.mark.asyncio
    async def test_create_basic(self, db_session):
        items = [
            {
                "ingredient_id": INGREDIENT_ID,
                "ingredient_name": "鲈鱼",
                "expected_quantity": 20.0,
                "expected_unit": "kg",
            }
        ]
        result = await create_receiving_order(
            tenant_id=TENANT_ID,
            store_id=STORE_ID,
            supplier_id=None,
            delivery_note_no="DN-20260331-001",
            receiver_id=None,
            items=items,
            db=db_session,
        )
        assert result["order_id"] is not None
        assert result["status"] == ReceivingOrderStatus.draft.value
        assert result["total_items"] == 1
        assert result["delivery_note_no"] == "DN-20260331-001"

    @pytest.mark.asyncio
    async def test_empty_items_raises(self, db_session):
        with pytest.raises(ValueError, match="至少包含一项"):
            await create_receiving_order(
                tenant_id=TENANT_ID,
                store_id=STORE_ID,
                supplier_id=None,
                delivery_note_no=None,
                receiver_id=None,
                items=[],
                db=db_session,
            )

    @pytest.mark.asyncio
    async def test_multiple_items(self, db_session):
        items = [
            {
                "ingredient_id": INGREDIENT_ID,
                "ingredient_name": "鲈鱼",
                "expected_quantity": 20.0,
                "expected_unit": "kg",
            },
            {
                "ingredient_id": INGREDIENT_ID_2,
                "ingredient_name": "虾",
                "expected_quantity": 10.0,
                "expected_unit": "kg",
            },
        ]
        result = await create_receiving_order(
            tenant_id=TENANT_ID,
            store_id=STORE_ID,
            supplier_id=None,
            delivery_note_no=None,
            receiver_id=None,
            items=items,
            db=db_session,
        )
        assert result["total_items"] == 2


# ─── 单项验收 ─────────────────────────────────────────────


class TestInspectItem:
    @pytest_asyncio.fixture
    async def order_with_items(self, db_session):
        """创建一个有2项的收货单，返回(order_id, item1_id, item2_id)"""
        items = [
            {
                "ingredient_id": INGREDIENT_ID,
                "ingredient_name": "鲈鱼",
                "expected_quantity": 20.0,
                "expected_unit": "kg",
                "unit_price_fen": 3500,
            },
            {
                "ingredient_id": INGREDIENT_ID_2,
                "ingredient_name": "虾",
                "expected_quantity": 10.0,
                "expected_unit": "kg",
                "unit_price_fen": 5500,
            },
        ]
        order_info = await create_receiving_order(
            tenant_id=TENANT_ID,
            store_id=STORE_ID,
            supplier_id=None,
            delivery_note_no=None,
            receiver_id=None,
            items=items,
            db=db_session,
        )
        # 获取明细 IDs
        detail = await get_receiving_order(
            order_id=order_info["order_id"],
            tenant_id=TENANT_ID,
            db=db_session,
        )
        return order_info["order_id"], detail["items"][0]["item_id"], detail["items"][1]["item_id"]

    @pytest.mark.asyncio
    async def test_full_accept(self, db_session, order_with_items):
        order_id, item1_id, _ = order_with_items
        result = await inspect_item(
            order_id=order_id,
            item_id=item1_id,
            tenant_id=TENANT_ID,
            db=db_session,
            actual_quantity=Decimal("20"),
            accepted_quantity=Decimal("20"),
            batch_no="BATCH-001",
            expiry_date=date(2026, 5, 1),
        )
        assert result["status"] == ReceivingItemStatus.accepted.value
        assert result["accepted_quantity"] == 20.0
        assert result["rejected_quantity"] == 0.0

    @pytest.mark.asyncio
    async def test_partial_accept(self, db_session, order_with_items):
        order_id, item1_id, _ = order_with_items
        result = await inspect_item(
            order_id=order_id,
            item_id=item1_id,
            tenant_id=TENANT_ID,
            db=db_session,
            actual_quantity=Decimal("20"),
            accepted_quantity=Decimal("15"),
            rejection_reason="3箱有轻微腐烂",
        )
        assert result["status"] == ReceivingItemStatus.partial.value
        assert result["accepted_quantity"] == 15.0
        assert result["rejected_quantity"] == 5.0

    @pytest.mark.asyncio
    async def test_full_reject(self, db_session, order_with_items):
        order_id, item1_id, _ = order_with_items
        result = await inspect_item(
            order_id=order_id,
            item_id=item1_id,
            tenant_id=TENANT_ID,
            db=db_session,
            actual_quantity=Decimal("20"),
            accepted_quantity=Decimal("0"),
            rejection_reason="全部变质",
        )
        assert result["status"] == ReceivingItemStatus.rejected.value
        assert result["accepted_quantity"] == 0.0
        assert result["rejected_quantity"] == 20.0

    @pytest.mark.asyncio
    async def test_accepted_exceeds_actual_raises(self, db_session, order_with_items):
        order_id, item1_id, _ = order_with_items
        with pytest.raises(ValueError, match="不能超过实际到货数量"):
            await inspect_item(
                order_id=order_id,
                item_id=item1_id,
                tenant_id=TENANT_ID,
                db=db_session,
                actual_quantity=Decimal("10"),
                accepted_quantity=Decimal("15"),
            )

    @pytest.mark.asyncio
    async def test_order_status_changes_to_inspecting(self, db_session, order_with_items):
        order_id, item1_id, _ = order_with_items
        await inspect_item(
            order_id=order_id,
            item_id=item1_id,
            tenant_id=TENANT_ID,
            db=db_session,
            actual_quantity=Decimal("20"),
            accepted_quantity=Decimal("20"),
        )
        order = await get_receiving_order(
            order_id=order_id, tenant_id=TENANT_ID, db=db_session
        )
        assert order["status"] == ReceivingOrderStatus.inspecting.value


# ─── 完成验收（入库） ──────────────────────────────────────


class TestCompleteReceiving:
    @pytest_asyncio.fixture
    async def inspected_order(self, db_session):
        """创建并逐项验收完毕的收货单"""
        items = [
            {
                "ingredient_id": INGREDIENT_ID,
                "ingredient_name": "鲈鱼",
                "expected_quantity": 20.0,
                "expected_unit": "kg",
                "unit_price_fen": 3500,
            },
            {
                "ingredient_id": INGREDIENT_ID_2,
                "ingredient_name": "虾",
                "expected_quantity": 10.0,
                "expected_unit": "kg",
                "unit_price_fen": 5500,
            },
        ]
        order_info = await create_receiving_order(
            tenant_id=TENANT_ID,
            store_id=STORE_ID,
            supplier_id=None,
            delivery_note_no=None,
            receiver_id=None,
            items=items,
            db=db_session,
        )
        detail = await get_receiving_order(
            order_id=order_info["order_id"], tenant_id=TENANT_ID, db=db_session
        )
        return order_info["order_id"], detail["items"]

    @pytest.mark.asyncio
    async def test_fully_received_updates_inventory(self, db_session, inspected_order):
        """验收完成后库存正确增加"""
        order_id, items = inspected_order
        # 验收两项（全通过）
        for item in items:
            await inspect_item(
                order_id=order_id,
                item_id=item["item_id"],
                tenant_id=TENANT_ID,
                db=db_session,
                actual_quantity=Decimal(str(item["expected_quantity"])),
                accepted_quantity=Decimal(str(item["expected_quantity"])),
                batch_no="BATCH-001",
                expiry_date=date(2026, 6, 1),
            )

        result = await complete_receiving(
            order_id=order_id,
            tenant_id=TENANT_ID,
            store_id=STORE_ID,
            db=db_session,
        )

        assert result["status"] == ReceivingOrderStatus.fully_received.value
        assert result["received_items"] == 2
        assert result["rejected_items"] == 0
        assert len(result["inventory_results"]) == 2

        # 验证库存已增加：原来 10kg，入库 20kg = 30kg
        from sqlalchemy import select
        ing = (await db_session.execute(
            select(Ingredient).where(Ingredient.id == uuid.UUID(INGREDIENT_ID))
        )).scalar_one()
        assert ing.current_quantity == 30.0  # 10 + 20

    @pytest.mark.asyncio
    async def test_partial_receive_only_accepted_enters_inventory(self, db_session, inspected_order):
        """部分拒收后只入库验收通过数量"""
        order_id, items = inspected_order
        # 第一项：全通过（20kg）
        await inspect_item(
            order_id=order_id,
            item_id=items[0]["item_id"],
            tenant_id=TENANT_ID,
            db=db_session,
            actual_quantity=Decimal("20"),
            accepted_quantity=Decimal("20"),
        )
        # 第二项：拒收 3kg，通过 7kg
        await inspect_item(
            order_id=order_id,
            item_id=items[1]["item_id"],
            tenant_id=TENANT_ID,
            db=db_session,
            actual_quantity=Decimal("10"),
            accepted_quantity=Decimal("7"),
            rejection_reason="腐烂",
        )

        result = await complete_receiving(
            order_id=order_id,
            tenant_id=TENANT_ID,
            store_id=STORE_ID,
            db=db_session,
        )

        assert result["status"] == ReceivingOrderStatus.partially_received.value
        assert result["received_items"] == 2
        assert result["rejected_items"] == 1

        # 虾原来 3kg，验收通过 7kg = 10kg
        from sqlalchemy import select
        ing2 = (await db_session.execute(
            select(Ingredient).where(Ingredient.id == uuid.UUID(INGREDIENT_ID_2))
        )).scalar_one()
        assert ing2.current_quantity == 10.0  # 3 + 7

    @pytest.mark.asyncio
    async def test_pending_items_raises(self, db_session, inspected_order):
        """有未验收项时，完成验收应报错"""
        order_id, items = inspected_order
        # 只验收第一项
        await inspect_item(
            order_id=order_id,
            item_id=items[0]["item_id"],
            tenant_id=TENANT_ID,
            db=db_session,
            actual_quantity=Decimal("20"),
            accepted_quantity=Decimal("20"),
        )
        with pytest.raises(ValueError, match="未完成验收"):
            await complete_receiving(
                order_id=order_id,
                tenant_id=TENANT_ID,
                store_id=STORE_ID,
                db=db_session,
            )

    @pytest.mark.asyncio
    async def test_transaction_record_created(self, db_session, inspected_order):
        """验收完成后 ingredient_transactions 有对应 receiving 类型流水"""
        order_id, items = inspected_order
        for item in items:
            await inspect_item(
                order_id=order_id,
                item_id=item["item_id"],
                tenant_id=TENANT_ID,
                db=db_session,
                actual_quantity=Decimal(str(item["expected_quantity"])),
                accepted_quantity=Decimal(str(item["expected_quantity"])),
            )
        await complete_receiving(
            order_id=order_id,
            tenant_id=TENANT_ID,
            store_id=STORE_ID,
            db=db_session,
        )

        from sqlalchemy import select
        txns = (await db_session.execute(
            select(IngredientTransaction).where(
                IngredientTransaction.transaction_type == TransactionType.receiving.value,
                IngredientTransaction.tenant_id == uuid.UUID(TENANT_ID),
            )
        )).scalars().all()
        assert len(txns) == 2
        for txn in txns:
            assert txn.quantity_after > txn.quantity_before


# ─── 全部拒收 ─────────────────────────────────────────────


class TestRejectAll:
    @pytest.mark.asyncio
    async def test_reject_all_sets_status(self, db_session):
        items = [
            {
                "ingredient_id": INGREDIENT_ID,
                "ingredient_name": "鲈鱼",
                "expected_quantity": 20.0,
                "expected_unit": "kg",
            }
        ]
        order_info = await create_receiving_order(
            tenant_id=TENANT_ID,
            store_id=STORE_ID,
            supplier_id=None,
            delivery_note_no=None,
            receiver_id=None,
            items=items,
            db=db_session,
        )
        result = await reject_all(
            order_id=order_info["order_id"],
            tenant_id=TENANT_ID,
            db=db_session,
            rejection_reason="整批腐烂",
        )
        assert result["status"] == ReceivingOrderStatus.rejected.value
        assert result["rejected_items"] == 1

    @pytest.mark.asyncio
    async def test_reject_all_inventory_unchanged(self, db_session):
        """全部拒收后库存不应变化"""
        from sqlalchemy import select as sa_select

        before = (await db_session.execute(
            sa_select(Ingredient.current_quantity).where(
                Ingredient.id == uuid.UUID(INGREDIENT_ID)
            )
        )).scalar()

        items = [
            {
                "ingredient_id": INGREDIENT_ID,
                "ingredient_name": "鲈鱼",
                "expected_quantity": 50.0,
                "expected_unit": "kg",
            }
        ]
        order_info = await create_receiving_order(
            tenant_id=TENANT_ID,
            store_id=STORE_ID,
            supplier_id=None,
            delivery_note_no=None,
            receiver_id=None,
            items=items,
            db=db_session,
        )
        await reject_all(
            order_id=order_info["order_id"],
            tenant_id=TENANT_ID,
            db=db_session,
        )

        after = (await db_session.execute(
            sa_select(Ingredient.current_quantity).where(
                Ingredient.id == uuid.UUID(INGREDIENT_ID)
            )
        )).scalar()
        assert before == after


# ─── 多租户隔离 ───────────────────────────────────────────


class TestMultiTenantIsolation:
    @pytest.mark.asyncio
    async def test_cannot_access_other_tenant_order(self, db_session):
        """不同租户不能查看对方的收货单"""
        other_tenant_id = str(uuid.uuid4())

        items = [
            {
                "ingredient_id": INGREDIENT_ID,
                "ingredient_name": "鲈鱼",
                "expected_quantity": 10.0,
                "expected_unit": "kg",
            }
        ]
        order_info = await create_receiving_order(
            tenant_id=TENANT_ID,
            store_id=STORE_ID,
            supplier_id=None,
            delivery_note_no=None,
            receiver_id=None,
            items=items,
            db=db_session,
        )

        with pytest.raises(ValueError, match="不存在"):
            await get_receiving_order(
                order_id=order_info["order_id"],
                tenant_id=other_tenant_id,
                db=db_session,
            )
