"""§17-C OrderItem row-lock Tier 1 并发反测 — 真 PG

PR-Tier1 §17-C of 2026-05-13 audit doc §4.1 P1 — OrderItem 漏锁 4 路径修复:
  - cashier_engine.update_item / remove_item (OrderItem FOR UPDATE + Order FOR UPDATE)
  - order_service.update_item_quantity / remove_item (OrderItem FOR UPDATE 仅)

验证 audit doc §4.1 OrderItem 漏锁**真行为** (与 mock SQL grep 互补):

  - T1: N=10 concurrent update_item_quantity 同 item → 最终 item.subtotal_fen 与
        Order.total_amount_fen 自洽 (FOR UPDATE 串行化 + raw arithmetic 累积安全)
  - T2: N=5 concurrent update_item_quantity 不同 item 同 order → Order.total 累积正确
        (cross-item Order arithmetic 不需 Order FOR UPDATE 也 PG 原子)
  - T3: cashier_engine.update_item N=10 concurrent → Python recalc 路径 FOR UPDATE
        串行化让 Order.total 累积正确 (Python-side new_total 不是 PG 原子, 必须 lock)

业务场景 (audit doc §4.1 P1):
  - 服务员 PWA 加菜后改数量重试网络抖动 → 双改同 item
  - 桌长 POS + 服务员 PWA 同时改不同 item → cross-item race
  - 500 桌徐记海鲜峰值: order.total 必须与 sum(item.subtotal) 自洽 (账单核对底线)

跑法 (opt-in via INTEGRATION_PG_DSN):

    INTEGRATION_PG_DSN=postgresql://tunxiang_test:test_password_dev_only@localhost:5433/tunxiang_os_test \\
        pytest tests/concurrent/test_cashier_orderitem_concurrent_tier1.py \\
        --confcutdir tests/concurrent --override-ini asyncio_mode=auto -v

未设 INTEGRATION_PG_DSN → 全部 skip (opt-in 模式).

关联:
  - audit doc §4.1 OrderItem 漏锁 4 路径
  - §17-A/§17-B 范本: tests/concurrent/test_cashier_table_concurrent_tier1.py +
    tests/concurrent/test_cashier_settle_concurrent_tier1.py
"""
from __future__ import annotations

import asyncio
import os
import sys
import types
import uuid

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

# ── 路径 + namespace 包 ──────────────────────────────────────────────────
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
TX_TRADE_DIR = os.path.join(ROOT, "services", "tx-trade")
TX_TRADE_SRC = os.path.join(TX_TRADE_DIR, "src")
for p in [ROOT, TX_TRADE_SRC]:
    if p not in sys.path:
        sys.path.insert(0, p)


def _ensure_ns(name: str, path: str) -> None:
    if name not in sys.modules:
        mod = types.ModuleType(name)
        mod.__path__ = [path]  # type: ignore[attr-defined]
        mod.__package__ = name
        sys.modules[name] = mod
    elif not hasattr(sys.modules[name], "__path__"):
        mod = types.ModuleType(name)
        mod.__path__ = [path]
        mod.__package__ = name
        sys.modules[name] = mod


_ensure_ns("services.tx_trade", TX_TRADE_DIR)
_ensure_ns("services.tx_trade.src", TX_TRADE_SRC)
for _sub in ("api", "models", "services", "repositories", "routers"):
    _sub_path = os.path.join(TX_TRADE_SRC, _sub)
    if os.path.isdir(_sub_path):
        _ensure_ns(f"services.tx_trade.src.{_sub}", _sub_path)


if sys.version_info < (3, 10):
    pytest.skip(
        "需 Python 3.10+ (shared.events 用 dataclass slots=True); CI Python 3.11 跑通",
        allow_module_level=True,
    )

from shared.test_utils.integration_pg import requires_integration_pg  # noqa: E402

pytestmark = [requires_integration_pg]


# ── helpers ────────────────────────────────────────────────────────────────


def _new_uuid() -> uuid.UUID:
    return uuid.uuid4()


async def _seed_store(session: AsyncSession, tenant_id: uuid.UUID) -> uuid.UUID:
    store_id = _new_uuid()
    await session.execute(
        text("""
            INSERT INTO stores (id, tenant_id, store_name, store_code)
            VALUES (CAST(:id AS uuid), CAST(:tid AS uuid), :name, :code)
        """),
        {
            "id": str(store_id),
            "tid": str(tenant_id),
            "name": f"s17c-{uuid.uuid4().hex[:8]}",
            "code": f"S17C-{uuid.uuid4().hex[:12]}",
        },
    )
    return store_id


async def _seed_order(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    store_id: uuid.UUID,
    *,
    table_no: str = "A01",
    status: str = "confirmed",
    total_fen: int = 0,
) -> uuid.UUID:
    order_id = _new_uuid()
    await session.execute(
        text("""
            INSERT INTO orders (
                id, tenant_id, store_id, order_no, status,
                total_amount_fen, discount_amount_fen, final_amount_fen,
                table_number, order_metadata
            )
            VALUES (
                CAST(:id AS uuid), CAST(:tid AS uuid), CAST(:sid AS uuid),
                :order_no, :status, :total, 0, :total,
                :table_no, '{}'::jsonb
            )
        """),
        {
            "id": str(order_id),
            "tid": str(tenant_id),
            "sid": str(store_id),
            "order_no": f"TX{uuid.uuid4().hex[:14].upper()}",
            "status": status,
            "total": total_fen,
            "table_no": table_no,
        },
    )
    return order_id


async def _seed_orderitem(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    order_id: uuid.UUID,
    *,
    item_name: str = "测试菜",
    quantity: int = 2,
    unit_price_fen: int = 200,
    pricing_mode: str = "fixed",
) -> uuid.UUID:
    """INSERT 1 order_item with subtotal = quantity * unit_price."""
    item_id = _new_uuid()
    subtotal = quantity * unit_price_fen
    await session.execute(
        text("""
            INSERT INTO order_items (
                id, tenant_id, order_id, item_name, quantity,
                unit_price_fen, subtotal_fen, pricing_mode, return_flag,
                customizations
            )
            VALUES (
                CAST(:id AS uuid), CAST(:tid AS uuid), CAST(:oid AS uuid),
                :name, :qty, :unit, :subtotal, :mode, FALSE, '{}'::jsonb
            )
        """),
        {
            "id": str(item_id),
            "tid": str(tenant_id),
            "oid": str(order_id),
            "name": item_name,
            "qty": quantity,
            "unit": unit_price_fen,
            "subtotal": subtotal,
            "mode": pricing_mode,
        },
    )
    return item_id


@pytest.fixture(autouse=True)
async def _ensure_v342_schema(engine):
    """drift workaround — order_items barcode 列 (与 §17-A/§17-B 同 pattern)."""
    from sqlalchemy import text as sql_text
    async with engine.begin() as conn:
        await conn.execute(sql_text("""
            ALTER TABLE order_items
                ADD COLUMN IF NOT EXISTS barcode             VARCHAR(30),
                ADD COLUMN IF NOT EXISTS barcode_scanned_at  TIMESTAMPTZ,
                ADD COLUMN IF NOT EXISTS scanned_by          UUID
        """))


@pytest_asyncio.fixture(autouse=True)
async def _silence_emit_event(monkeypatch):
    """no-op emit_event."""
    import services.tx_trade.src.services.cashier_engine as cashier_module
    import services.tx_trade.src.services.order_service as order_module

    import shared.events.src.emitter as emitter_module

    async def _noop_emit(*args, **kwargs):
        return None

    monkeypatch.setattr(emitter_module, "emit_event", _noop_emit)
    monkeypatch.setattr(cashier_module, "emit_event", _noop_emit)
    monkeypatch.setattr(order_module, "emit_event", _noop_emit)
    yield
    for _ in range(5):
        await asyncio.sleep(0)


# ───────────────────────────────────────────────────────────────────
# T1: order_service.update_item_quantity N=10 同 item — OrderItem FOR UPDATE
# ───────────────────────────────────────────────────────────────────
async def test_order_service_update_item_quantity_concurrent_same_item(session_factory):
    """T1 — N=10 并发改同 item.quantity 1→2→3→...→10 (distinct), FOR UPDATE 串行化.

    setup: 1 store + 1 order (total=0 起) + 1 item (qty=1 / unit=100 / subtotal=100)
    runner: N=10 workers 各 update_item_quantity(item, new_qty=worker_idx+1)
    断言:
      - 所有 worker 成功 (不抛)
      - 终态 item.subtotal_fen == final_qty * 100 (最后写入决定)
      - 终态 Order.total_amount_fen == item.subtotal_fen (raw arithmetic 累积自洽 —
        Order.total 起始 100, 每路加 diff = unit*new_qty - old_subtotal, 累积 = final_subtotal)

    若 OrderItem 无锁: 两路读相同 subtotal=100, W1 new_qty=5 算 diff=400, W2 new_qty=10 算 diff=900.
    实际 item.subtotal_fen 应该 = 500 (W1 先 commit) 然后 W2 should 读 500 算 diff=500.
    无锁下 W2 用 stale subtotal=100 算 diff=900 → Order.total += 400+900 = 1300, item.subtotal=1000.
    总账不平: order.total=1300 ≠ item.subtotal=1000. 锁后 W2 读 W1 commit 后的 500 → diff=500 →
    order.total=100+400+500=1000 == item.subtotal ✓
    """
    from services.tx_trade.src.services.order_service import OrderService

    tenant_id = _new_uuid()
    n = 10

    async with session_factory() as s:
        store_id = await _seed_store(s, tenant_id)
        # Order initial total = item initial subtotal = 100 (qty=1 * unit=100)
        order_id = await _seed_order(s, tenant_id, store_id, total_fen=100)
        item_id = await _seed_orderitem(
            s, tenant_id, order_id, quantity=1, unit_price_fen=100
        )
        await s.commit()

    async def _update_factory(new_qty: int):
        async def _do(session: AsyncSession) -> dict:
            svc = OrderService(db=session, tenant_id=str(tenant_id))
            return await svc.update_item_quantity(item_id=str(item_id), new_quantity=new_qty)
        return _do

    async def _run_one(op):
        async with session_factory() as sess:
            await sess.execute(
                text("SELECT set_config('app.tenant_id', :tid, true)"),
                {"tid": str(tenant_id)},
            )
            try:
                result = await op(sess)
                await sess.commit()
                return result
            except BaseException as e:
                await sess.rollback()
                return e

    ops = [await _update_factory(i + 1) for i in range(n)]
    results = await asyncio.wait_for(
        asyncio.gather(*[_run_one(op) for op in ops], return_exceptions=True),
        timeout=30.0,
    )

    succeeded = [r for r in results if not isinstance(r, BaseException)]
    failed = [r for r in results if isinstance(r, BaseException)]

    assert len(succeeded) == n, (
        f"expected {n} success, got {len(succeeded)} + {len(failed)} fail. "
        f"errors: {[(type(e).__name__, str(e)[:80]) for e in failed]}"
    )

    # 终态自洽: order.total_amount_fen == item.subtotal_fen
    async with session_factory() as s:
        await s.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": str(tenant_id)}
        )
        order_row = (await s.execute(
            text("SELECT total_amount_fen FROM orders WHERE id=CAST(:oid AS uuid)"),
            {"oid": str(order_id)},
        )).first()
        item_row = (await s.execute(
            text("SELECT subtotal_fen, quantity FROM order_items WHERE id=CAST(:iid AS uuid)"),
            {"iid": str(item_id)},
        )).first()

    # 关键自洽: total 与 subtotal 一致 (锁失败的特征是不一致)
    assert order_row.total_amount_fen == item_row.subtotal_fen, (
        f"Order.total ({order_row.total_amount_fen}) != Item.subtotal ({item_row.subtotal_fen}) — "
        f"OrderItem FOR UPDATE 未生效, diff 累积错乱 (item.quantity={item_row.quantity})"
    )


# ───────────────────────────────────────────────────────────────────
# T2: cashier_engine.update_item N=10 同 item — OrderItem + Order 双锁
# ───────────────────────────────────────────────────────────────────
async def test_cashier_update_item_concurrent_same_item(session_factory):
    """T2 — cashier_engine.update_item 必须 OrderItem FOR UPDATE + Order FOR UPDATE.

    cashier_engine.update_item Python-side `new_total = order.total + diff` UPDATE Order
    literal value, 不是 raw arithmetic. 必须 Order FOR UPDATE 串行化 Python recalc.

    setup: 1 store + 1 order (total=100) + 1 item (qty=1 / unit=100 / subtotal=100)
    runner: N=10 workers 各 update_item(order, item, new_qty=worker_idx+1)
    断言: 终态 Order.total == item.subtotal (账单自洽)
    """
    from services.tx_trade.src.services.cashier_engine import CashierEngine

    tenant_id = _new_uuid()
    n = 10

    async with session_factory() as s:
        store_id = await _seed_store(s, tenant_id)
        order_id = await _seed_order(s, tenant_id, store_id, total_fen=100)
        item_id = await _seed_orderitem(
            s, tenant_id, order_id, quantity=1, unit_price_fen=100
        )
        await s.commit()

    async def _update_factory(new_qty: int):
        async def _do(session: AsyncSession) -> dict:
            eng = CashierEngine(db=session, tenant_id=str(tenant_id))
            return await eng.update_item(
                order_id=str(order_id),
                item_id=str(item_id),
                quantity=new_qty,
            )
        return _do

    async def _run_one(op):
        async with session_factory() as sess:
            await sess.execute(
                text("SELECT set_config('app.tenant_id', :tid, true)"),
                {"tid": str(tenant_id)},
            )
            try:
                result = await op(sess)
                await sess.commit()
                return result
            except BaseException as e:
                await sess.rollback()
                return e

    ops = [await _update_factory(i + 1) for i in range(n)]
    results = await asyncio.wait_for(
        asyncio.gather(*[_run_one(op) for op in ops], return_exceptions=True),
        timeout=30.0,
    )

    succeeded = [r for r in results if not isinstance(r, BaseException)]
    failed = [r for r in results if isinstance(r, BaseException)]

    assert len(succeeded) == n, (
        f"expected {n} success, got {len(succeeded)} + {len(failed)} fail. "
        f"errors: {[(type(e).__name__, str(e)[:80]) for e in failed]}"
    )

    async with session_factory() as s:
        await s.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": str(tenant_id)}
        )
        order_row = (await s.execute(
            text("SELECT total_amount_fen, final_amount_fen FROM orders WHERE id=CAST(:oid AS uuid)"),
            {"oid": str(order_id)},
        )).first()
        item_row = (await s.execute(
            text("SELECT subtotal_fen FROM order_items WHERE id=CAST(:iid AS uuid)"),
            {"iid": str(item_id)},
        )).first()

    # 关键自洽: total 与 subtotal 一致
    assert order_row.total_amount_fen == item_row.subtotal_fen, (
        f"cashier_engine.update_item: Order.total ({order_row.total_amount_fen}) != "
        f"Item.subtotal ({item_row.subtotal_fen}) — "
        f"Python recalc race 未防住, 必须 OrderItem + Order 双锁"
    )
    # final_amount = total (discount=0)
    assert order_row.final_amount_fen == order_row.total_amount_fen


# ───────────────────────────────────────────────────────────────────
# T3: order_service.update_item_quantity N=5 不同 item 同 order — cross-item
# ───────────────────────────────────────────────────────────────────
async def test_update_item_concurrent_distinct_items_same_order(session_factory):
    """T3 — N=5 workers 改不同 item 同 order, raw arithmetic Order.total 累积正确.

    setup: 1 store + 1 order (total=500 起) + 5 items 各 (qty=1 / unit=100 / subtotal=100)
    runner: 5 workers 各 update_item_quantity(item_i, new_qty=5) — 每 item 各加 400
    断言:
      - Order.total = 500 + 5*400 = 2500
      - 每 item.subtotal = 500

    Cross-item Order arithmetic 是 PG 原子 (`Order.total + diff`), 不需 Order FOR UPDATE.
    OrderItem 各自独立, 不存在 cross-item race.
    """
    from services.tx_trade.src.services.order_service import OrderService

    tenant_id = _new_uuid()
    n_items = 5

    async with session_factory() as s:
        store_id = await _seed_store(s, tenant_id)
        order_id = await _seed_order(s, tenant_id, store_id, total_fen=n_items * 100)
        item_ids: list[uuid.UUID] = []
        for i in range(n_items):
            iid = await _seed_orderitem(
                s, tenant_id, order_id,
                item_name=f"item_{i}",
                quantity=1,
                unit_price_fen=100,
            )
            item_ids.append(iid)
        await s.commit()

    async def _update_factory(item_id: uuid.UUID):
        async def _do(session: AsyncSession) -> dict:
            svc = OrderService(db=session, tenant_id=str(tenant_id))
            return await svc.update_item_quantity(item_id=str(item_id), new_quantity=5)
        return _do

    async def _run_one(op):
        async with session_factory() as sess:
            await sess.execute(
                text("SELECT set_config('app.tenant_id', :tid, true)"),
                {"tid": str(tenant_id)},
            )
            try:
                result = await op(sess)
                await sess.commit()
                return result
            except BaseException as e:
                await sess.rollback()
                return e

    ops = [await _update_factory(iid) for iid in item_ids]
    results = await asyncio.wait_for(
        asyncio.gather(*[_run_one(op) for op in ops], return_exceptions=True),
        timeout=30.0,
    )

    succeeded = [r for r in results if not isinstance(r, BaseException)]
    failed = [r for r in results if isinstance(r, BaseException)]
    assert len(succeeded) == n_items, (
        f"expected {n_items} success, got {len(succeeded)} + {len(failed)} fail. "
        f"errors: {[(type(e).__name__, str(e)[:80]) for e in failed]}"
    )

    async with session_factory() as s:
        await s.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": str(tenant_id)}
        )
        order_row = (await s.execute(
            text("SELECT total_amount_fen FROM orders WHERE id=CAST(:oid AS uuid)"),
            {"oid": str(order_id)},
        )).first()
        items_total = (await s.execute(
            text(
                "SELECT COALESCE(SUM(subtotal_fen), 0) AS sum FROM order_items "
                "WHERE order_id=CAST(:oid AS uuid)"
            ),
            {"oid": str(order_id)},
        )).first()

    expected = n_items * 5 * 100  # 5 items × qty 5 × unit 100 = 2500
    assert order_row.total_amount_fen == expected, (
        f"Order.total ({order_row.total_amount_fen}) != expected {expected} — "
        f"cross-item raw arithmetic 应该 PG 原子累积安全"
    )
    assert items_total.sum == expected, (
        f"sum(items.subtotal) ({items_total.sum}) != expected {expected}"
    )
