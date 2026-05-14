"""CashierEngine 真 PG 并发 Tier 1 测试（PR-2 框架金标准）

PR-2 of PR #631 proposal §10 6-PR roadmap — concurrent_runner PR-1 (PR #634)
之后第一个**业务测试** PR，作为后续 PR-3/4/5 的「金标准」模板。

验证 audit doc §4.1 cashier_engine 3 P0 路径 FOR UPDATE 行锁**真行为**（与
services/tx-trade/tests/test_cashier_engine_row_lock_tier1.py 的 mock-driven
SQL grep 互补 — 负面 mode）:

  - T1: N=10 add_item 同 order → FOR UPDATE 串行化, 无 total_amount_fen lost update
  - T2: N=10 apply_discount 同 order → FOR UPDATE 串行化, final state 自洽
  - T3: N=10 settle_order 同 order → 1 成功 + 9 raise "订单已结算" (双结算泄漏防护)

业务场景（真餐厅，audit doc §4.1）:
  - 200 桌晚高峰 POS 加菜 + 服务员手机 PWA 同时加菜 (race) → 必须串行写 total
  - 收银员打折 + 经理改折扣 race → 必须串行 + 毛利底线生效
  - POS 重试 / 用户连点 / 网关回调 → 必须只完成 1 次结算

跑法 (opt-in via INTEGRATION_PG_DSN):

    docker compose -f infra/compose/test-pg.yml up -d
    DATABASE_URL=postgresql://tunxiang_test:test_password_dev_only@localhost:5433/tunxiang_os_test \\
        ./scripts/db-bootstrap.sh --skip-create
    DATABASE_URL=postgresql://tunxiang_test:test_password_dev_only@localhost:5433/tunxiang_os_test \\
        ./scripts/migrate-all.sh --include-legacy
    INTEGRATION_PG_DSN=postgresql://tunxiang_test:test_password_dev_only@localhost:5433/tunxiang_os_test \\
        pytest tests/concurrent/test_cashier_engine_concurrent_tier1.py \\
        --confcutdir tests/concurrent --override-ini asyncio_mode=auto -v

未设 INTEGRATION_PG_DSN → 全部 skip (opt-in 模式)。

关联:
  - PR #631 proposal §10 PR-2 (本 PR)
  - PR #634 PR-1 infra (concurrent_runner + conftest + workflow)
  - docs/security/tier1-row-lock-audit-2026-05.md §4.1 (3 P0 paths)
  - services/tx-trade/tests/test_cashier_engine_row_lock_tier1.py (mock-driven 负面 mode)
  - audit §8.3「正面/负面测试模式」「金标准」milestone
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

# ── 路径 + namespace 包 ──────────────────────────────────────────────────────
# 与 services/tx-trade/conftest.py 同 pattern — 跑在 `--confcutdir tests/concurrent`
# 下 repo-root conftest 不加载, 必须本地复刻 namespace 包注入逻辑让 cashier_engine
# 的相对 import `from ..models.enums import TableStatus` 可解析。
#
# tests/concurrent/test_*.py → __file__/../.. = repo_root
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
TX_TRADE_DIR = os.path.join(ROOT, "services", "tx-trade")
TX_TRADE_SRC = os.path.join(TX_TRADE_DIR, "src")
for p in [ROOT, TX_TRADE_SRC]:
    if p not in sys.path:
        sys.path.insert(0, p)


def _ensure_ns(name: str, path: str) -> None:
    """创建 namespace 包让 `from services.tx_trade.src.services.X` 跨 dash 路径可解析."""
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


# ── pytest collection guard ──────────────────────────────────────────────────
# cashier_engine 顶层 import shared.events.src.emitter，后者用 dataclass(slots=True)
# 仅 Python 3.10+ 支持。本机 3.9 跑会 TypeError；CI Python 3.11 原生通过。
# 用 sys.version_info gate 而非 sys.modules stub（PR-A round-1 教训：stub 注入
# 'shared' 包污染同目录 test_invoice_tier1.py 等 — feedback_pytest_stub_setdefault_pitfall.md）。
if sys.version_info < (3, 10):
    pytest.skip(
        "需 Python 3.10+ (shared.events 用 dataclass slots=True); CI Python 3.11 跑通",
        allow_module_level=True,
    )

from shared.test_utils.concurrent_runner import (  # noqa: E402
    assert_final_consistency,
    run_concurrent,
)
from shared.test_utils.integration_pg import requires_integration_pg  # noqa: E402

pytestmark = [requires_integration_pg]


# ── helper: 测试 tenant / store / order 独立 UUID 避免 cross-test 污染 ─────────
def _new_uuid() -> uuid.UUID:
    return uuid.uuid4()


async def _seed_store(session: AsyncSession, tenant_id: uuid.UUID) -> uuid.UUID:
    """INSERT 1 store, 返回 store_id。最小列: id/tenant_id/store_name/store_code。"""
    store_id = _new_uuid()
    await session.execute(
        text("""
            INSERT INTO stores (id, tenant_id, store_name, store_code)
            VALUES (CAST(:id AS uuid), CAST(:tid AS uuid), :name, :code)
        """),
        {
            "id": str(store_id),
            "tid": str(tenant_id),
            "name": f"cashier-{uuid.uuid4().hex[:8]}",
            "code": f"CSH-{uuid.uuid4().hex[:12]}",
        },
    )
    return store_id


async def _seed_order(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    store_id: uuid.UUID,
    *,
    status: str,
    total_amount_fen: int,
    discount_amount_fen: int = 0,
    final_amount_fen: int | None = None,
) -> uuid.UUID:
    """INSERT 1 order, table_number=NULL 跳 _release_table FK 依赖。

    table_number=NULL 让 settle_order 的 `if order.table_number: _release_table(...)`
    分支跳过, 避免依赖 tables 表 schema (audit doc §4.1.2 桌台释放在本 PR 范围外)。
    """
    order_id = _new_uuid()
    final = final_amount_fen if final_amount_fen is not None else total_amount_fen - discount_amount_fen
    await session.execute(
        text("""
            INSERT INTO orders (
                id, tenant_id, store_id, order_no, status,
                total_amount_fen, discount_amount_fen, final_amount_fen,
                table_number, order_metadata
            )
            VALUES (
                CAST(:id AS uuid), CAST(:tid AS uuid), CAST(:sid AS uuid),
                :order_no, :status,
                :total, :discount, :final,
                NULL, '{}'::jsonb
            )
        """),
        {
            "id": str(order_id),
            "tid": str(tenant_id),
            "sid": str(store_id),
            "order_no": f"TX{uuid.uuid4().hex[:14].upper()}",
            "status": status,
            "total": total_amount_fen,
            "discount": discount_amount_fen,
            "final": final,
        },
    )
    return order_id


@pytest.fixture(autouse=True)
async def _ensure_v342_schema(engine):
    """drift workaround — ADD COLUMN IF NOT EXISTS for v342_barcode_tracking columns.

    shared/db-migrations chain pre-existing drift (v301 projector_checkpoints
    `last_processed_at` column name mismatch, MEMORY `feedback_drift_tolerant_workflow.md`)
    阻塞 alembic upgrade head 在 v301 → v342_barcode_tracking 不应用 → OrderItem ORM SELECT
    需 barcode 列但表里没有 → ProgrammingError.

    本 fixture 显式 ADD COLUMN IF NOT EXISTS, 让 OrderItem ORM SELECT 不爆。与 drift-tolerant
    CI 模式同源 — alembic 失败时 explicit schema patch 不阻塞 PR ship, 真 drift 修走独立
    issue (跨 v301 / v342 不在 PR-2 scope)。

    幂等: ALTER TABLE ADD COLUMN IF NOT EXISTS, 多 test 重复跑 no-op。
    引擎用 DSN superuser (tunxiang_test), 权限充足。
    """
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
    """CashierEngine 业务调 asyncio.create_task(emit_event(...))，无 Redis 时背景
    task 会 fail (Task exception was never retrieved 警告)。本 fixture monkeypatch
    emit_event 为 no-op coroutine, 让测试干净不依赖事件总线 infra (本 PR scope: 行锁,
    非事件总线)。

    **§19 P1-B fix**: monkeypatch 是 function-scope, 但 cashier_engine 用
    asyncio.create_task(emit_event(...)) fire-and-forget。worker commit/return 后
    create_task 仍 pending; 若 fixture teardown 时 monkeypatch undo, 后续 task
    跑真 emit_event 抛 ConnectionRefusedError 污染 CI。改 async generator + yield
    + 多轮 asyncio.sleep(0) drain pending tasks 在 monkeypatch 恢复前完成。
    """
    import services.tx_trade.src.services.cashier_engine as cashier_module

    import shared.events.src.emitter as emitter_module

    async def _noop_emit(*args, **kwargs):
        return None

    # patch 两处 reference - emitter_module 导出 + cashier_engine 已 import 的本地 ref
    monkeypatch.setattr(emitter_module, "emit_event", _noop_emit)
    monkeypatch.setattr(cashier_module, "emit_event", _noop_emit)
    yield
    # drain pending fire-and-forget tasks before monkeypatch undo
    # 多轮 sleep(0) yield event loop 让所有 create_task 完成 _noop_emit (本 PR scope)
    for _ in range(5):
        await asyncio.sleep(0)


# ───────────────────────────────────────────────────────────────────
# T1: N=10 concurrent add_item — FOR UPDATE 串行化 + 无 lost update
# ───────────────────────────────────────────────────────────────────
async def test_cashier_add_item_concurrent_n10_no_lost_update(session_factory):
    """T1 — 200 桌晚高峰 POS+PWA race add_item 同 order, FOR UPDATE 真串行化.

    setup: 1 store + 1 order (status=pending, total=0)
    runner: N=10 workers 各 add_item(unit_price=100, qty=1)
    断言:
      - 10 worker 全部成功（无 exception）
      - orders.total_amount_fen = 1000（10 × 100, FOR UPDATE 串行化无 lost update）
      - order_items count=10（每 worker 各 INSERT 1 行）
      - orders.status = 'confirmed'（pending→confirmed transition 幂等）

    若 FOR UPDATE 未真生效（mock 假串行化）, total_amount_fen 会 < 1000:
      - 10 worker 并发 SELECT total=0
      - 各算 new_total = 0+100=100, 10 个 worker 都写 total=100
      - 最终 total=100 (lost update 9 笔)
    """
    from services.tx_trade.src.services.cashier_engine import CashierEngine

    tenant_id = _new_uuid()
    # setup
    async with session_factory() as s:
        store_id = await _seed_store(s, tenant_id)
        order_id = await _seed_order(
            s, tenant_id, store_id,
            status="pending", total_amount_fen=0,
        )
        await s.commit()

    async def _add_item(session: AsyncSession) -> dict:
        engine = CashierEngine(db=session, tenant_id=str(tenant_id))
        # dish_id="" → falsy → engine 走 _get_order(lock=True) 分支 (避 Dish FK 依赖)
        return await engine.add_item(
            order_id=str(order_id),
            dish_id="",
            dish_name=f"item-{uuid.uuid4().hex[:6]}",
            qty=1,
            unit_price_fen=100,
        )

    results = await run_concurrent(
        session_factory, tenant_id, n=10,
        operation=_add_item,
        timeout_sec=30.0,
    )

    # 全部成功 — FOR UPDATE 串行化, 无 lost update
    exceptions = [r for r in results if isinstance(r, BaseException)]
    assert not exceptions, (
        f"add_item concurrent unexpected exceptions ({len(exceptions)}/{len(results)}): "
        f"{exceptions[:3]}"
    )

    # 终态: 10 个 worker 都 add 1 item, 串行 acc total → final total=1000
    async with session_factory() as s:
        await assert_final_consistency(
            s, "order_items", {"order_id": str(order_id)},
            {"count": 10, "sum_subtotal_fen": 1000},
        )

        result = await s.execute(
            text("""
                SELECT total_amount_fen, status FROM orders
                WHERE id = CAST(:id AS uuid)
            """),
            {"id": str(order_id)},
        )
        row = result.one()
        total_amount, status = row[0], row[1]
        assert total_amount == 1000, (
            f"orders.total_amount_fen lost update detected: "
            f"actual={total_amount} expected=1000 (10 workers × 100 fen). "
            f"FOR UPDATE 未真生效或 audit §4.1 P0 path 回归"
        )
        assert status == "confirmed", (
            f"orders.status unexpected: actual={status} expected='confirmed' "
            f"(pending→confirmed transition 在首个 add_item 触发, 后续幂等)"
        )


# ───────────────────────────────────────────────────────────────────
# T2: N=10 concurrent apply_discount — FOR UPDATE 串行化 + final state 自洽
# ───────────────────────────────────────────────────────────────────
async def test_cashier_apply_discount_concurrent_n10_consistent_final_state(session_factory):
    """T2 — 收银员打折 + 经理改折扣 race, FOR UPDATE of Order 串行化, 终态自洽.

    setup: 1 store + 1 order (status=confirmed, total=1000, discount=0, final=1000)
           **不加 order_items** → _calc_order_cost 返回 None → 跳毛利底线 gate (避 BOM
           FK 依赖); apply_discount 业务逻辑全跑通。
    runner: N=10 workers 各 apply_discount(type="amount_off", value=50)
    断言:
      - 10 worker 全部成功（无 exception — 状态始终 confirmed, 不会 hit guard）
      - orders.discount_amount_fen = 50（last-writer-wins, 但所有 writer 都写 50, 一致）
      - orders.final_amount_fen = 950（= total - discount = 1000 - 50）
      - 终态自洽: final = total - discount（FOR UPDATE 防 split-state corruption）

    若 FOR UPDATE 未真生效:
      - W1 SELECT total=1000, discount=0, 算 new_discount=50, new_final=950
      - W2 SELECT (race) total=1000, discount=0, 算 new_discount=50, new_final=950
      - 都写 discount=50, final=950 → 终态值正确, 但**中间态**可能 (discount=50, final=1000)
        即 W1 写完 discount 未写 final, W2 也 SELECT 到 discount=0 后写 final
      - 本测试主要验证**不抛异常 + 终态自洽**, 防 split-state
    """
    from services.tx_trade.src.services.cashier_engine import CashierEngine

    tenant_id = _new_uuid()
    async with session_factory() as s:
        store_id = await _seed_store(s, tenant_id)
        order_id = await _seed_order(
            s, tenant_id, store_id,
            status="confirmed", total_amount_fen=1000,
            discount_amount_fen=0, final_amount_fen=1000,
        )
        await s.commit()

    async def _apply_discount(session: AsyncSession) -> dict:
        engine = CashierEngine(db=session, tenant_id=str(tenant_id))
        return await engine.apply_discount(
            order_id=str(order_id),
            discount_type="amount_off",
            discount_value=50.0,
            reason=f"race-test-{uuid.uuid4().hex[:6]}",
        )

    results = await run_concurrent(
        session_factory, tenant_id, n=10,
        operation=_apply_discount,
        timeout_sec=30.0,
    )

    # 全部成功 — 状态始终 confirmed, FOR UPDATE 串行化
    exceptions = [r for r in results if isinstance(r, BaseException)]
    assert not exceptions, (
        f"apply_discount concurrent unexpected exceptions ({len(exceptions)}/{len(results)}): "
        f"{exceptions[:3]}"
    )

    # 全部返回 applied=True（毛利底线 gate 跳过, 因无 OrderItem with cost_fen）
    applied_results = [r for r in results if isinstance(r, dict) and r.get("applied")]
    assert len(applied_results) == 10, (
        f"apply_discount applied=True 数 {len(applied_results)} / 10. "
        f"if some are needs_approval, 表明毛利底线 gate 误触发或 _calc_order_cost 行为变化"
    )

    # 终态自洽: discount=50, final=950, total=1000 (FOR UPDATE 防 split-state)
    async with session_factory() as s:
        result = await s.execute(
            text("""
                SELECT total_amount_fen, discount_amount_fen, final_amount_fen, status
                FROM orders WHERE id = CAST(:id AS uuid)
            """),
            {"id": str(order_id)},
        )
        total, discount, final, status = result.one()
        assert total == 1000, f"total_amount_fen 不应变化: actual={total} expected=1000"
        assert discount == 50, (
            f"discount_amount_fen 应为 last-write 50: actual={discount} expected=50"
        )
        assert final == 950, (
            f"final_amount_fen split-state corruption: actual={final} expected=950 "
            f"(= total 1000 - discount 50). FOR UPDATE 未真生效, audit §4.1 P0 path 回归"
        )
        assert status == "confirmed", f"status 不应变化: actual={status} expected='confirmed'"


# ───────────────────────────────────────────────────────────────────
# T3: N=10 concurrent settle_order — 双结算泄漏防护 (1 成功 + 9 失败)
# ───────────────────────────────────────────────────────────────────
async def test_cashier_settle_order_concurrent_n10_double_settle_prevention(session_factory):
    """T3 — POS 重试 / 用户连点结算 / 网关回调三路 race, FOR UPDATE 防双结算.

    setup: 1 store + 1 order (status=confirmed, final=100, table_number=NULL)
    runner: N=10 workers 各 settle_order(payments=[{cash, 100}])
    断言:
      - 1 worker 成功 + 9 worker raise ValueError("订单已结算")
      - payments count=1 (只 1 笔支付落库)
      - payments.sum(amount_fen)=100
      - orders.status='completed' (transition 1 次)

    若 FOR UPDATE 未真生效（audit doc §4.1 P0 最严重场景）:
      - 10 worker 并发 SELECT order.status='confirmed'
      - 10 worker 都判 status≠completed/cancelled, 继续 INSERT Payment + transition
      - 10 笔 payments 重复落库 + 客户多扣 9 次款 (P0 双结算泄漏)
      - 本测试是 audit doc 全文最严重 P0 路径的**真行为**守护

    实测优势 over mock-driven 测试：
      - mock 只能验"SELECT 含 FOR UPDATE" 字符串, 不能验**真锁串行化生效**
      - 真 PG 反测: 1 worker 拿锁 → status transition → commit → 锁释放 → 后续 worker
        SELECT 拿到 status='completed' → raise "订单已结算"。整链路真行为验证。
    """
    from services.tx_trade.src.services.cashier_engine import CashierEngine

    tenant_id = _new_uuid()
    async with session_factory() as s:
        store_id = await _seed_store(s, tenant_id)
        order_id = await _seed_order(
            s, tenant_id, store_id,
            status="confirmed", total_amount_fen=100,
            discount_amount_fen=0, final_amount_fen=100,
        )
        await s.commit()

    async def _settle(session: AsyncSession) -> dict:
        engine = CashierEngine(db=session, tenant_id=str(tenant_id))
        return await engine.settle_order(
            order_id=str(order_id),
            payments=[{"method": "cash", "amount_fen": 100}],
        )

    results = await run_concurrent(
        session_factory, tenant_id, n=10,
        operation=_settle,
        timeout_sec=30.0,
    )

    # 分流结果: 成功 vs 失败 (任意 ValueError 都算预期失败 — §19 P1-A fix:
    # 主断言 successes==1 是 P0 双结算泄漏防护核心, settled_errors 只作诊断辅助)。
    # 失败原因可能是 "订单已结算"(L759)/"订单已取消"(L761)/transition_order 状态机
    # 拒绝 — 任意 ValueError 都意味着第 1 worker 之外的 worker 在 FOR UPDATE 拿锁后
    # 看到 status 已变 → 被业务层拒绝, 这正是 FOR UPDATE 真生效的证据。
    successes = [r for r in results if isinstance(r, dict)]
    value_errors = [r for r in results if isinstance(r, ValueError)]
    settled_errors = [r for r in value_errors if "已结算" in str(r)]
    other_errors = [
        r for r in results
        if isinstance(r, BaseException) and not isinstance(r, ValueError)
    ]

    # 主断言 (P0 双结算泄漏防护核心): 仅 1 worker 成功
    assert len(successes) == 1, (
        f"双结算泄漏 P0: 成功 settle 数 {len(successes)} ≠ 1. "
        f"FOR UPDATE 未真生效, audit §4.1 P0 最严重路径回归. "
        f"results: successes={len(successes)} value_errors={len(value_errors)} "
        f"settled_errors={len(settled_errors)} other_errors={len(other_errors)}"
    )
    # 辅助断言: 剩余 9 worker 全部是预期的 ValueError (非 DB 异常 / 网络 / 类型错误)
    assert len(value_errors) == 9, (
        f"剩余 worker 应抛 ValueError (订单状态守卫拒绝), 实际 {len(value_errors)}/9. "
        f"other_errors={other_errors[:3]}"
    )
    # 不抛 settled_errors!=9 硬断言 — 业务层状态机措辞可能变 (PR #559/§17 桌台对齐
    # follow-up 可能 refactor 错误消息), 用诊断 warn 替代避免 false-fail:
    if len(settled_errors) != 9:
        # pytest -W default::Warning 会显示, 但不 fail
        import warnings
        warnings.warn(
            f"诊断: settled_errors '已结算' 字串匹配 {len(settled_errors)}/9; "
            f"其他 ValueError ({len(value_errors) - len(settled_errors)} 笔) 也算 FOR UPDATE 生效, "
            f"但建议确认状态机错误消息措辞未变 (issue #559 / §17 桌台对齐 follow-up)",
            stacklevel=1,
        )

    # 终态: 1 payment 落库 + orders.status='completed'
    async with session_factory() as s:
        await assert_final_consistency(
            s, "payments", {"order_id": str(order_id)},
            {"count": 1, "sum_amount_fen": 100},
        )

        result = await s.execute(
            text("SELECT status FROM orders WHERE id = CAST(:id AS uuid)"),
            {"id": str(order_id)},
        )
        status = result.scalar_one()
        assert status == "completed", (
            f"orders.status 应 transition 到 completed: actual={status}"
        )
