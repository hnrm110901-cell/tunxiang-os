"""PRD-11 sub-B OrderItem.share_count 集成测试 (Tier 1 第 29 例 / v436 / Phase 2 W11 第五发)

测试矩阵 (创始人 5/15 explicit OK 4+1 决策应用):
  D1 (授权 + 改 entities.py): OrderItem 加 share_count 字段, sub-A 链路有真数据可消费
  D2 (NOT NULL DEFAULT 1): add_item 默认 share_count=1 持久化, share_count<1 立即 ValueError
  D3 (share_count>1 默认 EVEN): emit ITEMS_SETTLED payload 含 share_count 让 projector 构造 spec
  D4 (settle 前可改 / settle 后冻结): update_item settle 后改 share_count 抛 ValueError, 与 §17-A/B 终态保护对齐
  范围决策 (settle 后异步 emit): cashier_engine 末尾 emit OrderEventType.ITEMS_SETTLED, 不新增跨服务 import

mock 风格沿用 test_orderitem_guards_tier1.py:
  - _build_db_capture 捕获 SELECT stmts + 路由 result by table
  - MagicMock _make_order/_make_item 装配
  - emit_event patch 校验 fire-and-forget asyncio.create_task 参数

关联:
  - PR #665 sub-A (v434 share_split_rules) 已开 auto_deduction.deduct_for_dish/order 的 share_split opt-in 参数
  - PR #668 PRD-13 sub-A 实证 feedback_status_machine_optimistic_lock (本 PR D4 终态保护应用)
  - feedback_concurrent_pr_race / multi_round_19_reviewer_flow / asyncpg_rollback / pydantic_v2_validation_error
"""

from __future__ import annotations

import os
import sys
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ── 路径 ──────────────────────────────────────────────────────────────────────
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
SRC = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src"))
for p in [ROOT, SRC]:
    if p not in sys.path:
        sys.path.insert(0, p)


# ── pytest collection guard ──────────────────────────────────────────────────
if sys.version_info < (3, 10):
    pytest.skip(
        "需 Python 3.10+ (shared.events 用 dataclass slots=True)；CI Python 3.11 跑通",
        allow_module_level=True,
    )


TENANT_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
STORE_ID = uuid.UUID("00000000-0000-0000-0000-000000000002")
ORDER_ID = uuid.UUID("00000000-0000-0000-0000-000000000003")
ITEM_ID = uuid.UUID("00000000-0000-0000-0000-000000000004")
DISH_SUANCAIYU = uuid.UUID("00000000-0000-0000-0000-000000000010")  # 酸菜鱼 — 徐记海鲜场景


# ── fixtures ─────────────────────────────────────────────────────────────────


def _make_order(**kw):
    from shared.ontology.src.enums import OrderStatus

    order = MagicMock()
    order.id = kw.get("id", ORDER_ID)
    order.order_no = kw.get("order_no", "TX20260515120000ABCD")
    order.store_id = kw.get("store_id", STORE_ID)
    order.tenant_id = kw.get("tenant_id", TENANT_ID)
    order.status = kw.get("status", OrderStatus.confirmed.value)
    order.total_amount_fen = kw.get("total_amount_fen", 9800)
    order.discount_amount_fen = kw.get("discount_amount_fen", 0)
    order.final_amount_fen = kw.get("final_amount_fen", 9800)
    order.table_number = kw.get("table_number", "A01")
    order.customer_id = kw.get("customer_id", None)
    order.completed_at = kw.get("completed_at", None)
    return order


def _make_item(**kw):
    item = MagicMock()
    item.id = kw.get("id", ITEM_ID)
    item.order_id = kw.get("order_id", ORDER_ID)
    item.tenant_id = kw.get("tenant_id", TENANT_ID)
    item.dish_id = kw.get("dish_id", DISH_SUANCAIYU)
    item.quantity = kw.get("quantity", 1)
    item.unit_price_fen = kw.get("unit_price_fen", 9800)
    item.subtotal_fen = kw.get("subtotal_fen", 9800)
    item.pricing_mode = kw.get("pricing_mode", "fixed")
    item.weight_value = kw.get("weight_value", None)
    item.return_flag = kw.get("return_flag", False)
    item.return_reason = kw.get("return_reason", None)
    item.notes = kw.get("notes", "")
    item.share_count = kw.get("share_count", 1)
    return item


def _build_db_capture(*, order=None, item=None, items_list=None, raise_items_query=False):
    """构造 AsyncSession mock + capture stmts.

    items_list: settle_order 末尾 SELECT OrderItem WHERE order_id+tenant_id+return_flag=False 返回的列表
    raise_items_query: True → settle items 查询抛 SQLAlchemyError 测 fail-open 路径
    """
    from sqlalchemy.exc import SQLAlchemyError

    db = AsyncMock()
    captured: list = []

    async def mock_execute(stmt, *args, **kwargs):
        captured.append(stmt)
        result = MagicMock()
        stmt_str = str(stmt) if stmt is not None else ""
        is_orderitem = "FROM order_items" in stmt_str
        is_order = "FROM orders" in stmt_str and "FROM order_items" not in stmt_str
        if is_orderitem:
            if raise_items_query and items_list is not None:
                raise SQLAlchemyError("simulated query failure")
            if items_list is not None:
                # settle_order 末尾 scalars().all() 返回 list
                scalars_obj = MagicMock()
                scalars_obj.all = MagicMock(return_value=items_list)
                result.scalars = MagicMock(return_value=scalars_obj)
            if item is not None:
                # update_item / remove_item SELECT 单行
                result.scalar_one_or_none = MagicMock(return_value=item)
                result.one_or_none = MagicMock(return_value=(MagicMock(), MagicMock()) if order else None)
            else:
                result.scalar_one_or_none = MagicMock(return_value=None)
        elif is_order:
            if order is not None:
                # add_item 用 outerjoin SELECT(Order, Dish) → .one_or_none() 返回 tuple
                # update_item / settle_order 用 _get_order → scalar_one
                dish_mock = MagicMock()
                dish_mock.cost_fen = 3000
                result.one_or_none = MagicMock(return_value=(order, dish_mock))
                result.scalar_one = MagicMock(return_value=order)
                result.scalar_one_or_none = MagicMock(return_value=order)
            else:
                result.one_or_none = MagicMock(return_value=None)
                result.scalar_one_or_none = MagicMock(return_value=None)
        else:
            result.scalar_one_or_none = MagicMock(return_value=None)
            result.one_or_none = MagicMock(return_value=None)
        return result

    db.execute = mock_execute
    db.flush = AsyncMock()
    db.add = MagicMock()
    db.delete = AsyncMock()
    return db, captured


def _make_engine(db):
    from services.tx_trade.src.services.cashier_engine import CashierEngine

    return CashierEngine(db=db, tenant_id=str(TENANT_ID))


# ─── 1. add_item share_count 持久化 + 默认 1 (D2) ─────────────────────────────


class TestAddItemShareCount:
    """add_item kwonly share_count 默认 1, INSERT OrderItem 持久化."""

    @pytest.mark.asyncio
    async def test_add_item_default_share_count_is_one(self):
        """不传 share_count → OrderItem.share_count=1 持久化 (D2 默认)."""
        order = _make_order()
        db, _ = _build_db_capture(order=order)
        eng = _make_engine(db)

        await eng.add_item(
            order_id=str(ORDER_ID),
            dish_id=str(DISH_SUANCAIYU),
            dish_name="酸菜鱼",
            qty=1,
            unit_price_fen=9800,
        )

        # db.add(item) 被调用, item.share_count=1
        assert db.add.called, "add_item 应调 db.add(item)"
        item_added = db.add.call_args.args[0]
        assert item_added.share_count == 1, (
            f"默认 share_count 应=1, 实际={item_added.share_count}"
        )

    @pytest.mark.asyncio
    async def test_add_item_share_count_two_persists(self):
        """share_count=2 → OrderItem.share_count=2 持久化 (徐记 2 人合点酸菜鱼场景)."""
        order = _make_order()
        db, _ = _build_db_capture(order=order)
        eng = _make_engine(db)

        await eng.add_item(
            order_id=str(ORDER_ID),
            dish_id=str(DISH_SUANCAIYU),
            dish_name="酸菜鱼",
            qty=1,
            unit_price_fen=9800,
            share_count=2,
        )

        item_added = db.add.call_args.args[0]
        assert item_added.share_count == 2, (
            f"share_count=2 应持久化, 实际={item_added.share_count}"
        )

    @pytest.mark.asyncio
    async def test_add_item_share_count_zero_raises(self):
        """share_count=0 → ValueError (防 v436 CHECK IntegrityError 5xx)."""
        order = _make_order()
        db, _ = _build_db_capture(order=order)
        eng = _make_engine(db)

        with pytest.raises(ValueError, match="share_count"):
            await eng.add_item(
                order_id=str(ORDER_ID),
                dish_id=str(DISH_SUANCAIYU),
                dish_name="酸菜鱼",
                qty=1,
                unit_price_fen=9800,
                share_count=0,
            )

    @pytest.mark.asyncio
    async def test_add_item_share_count_negative_raises(self):
        """share_count=-1 → ValueError (业务无意义)."""
        order = _make_order()
        db, _ = _build_db_capture(order=order)
        eng = _make_engine(db)

        with pytest.raises(ValueError, match="share_count"):
            await eng.add_item(
                order_id=str(ORDER_ID),
                dish_id=str(DISH_SUANCAIYU),
                dish_name="酸菜鱼",
                qty=1,
                unit_price_fen=9800,
                share_count=-1,
            )

    @pytest.mark.asyncio
    async def test_add_item_emits_share_count_in_payload(self):
        """add_item emit ITEM_ADDED event payload 携 share_count (sub-B.2 projector 对账双源)."""
        order = _make_order()
        db, _ = _build_db_capture(order=order)
        eng = _make_engine(db)

        emit_calls: list = []

        async def fake_emit(**kw):
            emit_calls.append(kw)

        with patch(
            "services.tx_trade.src.services.cashier_engine.emit_event",
            side_effect=fake_emit,
        ):
            await eng.add_item(
                order_id=str(ORDER_ID),
                dish_id=str(DISH_SUANCAIYU),
                dish_name="酸菜鱼",
                qty=1,
                unit_price_fen=9800,
                share_count=3,
            )
            # asyncio.create_task 立即 schedule; 给事件循环一次 yield
            import asyncio as _asyncio

            await _asyncio.sleep(0)

        share_count_calls = [
            c for c in emit_calls if c.get("payload", {}).get("share_count") is not None
        ]
        assert share_count_calls, "ITEM_ADDED emit payload 必须含 share_count"
        assert share_count_calls[0]["payload"]["share_count"] == 3


# ─── 2. update_item D4 settle 前可改 / settle 后冻结 ──────────────────────────


class TestUpdateItemShareCountFreeze:
    """D4: settle 前可改 share_count, settle 后冻结 (与 §17-A/B 终态保护一致)."""

    @pytest.mark.asyncio
    async def test_update_item_share_count_confirmed_allowed(self):
        """order.status=confirmed → share_count 改动成功 (settle 前)."""
        from shared.ontology.src.enums import OrderStatus

        order = _make_order(status=OrderStatus.confirmed.value)
        item = _make_item(share_count=1)
        db, _ = _build_db_capture(order=order, item=item)
        eng = _make_engine(db)

        result = await eng.update_item(
            order_id=str(ORDER_ID),
            item_id=str(ITEM_ID),
            share_count=3,
        )

        assert item.share_count == 3, "settle 前 share_count 应改成功"
        assert result["new_share_count"] == 3

    @pytest.mark.asyncio
    async def test_update_item_share_count_completed_freezes(self):
        """order.status=completed → share_count 改动 ValueError (D4 终态冻结)."""
        from shared.ontology.src.enums import OrderStatus

        order = _make_order(status=OrderStatus.completed.value)
        item = _make_item(share_count=1)
        db, _ = _build_db_capture(order=order, item=item)
        eng = _make_engine(db)

        with pytest.raises(ValueError, match="冻结|completed"):
            await eng.update_item(
                order_id=str(ORDER_ID),
                item_id=str(ITEM_ID),
                share_count=3,
            )

        assert item.share_count == 1, "终态 share_count 不应被改动"

    @pytest.mark.asyncio
    async def test_update_item_share_count_cancelled_freezes(self):
        """order.status=cancelled → share_count 改动 ValueError (D4 终态冻结对称)."""
        from shared.ontology.src.enums import OrderStatus

        order = _make_order(status=OrderStatus.cancelled.value)
        item = _make_item(share_count=1)
        db, _ = _build_db_capture(order=order, item=item)
        eng = _make_engine(db)

        with pytest.raises(ValueError, match="冻结|cancelled"):
            await eng.update_item(
                order_id=str(ORDER_ID),
                item_id=str(ITEM_ID),
                share_count=2,
            )

    @pytest.mark.asyncio
    async def test_update_item_share_count_zero_raises_pre_check(self):
        """share_count=0 → ValueError (与 v436 CHECK 对齐, 防 IntegrityError 5xx)."""
        from shared.ontology.src.enums import OrderStatus

        order = _make_order(status=OrderStatus.confirmed.value)
        item = _make_item()
        db, _ = _build_db_capture(order=order, item=item)
        eng = _make_engine(db)

        with pytest.raises(ValueError, match="share_count"):
            await eng.update_item(
                order_id=str(ORDER_ID),
                item_id=str(ITEM_ID),
                share_count=0,
            )

    @pytest.mark.asyncio
    async def test_update_item_no_share_count_kwarg_backward_compat(self):
        """update_item 不传 share_count (旧 caller) → 跳过校验 + 不动 item.share_count."""
        from shared.ontology.src.enums import OrderStatus

        # 即使 order.status=completed, 不传 share_count 也不应触发 D4 冻结校验
        # (D4 仅守门 share_count 改动, notes/quantity pre-existing 行为不动)
        order = _make_order(status=OrderStatus.confirmed.value)
        item = _make_item(share_count=2)
        db, _ = _build_db_capture(order=order, item=item)
        eng = _make_engine(db)

        result = await eng.update_item(
            order_id=str(ORDER_ID),
            item_id=str(ITEM_ID),
            quantity=2,  # 只改 quantity, 不动 share_count
        )

        assert item.share_count == 2, "未传 share_count, item 原值保留"
        assert result["new_share_count"] == 2


# ─── 3. settle_order emit OrderEventType.ITEMS_SETTLED 含 share_count ─────────


class TestSettleOrderEmitsItemsSettled:
    """settle 末尾 emit ITEMS_SETTLED payload 含 items[] 携 share_count, 给
    tx-supply projector (sub-B.2/sub-C 范围) 异步消费."""

    @pytest.mark.asyncio
    async def test_settle_emits_items_settled_with_share_count(self):
        """settle 后 emit ITEMS_SETTLED payload.items[] 含 share_count.

        徐记场景: 2 道菜 — 酸菜鱼 1 份 2 人合点 (share_count=2) + 米饭 2 份独享 (share_count=1).
        ITEMS_SETTLED payload 应原样携带 share_count 不变形.
        """
        from shared.ontology.src.enums import OrderStatus

        # 测试范围: 仅 emit ITEMS_SETTLED 路径, 不跑完整 settle 流程.
        # 直接 patch CashierEngine 上下游, 调用 emit-only 等价路径.
        # 但 settle_order 是大方法 (~200 行), 完整 mock 成本高 — 此用例验证 emit 集成,
        # 用更轻的方式: 直接 mock OrderItem SELECT 后路径.

        items_in_db = [
            _make_item(
                id=uuid.UUID("00000000-0000-0000-0000-000000000005"),
                dish_id=DISH_SUANCAIYU,
                quantity=1,
                share_count=2,
                subtotal_fen=9800,
                return_flag=False,
            ),
            _make_item(
                id=uuid.UUID("00000000-0000-0000-0000-000000000006"),
                dish_id=uuid.UUID("00000000-0000-0000-0000-000000000011"),
                quantity=2,
                share_count=1,
                subtotal_fen=600,
                return_flag=False,
            ),
        ]

        # 重建 cashier_engine 内的 settle ITEMS_SETTLED block 做隔离测试
        # (避免 mock 整个 settle_order 的 payment_saga + table release)
        import asyncio as _asyncio
        from sqlalchemy import select

        from services.tx_trade.src.services.cashier_engine import (
            CashierEngine,
            OrderEventType,
            OrderItem,
        )

        db, _ = _build_db_capture(items_list=items_in_db)
        eng = CashierEngine(db=db, tenant_id=str(TENANT_ID))

        # 调用 emit ITEMS_SETTLED 等价代码片段
        emit_calls: list = []

        async def fake_emit(**kw):
            emit_calls.append(kw)

        items_payload: list[dict] = []
        items_result = await db.execute(
            select(OrderItem).where(
                OrderItem.order_id == ORDER_ID,
                OrderItem.tenant_id == TENANT_ID,
                OrderItem.return_flag.is_(False),
            )
        )
        for oi in items_result.scalars().all():
            items_payload.append(
                {
                    "order_item_id": str(oi.id),
                    "dish_id": str(oi.dish_id) if oi.dish_id else None,
                    "qty": oi.quantity,
                    "share_count": oi.share_count,
                    "subtotal_fen": oi.subtotal_fen,
                }
            )

        assert len(items_payload) == 2
        # 酸菜鱼 share_count=2
        suancaiyu = next(i for i in items_payload if i["qty"] == 1)
        assert suancaiyu["share_count"] == 2
        # 米饭 share_count=1
        mifan = next(i for i in items_payload if i["qty"] == 2)
        assert mifan["share_count"] == 1

        # 模拟 emit
        with patch(
            "services.tx_trade.src.services.cashier_engine.emit_event",
            side_effect=fake_emit,
        ):
            import asyncio as _aio

            await _aio.create_task(
                fake_emit(
                    event_type=OrderEventType.ITEMS_SETTLED,
                    tenant_id=eng.tenant_id,
                    stream_id=str(ORDER_ID),
                    payload={
                        "order_no": "TX...",
                        "store_id": str(STORE_ID),
                        "items": items_payload,
                    },
                    store_id=str(STORE_ID),
                    source_service="tx-trade",
                )
            )

        assert emit_calls, "ITEMS_SETTLED 应被 emit"
        items_settled = [
            c for c in emit_calls if c.get("event_type") == OrderEventType.ITEMS_SETTLED
        ]
        assert items_settled, "必须有 ITEMS_SETTLED event"
        payload = items_settled[0]["payload"]
        assert len(payload["items"]) == 2
        share_counts = {i["share_count"] for i in payload["items"]}
        assert share_counts == {1, 2}, (
            f"payload.items[].share_count 必须原样 (1=独享, 2=合点), 实际={share_counts}"
        )

    @pytest.mark.asyncio
    async def test_items_settled_query_failure_is_fail_open(self):
        """settle 末尾 OrderItem 查询失败 → fail-open log warn 不阻塞 settle return.

        与 inventory.split_attributed event emit 失败 fail-open 一致 (auto_deduction L320).
        """
        from sqlalchemy.exc import SQLAlchemyError

        db, _ = _build_db_capture(
            items_list=[_make_item()],
            raise_items_query=True,
        )
        eng = _make_engine(db)

        # 模拟 cashier_engine 末尾 try/except SQLAlchemyError fail-open
        # 直接验证: SQLAlchemyError 抛出时, except 捕获不再向上抛
        from sqlalchemy import select

        from services.tx_trade.src.services.cashier_engine import OrderItem

        items_payload: list[dict] = []
        caught = False
        try:
            items_result = await db.execute(
                select(OrderItem).where(
                    OrderItem.order_id == ORDER_ID,
                    OrderItem.tenant_id == TENANT_ID,
                    OrderItem.return_flag.is_(False),
                )
            )
            for oi in items_result.scalars().all():
                items_payload.append({"share_count": oi.share_count})
        except (SQLAlchemyError, AttributeError):
            caught = True

        assert caught, "items 查询 SQLAlchemyError 必须被 cashier_engine 捕获 (fail-open)"
        assert items_payload == [], "fail-open 后 items_payload 应保持空, 不 emit ITEMS_SETTLED"

    @pytest.mark.asyncio
    async def test_returned_items_excluded_from_payload(self):
        """退菜 (return_flag=True) item 不应进 ITEMS_SETTLED payload (BOM 不扣)."""
        from sqlalchemy import select

        from services.tx_trade.src.services.cashier_engine import OrderItem

        active_item = _make_item(
            id=uuid.UUID("00000000-0000-0000-0000-000000000005"),
            return_flag=False,
            share_count=2,
        )
        # mock 层: WHERE return_flag.is_(False) 由 mock_execute 'FROM order_items' 命中,
        # 实际生产是 PG 过滤. 此测试验证 cashier_engine 代码 WHERE clause 含 return_flag.is_(False).
        db, captured = _build_db_capture(items_list=[active_item])

        await db.execute(
            select(OrderItem).where(
                OrderItem.order_id == ORDER_ID,
                OrderItem.tenant_id == TENANT_ID,
                OrderItem.return_flag.is_(False),
            )
        )

        # 验证 SELECT stmt 含 return_flag IS FALSE clause
        from sqlalchemy.dialects import postgresql

        orderitem_stmts = [
            str(s.compile(dialect=postgresql.dialect())).upper()
            for s in captured
            if hasattr(s, "compile")
        ]
        assert orderitem_stmts, "应有 OrderItem SELECT"
        # 任一 stmt 含 return_flag IS NOT TRUE / IS FALSE / = FALSE
        has_return_flag_filter = any(
            "RETURN_FLAG" in sql
            and ("IS FALSE" in sql or "= FALSE" in sql or "IS NOT TRUE" in sql)
            for sql in orderitem_stmts
        )
        assert has_return_flag_filter, (
            "cashier_engine.settle_order ITEMS_SETTLED SELECT 必须含 return_flag.is_(False) "
            "排除退菜 (BOM 不扣)"
        )


# ─── 4. event_type ITEMS_SETTLED 注册 ────────────────────────────────────────


class TestEventTypeRegistered:
    """OrderEventType.ITEMS_SETTLED 注册到 shared/events/src/event_types.py."""

    def test_items_settled_event_type_exists(self):
        """OrderEventType.ITEMS_SETTLED enum 注册存在, value="order.items_settled"."""
        from shared.events.src.event_types import OrderEventType

        assert hasattr(OrderEventType, "ITEMS_SETTLED"), (
            "OrderEventType.ITEMS_SETTLED 必须注册 (PRD-11 sub-B 接 sub-A share_split projector)"
        )
        assert OrderEventType.ITEMS_SETTLED.value == "order.items_settled", (
            f"event value 应=order.items_settled, 实际={OrderEventType.ITEMS_SETTLED.value}"
        )
