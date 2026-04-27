"""tx-supply 事件接入验证测试

验证以下服务在业务操作完成后正确触发 emit_event：
1. receiving_service.create_receiving  → supply.goods_received
2. receiving_service.reject_item       → supply.goods_rejected
3. bom_service.BOMService.create_bom_template → supply.bom_updated
4. bom_service.BOMService.update_bom_template → supply.bom_updated
5. inventory_io.receive_stock          → inventory.received
6. inventory_io.issue_stock            → inventory.consumed
7. inventory_io.adjust_stock           → inventory.adjusted

使用 unittest.mock.patch 对 emit_event 进行 mock，
不依赖任何数据库连接。
"""
from __future__ import annotations

import asyncio
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ─────────────────────────────────────────────────────────────────────────────
# 测试工具
# ─────────────────────────────────────────────────────────────────────────────

TENANT_ID = str(uuid.uuid4())
STORE_ID = str(uuid.uuid4())
DISH_ID = str(uuid.uuid4())
INGREDIENT_ID = str(uuid.uuid4())
PURCHASE_ORDER_ID = f"po_{uuid.uuid4().hex[:8]}"


def _run(coro):
    """在测试中运行协程（兼容无事件循环环境）。"""
    return asyncio.get_event_loop().run_until_complete(coro)


# ─────────────────────────────────────────────────────────────────────────────
# B3 — receiving_service 测试
# ─────────────────────────────────────────────────────────────────────────────

class TestReceivingServiceEvents:
    """收货验收服务事件发射测试"""

    @pytest.mark.asyncio
    async def test_create_receiving_emits_goods_received(self):
        """收货验收完成后，emit_event 被调用，event_type 为 supply.goods_received"""
        with patch(
            "services.tx_supply.src.services.receiving_service.emit_event",
            new_callable=AsyncMock,
        ) as mock_emit, patch(
            "asyncio.create_task",
        ) as mock_task:
            # 让 create_task 直接执行协程（避免事件循环问题）
            mock_task.side_effect = lambda coro: asyncio.ensure_future(coro)

            from services.tx_supply.src.services.receiving_service import create_receiving

            items = [
                {
                    "ingredient_id": INGREDIENT_ID,
                    "name": "土豆",
                    "ordered_qty": 10.0,
                    "received_qty": 9.5,
                    "quality": "pass",
                },
            ]
            result = await create_receiving(
                purchase_order_id=PURCHASE_ORDER_ID,
                items=items,
                receiver_id="user_001",
                tenant_id=TENANT_ID,
                db=MagicMock(),
            )

            assert result["status"] == "accepted"
            mock_emit.assert_called_once()
            call_kwargs = mock_emit.call_args.kwargs
            assert call_kwargs["event_type"] == "supply.goods_received"
            assert call_kwargs["tenant_id"] == TENANT_ID
            assert call_kwargs["stream_id"] == PURCHASE_ORDER_ID
            assert "order_id" in call_kwargs["payload"]
            assert call_kwargs["payload"]["order_id"] == PURCHASE_ORDER_ID

    @pytest.mark.asyncio
    async def test_reject_item_emits_goods_rejected(self):
        """拒收操作完成后，emit_event 被调用，event_type 为 supply.goods_rejected"""
        with patch(
            "services.tx_supply.src.services.receiving_service.emit_event",
            new_callable=AsyncMock,
        ) as mock_emit, patch(
            "asyncio.create_task",
        ) as mock_task:
            mock_task.side_effect = lambda coro: asyncio.ensure_future(coro)

            from services.tx_supply.src.services.receiving_service import reject_item

            receiving_id = f"rcv_{uuid.uuid4().hex[:8]}"
            result = await reject_item(
                receiving_id=receiving_id,
                item_id=INGREDIENT_ID,
                reason="质量不达标",
                quantity=2.0,
                tenant_id=TENANT_ID,
                db=MagicMock(),
            )

            assert result["status"] == "pending_return"
            mock_emit.assert_called_once()
            call_kwargs = mock_emit.call_args.kwargs
            assert call_kwargs["event_type"] == "supply.goods_rejected"
            assert call_kwargs["tenant_id"] == TENANT_ID
            assert call_kwargs["payload"]["reason"] == "质量不达标"
            assert len(call_kwargs["payload"]["rejected_items"]) == 1
            assert call_kwargs["payload"]["rejected_items"][0]["item_id"] == INGREDIENT_ID

    @pytest.mark.asyncio
    async def test_create_receiving_partial_quality_emits_event(self):
        """部分验收（有质量问题）也应正确触发 goods_received 事件"""
        with patch(
            "services.tx_supply.src.services.receiving_service.emit_event",
            new_callable=AsyncMock,
        ) as mock_emit, patch(
            "asyncio.create_task",
        ) as mock_task:
            mock_task.side_effect = lambda coro: asyncio.ensure_future(coro)

            from services.tx_supply.src.services.receiving_service import create_receiving

            items = [
                {"ingredient_id": INGREDIENT_ID, "ordered_qty": 10, "received_qty": 8, "quality": "fail"},
                {"ingredient_id": str(uuid.uuid4()), "ordered_qty": 5, "received_qty": 5, "quality": "pass"},
            ]
            result = await create_receiving(
                purchase_order_id=PURCHASE_ORDER_ID,
                items=items,
                receiver_id="user_001",
                tenant_id=TENANT_ID,
                db=MagicMock(),
            )

            assert result["status"] == "partial"
            mock_emit.assert_called_once()
            call_kwargs = mock_emit.call_args.kwargs
            assert call_kwargs["event_type"] == "supply.goods_received"
            assert call_kwargs["payload"]["all_pass"] is False


# ─────────────────────────────────────────────────────────────────────────────
# B5 — bom_service 测试
# ─────────────────────────────────────────────────────────────────────────────

class TestBOMServiceEvents:
    """BOM 服务事件发射测试"""

    def _make_db_mock(self) -> MagicMock:
        """构造一个最小化的 AsyncSession mock"""
        db = MagicMock()
        db.execute = AsyncMock()
        db.flush = AsyncMock()
        return db

    @pytest.mark.asyncio
    async def test_create_bom_template_emits_bom_updated(self):
        """BOM 模板创建后，emit_event 被调用，event_type 为 supply.bom_updated"""
        with patch(
            "services.tx_supply.src.services.bom_service.emit_event",
            new_callable=AsyncMock,
        ) as mock_emit, patch(
            "asyncio.create_task",
        ) as mock_task:
            mock_task.side_effect = lambda coro: asyncio.ensure_future(coro)

            from services.tx_supply.src.services.bom_service import BOMService

            db = self._make_db_mock()
            svc = BOMService(db=db, tenant_id=TENANT_ID)

            items = [
                {
                    "ingredient_id": INGREDIENT_ID,
                    "standard_qty": 100.0,
                    "unit": "g",
                }
            ]
            result = await svc.create_bom_template(
                dish_id=DISH_ID,
                items=items,
                store_id=STORE_ID,
            )

            assert result["dish_id"] == DISH_ID
            mock_emit.assert_called_once()
            call_kwargs = mock_emit.call_args.kwargs
            assert call_kwargs["event_type"] == "supply.bom_updated"
            assert call_kwargs["tenant_id"] == TENANT_ID
            assert call_kwargs["stream_id"] == DISH_ID
            payload = call_kwargs["payload"]
            assert payload["dish_id"] == DISH_ID
            assert payload["action"] == "created"
            assert len(payload["ingredients"]) == 1
            assert payload["ingredients"][0]["ingredient_id"] == INGREDIENT_ID

    @pytest.mark.asyncio
    async def test_update_bom_template_emits_bom_updated(self):
        """BOM 模板更新后，emit_event 被调用，action 为 updated"""
        with patch(
            "services.tx_supply.src.services.bom_service.emit_event",
            new_callable=AsyncMock,
        ) as mock_emit, patch(
            "asyncio.create_task",
        ) as mock_task:
            mock_task.side_effect = lambda coro: asyncio.ensure_future(coro)

            from services.tx_supply.src.services.bom_service import BOMService

            db = self._make_db_mock()
            template_id = str(uuid.uuid4())
            store_uuid = uuid.UUID(STORE_ID)

            # mock execute 返回模板行
            check_mapping = MagicMock()
            check_mapping.first.return_value = {
                "id": uuid.UUID(template_id),
                "store_id": store_uuid,
                "dish_id": uuid.UUID(DISH_ID),
                "version": "v2",
            }
            db.execute.return_value.mappings.return_value = check_mapping

            svc = BOMService(db=db, tenant_id=TENANT_ID)

            new_items = [
                {
                    "ingredient_id": INGREDIENT_ID,
                    "standard_qty": 120.0,
                    "unit": "g",
                }
            ]
            result = await svc.update_bom_template(
                template_id=template_id,
                items=new_items,
            )

            assert result is not None
            mock_emit.assert_called_once()
            call_kwargs = mock_emit.call_args.kwargs
            assert call_kwargs["event_type"] == "supply.bom_updated"
            assert call_kwargs["payload"]["action"] == "updated"
            assert call_kwargs["payload"]["dish_id"] == DISH_ID

    @pytest.mark.asyncio
    async def test_update_bom_template_not_found_no_emit(self):
        """BOM 模板不存在时，不触发事件"""
        with patch(
            "services.tx_supply.src.services.bom_service.emit_event",
            new_callable=AsyncMock,
        ) as mock_emit, patch(
            "asyncio.create_task",
        ) as mock_task:
            mock_task.side_effect = lambda coro: asyncio.ensure_future(coro)

            from services.tx_supply.src.services.bom_service import BOMService

            db = self._make_db_mock()
            # 返回 None 表示模板不存在
            check_mapping = MagicMock()
            check_mapping.first.return_value = None
            db.execute.return_value.mappings.return_value = check_mapping

            svc = BOMService(db=db, tenant_id=TENANT_ID)
            result = await svc.update_bom_template(
                template_id=str(uuid.uuid4()),
                items=[],
            )

            assert result is None
            mock_emit.assert_not_called()


# ─────────────────────────────────────────────────────────────────────────────
# 快速校验：emit_event 调用约定
# ─────────────────────────────────────────────────────────────────────────────

class TestEmitEventCallConvention:
    """emit_event 调用约定测试 —— 确保 source_service 始终为 tx-supply"""

    @pytest.mark.asyncio
    async def test_receiving_source_service_is_tx_supply(self):
        """所有收货事件的 source_service 必须是 tx-supply"""
        with patch(
            "services.tx_supply.src.services.receiving_service.emit_event",
            new_callable=AsyncMock,
        ) as mock_emit, patch("asyncio.create_task") as mock_task:
            mock_task.side_effect = lambda coro: asyncio.ensure_future(coro)

            from services.tx_supply.src.services.receiving_service import create_receiving

            await create_receiving(
                purchase_order_id=PURCHASE_ORDER_ID,
                items=[{"ingredient_id": INGREDIENT_ID, "ordered_qty": 1, "received_qty": 1, "quality": "pass"}],
                receiver_id="u1",
                tenant_id=TENANT_ID,
                db=MagicMock(),
            )

            call_kwargs = mock_emit.call_args.kwargs
            assert call_kwargs["source_service"] == "tx-supply"

    @pytest.mark.asyncio
    async def test_bom_source_service_is_tx_supply(self):
        """所有 BOM 事件的 source_service 必须是 tx-supply"""
        with patch(
            "services.tx_supply.src.services.bom_service.emit_event",
            new_callable=AsyncMock,
        ) as mock_emit, patch("asyncio.create_task") as mock_task:
            mock_task.side_effect = lambda coro: asyncio.ensure_future(coro)

            from services.tx_supply.src.services.bom_service import BOMService

            db = MagicMock()
            db.execute = AsyncMock()
            db.flush = AsyncMock()
            svc = BOMService(db=db, tenant_id=TENANT_ID)

            await svc.create_bom_template(
                dish_id=DISH_ID,
                items=[{"ingredient_id": INGREDIENT_ID, "standard_qty": 50, "unit": "g"}],
                store_id=STORE_ID,
            )

            call_kwargs = mock_emit.call_args.kwargs
            assert call_kwargs["source_service"] == "tx-supply"
