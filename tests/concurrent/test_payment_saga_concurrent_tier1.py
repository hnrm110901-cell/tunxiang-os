"""PaymentSagaService 真 PG 并发 Tier 1 测试（PR-3 — SKIP LOCKED 真行为验证）

PR-3 of PR #631 proposal §10 6-PR roadmap — PR-2 (PR #638 cashier 框架金标准)
之后第二个业务测试 PR，验证 audit doc §4.1.3 payment_saga 2 P0 路径**真行为**：
PR #553 ship 后这两条路径只有 mock-driven SQL grep（负面 mode），无真 PG race 验证。

  - T1: N=10 concurrent compensate 同 saga → 1 真退款 + 9 幂等 skip / 让出
        （3 状态分支 COMPENSATED / COMPENSATING / FAILED 真行为验证；
         核心断言: 真 gateway.refund 调用次数 = 1，**P0 双退款防护核心**）
  - T2: N=10 concurrent recover_pending_sagas 多 worker → SKIP LOCKED 各拿不同 saga，
        无重处理（核心断言: 处理总数 = N（每 saga 处理 1 次），无 saga stuck 在 pending）

业务场景（真餐厅，audit doc §4.1.3）:
  - S3 失败触发 compensate，同时 POS 重试 + 客户连点 retry → 必须只 refund 1 次（P0 资金）
  - 多 pod / 多 worker 启动 + crash recovery scan 同时跑 → SKIP LOCKED 让 worker 自然分裂
    工作集，不重复处理同 saga 触发 double-refund / double-complete

跑法 (opt-in via INTEGRATION_PG_DSN):

    docker compose -f infra/compose/test-pg.yml up -d
    DATABASE_URL=postgresql://tunxiang_test:test_password_dev_only@localhost:5433/tunxiang_os_test \\
        ./scripts/db-bootstrap.sh --skip-create
    DATABASE_URL=postgresql://tunxiang_test:test_password_dev_only@localhost:5433/tunxiang_os_test \\
        ./scripts/migrate-all.sh --include-legacy
    INTEGRATION_PG_DSN=postgresql://tunxiang_test:test_password_dev_only@localhost:5433/tunxiang_os_test \\
        pytest tests/concurrent/test_payment_saga_concurrent_tier1.py \\
        --confcutdir tests/concurrent --override-ini asyncio_mode=auto -v

未设 INTEGRATION_PG_DSN → 全部 skip (opt-in 模式)。

关联:
  - PR #631 proposal §10 PR-3 (本 PR)
  - PR #634 PR-1 infra (concurrent_runner + conftest + workflow)
  - PR #638 PR-2 cashier 框架金标准 (本 PR 范本)
  - docs/security/tier1-row-lock-audit-2026-05.md §4.1.3 (payment_saga 2 P0 paths)
  - PR #553 6-PR roadmap PR-C (源 fix: compensate FOR UPDATE + 3 幂等 / recover SKIP LOCKED)
  - audit §8.3「正面/负面测试模式」「金标准」milestone (PR-2 落地)

Issue #639 P2-A 应用：扫 v2*/v3*/v4*/v092 找 ALTER TABLE payments / payment_sagas →
  只发现 v092 ADD idempotency_key (payments)，v091 创建 payment_sagas 后无任何 column drift；
  v284 仅 ALTER TABLE payment_sagas ENABLE/FORCE RLS，非 column add。结论: payment_sagas
  schema = v091 原状，本 PR 无 _ensure_post_v206_schema fixture 需要（与 PR-2 cashier
  _ensure_v342_schema 不同），由 PR-2 fixture autouse 兜底已足。
"""
from __future__ import annotations

import asyncio
import os
import sys
import types
import uuid
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

# ── 路径 + namespace 包 (与 PR-2 cashier 同 pattern) ─────────────────────────
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


# ── pytest collection guard (Python 3.10+) ──────────────────────────────────
# payment_saga_service 顶层 import shared.events.UniversalPublisher，shared.events 用
# dataclass(slots=True) 仅 Python 3.10+ 支持。本机 3.9 跑会 TypeError；CI Python 3.11
# 原生通过。用 sys.version_info gate 而非 sys.modules stub（PR-A round-1 教训：stub 注入
# 'shared' 包污染同目录其它 test — feedback_pytest_stub_setdefault_pitfall.md）。
if sys.version_info < (3, 10):
    pytest.skip(
        "需 Python 3.10+ (shared.events 用 dataclass slots=True); CI Python 3.11 跑通",
        allow_module_level=True,
    )

from shared.test_utils.concurrent_runner import run_concurrent  # noqa: E402
from shared.test_utils.integration_pg import requires_integration_pg  # noqa: E402

pytestmark = [requires_integration_pg]


# ── helper: 测试 tenant / store / order / saga 独立 UUID ─────────────────────
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
            "name": f"saga-{uuid.uuid4().hex[:8]}",
            "code": f"SGA-{uuid.uuid4().hex[:12]}",
        },
    )
    return store_id


async def _seed_order(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    store_id: uuid.UUID,
    *,
    status: str = "confirmed",
    final_amount_fen: int = 100,
) -> uuid.UUID:
    """INSERT 1 order, table_number=NULL。"""
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
                :order_no, :status,
                :total, 0, :final,
                NULL, '{}'::jsonb
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
        },
    )
    return order_id


async def _seed_saga(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    order_id: uuid.UUID,
    *,
    step: str,
    payment_id: uuid.UUID | None = None,
    payment_amount_fen: int = 100,
    updated_at_offset_min: int = 0,
) -> uuid.UUID:
    """INSERT 1 payment_saga 行，返回 saga_id。

    Args:
        step: SagaStep 任一 ('paying'/'completing'/'compensating'/'compensated'/'failed'/'done')
        payment_id: payment_id (可为 None — recover_pending_sagas paying 分支 NULL → FAILED)
        updated_at_offset_min: 0 → updated_at=NOW()。负值 → updated_at=NOW()+offset
            (e.g., -10 让 cutoff (now-5min) 满足 updated_at < cutoff，使 saga 进 recovery 范围)
    """
    saga_id = _new_uuid()
    updated_at = datetime.now(timezone.utc) + timedelta(minutes=updated_at_offset_min)
    await session.execute(
        text("""
            INSERT INTO payment_sagas (
                saga_id, tenant_id, order_id, payment_id,
                step, payment_amount_fen, payment_method,
                created_at, updated_at
            )
            VALUES (
                CAST(:saga_id AS uuid), CAST(:tid AS uuid), CAST(:oid AS uuid),
                CAST(:pid AS uuid),
                :step, :amt, :method,
                NOW(), :updated_at
            )
        """),
        {
            "saga_id": str(saga_id),
            "tid": str(tenant_id),
            "oid": str(order_id),
            "pid": str(payment_id) if payment_id else None,
            "step": step,
            "amt": payment_amount_fen,
            "method": "wechat",
            "updated_at": updated_at,
        },
    )
    return saga_id


class _MockGateway:
    """Mock PaymentGateway with thread-safe call counter for refund / create_payment.

    refund: 默认成功 (return None / no exception)
    create_payment: 不应被 compensate / recover 调用; 防御性返回 dict 结构
    并发安全: asyncio.Lock 保护 call_count（单 event-loop 严格不需要，但显式更稳）
    """

    def __init__(self) -> None:
        self.refund_calls: list[dict] = []
        self.create_calls: list[dict] = []
        self._lock = asyncio.Lock()

    async def refund(
        self,
        payment_id: str,
        refund_amount_fen: int,
        reason: str,
        **kwargs,
    ) -> None:
        async with self._lock:
            self.refund_calls.append({
                "payment_id": payment_id,
                "refund_amount_fen": refund_amount_fen,
                "reason": reason,
            })

    async def create_payment(self, **kwargs) -> dict:
        async with self._lock:
            self.create_calls.append(kwargs)
        # defensive — 不应被 compensate/recover 调用
        return {
            "payment_id": str(_new_uuid()),
            "payment_no": f"PNO{uuid.uuid4().hex[:14].upper()}",
        }


@pytest_asyncio.fixture(autouse=True)
async def _silence_publisher(monkeypatch):
    """payment_saga_service 业务用 asyncio.create_task(UniversalPublisher.publish(...))，
    无 Redis 时背景 task 会 fail (Task exception was never retrieved 警告 + 真 socket
    connect timeout 拖慢 N×3s 测试时间). monkeypatch publish 为 no-op classmethod。

    与 PR-2 cashier _silence_emit_event fixture 同模式 (PR-2 §19 P1-B fix 沿用) —
    monkeypatch 是 function-scope，但 service 用 fire-and-forget create_task；teardown
    时若 monkeypatch undo 而 task 仍 pending，后续真 publish 抛 ConnectionRefusedError
    污染 CI。改 async generator + yield + 多轮 asyncio.sleep(0) drain pending tasks
    在 monkeypatch 恢复前完成。
    """
    import shared.events.universal_publisher as pub_module

    async def _noop_publish(cls, *args, **kwargs):  # noqa: ARG001
        return None

    # patch classmethod 到模块级 (cls 参数显式给) — 比 setattr classmethod 更稳
    monkeypatch.setattr(
        pub_module.UniversalPublisher,
        "publish",
        classmethod(_noop_publish),
    )
    yield
    # drain pending fire-and-forget tasks before monkeypatch undo
    for _ in range(5):
        await asyncio.sleep(0)


# ───────────────────────────────────────────────────────────────────
# T1: N=10 concurrent compensate 同 saga — 1 真退款 + 9 幂等
# ───────────────────────────────────────────────────────────────────
async def test_payment_saga_compensate_concurrent_n10_single_refund(session_factory):
    """T1 — 同一 saga 多入口并发 compensate, FOR UPDATE + 3 状态分支幂等防双退款.

    setup: 1 store + 1 order(status=confirmed) + 1 saga(step=COMPLETING, payment_id=valid,
           payment_amount_fen=100) → compensate() 进 FOR UPDATE → 看 step≠COMPENSATED/
           COMPENSATING/FAILED → 调 gateway.refund → 转 COMPENSATED
    runner: N=10 workers 各 service.compensate(saga_id, reason="race-test")
    断言（核心 P0 双退款防护）:
      - gateway.refund 被调用 **正好 1 次**（FOR UPDATE 串行化 + COMPENSATING/COMPENSATED
        幂等检查 → 仅 1 worker 真 refund，9 worker 看到非初始 step 走幂等路径）
      - 真 refund worker 返回 True；其他 worker 返回 True (已 COMPENSATED 幂等) 或
        False (COMPENSATING in-progress / FAILED 让出)
      - 终态 saga.step = COMPENSATED
      - 终态 saga.compensated_at IS NOT NULL（refund 成功后 UPDATE 设置）

    若 FOR UPDATE 未真生效（audit doc §4.1.3 P0 最严重场景）:
      - 10 worker 并发 SELECT step='completing'（无锁串行化）
      - 10 worker 都判 step≠COMPENSATED/COMPENSATING/FAILED → 都走真 refund 分支
      - **gateway.refund 被调用 10 次** → 客户被多扣 9 次款（P0 资金事故）
      - 本测试是 audit doc §4.1.3 P0 最严重路径的真行为守护
    """
    from services.tx_trade.src.services.payment_saga_service import (
        PaymentSagaService,
        SagaStep,
    )

    tenant_id = _new_uuid()
    fake_payment_id = _new_uuid()

    # setup
    async with session_factory() as s:
        store_id = await _seed_store(s, tenant_id)
        order_id = await _seed_order(s, tenant_id, store_id, status="confirmed")
        saga_id = await _seed_saga(
            s, tenant_id, order_id,
            step=SagaStep.COMPLETING,
            payment_id=fake_payment_id,
            payment_amount_fen=100,
        )
        await s.commit()

    # 共享 mock gateway 收所有 worker refund 调用 — 验真 refund 数 = 1
    shared_gateway = _MockGateway()

    async def _compensate(session: AsyncSession) -> bool:
        service = PaymentSagaService(
            db=session,
            tenant_id=tenant_id,
            payment_gateway=shared_gateway,
            order_service=None,
        )
        return await service.compensate(saga_id=saga_id, reason="race-test-double-refund")

    results = await run_concurrent(
        session_factory, tenant_id, n=10,
        operation=_compensate,
        timeout_sec=30.0,
    )

    # 不应有 unexpected exception (业务返回 True/False, 不抛异常)
    exceptions = [r for r in results if isinstance(r, BaseException)]
    assert not exceptions, (
        f"compensate concurrent unexpected exceptions ({len(exceptions)}/{len(results)}): "
        f"{exceptions[:3]}"
    )

    # 主断言 (P0 双退款防护核心): gateway.refund 被调用正好 1 次
    refund_count = len(shared_gateway.refund_calls)
    assert refund_count == 1, (
        f"P0 双退款泄漏: gateway.refund 调用次数 {refund_count} ≠ 1. "
        f"FOR UPDATE 未真生效或 3 状态幂等检查 (COMPENSATED/COMPENSATING/FAILED) 回归. "
        f"audit doc §4.1.3 P0 最严重场景 — 客户多扣 {refund_count - 1} 次款. "
        f"refund_calls={shared_gateway.refund_calls!r}"
    )

    # 终态: saga.step = COMPENSATED + compensated_at NOT NULL
    async with session_factory() as s:
        result = await s.execute(
            text("""
                SELECT step, compensated_at, payment_id
                FROM payment_sagas WHERE saga_id = CAST(:sid AS uuid)
            """),
            {"sid": str(saga_id)},
        )
        row = result.one()
        step, compensated_at, pid = row[0], row[1], row[2]
        assert step == SagaStep.COMPENSATED, (
            f"saga.step 终态应为 COMPENSATED: actual={step} expected={SagaStep.COMPENSATED}"
        )
        assert compensated_at is not None, (
            "saga.compensated_at 应在 refund 成功后被 UPDATE: actual=NULL"
        )
        assert str(pid) == str(fake_payment_id), (
            f"saga.payment_id 不应变化: actual={pid} expected={fake_payment_id}"
        )

    # 辅助分流诊断 (不硬断言数, 只验语义): True/False 都是合法的幂等返回
    true_count = sum(1 for r in results if r is True)
    false_count = sum(1 for r in results if r is False)
    assert true_count + false_count == 10, (
        f"compensate 应返回 bool 类型, 实际 True={true_count} False={false_count} "
        f"others={[r for r in results if r is not True and r is not False][:3]}"
    )
    # 至少 1 worker True (真 refund 那个返回 True; 已 COMPENSATED 幂等也返回 True)
    assert true_count >= 1, (
        f"至少 1 worker 应返回 True (真 refund worker): actual True={true_count}"
    )


# ───────────────────────────────────────────────────────────────────
# T2: N=10 concurrent recover_pending_sagas — SKIP LOCKED 各 worker 自然分裂
# ───────────────────────────────────────────────────────────────────
async def test_payment_saga_recover_concurrent_n10_skip_locked_no_double(session_factory):
    """T2 — 多 worker 启动 + crash recovery scan 同时跑, FOR UPDATE SKIP LOCKED 真生效.

    setup: 1 store + N=10 orders(status=confirmed) + N=10 sagas(step=COMPLETING,
           payment_id=fake, updated_at = now - 10min < cutoff 5min). 每 saga 关联独立
           order，让 _complete_order 真跑 UPDATE orders SET status='completed'。
    runner: N=10 workers 各 service.recover_pending_sagas() 并发跑
    断言（核心 P0 SKIP LOCKED 真行为）:
      - 跨所有 worker 的 recovered count 总和 == N=10（每 saga 处理 1 次, 不重复）
      - gateway.refund 调用次数 == 0（_complete_order 成功 → 走 DONE 分支，无 refund 路径）
      - 终态: 10 sagas 全部 step='done'（_update_step DONE 转换）
      - 终态: 10 orders 全部 status='completed'（_complete_order UPDATE 触发）
      - 无 saga stuck 在 'paying'/'completing' 终态（recovery 全收尾）

    若 SKIP LOCKED 未真生效（audit doc §4.1.3 P0 第二严重场景）:
      - 多 worker SELECT 拿到同 saga 行（无锁互斥）
      - 多 worker 同时调 _complete_order → UPDATE orders (idempotent，但浪费工作)
      - sum(recovered) > 10（saga 被处理多次）
      - **更危险**: 若 saga 在 paying 状态需 compensate (本场景不触发, T1 已覆盖),
        多 worker 调 compensate → 多次 refund (与 T1 同 P0)
      - 本 T2 主验 SKIP LOCKED 总数 invariant；T1 主验 FOR UPDATE refund 单次

    与 T1 互补:
      - T1: 同 saga 多 compensate 入口 → FOR UPDATE + 3 状态幂等 → refund 单次
      - T2: 多 saga 多 worker scan → SKIP LOCKED → 各 saga 处理单次 (worker 自然分裂)
    """
    from services.tx_trade.src.services.payment_saga_service import (
        PaymentSagaService,
        SagaStep,
    )

    tenant_id = _new_uuid()
    n_sagas = 10

    # setup: 10 sagas + 10 orders, updated_at < cutoff (now - 5min) → 全部进 recovery
    saga_ids: list[uuid.UUID] = []
    order_ids: list[uuid.UUID] = []
    async with session_factory() as s:
        store_id = await _seed_store(s, tenant_id)
        for _ in range(n_sagas):
            order_id = await _seed_order(s, tenant_id, store_id, status="confirmed")
            saga_id = await _seed_saga(
                s, tenant_id, order_id,
                step=SagaStep.COMPLETING,
                payment_id=_new_uuid(),
                payment_amount_fen=100,
                updated_at_offset_min=-10,  # 10 min ago, < 5min cutoff
            )
            order_ids.append(order_id)
            saga_ids.append(saga_id)
        await s.commit()

    shared_gateway = _MockGateway()

    async def _recover(session: AsyncSession) -> int:
        service = PaymentSagaService(
            db=session,
            tenant_id=tenant_id,
            payment_gateway=shared_gateway,
            order_service=None,
        )
        return await service.recover_pending_sagas()

    results = await run_concurrent(
        session_factory, tenant_id, n=10,
        operation=_recover,
        timeout_sec=60.0,
    )

    # 不应有 unexpected exception
    exceptions = [r for r in results if isinstance(r, BaseException)]
    assert not exceptions, (
        f"recover_pending_sagas concurrent unexpected exceptions "
        f"({len(exceptions)}/{len(results)}): {exceptions[:3]}"
    )

    # 主断言 (SKIP LOCKED invariant): 跨 worker 处理总数 = N (每 saga 处理 1 次)
    counts = [r for r in results if isinstance(r, int)]
    total_recovered = sum(counts)
    assert total_recovered == n_sagas, (
        f"SKIP LOCKED 失效 P0: 跨 worker 处理总数 {total_recovered} ≠ N={n_sagas}. "
        f"未生效则 saga 被多 worker 重复处理 → 触发 double-complete (本场景) 或 "
        f"double-refund (paying+payment_id 场景, 由 T1 守护). "
        f"per-worker counts: {sorted(counts)}"
    )

    # 主断言 (无重 refund): _complete_order 全成功 → refund 路径未触发
    refund_count = len(shared_gateway.refund_calls)
    assert refund_count == 0, (
        f"COMPLETING + payment_id valid 路径不应触发 refund: "
        f"refund_calls={refund_count} expected=0. "
        f"refund_calls_detail={shared_gateway.refund_calls[:3]}"
    )

    # 终态: 10 sagas 全部 step='done'
    async with session_factory() as s:
        result = await s.execute(
            text("""
                SELECT step, COUNT(*) FROM payment_sagas
                WHERE tenant_id = CAST(:tid AS uuid)
                GROUP BY step ORDER BY step
            """),
            {"tid": str(tenant_id)},
        )
        rows = result.all()
        step_counts = {r[0]: r[1] for r in rows}
        assert step_counts == {SagaStep.DONE: n_sagas}, (
            f"终态 saga.step 分布异常: actual={step_counts!r} "
            f"expected={{'done': {n_sagas}}} "
            f"(SKIP LOCKED + _complete_order 成功 → 全转 DONE, 无 stuck pending)"
        )

        # 终态: 10 orders 全部 status='completed'
        result = await s.execute(
            text("""
                SELECT status, COUNT(*) FROM orders
                WHERE tenant_id = CAST(:tid AS uuid)
                GROUP BY status ORDER BY status
            """),
            {"tid": str(tenant_id)},
        )
        rows = result.all()
        order_status_counts = {r[0]: r[1] for r in rows}
        assert order_status_counts == {"completed": n_sagas}, (
            f"终态 orders.status 分布异常: actual={order_status_counts!r} "
            f"expected={{'completed': {n_sagas}}} "
            f"(_complete_order 成功 UPDATE 全 confirmed → completed)"
        )
