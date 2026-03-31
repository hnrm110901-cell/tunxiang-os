"""门店调拨流程测试

覆盖：
- 创建调拨申请
- 审批（库存足够 / 库存不足）
- 发货（from_store 库存减少）
- 收货（to_store 库存增加）
- 运输损耗记录
- 库存不足时调拨被拒
- 多租户隔离（不同 tenant 的门店不能互调）
- 同门店调拨报错
"""
from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from unittest.mock import MagicMock

from shared.ontology.src.base import TenantBase
from shared.ontology.src.entities import Ingredient, IngredientTransaction, TransferOrder
from shared.ontology.src.enums import TransactionType, TransferOrderStatus

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../../.."))

from services.tx_supply.src.services.transfer_service import (
    InsufficientStockError,
    approve_transfer_order,
    cancel_transfer_order,
    create_transfer_order,
    get_transfer_order,
    list_transfer_orders,
    receive_transfer_order,
    ship_transfer_order,
)


# ─── Fixtures ─────────────────────────────────────────────

TENANT_ID = str(uuid.uuid4())
STORE_A = str(uuid.uuid4())  # 调出门店
STORE_B = str(uuid.uuid4())  # 调入门店
ING_A_ID = str(uuid.uuid4())  # STORE_A 的食材台账 ID
ING_B_ID = str(uuid.uuid4())  # STORE_B 的同名食材台账 ID


@pytest_asyncio.fixture
async def db_session():
    """SQLite 内存数据库"""
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

        # 创建门店 A 和 B
        for store_id, name in [(STORE_A, "门店A"), (STORE_B, "门店B")]:
            await session.execute(
                text("""
                    INSERT INTO stores (id, tenant_id, store_name, address,
                        created_at, updated_at, is_deleted)
                    VALUES (:id, :tenant_id, :name, :addr,
                        CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, 0)
                """),
                {"id": store_id, "tenant_id": TENANT_ID, "name": name, "addr": "地址"},
            )

        # 门店 A 食材（鲈鱼 50kg）
        ing_a = Ingredient(
            id=uuid.UUID(ING_A_ID),
            tenant_id=uuid.UUID(TENANT_ID),
            store_id=uuid.UUID(STORE_A),
            ingredient_name="鲈鱼",
            unit="kg",
            current_quantity=50.0,
            min_quantity=10.0,
            unit_price_fen=3000,
            status="normal",
        )
        # 门店 B 食材（鲈鱼 5kg）
        ing_b = Ingredient(
            id=uuid.UUID(ING_B_ID),
            tenant_id=uuid.UUID(TENANT_ID),
            store_id=uuid.UUID(STORE_B),
            ingredient_name="鲈鱼",
            unit="kg",
            current_quantity=5.0,
            min_quantity=10.0,
            unit_price_fen=3000,
            status="low",
        )
        session.add(ing_a)
        session.add(ing_b)
        await session.flush()

        yield session
        await session.rollback()

    await engine.dispose()


# ─── 创建调拨单 ───────────────────────────────────────────


class TestCreateTransferOrder:
    @pytest.mark.asyncio
    async def test_create_basic(self, db_session):
        items = [
            {
                "ingredient_id": ING_A_ID,
                "ingredient_name": "鲈鱼",
                "requested_quantity": 15.0,
                "unit": "kg",
            }
        ]
        result = await create_transfer_order(
            tenant_id=TENANT_ID,
            from_store_id=STORE_A,
            to_store_id=STORE_B,
            items=items,
            db=db_session,
            transfer_reason="门店B备货不足",
            requested_by=str(uuid.uuid4()),
        )
        assert result["order_id"] is not None
        assert result["status"] == TransferOrderStatus.draft.value
        assert result["from_store_id"] == STORE_A
        assert result["to_store_id"] == STORE_B
        assert result["item_count"] == 1

    @pytest.mark.asyncio
    async def test_same_store_raises(self, db_session):
        with pytest.raises(ValueError, match="不能是同一门店"):
            await create_transfer_order(
                tenant_id=TENANT_ID,
                from_store_id=STORE_A,
                to_store_id=STORE_A,
                items=[{"ingredient_id": ING_A_ID, "ingredient_name": "鲈鱼",
                        "requested_quantity": 1.0, "unit": "kg"}],
                db=db_session,
            )

    @pytest.mark.asyncio
    async def test_empty_items_raises(self, db_session):
        with pytest.raises(ValueError, match="至少包含一项"):
            await create_transfer_order(
                tenant_id=TENANT_ID,
                from_store_id=STORE_A,
                to_store_id=STORE_B,
                items=[],
                db=db_session,
            )


# ─── 审批 ─────────────────────────────────────────────────


class TestApproveTransfer:
    @pytest_asyncio.fixture
    async def draft_order(self, db_session):
        items = [
            {
                "ingredient_id": ING_A_ID,
                "ingredient_name": "鲈鱼",
                "requested_quantity": 15.0,
                "unit": "kg",
            }
        ]
        result = await create_transfer_order(
            tenant_id=TENANT_ID,
            from_store_id=STORE_A,
            to_store_id=STORE_B,
            items=items,
            db=db_session,
        )
        return result["order_id"]

    @pytest.mark.asyncio
    async def test_approve_sufficient_stock(self, db_session, draft_order):
        """库存充足时审批成功"""
        approver_id = str(uuid.uuid4())
        result = await approve_transfer_order(
            order_id=draft_order,
            tenant_id=TENANT_ID,
            db=db_session,
            approved_by=approver_id,
            approved_items=[],
        )
        assert result["status"] == TransferOrderStatus.approved.value
        assert result["approved_by"] == approver_id

    @pytest.mark.asyncio
    async def test_approve_insufficient_stock_raises(self, db_session, draft_order):
        """库存不足时审批应抛出 InsufficientStockError"""
        # 先修改门店A库存为0
        ing = (await db_session.execute(
            select(Ingredient).where(Ingredient.id == uuid.UUID(ING_A_ID))
        )).scalar_one()
        ing.current_quantity = 0.0
        await db_session.flush()

        with pytest.raises(InsufficientStockError, match="库存不足"):
            await approve_transfer_order(
                order_id=draft_order,
                tenant_id=TENANT_ID,
                db=db_session,
                approved_by=str(uuid.uuid4()),
                approved_items=[],
            )


# ─── 发货 ─────────────────────────────────────────────────


class TestShipTransfer:
    @pytest_asyncio.fixture
    async def approved_order(self, db_session):
        items = [
            {
                "ingredient_id": ING_A_ID,
                "ingredient_name": "鲈鱼",
                "requested_quantity": 15.0,
                "unit": "kg",
            }
        ]
        order_info = await create_transfer_order(
            tenant_id=TENANT_ID,
            from_store_id=STORE_A,
            to_store_id=STORE_B,
            items=items,
            db=db_session,
        )
        detail = await get_transfer_order(
            order_id=order_info["order_id"], tenant_id=TENANT_ID, db=db_session
        )
        await approve_transfer_order(
            order_id=order_info["order_id"],
            tenant_id=TENANT_ID,
            db=db_session,
            approved_by=str(uuid.uuid4()),
            approved_items=[],
        )
        return order_info["order_id"], detail["items"][0]["item_id"]

    @pytest.mark.asyncio
    async def test_ship_deducts_from_store(self, db_session, approved_order):
        """发货后 from_store 库存减少"""
        order_id, item_id = approved_order

        result = await ship_transfer_order(
            order_id=order_id,
            tenant_id=TENANT_ID,
            db=db_session,
            shipped_items=[{"item_id": item_id, "shipped_quantity": 15.0, "batch_no": "B001"}],
        )

        assert result["status"] == TransferOrderStatus.shipped.value
        assert len(result["inventory_results"]) == 1

        # 门店A：50 - 15 = 35
        ing_a = (await db_session.execute(
            select(Ingredient).where(Ingredient.id == uuid.UUID(ING_A_ID))
        )).scalar_one()
        assert ing_a.current_quantity == 35.0

    @pytest.mark.asyncio
    async def test_ship_creates_transfer_out_transaction(self, db_session, approved_order):
        """发货创建 transfer_out 流水"""
        order_id, item_id = approved_order

        await ship_transfer_order(
            order_id=order_id,
            tenant_id=TENANT_ID,
            db=db_session,
            shipped_items=[{"item_id": item_id, "shipped_quantity": 15.0}],
        )

        txns = (await db_session.execute(
            select(IngredientTransaction).where(
                IngredientTransaction.transaction_type == TransactionType.transfer_out.value,
                IngredientTransaction.tenant_id == uuid.UUID(TENANT_ID),
            )
        )).scalars().all()
        assert len(txns) == 1
        assert txns[0].quantity == 15.0

    @pytest.mark.asyncio
    async def test_ship_insufficient_stock_raises(self, db_session, approved_order):
        """发货时库存不足应报错"""
        order_id, item_id = approved_order

        # 手动把库存调低
        ing_a = (await db_session.execute(
            select(Ingredient).where(Ingredient.id == uuid.UUID(ING_A_ID))
        )).scalar_one()
        ing_a.current_quantity = 1.0
        await db_session.flush()

        with pytest.raises(InsufficientStockError, match="库存不足"):
            await ship_transfer_order(
                order_id=order_id,
                tenant_id=TENANT_ID,
                db=db_session,
                shipped_items=[{"item_id": item_id, "shipped_quantity": 15.0}],
            )


# ─── 收货 ─────────────────────────────────────────────────


class TestReceiveTransfer:
    @pytest_asyncio.fixture
    async def shipped_order(self, db_session):
        items = [
            {
                "ingredient_id": ING_A_ID,
                "ingredient_name": "鲈鱼",
                "requested_quantity": 15.0,
                "unit": "kg",
            }
        ]
        order_info = await create_transfer_order(
            tenant_id=TENANT_ID,
            from_store_id=STORE_A,
            to_store_id=STORE_B,
            items=items,
            db=db_session,
        )
        detail = await get_transfer_order(
            order_id=order_info["order_id"], tenant_id=TENANT_ID, db=db_session
        )
        item_id = detail["items"][0]["item_id"]

        await approve_transfer_order(
            order_id=order_info["order_id"],
            tenant_id=TENANT_ID,
            db=db_session,
            approved_by=str(uuid.uuid4()),
            approved_items=[],
        )
        await ship_transfer_order(
            order_id=order_info["order_id"],
            tenant_id=TENANT_ID,
            db=db_session,
            shipped_items=[{"item_id": item_id, "shipped_quantity": 15.0}],
        )
        return order_info["order_id"], item_id

    @pytest.mark.asyncio
    async def test_receive_adds_to_store(self, db_session, shipped_order):
        """收货后 to_store 库存增加"""
        order_id, item_id = shipped_order

        result = await receive_transfer_order(
            order_id=order_id,
            tenant_id=TENANT_ID,
            db=db_session,
            received_items=[{"item_id": item_id, "received_quantity": 15.0}],
        )

        assert result["status"] == TransferOrderStatus.received.value
        assert len(result["inventory_results"]) == 1

        # 门店B：5 + 15 = 20
        ing_b = (await db_session.execute(
            select(Ingredient).where(Ingredient.id == uuid.UUID(ING_B_ID))
        )).scalar_one()
        assert ing_b.current_quantity == 20.0

    @pytest.mark.asyncio
    async def test_receive_with_transit_loss(self, db_session, shipped_order):
        """收货数量 < 发货数量时记录运输损耗"""
        order_id, item_id = shipped_order

        result = await receive_transfer_order(
            order_id=order_id,
            tenant_id=TENANT_ID,
            db=db_session,
            received_items=[{"item_id": item_id, "received_quantity": 13.0}],
        )

        assert result["status"] == TransferOrderStatus.received.value
        assert len(result["transit_losses"]) == 1
        assert result["transit_losses"][0]["loss"] == 2.0

        # 门店B：5 + 13 = 18（不是15）
        ing_b = (await db_session.execute(
            select(Ingredient).where(Ingredient.id == uuid.UUID(ING_B_ID))
        )).scalar_one()
        assert ing_b.current_quantity == 18.0

    @pytest.mark.asyncio
    async def test_receive_creates_transfer_in_transaction(self, db_session, shipped_order):
        """收货后创建 transfer_in 流水"""
        order_id, item_id = shipped_order

        await receive_transfer_order(
            order_id=order_id,
            tenant_id=TENANT_ID,
            db=db_session,
            received_items=[{"item_id": item_id, "received_quantity": 15.0}],
        )

        txns = (await db_session.execute(
            select(IngredientTransaction).where(
                IngredientTransaction.transaction_type == TransactionType.transfer_in.value,
                IngredientTransaction.tenant_id == uuid.UUID(TENANT_ID),
            )
        )).scalars().all()
        assert len(txns) == 1
        assert txns[0].quantity == 15.0


# ─── 取消 ─────────────────────────────────────────────────


class TestCancelTransfer:
    @pytest.mark.asyncio
    async def test_cancel_draft(self, db_session):
        items = [
            {
                "ingredient_id": ING_A_ID,
                "ingredient_name": "鲈鱼",
                "requested_quantity": 5.0,
                "unit": "kg",
            }
        ]
        order_info = await create_transfer_order(
            tenant_id=TENANT_ID,
            from_store_id=STORE_A,
            to_store_id=STORE_B,
            items=items,
            db=db_session,
        )
        result = await cancel_transfer_order(
            order_id=order_info["order_id"],
            tenant_id=TENANT_ID,
            db=db_session,
            reason="需求已满足",
        )
        assert result["status"] == TransferOrderStatus.cancelled.value

    @pytest.mark.asyncio
    async def test_cannot_cancel_shipped(self, db_session):
        """已发货的单据不能取消"""
        items = [
            {
                "ingredient_id": ING_A_ID,
                "ingredient_name": "鲈鱼",
                "requested_quantity": 5.0,
                "unit": "kg",
            }
        ]
        order_info = await create_transfer_order(
            tenant_id=TENANT_ID,
            from_store_id=STORE_A,
            to_store_id=STORE_B,
            items=items,
            db=db_session,
        )
        detail = await get_transfer_order(
            order_id=order_info["order_id"], tenant_id=TENANT_ID, db=db_session
        )
        item_id = detail["items"][0]["item_id"]

        await approve_transfer_order(
            order_id=order_info["order_id"],
            tenant_id=TENANT_ID,
            db=db_session,
            approved_by=str(uuid.uuid4()),
            approved_items=[],
        )
        await ship_transfer_order(
            order_id=order_info["order_id"],
            tenant_id=TENANT_ID,
            db=db_session,
            shipped_items=[{"item_id": item_id, "shipped_quantity": 5.0}],
        )

        with pytest.raises(ValueError, match="已发货"):
            await cancel_transfer_order(
                order_id=order_info["order_id"],
                tenant_id=TENANT_ID,
                db=db_session,
            )


# ─── 多租户隔离 ───────────────────────────────────────────


class TestMultiTenantIsolation:
    @pytest.mark.asyncio
    async def test_cannot_access_other_tenant_order(self, db_session):
        """不同租户不能查看对方的调拨单"""
        other_tenant = str(uuid.uuid4())

        items = [
            {
                "ingredient_id": ING_A_ID,
                "ingredient_name": "鲈鱼",
                "requested_quantity": 5.0,
                "unit": "kg",
            }
        ]
        order_info = await create_transfer_order(
            tenant_id=TENANT_ID,
            from_store_id=STORE_A,
            to_store_id=STORE_B,
            items=items,
            db=db_session,
        )

        with pytest.raises(ValueError, match="不存在"):
            await get_transfer_order(
                order_id=order_info["order_id"],
                tenant_id=other_tenant,
                db=db_session,
            )
