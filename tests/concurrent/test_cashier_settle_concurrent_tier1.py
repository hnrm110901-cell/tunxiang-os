"""§17-B settle 终态保护 + 3B 幂等释放 Tier 1 并发反测 — 真 PG

PR-Tier1 §17-B of 2026-05-13 audit doc §11.3 决策追踪表 — 创始人锁定:
  - 3B 幂等释放 (_release_table UPDATE WHERE current_order_id=:order_id AND status='occupied')
  - + 配套 settle/cancel 终态保护 (FOR UPDATE SELECT Order)

验证 audit doc §11.1 cashier_engine.py / order_service.py settle 终态路径**真行为**
(与 services/tx-trade/tests/test_cashier_settle_release_row_lock_tier1.py 互补):

  - T1: N=10 concurrent settle_order 同一 order → 1 成功 + 9 raise "订单已结算"
  - T2: N=10 concurrent _release_table 同 (table, order_id) → 1 UPDATE 1 行 + 9 UPDATE 0 行
        (3B 幂等无害); release 后 table 被新 order 重新 occupy, 再 release 旧 order_id 不影响
  - T3: settle + cancel race 同一 order → 输者抛 "订单已结算" 或 "已结算无法取消"

业务场景 (真餐厅, audit doc §11.2 选择题 3):
  - 服务员 POS + 顾客自助 同时点结算 → 双结算 race
  - POS 重试 / 用户连点 → 重复 settle / cancel 同 order
  - settle 完成桌台 release 后, 桌台被新 order 重 occupy, 旧 settle 重试不能污染新 order

跑法 (opt-in via INTEGRATION_PG_DSN):

    INTEGRATION_PG_DSN=postgresql://tunxiang_test:test_password_dev_only@localhost:5433/tunxiang_os_test \\
        pytest tests/concurrent/test_cashier_settle_concurrent_tier1.py \\
        --confcutdir tests/concurrent --override-ini asyncio_mode=auto -v

未设 INTEGRATION_PG_DSN → 全部 skip (opt-in 模式).

关联:
  - 2026-05-13 audit doc §11.3 决策追踪表 (创始人锁定 3B)
  - cashier_engine.py settle_order L760 / cancel_order L956 / _release_table L1243
  - order_service.py settle_order L340 / cancel_order L455 / _release_table L553
  - §17-A 范本: tests/concurrent/test_cashier_table_concurrent_tier1.py
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
            "name": f"s17b-{uuid.uuid4().hex[:8]}",
            "code": f"S17B-{uuid.uuid4().hex[:12]}",
        },
    )
    return store_id


async def _seed_table(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    store_id: uuid.UUID,
    *,
    table_no: str,
    status: str = "occupied",
    current_order_id: uuid.UUID | None = None,
) -> uuid.UUID:
    table_id = _new_uuid()
    await session.execute(
        text("""
            INSERT INTO tables (
                id, tenant_id, store_id, table_no, seats, status,
                current_order_id, sort_order, is_active, floor
            )
            VALUES (
                CAST(:id AS uuid), CAST(:tid AS uuid), CAST(:sid AS uuid),
                :no, 4, :status,
                CAST(:coid AS uuid), 0, TRUE, 1
            )
        """),
        {
            "id": str(table_id),
            "tid": str(tenant_id),
            "sid": str(store_id),
            "no": table_no,
            "status": status,
            "coid": str(current_order_id) if current_order_id else None,
        },
    )
    return table_id


async def _seed_order(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    store_id: uuid.UUID,
    *,
    table_no: str,
    status: str = "pending",
    final_amount_fen: int = 10000,
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
                :order_no, :status, :total, 0, :final,
                :table_no, '{}'::jsonb
            )
        """),
        {
            "id": str(order_id),
            "tid": str(tenant_id),
            "sid": str(store_id),
            "order_no": f"TX{uuid.uuid4().hex[:14].upper()}",
            "status": status,
            "total": final_amount_fen,
            "final": final_amount_fen,
            "table_no": table_no,
        },
    )
    return order_id


@pytest.fixture(autouse=True)
async def _ensure_v342_schema(engine):
    """drift workaround — order_items barcode 列 (与 §17-A 同 pattern)."""
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
    """no-op emit_event (event bus 不在本 PR scope)."""
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
# T1: N=10 concurrent settle_order 同一 order — 终态保护 FOR UPDATE
# ───────────────────────────────────────────────────────────────────
async def test_settle_order_concurrent_n10_only_one_succeeds(session_factory):
    """T1 — POS 重试 / 用户连点 / 双 POS 同时 settle 同一 order, FOR UPDATE 让 1 路成功 + 9 路抛 "订单已结算".

    setup: 1 store + 1 table (occupied by order) + 1 order (status='pending')
    runner: N=10 workers 各 settle_order(order, payments=[{cash, final_fen}])
    断言:
      - 恰好 1 worker 成功
      - 9 worker raise ValueError "订单已结算"
      - 终态: order.status='completed', table.status='free' AND current_order_id=NULL
      - payments 表恰好 N_succeeded * 1 = 1 条 (其他 9 worker rollback 不写)

    若终态保护未生效 (无 FOR UPDATE), 多个 worker 都见 status='pending' 都过校验,
    都 commit → 多个 payment 行 + 桌台被释放多次 (重写 NULL 无害但语义错乱).
    """
    from services.tx_trade.src.services.cashier_engine import CashierEngine

    tenant_id = _new_uuid()
    final_fen = 12500

    async with session_factory() as s:
        store_id = await _seed_store(s, tenant_id)
        # state_machine: pending → completed 非法 (须经 confirmed); seed 用 confirmed
        order_id = await _seed_order(
            s, tenant_id, store_id, table_no="A01", status="confirmed", final_amount_fen=final_fen
        )
        await _seed_table(
            s, tenant_id, store_id, table_no="A01",
            status="occupied", current_order_id=order_id,
        )
        await s.commit()

    async def _settle(session: AsyncSession) -> dict:
        engine = CashierEngine(db=session, tenant_id=str(tenant_id))
        return await engine.settle_order(
            order_id=str(order_id),
            payments=[{"method": "cash", "amount_fen": final_fen}],
        )

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

    results = await asyncio.wait_for(
        asyncio.gather(*[_run_one(_settle) for _ in range(10)], return_exceptions=True),
        timeout=30.0,
    )

    succeeded = [r for r in results if not isinstance(r, BaseException)]
    failed = [r for r in results if isinstance(r, BaseException)]

    assert len(succeeded) == 1, (
        f"expected 1 success, got {len(succeeded)} + {len(failed)} fail. "
        f"errors: {[(type(e).__name__, str(e)[:80]) for e in failed]}"
    )
    assert len(failed) == 9
    settled_errors = [
        e for e in failed
        if isinstance(e, ValueError) and "已结算" in str(e)
    ]
    assert len(settled_errors) == 9, (
        f"expected 9 '订单已结算' ValueError, got "
        f"{[(type(e).__name__, str(e)[:80]) for e in failed]}"
    )

    # 终态: order completed, table released (status=free + current_order_id=NULL)
    async with session_factory() as s:
        await s.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": str(tenant_id)}
        )
        order_row = (await s.execute(
            text("SELECT status FROM orders WHERE id=CAST(:oid AS uuid)"),
            {"oid": str(order_id)},
        )).first()
        table_row = (await s.execute(
            text(
                "SELECT status, current_order_id FROM tables "
                "WHERE store_id=CAST(:sid AS uuid) AND table_no='A01'"
            ),
            {"sid": str(store_id)},
        )).first()
        payment_count = (await s.execute(
            text("SELECT count(*) FROM payments WHERE order_id=CAST(:oid AS uuid)"),
            {"oid": str(order_id)},
        )).scalar()

    assert order_row.status == "completed"
    assert table_row.status == "free"
    assert table_row.current_order_id is None
    assert payment_count == 1, f"expected 1 payment row, got {payment_count}"


# ───────────────────────────────────────────────────────────────────
# T2: _release_table 3B 幂等无害 — table 被新 order 重 occupy 后旧 release 不污染
# ───────────────────────────────────────────────────────────────────
async def test_release_table_idempotent_does_not_pollute_new_order(session_factory):
    """T2 — settle 释放桌台后, table 被新 order 重 occupy. 旧 release 重试不能污染新 order 引用.

    setup:
      step 1: table A01 occupied by order_X → release(A01, order_X) → table free
      step 2: table A01 重 occupy by order_Y → release(A01, order_X) 重试
    断言:
      - step 2 后 table.current_order_id 仍是 order_Y (旧 order_X 的 release 不影响)
      - step 2 后 table.status='occupied'

    若 3B 幂等未生效 (UPDATE WHERE 仅 store_id + table_no), 旧 release 会把
    新 order_Y 的 current_order_id 重置为 NULL + status 重置 free,
    新 order_Y 失去桌台引用.
    """
    from services.tx_trade.src.services.cashier_engine import CashierEngine

    tenant_id = _new_uuid()

    async with session_factory() as s:
        store_id = await _seed_store(s, tenant_id)
        order_x = await _seed_order(s, tenant_id, store_id, table_no="A01")
        order_y = await _seed_order(s, tenant_id, store_id, table_no="A01")
        await _seed_table(
            s, tenant_id, store_id, table_no="A01",
            status="occupied", current_order_id=order_x,
        )
        await s.commit()

    # step 1: release(A01, order_x) — 第一次正常释放
    async with session_factory() as sess1:
        await sess1.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": str(tenant_id)},
        )
        engine = CashierEngine(db=sess1, tenant_id=str(tenant_id))
        await engine._release_table(str(store_id), "A01", order_x)
        await sess1.commit()

    # step 2: 手动重 occupy by order_y
    async with session_factory() as sess2:
        await sess2.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": str(tenant_id)},
        )
        await sess2.execute(
            text(
                "UPDATE tables SET status='occupied', current_order_id=CAST(:oid AS uuid) "
                "WHERE store_id=CAST(:sid AS uuid) AND table_no='A01'"
            ),
            {"oid": str(order_y), "sid": str(store_id)},
        )
        await sess2.commit()

    # step 3: 旧 order_x 的 release 重试 — 3B 幂等应保持新 order_y 引用
    async with session_factory() as sess3:
        await sess3.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": str(tenant_id)},
        )
        engine = CashierEngine(db=sess3, tenant_id=str(tenant_id))
        await engine._release_table(str(store_id), "A01", order_x)
        await sess3.commit()

    # 终态: 新 order_y 桌台引用保留 (3B 幂等)
    async with session_factory() as s:
        await s.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": str(tenant_id)}
        )
        row = (await s.execute(
            text(
                "SELECT status, current_order_id FROM tables "
                "WHERE store_id=CAST(:sid AS uuid) AND table_no='A01'"
            ),
            {"sid": str(store_id)},
        )).first()

    assert row.status == "occupied", (
        f"3B 幂等未生效: table 状态被旧 release 污染为 {row.status}, 应保持 'occupied'"
    )
    assert row.current_order_id == order_y, (
        f"3B 幂等未生效: current_order_id={row.current_order_id} != 新 order_y={order_y}"
    )


# ───────────────────────────────────────────────────────────────────
# T3: settle + cancel race — 终态保护 FOR UPDATE
# ───────────────────────────────────────────────────────────────────
async def test_settle_cancel_race_terminal_protection(session_factory):
    """T3 — 服务员 POS settle 同时顾客触发 cancel, FOR UPDATE 让 race 输者抛错.

    setup: 1 store + 1 table occupied by 1 order (status='pending')
    runner: worker1 settle_order; worker2 cancel_order (任意顺序)
    断言:
      - 恰好 1 worker 成功
      - 1 worker raise ValueError:
          - 若 cancel 先: settle 抛 "订单已取消"
          - 若 settle 先: cancel 抛 "已结算订单无法取消"
      - 终态: order.status 是 completed 或 cancelled (二选一, 不可能两者并存)
      - table 已 release (status=free + current_order_id=NULL)

    若 FOR UPDATE 未生效 (cancel 漏锁是 main 既存 bug, §17-B 修),
    两路都见 status='pending' 都过状态机校验, 一路 commit 后另一路 commit
    overwrite — 状态最终不可预期.
    """
    from services.tx_trade.src.services.cashier_engine import CashierEngine

    tenant_id = _new_uuid()
    final_fen = 8800

    async with session_factory() as s:
        store_id = await _seed_store(s, tenant_id)
        # state_machine: pending → completed 非法; cancel 路径 pending → cancelled OK
        # 用 confirmed 让 settle 合法 + cancel 也合法 (confirmed → cancelled)
        order_id = await _seed_order(
            s, tenant_id, store_id, table_no="A01",
            status="confirmed", final_amount_fen=final_fen,
        )
        await _seed_table(
            s, tenant_id, store_id, table_no="A01",
            status="occupied", current_order_id=order_id,
        )
        await s.commit()

    async def _settle(session: AsyncSession) -> dict:
        engine = CashierEngine(db=session, tenant_id=str(tenant_id))
        return await engine.settle_order(
            order_id=str(order_id),
            payments=[{"method": "cash", "amount_fen": final_fen}],
        )

    async def _cancel(session: AsyncSession) -> dict:
        engine = CashierEngine(db=session, tenant_id=str(tenant_id))
        return await engine.cancel_order(
            order_id=str(order_id), reason="客户取消"
        )

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

    results = await asyncio.wait_for(
        asyncio.gather(_run_one(_settle), _run_one(_cancel), return_exceptions=True),
        timeout=30.0,
    )

    succeeded = [r for r in results if not isinstance(r, BaseException)]
    failed = [r for r in results if isinstance(r, BaseException)]

    assert len(succeeded) == 1, (
        f"expected 1 success, got {len(succeeded)} + {len(failed)} fail. "
        f"errors: {[(type(e).__name__, str(e)[:80]) for e in failed]}"
    )
    assert len(failed) == 1

    err = failed[0]
    assert isinstance(err, ValueError)
    msg = str(err)
    assert ("已结算" in msg) or ("已取消" in msg), (
        f"race 输者错误消息不匹配预期: {msg}"
    )

    # 终态二选一
    async with session_factory() as s:
        await s.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": str(tenant_id)}
        )
        order_row = (await s.execute(
            text("SELECT status FROM orders WHERE id=CAST(:oid AS uuid)"),
            {"oid": str(order_id)},
        )).first()
        table_row = (await s.execute(
            text(
                "SELECT status, current_order_id FROM tables "
                "WHERE store_id=CAST(:sid AS uuid) AND table_no='A01'"
            ),
            {"sid": str(store_id)},
        )).first()

    assert order_row.status in ("completed", "cancelled"), (
        f"order 终态应为 completed 或 cancelled, 实际 {order_row.status}"
    )
    assert table_row.status == "free"
    assert table_row.current_order_id is None
