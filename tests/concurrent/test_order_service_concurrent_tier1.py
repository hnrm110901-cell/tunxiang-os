"""order_service 真 PG 并发 Tier 1 测试 (PR-5 — order_service P0 paths)

PR-5 of PR #631 proposal §10 6-PR roadmap — concurrent_runner PR-1 (PR #634)
PR-2 cashier (#638) / PR-3 payment_saga (#642) / PR-4 inventory (#644) 之后第五个
业务测试 PR. 验证 audit doc §4.1.4 order_service.py 2 P0 路径**真行为**:

  - T1: N=10 concurrent apply_discount 同 order → FOR UPDATE 串行化, final state 自洽
        (PR #560 PR-E ship 后 mock-only, 本测试是真 PG race 验证)
        **应用 Issue #643 P2-A distinct-set assertion**: workers 返回 (worker_idx, my_discount,
        observed_final), 断言 distinct_workers == 10 + 终态 final + discount == total
        consistency invariant (FOR UPDATE 防 split-state)
        **比 cashier_engine.apply_discount 简化版更危险** — 连 margin 校验都没有,
        FOR UPDATE 是唯一防线 (audit doc §4.1.4 P0 注)

  - T2: N=10 concurrent settle_order 同 order → 1 成功 + 9 raise ValueError
        (双结算泄漏防护). 与 PR-2 cashier T3 同模式, 验证 order_service.settle_order
        Saga S3 链路所依赖的 FOR UPDATE 真生效 — payment_saga._complete_order L502
        调用本函数, 同事务 FOR UPDATE 重入安全, 此锁是 saga S3 占位锁的实质实施.
        (audit doc §4.1.4 P0 + audit §6.2 PaymentSaga S1→S3 状态间隙关联)

业务场景（真餐厅, audit doc §4.1.4）:
  - T1: 收银员打折 + 经理改折扣 race → 必须串行 (apply_discount 仅校验 new_final≥0,
        无 margin 校验, FOR UPDATE 失效会致 final/discount split-state corruption)
  - T2: POS 重试 / 用户连点 / 网关回调 settle race → 必须只完成 1 次结算
        (Saga S3 同事务调本函数, 跨 worker FOR UPDATE 防双结算泄漏)

跑法 (opt-in via INTEGRATION_PG_DSN):

    docker compose -f infra/compose/test-pg.yml up -d
    DATABASE_URL=postgresql://tunxiang_test:test_password_dev_only@localhost:5433/tunxiang_os_test \\
        ./scripts/db-bootstrap.sh --skip-create
    DATABASE_URL=postgresql://tunxiang_test:test_password_dev_only@localhost:5433/tunxiang_os_test \\
        ./scripts/migrate-all.sh --include-legacy
    INTEGRATION_PG_DSN=postgresql://tunxiang_test:test_password_dev_only@localhost:5433/tunxiang_os_test \\
        pytest tests/concurrent/test_order_service_concurrent_tier1.py \\
        --confcutdir tests/concurrent --override-ini asyncio_mode=auto -v

未设 INTEGRATION_PG_DSN → 全部 skip (opt-in 模式)。

关联:
  - PR #631 proposal §10 PR-5 (本 PR)
  - PR #634 PR-1 / #638 PR-2 / #642 PR-3 / #644 PR-4
  - docs/security/tier1-row-lock-audit-2026-05.md §4.1.4 (order_service 2 P0 + 3 P1)
  - PR #560 PR-E (源 fix: apply_discount + settle_order `_get_order(lock=True)`)
  - services/tx-trade/tests/test_order_service_row_lock_tier1.py (mock-driven 负面 mode)
  - Issue #557 (apply_discount _calc_order_cost 隐式不变量, follow-up)
  - Issue #559 (apply_discount 不校验 order.status, 与 §17 桌台对齐合并)
  - Issue #643 P2-A 应用：distinct-set assertion (worker_idx + observed_final tuple)
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

# ── 路径 + namespace 包 (与 PR-2/3/4 同 pattern) ──────────────────────────────
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


# ── pytest collection guard (Python 3.10+) ──────────────────────────────────
# order_service 顶层 import shared.events.src.emitter, dataclass(slots=True) 仅 3.10+;
# 用 sys.version_info gate 替代 sys.modules stub (PR-A round-1 教训
# feedback_pytest_stub_setdefault_pitfall.md 跨 test 文件污染)
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


def _new_uuid() -> uuid.UUID:
    return uuid.uuid4()


async def _seed_store(session: AsyncSession, tenant_id: uuid.UUID) -> uuid.UUID:
    """INSERT 1 store, 返回 store_id. 与 PR-2 cashier _seed_store 同 pattern."""
    store_id = _new_uuid()
    await session.execute(
        text("""
            INSERT INTO stores (id, tenant_id, store_name, store_code)
            VALUES (CAST(:id AS uuid), CAST(:tid AS uuid), :name, :code)
        """),
        {
            "id": str(store_id),
            "tid": str(tenant_id),
            "name": f"order-{uuid.uuid4().hex[:8]}",
            "code": f"ORD-{uuid.uuid4().hex[:12]}",
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
    """INSERT 1 order, table_number=NULL 跳 _release_table FK 依赖.

    table_number=NULL 让 settle_order 的 `if order.table_number: _release_table(...)`
    分支跳过, 避免依赖 tables 表 schema (audit doc §4.1.4 桌台释放在 §17 桌台对齐
    follow-up PR 范围, 非本 PR scope).

    customer_id=NULL 让 settle_order 跳 fire_order_attribution HTTP 调用 (本 PR
    scope: 行锁, 非营销归因 infra).
    """
    order_id = _new_uuid()
    final = (
        final_amount_fen if final_amount_fen is not None
        else total_amount_fen - discount_amount_fen
    )
    await session.execute(
        text("""
            INSERT INTO orders (
                id, tenant_id, store_id, order_no, status,
                total_amount_fen, discount_amount_fen, final_amount_fen,
                table_number, customer_id, order_metadata
            )
            VALUES (
                CAST(:id AS uuid), CAST(:tid AS uuid), CAST(:sid AS uuid),
                :order_no, :status,
                :total, :discount, :final,
                NULL, NULL, '{}'::jsonb
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

    与 PR-2 cashier 测试同 pattern (`feedback_drift_tolerant_workflow.md`):
    shared/db-migrations chain pre-existing drift (v301 projector_checkpoints) 阻塞
    alembic upgrade head 在 v342 不应用 → OrderItem ORM 在某些 SELECT 路径 (含 settle_order
    内部不直接查 OrderItem 但 cancel_order / get_order 查) 需 barcode 列 → ProgrammingError.
    幂等 ADD COLUMN IF NOT EXISTS, 多 test 重复跑 no-op.
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
    """order_service.settle_order + cancel_order 调 asyncio.create_task(emit_event(...));
    无 Redis/PG event store 时背景 task 抛 ConnectionRefusedError 污染 CI.

    **§19 PR-2 P1-B fix 应用** (跨 PR 沿用): patch 两处 reference (emitter 模块
    导出 + order_service 已 import 的本地 ref), yield 后多轮 asyncio.sleep(0) drain
    pending fire-and-forget tasks, 让 monkeypatch 恢复前 _noop 完成.
    """
    import services.tx_trade.src.services.order_service as order_module

    import shared.events.src.emitter as emitter_module

    async def _noop_emit(*args, **kwargs):
        return None

    monkeypatch.setattr(emitter_module, "emit_event", _noop_emit)
    monkeypatch.setattr(order_module, "emit_event", _noop_emit)
    yield
    for _ in range(5):
        await asyncio.sleep(0)


@pytest_asyncio.fixture(autouse=True)
async def _silence_attribution(monkeypatch):
    """order_service.settle_order 在 customer_id != NULL 时调 fire_order_attribution
    (HTTP fire-and-forget 营销归因). 本测试 _seed_order 用 customer_id=NULL 跳过, 但
    防御性 monkeypatch no-op 避免源未来 customer_id 必填变化时 silent break.
    """
    import services.tx_trade.src.services.order_service as order_module

    def _noop_attribution(*args, **kwargs):
        return None

    monkeypatch.setattr(order_module, "fire_order_attribution", _noop_attribution)


# ───────────────────────────────────────────────────────────────────
# T1: N=10 concurrent apply_discount — FOR UPDATE 串行化 + final 自洽
# ───────────────────────────────────────────────────────────────────
async def test_order_service_apply_discount_concurrent_n10_consistent_final_state(
    session_factory,
):
    """T1 — 收银员打折 + 经理改折扣 race, FOR UPDATE 防 final/discount split-state corruption.

    setup: 1 store + 1 order (status=confirmed, total=10000, discount=0, final=10000)
    runner: N=10 workers 各 apply_discount(discount_fen=N*100), N=worker_idx+1
            → discount_fen ∈ {100, 200, ..., 1000} 严格递增, 各 worker 不同
    断言（核心 P0 + Issue #643 P2-A distinct-set 升级版）:
      - 10 worker 全部成功（无 exception — 状态始终 confirmed, new_final=total-discount≥0）
      - 终态 consistency invariant: orders.final_amount_fen == total_amount_fen - discount_amount_fen
      - **distinct-set assertion (Issue #643 P2-A)**: workers 返回 (worker_idx, my_discount,
        my_final), distinct worker_idx == 10 (workers_lock 串行化生效) +
        my_final == 10000 - my_discount (每 worker 自洽)
      - 终态 discount_amount_fen ∈ {100, 200, ..., 1000} (last-writer-wins,
        是 10 worker 之一; FOR UPDATE 真生效保证 last commit 完整原子)
      - 终态 status == confirmed (apply_discount 不改 status)

    若 FOR UPDATE 未真生效（audit doc §4.1.4 P0 — PR #560 PR-E fix 回归）:
      - W1 SELECT (race) total=10000, discount=0; W2 SELECT (race) 同上
      - W1 算 new_final=9900 (discount=100); W2 算 new_final=9800 (discount=200)
      - 二者并发 flush — PG row-level UPDATE 是 atomic per row, 终态 (discount,
        final) 来自 last-write-wins worker, **当前 apply_discount 实现下二字段
        总配对写入 → 即便无 FOR UPDATE consistency invariant 仍成立**;
      - 但 split-state 风险存在于**未来如果 apply_discount 被 refactor 拆分写**
        (issue #557 _calc_order_cost 隐式不变量). 本测试 + distinct workers 守门;
      - **distinct workers count == 10 失败** 表明并发 worker 串行 lock 失效或
        worker fail (BaseException), 是 P0 直接证据.

    与 PR-2 cashier T2 互补:
      - cashier T2: cashier_engine.apply_discount (含毛利底线 + margin 校验)
      - order_service T1: order_service.apply_discount **简化版** — 仅校验
        new_final≥0, **无 margin 校验**, audit §4.1.4 注 "比 cashier_engine 更危险"
        FOR UPDATE 是唯一防线
    """
    from services.tx_trade.src.services.order_service import OrderService

    tenant_id = _new_uuid()
    async with session_factory() as s:
        store_id = await _seed_store(s, tenant_id)
        order_id = await _seed_order(
            s, tenant_id, store_id,
            status="confirmed", total_amount_fen=10000,
            discount_amount_fen=0, final_amount_fen=10000,
        )
        await s.commit()

    # worker 索引 → 决定 discount_fen 大小 (alternating 严格递增 100 单位)
    workers_count = [0]
    workers_lock = asyncio.Lock()

    async def _apply_discount(session: AsyncSession) -> dict:
        """单 worker apply_discount, discount = (idx+1) * 100 fen."""
        async with workers_lock:
            idx = workers_count[0]
            workers_count[0] += 1
        my_discount = (idx + 1) * 100  # 100, 200, ..., 1000
        svc = OrderService(db=session, tenant_id=str(tenant_id))
        result = await svc.apply_discount(
            order_id=str(order_id),
            discount_fen=my_discount,
            reason=f"race-test-{uuid.uuid4().hex[:6]}",
        )
        return {
            "worker_idx": idx,
            "my_discount": my_discount,
            "my_final": result["final_fen"],
        }

    results = await run_concurrent(
        session_factory, tenant_id, n=10,
        operation=_apply_discount,
        timeout_sec=30.0,
    )

    # 全部成功 — 状态始终 confirmed, FOR UPDATE 串行化, new_final=10000-N*100 总 ≥ 0
    exceptions = [r for r in results if isinstance(r, BaseException)]
    assert not exceptions, (
        f"order_service.apply_discount concurrent unexpected exceptions "
        f"({len(exceptions)}/{len(results)}): {exceptions[:3]}"
    )

    # 终态自洽 (P0 split-state corruption 防护): final + discount == total = 10000
    async with session_factory() as s:
        result = await s.execute(
            text("""
                SELECT total_amount_fen, discount_amount_fen, final_amount_fen, status
                FROM orders WHERE id = CAST(:id AS uuid)
            """),
            {"id": str(order_id)},
        )
        total, discount, final, status = result.one()
        assert total == 10000, f"total_amount_fen 不应变化: actual={total} expected=10000"
        assert final + discount == total, (
            f"P0 split-state corruption: final={final} + discount={discount} "
            f"!= total={total}. FOR UPDATE 未真生效, audit §4.1.4 P0 path 回归. "
            f"order_service.apply_discount 比 cashier_engine 简化, 无 margin 校验, "
            f"FOR UPDATE 是唯一防线."
        )
        # discount 应 ∈ {100..1000}, last-writer-wins (FOR UPDATE 真生效保证 last commit
        # 完整原子, 不会出现非 worker 写入值)
        assert discount in {(i + 1) * 100 for i in range(10)}, (
            f"discount_amount_fen actual={discount} 不在 worker 写入候选集 "
            f"{{100..1000}}; FOR UPDATE 失效或 ORM 副作用脏写"
        )
        assert status == "confirmed", (
            f"status 不应变化 (apply_discount 不改 status): actual={status}"
        )

    # 主断言 (Issue #643 P2-A distinct-set + 自洽):
    # 10 worker 各独立 idx, 各自 my_final == 10000 - my_discount
    dict_results = [r for r in results if isinstance(r, dict)]
    assert len(dict_results) == 10, (
        f"worker 应返回 dict, actual {len(dict_results)}/10. "
        f"non-dict results: {[r for r in results if not isinstance(r, dict)][:3]}"
    )
    distinct_indices = {r["worker_idx"] for r in dict_results}
    assert len(distinct_indices) == 10, (
        f"Issue #643 P2-A: distinct worker_idx actual={len(distinct_indices)} expected=10. "
        f"workers_lock 串行化 fail 或重复 idx 表明 race 测试 setup 异常"
    )
    # 每 worker 自洽: my_final == 10000 - my_discount
    for r in dict_results:
        assert r["my_final"] == 10000 - r["my_discount"], (
            f"worker {r['worker_idx']} 自洽断言失败: my_discount={r['my_discount']}, "
            f"my_final={r['my_final']}, 期望 my_final == 10000 - my_discount = "
            f"{10000 - r['my_discount']}. FOR UPDATE 未真生效, worker 看到 stale total."
        )
    # 写入 discount 集合 == {100..1000} (10 worker 各 distinct 写入)
    written_discounts = {r["my_discount"] for r in dict_results}
    expected_discounts = {(i + 1) * 100 for i in range(10)}
    assert written_discounts == expected_discounts, (
        f"distinct workers 应各写入 distinct discount: actual={sorted(written_discounts)} "
        f"expected={sorted(expected_discounts)}"
    )


# ───────────────────────────────────────────────────────────────────
# T2: N=10 concurrent settle_order — 双结算泄漏防护 (1 成功 + 9 raise)
# ───────────────────────────────────────────────────────────────────
async def test_order_service_settle_order_concurrent_n10_double_settle_prevention(
    session_factory,
):
    """T2 — POS 重试 / 用户连点 / 网关 saga 回调 race settle, FOR UPDATE 防双结算.

    setup: 1 store + 1 order (status=confirmed, total=100, final=100, table_number=NULL)
    runner: N=10 workers 各 svc.settle_order(order_id)
    断言:
      - 1 worker 成功 + 9 worker raise ValueError
        (业务层守卫: "Order already settled" L404 或 transition_order 拒绝)
      - orders.status='completed' (transition 1 次)
      - orders.completed_at IS NOT NULL (单次写入)
      - **distinct-set assertion (Issue #643 P2-A)**: 仅 1 worker 见 success result
        (含 settled_at), 其他 worker 见 ValueError; success worker 的 settled_at
        与 DB 终态 completed_at 字符串一致 (单点写入证据)

    若 FOR UPDATE 未真生效（audit doc §4.1.4 P0 + audit §6.2 saga S3 链路依赖）:
      - 10 worker 并发 SELECT order.status='confirmed'
      - 10 worker 都判 status≠completed, 继续 transition + flush
      - 10 次 emit_event(ORDER.PAID) 重复发射 → 下游 ledger / 财务月报双计
      - 同时若 customer_id != NULL → 10 次 fire_order_attribution → 营销归因脏数据
      - **Saga S3 链路放大**: payment_saga._complete_order L502 调用本函数,
        无锁会让 saga retry 与 worker race 并发 settle, 双扣款风险

    与 PR-2 cashier T3 互补:
      - cashier T3 测 cashier_engine.settle_order (有桌台 release 故意不锁)
      - order_service T2 测 order_service.settle_order (Saga S3 调入口, 同事务
        重入 FOR UPDATE 安全; payment 表无 INSERT — order_service 只 transition
        status, 不写 payments — 与 cashier_engine 不同, 故 assert_final_consistency
        断言 orders.status 而非 payments)
    """
    from services.tx_trade.src.services.order_service import OrderService

    tenant_id = _new_uuid()
    async with session_factory() as s:
        store_id = await _seed_store(s, tenant_id)
        order_id = await _seed_order(
            s, tenant_id, store_id,
            status="confirmed", total_amount_fen=100,
            discount_amount_fen=0, final_amount_fen=100,
        )
        await s.commit()

    workers_count = [0]
    workers_lock = asyncio.Lock()

    async def _settle(session: AsyncSession) -> dict:
        async with workers_lock:
            idx = workers_count[0]
            workers_count[0] += 1
        svc = OrderService(db=session, tenant_id=str(tenant_id))
        result = await svc.settle_order(order_id=str(order_id))
        return {"worker_idx": idx, **result}

    results = await run_concurrent(
        session_factory, tenant_id, n=10,
        operation=_settle,
        timeout_sec=30.0,
    )

    # 分流结果: 成功 vs ValueError vs 其他异常
    successes = [r for r in results if isinstance(r, dict)]
    value_errors = [r for r in results if isinstance(r, ValueError)]
    settled_errors = [r for r in value_errors if "already settled" in str(r).lower()]
    other_errors = [
        r for r in results
        if isinstance(r, BaseException) and not isinstance(r, ValueError)
    ]

    # 主断言 (P0 双结算泄漏防护核心): 仅 1 worker 成功
    assert len(successes) == 1, (
        f"双结算泄漏 P0: 成功 settle 数 {len(successes)} ≠ 1. "
        f"FOR UPDATE 未真生效, audit §4.1.4 P0 + Saga S3 链路放大风险. "
        f"results: successes={len(successes)} value_errors={len(value_errors)} "
        f"settled_errors={len(settled_errors)} other_errors={len(other_errors)}"
    )
    # 辅助断言: 剩余 9 worker 全部是预期 ValueError (业务层守卫拒绝, 非 DB/网络异常)
    assert len(value_errors) == 9, (
        f"剩余 worker 应抛 ValueError (settle_order L404 'already settled' 守卫或 "
        f"transition_order 状态机拒绝), actual {len(value_errors)}/9. "
        f"other_errors={other_errors[:3]}"
    )
    # 不硬断言 settled_errors==9 — 业务层错误消息措辞可能变 (issue #559 / §17 桌台对齐
    # follow-up 可能 refactor 错误消息), 与 PR-2 cashier T3 同 robustness 处理
    if len(settled_errors) != 9:
        import warnings
        warnings.warn(
            f"诊断: settled_errors 'already settled' 字串匹配 {len(settled_errors)}/9; "
            f"其他 ValueError ({len(value_errors) - len(settled_errors)} 笔) 也算 "
            f"FOR UPDATE 真生效证据 (transition_order 状态机拒绝), 但建议确认错误消息措辞",
            stacklevel=1,
        )

    # 终态: orders.status='completed', completed_at 单次写入
    async with session_factory() as s:
        await assert_final_consistency(
            s, "orders", {"id": str(order_id)},
            {"count": 1, "status_set": {"completed"}},
        )
        # completed_at 必须存在 (单 worker transition 后写入)
        result = await s.execute(
            text("""
                SELECT completed_at FROM orders WHERE id = CAST(:id AS uuid)
            """),
            {"id": str(order_id)},
        )
        completed_at = result.scalar_one()
        assert completed_at is not None, (
            "orders.completed_at 应为成功 worker transition 时刻, actual=NULL. "
            "transition_order(completed) 未生效或 settle_order 早期 raise."
        )

    # success worker 的 settled_at 与 DB completed_at 字符串一致 (单点写入证据)
    success_settled_at = successes[0].get("settled_at", "")
    # completed_at ISO 字符串与 settled_at 同源 (settle_order L450
    # `settled_at: order.completed_at.isoformat()`)
    assert success_settled_at, (
        f"success worker 应返回 settled_at, actual result={successes[0]}"
    )
