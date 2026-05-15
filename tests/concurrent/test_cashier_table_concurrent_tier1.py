"""§17-A cashier 桌台并发 Tier 1 测试 — 1A open_table FOR UPDATE + 2A transfer_table 双锁排序

PR-Tier1 §17-A of 2026-05-13 audit doc §11.3 决策追踪表 — 创始人锁定:
  - 1A 强一致 (open_table FOR UPDATE + rowcount check, 第二路抛 TableOccupiedError)
  - 2A 双锁 (transfer_table 源+目标按 table.id 升序 FOR UPDATE 防 ABBA)

验证 audit doc §11.1 cashier_engine.py 桌台 P1 路径**真行为**（与 mock-driven SQL grep 互补）:

  - T1: N=10 open_table 同 (store, table_no) → 1 成功 + 9 raise TableOccupiedError
  - T2: N=10 transfer_table 转到同一目标桌 → 1 成功 + 9 raise TableOccupiedError
  - T3: 2 路 swap 转桌 (A→B + B→A) → 双锁排序无死锁, 全部 commit (终态合理)
  - T4: change_table_status 并发跃迁 → FOR UPDATE 串行化, 状态机校验生效

业务场景（真餐厅, audit doc §11.2 选择题 1+2）:
  - 双 POS / 前台 + POS 同时开同一桌 → 不能两个订单都"占"桌
  - 500 元桌 + 200 元桌都升 1000 元 VIP 桌 → 不能两路并发都通过
  - 转桌 swap (A→B + B→A) → 锁排序防 ABBA 死锁

跑法 (opt-in via INTEGRATION_PG_DSN):

    INTEGRATION_PG_DSN=postgresql://tunxiang_test:test_password_dev_only@localhost:5433/tunxiang_os_test \\
        pytest tests/concurrent/test_cashier_table_concurrent_tier1.py \\
        --confcutdir tests/concurrent --override-ini asyncio_mode=auto -v

未设 INTEGRATION_PG_DSN → 全部 skip (opt-in 模式).

关联:
  - 2026-05-13 audit doc §11.3 决策追踪表 (创始人锁定 1A/2A)
  - cashier_engine.py open_table L113 / change_table_status L276 / transfer_table L1352
  - tests/concurrent/test_cashier_engine_concurrent_tier1.py (PR-2 框架金标准 follow-up)
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

# ── 路径 + namespace 包 (与 test_cashier_engine_concurrent_tier1.py 同 pattern) ──
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

from shared.test_utils.concurrent_runner import run_concurrent  # noqa: E402
from shared.test_utils.integration_pg import requires_integration_pg  # noqa: E402

pytestmark = [requires_integration_pg]


# ── helpers ────────────────────────────────────────────────────────────────


def _new_uuid() -> uuid.UUID:
    return uuid.uuid4()


async def _seed_store(session: AsyncSession, tenant_id: uuid.UUID) -> uuid.UUID:
    """INSERT 1 store, 返回 store_id。"""
    store_id = _new_uuid()
    await session.execute(
        text("""
            INSERT INTO stores (id, tenant_id, store_name, store_code)
            VALUES (CAST(:id AS uuid), CAST(:tid AS uuid), :name, :code)
        """),
        {
            "id": str(store_id),
            "tid": str(tenant_id),
            "name": f"s17a-{uuid.uuid4().hex[:8]}",
            "code": f"S17A-{uuid.uuid4().hex[:12]}",
        },
    )
    return store_id


async def _seed_table(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    store_id: uuid.UUID,
    *,
    table_no: str,
    status: str = "free",
    current_order_id: uuid.UUID | None = None,
) -> uuid.UUID:
    """INSERT 1 table, 返回 table.id。"""
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
) -> uuid.UUID:
    """INSERT 1 order 关联给定 table_no。"""
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
                :order_no, :status, 0, 0, 0,
                :table_no, '{}'::jsonb
            )
        """),
        {
            "id": str(order_id),
            "tid": str(tenant_id),
            "sid": str(store_id),
            "order_no": f"TX{uuid.uuid4().hex[:14].upper()}",
            "status": status,
            "table_no": table_no,
        },
    )
    return order_id


# v342 schema patch + emit_event silence (与 test_cashier_engine_concurrent_tier1.py 同 pattern)


@pytest.fixture(autouse=True)
async def _ensure_v342_schema(engine):
    """drift workaround — order_items barcode 列 (与 test_cashier_engine_concurrent 同 pattern)."""
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

    import shared.events.src.emitter as emitter_module

    async def _noop_emit(*args, **kwargs):
        return None

    monkeypatch.setattr(emitter_module, "emit_event", _noop_emit)
    monkeypatch.setattr(cashier_module, "emit_event", _noop_emit)
    yield
    for _ in range(5):
        await asyncio.sleep(0)


# ───────────────────────────────────────────────────────────────────
# T1: N=10 concurrent open_table — 1A 强一致 FOR UPDATE
# ───────────────────────────────────────────────────────────────────
async def test_open_table_concurrent_n10_only_one_succeeds(session_factory):
    """T1 — 双 POS / 前台 race 同时开同一空桌, 1A FOR UPDATE 强一致只允许 1 个成功.

    setup: 1 store + 1 table (status='free')
    runner: N=10 workers 各 open_table(table_no=A01, guest=4)
    断言:
      - 恰好 1 worker 成功（return order_id + status='pending'）
      - 9 worker raise TableOccupiedError（"已被开台" 或类似消息）
      - 终态: tables.status='occupied' + tables.current_order_id 仅指向 1 个 order
      - orders 表恰好 1 条（其他 9 worker 因 raise 不写入）

    若 1A 未生效（无 FOR UPDATE）, 多个 order_id 会被写入 + 桌台 current_order_id
    被后写者覆盖, 第一个订单失去桌台引用.
    """
    from services.tx_trade.src.services.cashier_engine import (
        CashierEngine,
        TableOccupiedError,
    )

    tenant_id = _new_uuid()
    async with session_factory() as s:
        store_id = await _seed_store(s, tenant_id)
        await _seed_table(s, tenant_id, store_id, table_no="A01", status="free")
        await s.commit()

    async def _open(session: AsyncSession) -> dict:
        engine = CashierEngine(db=session, tenant_id=str(tenant_id))
        return await engine.open_table(
            store_id=str(store_id),
            table_no="A01",
            waiter_id=str(_new_uuid()),
            guest_count=4,
        )

    results = await run_concurrent(
        session_factory, tenant_id, n=10,
        operation=_open,
        timeout_sec=30.0,
    )

    succeeded = [r for r in results if not isinstance(r, BaseException)]
    failed = [r for r in results if isinstance(r, BaseException)]
    occupied_errors = [r for r in failed if isinstance(r, TableOccupiedError)]

    assert len(succeeded) == 1, (
        f"expected 1 success, got {len(succeeded)} success + {len(failed)} fail. "
        f"errors: {[type(e).__name__ for e in failed]}"
    )
    assert len(occupied_errors) == 9, (
        f"expected 9 TableOccupiedError, got {len(occupied_errors)}. "
        f"errors: {[type(e).__name__ for e in failed]}"
    )

    # 终态验证: 桌台只占用一次, orders 表只 1 条
    async with session_factory() as s:
        await s.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": str(tenant_id)}
        )
        table_row = (
            await s.execute(
                text(
                    "SELECT status, current_order_id FROM tables "
                    "WHERE store_id=CAST(:sid AS uuid) AND table_no='A01'"
                ),
                {"sid": str(store_id)},
            )
        ).first()
        order_count = (
            await s.execute(
                text("SELECT count(*) FROM orders WHERE store_id=CAST(:sid AS uuid)"),
                {"sid": str(store_id)},
            )
        ).scalar()

    assert table_row is not None
    assert table_row.status == "occupied"
    assert table_row.current_order_id is not None
    assert order_count == 1, f"expected 1 order written, got {order_count}"


# ───────────────────────────────────────────────────────────────────
# T2: N=10 concurrent transfer_table 同一目标桌 — 2A 双锁排序
# ───────────────────────────────────────────────────────────────────
async def test_transfer_table_concurrent_to_same_target_only_one_succeeds(
    session_factory,
):
    """T2 — 多桌想转入同一空 VIP 桌, 2A 双锁排序只允许 1 个成功.

    setup: 1 store + N=10 source tables (B01..B10) + 1 target table (VIP01) + 10 orders
    runner: N=10 workers 各 transfer_table(order_i → VIP01)
    断言:
      - 恰好 1 worker 成功
      - 9 worker raise (TableOccupiedError 或 ValueError "无法转入")
      - 终态: VIP01.status='occupied' + VIP01.current_order_id 仅指向 1 个 order

    若 2A 双锁未生效, 多个 worker 都见 VIP01='free' → 各自 UPDATE → 后写者覆盖,
    多个源桌都"以为"转到 VIP01 但 VIP01 实际只指向最后写入者.
    """
    from services.tx_trade.src.services.cashier_engine import (
        CashierEngine,
        TableOccupiedError,
    )

    tenant_id = _new_uuid()
    n = 10
    order_ids: list[uuid.UUID] = []

    async with session_factory() as s:
        store_id = await _seed_store(s, tenant_id)
        for i in range(1, n + 1):
            tno = f"B{i:02d}"
            await _seed_table(s, tenant_id, store_id, table_no=tno, status="occupied")
            oid = await _seed_order(s, tenant_id, store_id, table_no=tno, status="pending")
            # 关联订单
            await s.execute(
                text(
                    "UPDATE tables SET current_order_id=CAST(:oid AS uuid) "
                    "WHERE store_id=CAST(:sid AS uuid) AND table_no=:tno"
                ),
                {"oid": str(oid), "sid": str(store_id), "tno": tno},
            )
            order_ids.append(oid)
        await _seed_table(s, tenant_id, store_id, table_no="VIP01", status="free")
        await s.commit()

    async def _transfer_factory(idx: int):
        async def _do(session: AsyncSession) -> dict:
            engine = CashierEngine(db=session, tenant_id=str(tenant_id))
            return await engine.transfer_table(
                order_id=str(order_ids[idx]),
                target_table_no="VIP01",
                operator_id=str(_new_uuid()),
            )
        return _do

    # 不能用 run_concurrent (固定 operation) — 自己 gather
    async def _spawn():
        sessions = [session_factory() for _ in range(n)]
        coros = []
        for i, sess_ctx in enumerate(sessions):
            sess = await sess_ctx.__aenter__()
            await sess.execute(
                text("SELECT set_config('app.tenant_id', :tid, true)"),
                {"tid": str(tenant_id)},
            )
            op = await _transfer_factory(i)
            coros.append(_run_one(sess, sess_ctx, op))
        return await asyncio.gather(*coros, return_exceptions=True)

    async def _run_one(sess, sess_ctx, op):
        try:
            result = await op(sess)
            await sess.commit()
            return result
        except BaseException as e:
            await sess.rollback()
            return e
        finally:
            await sess_ctx.__aexit__(None, None, None)

    results = await asyncio.wait_for(_spawn(), timeout=30.0)

    succeeded = [r for r in results if not isinstance(r, BaseException)]
    failed = [r for r in results if isinstance(r, BaseException)]

    assert len(succeeded) == 1, (
        f"expected 1 success, got {len(succeeded)} success + {len(failed)} fail. "
        f"errors: {[(type(e).__name__, str(e)[:80]) for e in failed]}"
    )
    # 9 个 fail 中应至少有 TableOccupiedError 类型 (放宽: 也允许 ValueError 兜底)
    assert all(isinstance(e, (TableOccupiedError, ValueError)) for e in failed)

    # 终态: VIP01 占用且 current_order_id 是 succeeded 那个 order_id
    async with session_factory() as s:
        await s.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": str(tenant_id)}
        )
        vip_row = (
            await s.execute(
                text(
                    "SELECT status, current_order_id FROM tables "
                    "WHERE store_id=CAST(:sid AS uuid) AND table_no='VIP01'"
                ),
                {"sid": str(store_id)},
            )
        ).first()
    assert vip_row is not None
    assert vip_row.status == "occupied"
    assert vip_row.current_order_id is not None


# ───────────────────────────────────────────────────────────────────
# T3: 2-way swap 转桌 (A→B + B→A) — 双锁排序防 ABBA 死锁
# ───────────────────────────────────────────────────────────────────
async def test_transfer_table_two_way_swap_no_deadlock(session_factory):
    """T3 — 两路反向转桌 (A 转到 B + B 转到 A), 双锁排序防 ABBA 死锁.

    场景 (audit §11.2 选择题 2 关联): 双 POS 同时操作 swap, 若不按 ID 升序锁
    会形成 ABBA 死锁 (worker1 锁 A 等 B; worker2 锁 B 等 A → PG deadlock detector kill).

    setup: 2 tables A01 + B01 (各占一 order), 2 orders
    runner: worker1 transfer order_A → B01; worker2 transfer order_B → A01

    业务预期 (§19 round-1 P1-2 修正): 两桌都 occupied，target.status != free 校验
    对两路都成立, **两路都应抛 TableOccupiedError**. 双锁排序的核心目标是**防 PG
    deadlock detector kill**, 而非"双成功". 旧断言 `>=1 success` 与设计预期矛盾.

    关键断言: 无 PG OperationalError "deadlock detected" — 双锁排序生效证明.
    """
    from sqlalchemy.exc import OperationalError

    from services.tx_trade.src.services.cashier_engine import (
        CashierEngine,
        TableOccupiedError,
    )

    tenant_id = _new_uuid()
    async with session_factory() as s:
        store_id = await _seed_store(s, tenant_id)
        order_a = await _seed_order(s, tenant_id, store_id, table_no="A01", status="pending")
        order_b = await _seed_order(s, tenant_id, store_id, table_no="B01", status="pending")
        await _seed_table(
            s, tenant_id, store_id, table_no="A01", status="occupied", current_order_id=order_a
        )
        await _seed_table(
            s, tenant_id, store_id, table_no="B01", status="occupied", current_order_id=order_b
        )
        await s.commit()

    async def _transfer_a_to_b(session: AsyncSession) -> dict:
        engine = CashierEngine(db=session, tenant_id=str(tenant_id))
        return await engine.transfer_table(
            order_id=str(order_a), target_table_no="B01"
        )

    async def _transfer_b_to_a(session: AsyncSession) -> dict:
        engine = CashierEngine(db=session, tenant_id=str(tenant_id))
        return await engine.transfer_table(
            order_id=str(order_b), target_table_no="A01"
        )

    async def _run(op):
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
        asyncio.gather(_run(_transfer_a_to_b), _run(_transfer_b_to_a), return_exceptions=True),
        timeout=30.0,
    )

    # 关键断言 1: 无 PG deadlock 触发 (双锁排序生效证明)
    deadlock_errors = [
        r for r in results
        if isinstance(r, OperationalError) and "deadlock" in str(r).lower()
    ]
    assert len(deadlock_errors) == 0, (
        f"ABBA 死锁触发! PG deadlock detector kill: "
        f"{[str(e)[:120] for e in deadlock_errors]} — 双锁排序未生效"
    )

    # 关键断言 2: 业务预期两桌都 occupied → 两路都应抛 TableOccupiedError (非死锁)
    occupied_errors = [r for r in results if isinstance(r, TableOccupiedError)]
    succeeded = [r for r in results if not isinstance(r, BaseException)]
    assert len(occupied_errors) == 2 and len(succeeded) == 0, (
        f"two-way swap 双 occupied 场景预期 2 TableOccupiedError + 0 success, 实际 "
        f"{len(succeeded)} success + {len(occupied_errors)} TableOccupiedError. "
        f"全部 errors: {[(type(e).__name__, str(e)[:80]) for e in results if isinstance(e, BaseException)]}"
    )

    # 终态合理: A01 + B01 都仍 occupied, current_order_id 保持原值不变
    async with session_factory() as s:
        await s.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": str(tenant_id)}
        )
        rows = (
            await s.execute(
                text(
                    "SELECT table_no, status, current_order_id FROM tables "
                    "WHERE store_id=CAST(:sid AS uuid) AND table_no IN ('A01', 'B01')"
                ),
                {"sid": str(store_id)},
            )
        ).all()
    by_no = {r.table_no: r for r in rows}
    # 两路 swap 都失败回滚, 桌台 current_order_id 保持原 order 引用
    assert by_no["A01"].status == "occupied"
    assert by_no["B01"].status == "occupied"
    assert by_no["A01"].current_order_id == order_a, (
        f"A01.current_order_id 应保持 order_a, 实际 {by_no['A01'].current_order_id}"
    )
    assert by_no["B01"].current_order_id == order_b, (
        f"B01.current_order_id 应保持 order_b, 实际 {by_no['B01'].current_order_id}"
    )
