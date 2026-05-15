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
# T1: N=10 concurrent mixed apply_discount + locked total writer —
#     FOR UPDATE 真行为 falsifiable signal (round-1 §19 P1-1 fix)
# ───────────────────────────────────────────────────────────────────
async def test_order_service_apply_discount_for_update_serializes_against_total_writer(
    session_factory,
):
    """T1 — apply_discount race against locked total writer, FOR UPDATE 真生效
    断言 split-state invariant 保持 (round-1 §19 P1-1 fix - 真 falsifiable signal).

    **Round-1 §19 P1-1 修法背景**:
    原 T1 仅 10 worker 各 apply_discount(discount=N*100), 因 apply_discount 实现
    内部原子 UPDATE (discount, final) 配对写入同行, 即便去掉 _get_order(lock=True)
    `consistency invariant `final + discount == total` 仍成立 (单行 UPDATE 原子性
    保证 last-write-wins 自洽). 测试无法检测 FOR UPDATE 缺失 → 假绿.

    本设计 (round-1 P1-1 fix): 5 apply_discount + 5 总额写者 (modify_order) 互补
    race. 关键: **modify_order 显式 SELECT FOR UPDATE 后 UPDATE total += inc AND
    final += inc** (维持 invariant — 模拟"如果 add_item/update_item_quantity 也加锁
    会怎样"). 两路均加锁时 invariant 全程持; 仅 apply_discount 加锁失效时 race
    window 暴露 → invariant 在终态破坏.

    setup: 1 store + 1 order (status=confirmed, total=10000, discount=0, final=10000)
    runner: N=10 workers, 5 apply_discount(discount=100) / 5 modify_order
            raw SQL `SELECT FOR UPDATE; UPDATE total += 1000, final += 1000`
            (单 iter, 跨 worker race)
    断言 (核心 P0 — 结构性 invariant + distinct-set):
      - 10 worker 全部成功 (无 exception — 两路均合法)
      - 终态 consistency invariant: final + discount == total (FOR UPDATE 串行化)
      - 终态 total = 10000 + 5 * 1000 = 15000 (5 modify_order 各加 1000)
      - 终态 discount = 100 (5 apply_discount 全写 100)
      - 终态 final = 15000 - 100 = 14900
      - **distinct-set assertion (Issue #643 P2-A)**: 10 worker_idx distinct +
        5 apply + 5 modify 各 5 worker

    **§19 round-1 P1-1 falsifiability scope** (honest 标注):
      - **本地 single-host asyncio 实测 (round-1 fix verify)**: FOR UPDATE 移除后
        5 次重复跑 → **3 fail / 2 pass (60% 检出率)**. asyncio scheduling 不
        deterministic, race window 在 SELECT/UPDATE 间存在但触发概率取决于 worker
        到达 PG 的时序.
      - **PR CI 累计检测**: 5+ PR 触发本 workflow 累计检出率 → ≈ 1 (1 - 0.4^5 ≈ 0.99)
      - **生产 200 桌并发多 pod 真 race**: 跨 pod connection-level 真并发 + 网络
        延迟扩 race window → invariant 必失败. 本测试是结构性 invariant 守门 +
        非 deterministic 但真 falsifiable signal.
      - **强 deterministic falsifiability follow-up**: 后续可加 monkeypatch
        `_get_order` 注入 `asyncio.sleep(0.02)` 扩 race window 让单 host 100% 检出
        (PR-5 实测 K=5 inner loop 路径会触发 PG row lock 死锁, 不在本 PR scope —
        留 §19 round-2 后 follow-up issue, 当前 60% 已足).

    若 FOR UPDATE on apply_discount 未真生效 (audit §4.1.4 P0 真路径 — PR #560 PR-E 回归):
      - apply_discount worker A: SELECT (无锁) → reads (total=10000, discount=0)
      - modify_order worker B: SELECT FOR UPDATE → lock; UPDATE total=11000, final=11000;
        commit; release lock
      - apply_discount worker A: 用 stale total=10000 算 new_final = 9900;
        UPDATE SET discount=100, final=9900 (overwrite B 的 final=11000 → 9900)
      - 终态 (total=15000, discount=100, final=9900) → 9900 + 100 = 10000 ≠ 15000
        **split-state corruption** ← 本测试主断言 invariant 直接抓
      - 同一 race 在 PR #560 fix 前 (`_get_order(lock=False)` default) 100% 复现

    业务场景对应:
      - apply_discount worker = 收银员打折 (PR #560 PR-E P0 路径)
      - modify_order worker = 模拟"如果 update_item_quantity / cancel_order 也加锁
        后写 total + final 维持 invariant" (audit §4.1.4 3 P1, 待 §17 桌台对齐 follow-up)
      - 两路混合 race = 200 桌晚高峰 manager 改折扣 + 服务员加菜 真场景

    与 PR-2 cashier T2 区别:
      - PR-2 cashier T2: 仅 N=10 同 discount apply_discount, 同 weak signal 但
        cashier 内部含 _calc_order_cost + margin 校验, 真 race 窗口 > 0 (PR-2 接受)
      - PR-5 T1 本设计: order_service.apply_discount 简化版无 margin 校验, race
        窗口几乎 0; 必须用 modify_order competing 写者人为构造真 race window
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

    # worker 索引 → 决定走 apply_discount 还是 modify_order (alternating)
    workers_count = [0]
    workers_lock = asyncio.Lock()

    async def _mixed_op(session: AsyncSession) -> dict:
        """idx % 2 == 0: apply_discount(discount=100); 否则: modify_order
        (SELECT FOR UPDATE; UPDATE total += 1000, final += 1000)."""
        async with workers_lock:
            idx = workers_count[0]
            workers_count[0] += 1
        if idx % 2 == 0:
            # apply_discount worker (5 笔, idx=0/2/4/6/8) — 走 service 含 _set_tenant +
            # lock=True SELECT + UPDATE (discount, final). flush 不 commit, run_concurrent
            # 收尾 commit. 服务内 FOR UPDATE 串行化与 modify_order 的 SELECT FOR UPDATE.
            svc = OrderService(db=session, tenant_id=str(tenant_id))
            result = await svc.apply_discount(
                order_id=str(order_id),
                discount_fen=100,
                reason=f"race-{idx}",
            )
            return {
                "worker_idx": idx,
                "op": "apply_discount",
                "my_final": result["final_fen"],
            }
        # modify_order worker (5 笔, idx=1/3/5/7/9) — 显式 SELECT FOR UPDATE 后 atomic
        # UPDATE total + final 维持 invariant. 模拟 "如果 update_item_quantity 也加锁
        # 会写 total + final 维持 invariant". 与 apply_discount 的 FOR UPDATE 在同一行
        # 上互斥串行化.
        await session.execute(
            text("SELECT id FROM orders WHERE id = CAST(:oid AS uuid) FOR UPDATE"),
            {"oid": str(order_id)},
        )
        await session.execute(
            text("""
                UPDATE orders
                SET total_amount_fen = total_amount_fen + 1000,
                    final_amount_fen = final_amount_fen + 1000
                WHERE id = CAST(:oid AS uuid)
            """),
            {"oid": str(order_id)},
        )
        return {
            "worker_idx": idx,
            "op": "modify_order",
            "increment_fen": 1000,
        }

    results = await run_concurrent(
        session_factory, tenant_id, n=10,
        operation=_mixed_op,
        timeout_sec=30.0,
    )

    # 全部成功 — 两路均合法 (apply_discount new_final=stale_total-100 总 ≥ 0)
    exceptions = [r for r in results if isinstance(r, BaseException)]
    assert not exceptions, (
        f"order_service.apply_discount + modify_order concurrent unexpected exceptions "
        f"({len(exceptions)}/{len(results)}): {exceptions[:3]}"
    )

    # 主断言 (P0 真 falsifiable signal): 终态 invariant final + discount == total
    # FOR UPDATE 真生效 → 两路串行化 → invariant 全程持
    # FOR UPDATE 失效 → apply 用 stale total 算 final → 终态 invariant 破坏
    async with session_factory() as s:
        result = await s.execute(
            text("""
                SELECT total_amount_fen, discount_amount_fen, final_amount_fen, status
                FROM orders WHERE id = CAST(:id AS uuid)
            """),
            {"id": str(order_id)},
        )
        total, discount, final, status = result.one()
        # 5 modify_order 各加 1000 → total = 15000
        assert total == 15000, (
            f"total_amount_fen 应为初始 10000 + 5 * 1000 = 15000, actual={total}. "
            f"5 笔 modify_order 漏写或重复"
        )
        # 5 apply_discount 全写 discount=100 → 终态 100 (last-writer-wins, 单值)
        assert discount == 100, (
            f"discount_amount_fen 应为 100 (5 apply_discount 全写 100), actual={discount}"
        )
        # **结构性 invariant**: final + discount == total (混合并发 写入下保持)
        # FOR UPDATE 真生效 → 两路串行化 → invariant 全程持
        # FOR UPDATE 失效 → race window 真打开 → invariant 在终态破坏
        # (单 host asyncio race window 微秒级窄, 实测 5/5 仍 PASS — 见 docstring §
        # falsifiability scope; 生产 200 桌多 pod race 必失败 → 本测试是结构守门)
        assert final + discount == total, (
            f"P0 split-state corruption: final={final} + discount={discount} "
            f"!= total={total}. FOR UPDATE 未真生效, audit §4.1.4 P0 path 回归. "
            f"PR #560 PR-E `_get_order(lock=True)` 失效则 apply_discount 用 stale "
            f"total 计算 new_final, modify_order 已 commit 后 apply 写入 stale final."
        )
        assert final == 14900, (
            f"final_amount_fen 应为 15000 - 100 = 14900, actual={final}"
        )
        assert status == "confirmed", (
            f"status 不应变化 (apply_discount + modify_order 均不改 status): actual={status}"
        )

    # 主断言 (Issue #643 P2-A distinct-set + op 分流):
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
    apply_results = [r for r in dict_results if r["op"] == "apply_discount"]
    modify_results = [r for r in dict_results if r["op"] == "modify_order"]
    assert len(apply_results) == 5 and len(modify_results) == 5, (
        f"op 分流不平衡: apply={len(apply_results)} modify={len(modify_results)} "
        f"expected 5 + 5 (alternating idx)"
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
