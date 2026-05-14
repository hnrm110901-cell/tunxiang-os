"""inventory_io + auto_deduction 真 PG 并发 Tier 1 测试 (PR-4 — ADR 0002 ABBA 真行为)

PR-4 of PR #631 proposal §10 6-PR roadmap — PR-3 (PR #642 payment_saga) 之后第三个
业务测试 PR，验证 audit doc §4.3 inventory_io + auto_deduction 2 P0 路径**真行为**:

  - T1: N=10 concurrent receive_stock 同 ingredient → FOR UPDATE 串行化 + 无 lost
        update（PR #547 PR-B ship 后 mock-only，本测试是真 PG race 验证）
        **应用 Issue #643 P2-A distinct-set assertion**: workers 返回 transaction_id,
        断言 set_size = N + sum_count = N（每 worker 处理 1 次，无 lost work）

  - T2: N=10 concurrent deduct_for_order **跨 dish ABBA 死锁防护真行为**（ADR 0002
        / Issue #549 / audit §4.3 P0）— 2 dishes 共享 2 ingredients 且 BOM 内顺序
        REVERSED，N workers alternating dish 触发 deadlock 风险；sorted(key=str)
        预聚合锁排序保证一致性 → 无 PostgresDeadlockDetected。

业务场景（真餐厅，audit doc §4.3）:
  - T1: 多 POS 重复扫到货 + 采购员补录入库 race → 必须串行写 current_quantity
       （毛利底线硬约束 — 加权平均单价错算会侵蚀毛利）
  - T2: 200 桌晚高峰 N 单同时完成 → 多 dish 共享 ingredient（如葱姜蒜跨菜系）→
       订单 A=[红烧鱼, 宫保鸡丁] vs B=[宫保鸡丁, 红烧鱼] ABBA → ADR 0002 sorted()
       防死锁；任一锁顺序不一致都会有 worker 被 PG deadlock detector 杀掉 → 库存
       数据丢失 + 订单 settle 失败级联

跑法 (opt-in via INTEGRATION_PG_DSN):

    docker compose -f infra/compose/test-pg.yml up -d
    DATABASE_URL=postgresql://tunxiang_test:test_password_dev_only@localhost:5433/tunxiang_os_test \\
        ./scripts/db-bootstrap.sh --skip-create
    DATABASE_URL=postgresql://tunxiang_test:test_password_dev_only@localhost:5433/tunxiang_os_test \\
        ./scripts/migrate-all.sh --include-legacy
    INTEGRATION_PG_DSN=postgresql://tunxiang_test:test_password_dev_only@localhost:5433/tunxiang_os_test \\
        pytest tests/concurrent/test_inventory_concurrent_tier1.py \\
        --confcutdir tests/concurrent --override-ini asyncio_mode=auto -v

未设 INTEGRATION_PG_DSN → 全部 skip (opt-in 模式)。

关联:
  - PR #631 proposal §10 PR-4 (本 PR)
  - PR #634 PR-1 / #638 PR-2 / #642 PR-3
  - docs/security/tier1-row-lock-audit-2026-05.md §4.3 (inventory + auto_deduction)
  - docs/adr/0002-cross-dish-row-lock-abba.md (跨 dish 锁排序 ABBA 防护)
  - PR #547 PR-B (源 fix: receive/issue/adjust + auto_deduction sorted())
  - PR #567 (deduct_for_order 跨 dish 锁排序实施)
  - Issue #549 (跨 dish ABBA follow-up — architect default 1A/2A/3B)
  - Issue #643 P2-A 应用：distinct-set assertion 升级模板（T1 worker 返回 tx_id）

Issue #643 P2-A pattern 应用：本 PR 首次实战 worker 返回 (count, ids) tuple +
test 断言 distinct-set。后续 PR-5 全部参照本模板。
"""
from __future__ import annotations

import asyncio
import os
import sys
import types
import uuid
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

# ── 路径 + namespace 包 (与 PR-2/3 同 pattern) ──────────────────────────────
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
TX_SUPPLY_DIR = os.path.join(ROOT, "services", "tx-supply")
TX_SUPPLY_SRC = os.path.join(TX_SUPPLY_DIR, "src")
for p in [ROOT, TX_SUPPLY_SRC]:
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


_ensure_ns("services.tx_supply", TX_SUPPLY_DIR)
_ensure_ns("services.tx_supply.src", TX_SUPPLY_SRC)
for _sub in ("api", "models", "services", "repositories", "routers"):
    _sub_path = os.path.join(TX_SUPPLY_SRC, _sub)
    if os.path.isdir(_sub_path):
        _ensure_ns(f"services.tx_supply.src.{_sub}", _sub_path)


# ── pytest collection guard (Python 3.10+) ──────────────────────────────────
# auto_deduction / inventory_io 顶层 import shared.ontology.src.entities + enums，
# shared 内 dataclass(slots=True) 仅 Python 3.10+ 支持。本机 3.9 跑会 TypeError;
# CI Python 3.11 原生通过. 用 sys.version_info gate 而非 sys.modules stub
# (PR-A round-1 教训 — feedback_pytest_stub_setdefault_pitfall.md).
if sys.version_info < (3, 10):
    pytest.skip(
        "需 Python 3.10+ (shared.* 用 dataclass slots=True); CI Python 3.11 跑通",
        allow_module_level=True,
    )

from shared.test_utils.concurrent_runner import run_concurrent  # noqa: E402
from shared.test_utils.integration_pg import requires_integration_pg  # noqa: E402

pytestmark = [requires_integration_pg]


# ── helper: seed store / ingredient / dish / dish_ingredient ────────────────
def _new_uuid() -> uuid.UUID:
    return uuid.uuid4()


async def _seed_store(session: AsyncSession, tenant_id: uuid.UUID) -> uuid.UUID:
    """INSERT 1 store, 返回 store_id."""
    store_id = _new_uuid()
    await session.execute(
        text("""
            INSERT INTO stores (id, tenant_id, store_name, store_code)
            VALUES (CAST(:id AS uuid), CAST(:tid AS uuid), :name, :code)
        """),
        {
            "id": str(store_id),
            "tid": str(tenant_id),
            "name": f"inv-{uuid.uuid4().hex[:8]}",
            "code": f"INV-{uuid.uuid4().hex[:12]}",
        },
    )
    return store_id


async def _seed_ingredient(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    store_id: uuid.UUID,
    *,
    current_quantity: float = 0.0,
    min_quantity: float = 10.0,
    unit_price_fen: int = 100,
    name: str | None = None,
) -> uuid.UUID:
    """INSERT 1 ingredient, 返回 ingredient_id.

    最小列: id/tenant_id/store_id/ingredient_name/unit/current_quantity/min_quantity/
    unit_price_fen/status. 其他 nullable 默认.
    """
    ingredient_id = _new_uuid()
    await session.execute(
        text("""
            INSERT INTO ingredients (
                id, tenant_id, store_id, ingredient_name, unit,
                current_quantity, min_quantity, unit_price_fen, status
            )
            VALUES (
                CAST(:id AS uuid), CAST(:tid AS uuid), CAST(:sid AS uuid),
                :name, :unit, :curr, :minq, :price, :status
            )
        """),
        {
            "id": str(ingredient_id),
            "tid": str(tenant_id),
            "sid": str(store_id),
            "name": name or f"ing-{uuid.uuid4().hex[:6]}",
            "unit": "kg",
            "curr": current_quantity,
            "minq": min_quantity,
            "price": unit_price_fen,
            "status": "normal",
        },
    )
    return ingredient_id


async def _seed_dish(session: AsyncSession, tenant_id: uuid.UUID) -> uuid.UUID:
    """INSERT 1 dish, 返回 dish_id. category_id NULL (FK nullable)."""
    dish_id = _new_uuid()
    await session.execute(
        text("""
            INSERT INTO dishes (id, tenant_id, dish_name, dish_code, price_fen)
            VALUES (
                CAST(:id AS uuid), CAST(:tid AS uuid),
                :name, :code, :price
            )
        """),
        {
            "id": str(dish_id),
            "tid": str(tenant_id),
            "name": f"dish-{uuid.uuid4().hex[:6]}",
            "code": f"DSH-{uuid.uuid4().hex[:12]}",
            "price": 1000,
        },
    )
    return dish_id


async def _seed_dish_ingredient(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    dish_id: uuid.UUID,
    ingredient_id: uuid.UUID,
    *,
    quantity: float = 1.0,
    unit: str = "kg",
) -> uuid.UUID:
    """INSERT 1 dish_ingredient row (BOM line).

    注意: dish_ingredients.ingredient_id 是 String(50) 不是 UUID FK (v001 schema).
    auto_deduction.py 内部 uuid.UUID(ing_id) 转换. 测试存 str(uuid) 兼容.
    """
    di_id = _new_uuid()
    await session.execute(
        text("""
            INSERT INTO dish_ingredients (
                id, tenant_id, dish_id, ingredient_id, quantity, unit
            )
            VALUES (
                CAST(:id AS uuid), CAST(:tid AS uuid), CAST(:did AS uuid),
                :iid, :qty, :unit
            )
        """),
        {
            "id": str(di_id),
            "tid": str(tenant_id),
            "did": str(dish_id),
            "iid": str(ingredient_id),  # String(50) 兼容
            "qty": quantity,
            "unit": unit,
        },
    )
    return di_id


@pytest_asyncio.fixture(autouse=True)
async def _silence_doc_number(monkeypatch):
    """inventory_io.receive_stock 调 gen_doc_number(...) 生成可读单号. 测试环境无
    sequence_states/doc_number 基建 → 抛 DocNumberError → 业务 fail-open log warn
    + UPDATE 跳过 (L143 except DocNumberError + L188 if doc_number is not None).
    本 fixture 显式 monkeypatch gen_doc_number 抛 DocNumberError (而非依赖真实
    异常路径), 让测试干净不依赖 doc_number infra; 与业务 graceful degradation
    模式一致 (feedback_graceful_degradation_pattern.md).

    monkeypatch target: inventory_io 模块内部 import 的 gen_doc_number ref
    (`from ..utils.doc_number import gen_doc_number, DocNumberError`).
    """
    try:
        import services.tx_supply.src.services.inventory_io as inv_module

        async def _raise_doc_number_error(*args, **kwargs):
            raise inv_module.DocNumberError("test env: doc_number disabled")

        monkeypatch.setattr(inv_module, "gen_doc_number", _raise_doc_number_error)
    except (ImportError, AttributeError):
        # inventory_io 内部结构变化 / DocNumberError 不在该路径 → 测试不强依赖,
        # 真 gen_doc_number 也会 fail-open (sequence_states 表不存在), 影响 0
        pass
    yield


# ───────────────────────────────────────────────────────────────────
# T1: N=10 concurrent receive_stock 同 ingredient — FOR UPDATE 真生效 + distinct-set
# ───────────────────────────────────────────────────────────────────
async def test_inventory_receive_stock_concurrent_n10_no_lost_update(session_factory):
    """T1 — 多 POS 重复扫到货 + 采购员补录入库 race, FOR UPDATE 真串行化无 lost update.

    setup: 1 store + 1 ingredient (current_quantity=0, min_quantity=10, unit_price_fen=100)
    runner: N=10 workers 各 receive_stock(quantity=10, unit_cost_fen=100, batch_no=...)
    断言（核心 P0 + Issue #643 P2-A distinct-set 升级版）:
      - 10 worker 全部成功（无 exception — FOR UPDATE 串行化）
      - ingredient.current_quantity = 100 (10 × 10) — FOR UPDATE 真生效, 无 lost update
      - ingredient_transactions count = 10 (每 worker 创建 1 笔 purchase tx)
      - **distinct-set assertion (Issue #643 P2-A 升级)**: workers 返回 transaction_id,
        `set(tx_ids) == 10 distinct UUIDs` (无 lost work, 无重复 tx ID)
      - 加权平均 unit_price_fen = 100 (所有 worker 同 unit_cost_fen=100, 平均不变)

    若 FOR UPDATE 未真生效（audit doc §4.3 P0 — PR #547 PR-B fix 回归）:
      - 10 worker 并发 SELECT current_quantity=0 (无锁串行化)
      - 各算 new_quantity = 0 + 10 = 10, 各写 current_quantity=10
      - 终态 current_quantity=10 (lost update 9 笔 = 90 单位库存丢失)
      - **毛利底线硬约束**: 加权平均单价错算 → 财务对账失败 → 不能下采购单
    """
    from services.tx_supply.src.services.inventory_io import receive_stock

    tenant_id = _new_uuid()

    # setup
    async with session_factory() as s:
        store_id = await _seed_store(s, tenant_id)
        ingredient_id = await _seed_ingredient(
            s, tenant_id, store_id,
            current_quantity=0.0,
            min_quantity=10.0,
            unit_price_fen=100,
        )
        await s.commit()

    async def _receive(session: AsyncSession) -> tuple[str, float]:
        """单 worker receive_stock + 返回 (tx_id, new_quantity) tuple.

        §19 PR-4 P1-1 fix: distinct-set tx_id 仅是 uuid4 现场生成，FOR UPDATE 失效
        也不会触发. 改返回 new_quantity 形成 [10, 20, ..., 100] 严格递增序列断言 —
        FOR UPDATE 真生效则各 worker quantity_after 互异且累加; lost update 则会出现
        重复值 (e.g., 多 worker 看到 qty_before=0 都写 10).
        """
        result = await receive_stock(
            ingredient_id=str(ingredient_id),
            quantity=10.0,
            unit_cost_fen=100,
            batch_no=f"B-{uuid.uuid4().hex[:6]}",
            expiry_date=None,
            store_id=str(store_id),
            tenant_id=str(tenant_id),
            db=session,
        )
        return (result["transaction_id"], result["new_quantity"])

    results = await run_concurrent(
        session_factory, tenant_id, n=10,
        operation=_receive,
        timeout_sec=30.0,
    )

    # 全部成功
    exceptions = [r for r in results if isinstance(r, BaseException)]
    assert not exceptions, (
        f"receive_stock concurrent unexpected exceptions ({len(exceptions)}/{len(results)}): "
        f"{exceptions[:3]}"
    )

    # 主断言 (P0 lost update 防护核心): current_quantity = 100, 无 lost update
    async with session_factory() as s:
        result = await s.execute(
            text("""
                SELECT current_quantity, unit_price_fen, status
                FROM ingredients WHERE id = CAST(:id AS uuid)
            """),
            {"id": str(ingredient_id)},
        )
        row = result.one()
        current_qty, unit_price, status = row[0], row[1], row[2]
        assert abs(current_qty - 100.0) < 1e-6, (
            f"P0 lost update 检测: current_quantity actual={current_qty} expected=100.0 "
            f"(10 workers × 10.0 each). FOR UPDATE 未真生效, audit §4.3 PR-B (#547) "
            f"path 回归 — 毛利底线硬约束失败"
        )
        # 加权平均: 所有 worker 同 unit_cost=100 → 平均仍是 100 (基础 unit_price=100, 所有
        # 入库都 100, 加权平均不变 = 100)
        assert unit_price == 100, (
            f"加权平均 unit_price_fen actual={unit_price} expected=100 "
            f"(所有 worker unit_cost=100 一致, 加权平均不变)"
        )
        # status: current=100 > min=10 → normal
        assert status == "normal", f"status actual={status} expected=normal"

        # 主断言 (transaction count): 10 笔 purchase tx 落库
        result = await s.execute(
            text("""
                SELECT COUNT(*), COALESCE(SUM(quantity), 0)
                FROM ingredient_transactions
                WHERE ingredient_id = CAST(:iid AS uuid)
                  AND transaction_type = 'purchase'
            """),
            {"iid": str(ingredient_id)},
        )
        count, total_qty = result.one()
        assert count == 10, (
            f"ingredient_transactions count actual={count} expected=10 "
            f"(每 worker 1 笔 purchase)"
        )
        assert abs(total_qty - 100.0) < 1e-6, (
            f"transactions sum quantity actual={total_qty} expected=100.0"
        )

    # 主断言 (Issue #643 P2-A 升级 — §19 PR-4 P1-1 fix):
    # worker 返回 (tx_id, new_quantity) 严格递增序列. FOR UPDATE 串行化下各 worker
    # quantity_after 互异 (10, 20, 30, ..., 100); lost update 时序列会重复或缺值.
    # 这才是真有 BUG-detection signal 的断言 (P2-A 模板正解).
    pairs = [r for r in results if isinstance(r, tuple)]
    assert len(pairs) == 10, (
        f"worker 返回 (tx_id, new_quantity) tuple 数 actual={len(pairs)} expected=10. "
        f"non-tuple results: {[r for r in results if not isinstance(r, tuple)][:3]}"
    )
    tx_ids = [p[0] for p in pairs]
    new_qtys = sorted(p[1] for p in pairs)
    expected_qtys = [10.0 * (i + 1) for i in range(10)]  # [10, 20, ..., 100]
    assert new_qtys == expected_qtys, (
        f"Issue #643 P2-A FOR UPDATE 串行化真生效断言失败: "
        f"sorted(quantity_after) actual={new_qtys} expected={expected_qtys}. "
        f"FOR UPDATE 真生效 → 10 worker 各自看到不同 qty_before (0/10/20/.../90), "
        f"写入 qty_after (10/20/30/.../100). lost update 时多 worker 看到 qty_before=0 "
        f"都写 qty_after=10, 序列会出现重复值 (e.g., [10,10,...,10] 或 [10,20,20,...])"
    )
    # 辅助断言: tx_ids 仍 distinct (uuid4 现场生成 ~0 概率撞), 留作 sanity check
    assert len(set(tx_ids)) == 10, f"tx_ids 重复 (uuid4 撞概率应 ~0): {tx_ids}"


# ───────────────────────────────────────────────────────────────────
# T2: N=10 concurrent deduct_for_dish — ADR 0002 within-dish ABBA 死锁防护真行为
# ───────────────────────────────────────────────────────────────────
async def test_inventory_deduct_for_dish_within_dish_abba_no_deadlock(
    session_factory, monkeypatch,
):
    """T2 — single dish 多 ingredient BOM 反向序, deduct_for_dish L131 sort 真生效.

    §19 PR-4 P0-1 fix: 原设计调 deduct_for_order 跨 dish 不能真触发 ABBA, 因为:
      (a) Python set[uuid.UUID] 迭代顺序 hash-deterministic 跨 worker 一致, 即使
          源 L284 sorted 移除也不会 ABBA;
      (b) deduct_for_order 用 db.begin_nested() savepoint, L284 预聚合已锁齐所有
          ingredient, 后续 deduct_for_dish 内部 SELECT FOR UPDATE 是同事务 reentrant
          不再申请新锁, 即使源 L131 sorted 移除也不会 ABBA.

    新设计: 直接调 deduct_for_dish (绕过 deduct_for_order 预聚合), monkeypatch
    `_get_bom_for_dish` 返回**显式控制**的 BOM 顺序 (D1=[A,B] / D2=[B,A]),
    保证 worker 看到的 BOM 顺序差异. 这才能真测试 L131 内部 sort:

    setup: 1 store + 2 ingredients (ing_a, ing_b, current_quantity=1000 each, min=10)
           + 2 dishes (D1, D2) (无 dish_ingredients 行, BOM 由 monkeypatch 提供)
           + monkeypatch _get_bom_for_dish:
             - D1 → [{ingredient_id: ing_a, qty: 1.0}, {ingredient_id: ing_b, qty: 1.0}]
             - D2 → [{ingredient_id: ing_b, qty: 1.0}, {ingredient_id: ing_a, qty: 1.0}]
    runner: N=10 workers, 偶数 worker → deduct_for_dish(d1) / 奇数 → deduct_for_dish(d2)
    断言（核心 ADR 0002 ABBA 防护真行为, audit §4.3 P0 Issue #549）:
      - 10 worker 全部成功 — L131 `sorted_bom_lines.sort(key=lambda x: str(x[ingredient_id]))`
        真生效, 所有 worker 都按 str(uuid) 升序锁 ing → 无 ABBA
      - ing_a.current_quantity = 990 (1000 - 10 workers × 1.0)
      - ing_b.current_quantity = 990
      - ingredient_transactions consume count = 20 (10 worker × 2 BOM lines/dish)
      - **distinct-set assertion**: 10 worker 各独立 worker_idx, sum_deducted = 20

    若 L131 sort 未生效（ADR 0002 / PR #547 PR-B 回归）:
      - D1 worker (idx 偶): sorted_bom_lines = [A, B] (按 monkeypatch 输入序), 锁 A 后等 B
      - D2 worker (idx 奇): sorted_bom_lines = [B, A] (按 monkeypatch 输入序), 锁 B 后等 A
      - PG deadlock detector 触发 → 一方 raise DeadlockDetected
      - **食安/毛利硬约束**: 200 桌晚高峰跨菜系共享 ingredient (葱姜蒜) 死锁 →
        出餐失败 → 订单 settle 失败级联

    与 T1 互补:
      - T1: 同 ingredient 多 receive_stock → FOR UPDATE 防 lost update (单点锁)
      - T2: 同 dish 多 ingredient 反向序 → L131 sort 防 ABBA (多点锁排序)
    """
    import services.tx_supply.src.services.auto_deduction as auto_dedup_module
    from services.tx_supply.src.services.auto_deduction import deduct_for_dish

    tenant_id = _new_uuid()

    # setup: 2 ingredients + 2 dishes (BOM 由 monkeypatch 提供, 不存 dish_ingredients)
    async with session_factory() as s:
        store_id = await _seed_store(s, tenant_id)
        ing_a = await _seed_ingredient(
            s, tenant_id, store_id,
            current_quantity=1000.0, min_quantity=10.0, name="ing-a-abba",
        )
        ing_b = await _seed_ingredient(
            s, tenant_id, store_id,
            current_quantity=1000.0, min_quantity=10.0, name="ing-b-abba",
        )
        d1 = await _seed_dish(s, tenant_id)
        d2 = await _seed_dish(s, tenant_id)
        await s.commit()

    # monkeypatch _get_bom_for_dish — D1/D2 BOM 反向序
    # 源 _get_bom_for_dish 返回 list[dict[str, Any]] with keys {ingredient_id, quantity, unit}
    # ingredient_id 类型: source 用 row.ingredient_id (String(50)) 直接返回 str.
    # auto_deduction.deduct_for_dish L122-130 build sorted_bom_lines, L131 sort by str(ing_id).
    bom_d1 = [
        {"ingredient_id": str(ing_a), "quantity": 1.0, "unit": "kg"},
        {"ingredient_id": str(ing_b), "quantity": 1.0, "unit": "kg"},
    ]
    bom_d2 = [
        {"ingredient_id": str(ing_b), "quantity": 1.0, "unit": "kg"},  # REVERSED — 触发 ABBA
        {"ingredient_id": str(ing_a), "quantity": 1.0, "unit": "kg"},
    ]

    async def _mock_get_bom(db, dish_uuid, tenant_uuid):  # noqa: ARG001
        if dish_uuid == d1:
            return bom_d1
        if dish_uuid == d2:
            return bom_d2
        return []

    monkeypatch.setattr(auto_dedup_module, "_get_bom_for_dish", _mock_get_bom)

    # worker 索引 → 决定用 D1 还是 D2 (alternating)
    workers_count = [0]
    workers_lock = asyncio.Lock()

    async def _deduct(session: AsyncSession) -> dict[str, Any]:
        """单 worker deduct_for_dish, 偶数 → D1 / 奇数 → D2 (反向序 BOM)."""
        async with workers_lock:
            idx = workers_count[0]
            workers_count[0] += 1
        dish_id = d1 if idx % 2 == 0 else d2
        result = await deduct_for_dish(
            dish_id=str(dish_id),
            quantity=1,
            store_id=str(store_id),
            tenant_id=str(tenant_id),
            db=session,
        )
        return {
            "worker_idx": idx,
            "dish_id": str(dish_id),
            "deducted_count": len(result.get("deducted", [])),
            "missing_bom": result.get("missing_bom", False),
            "insufficient_count": len(result.get("insufficient_stock", [])),
        }

    results = await run_concurrent(
        session_factory, tenant_id, n=10,
        operation=_deduct,
        timeout_sec=60.0,  # ABBA deadlock detection 需更长 timeout 兜底
    )

    # 主断言 (P0 ABBA 防护核心): 全 worker 成功, 无 DeadlockDetected
    exceptions = [r for r in results if isinstance(r, BaseException)]
    assert not exceptions, (
        f"P0 ABBA 死锁泄漏: deduct_for_dish concurrent unexpected exceptions "
        f"({len(exceptions)}/{len(results)}): {exceptions[:3]!r}. "
        f"ADR 0002 / L131 sorted_bom_lines.sort(key=str) 未生效, audit §4.3 P0 "
        f"Issue #549 回归. PostgresDeadlockDetected 表明 D1 worker (BOM=[A,B]) 锁 A 后等 B "
        f"+ D2 worker (BOM=[B,A]) 锁 B 后等 A 触发 ABBA"
    )

    # 主断言 (库存正确扣减 — sorted() 后 worker 顺序入锁 + 串行 commit): ing_a / ing_b 各 -10
    async with session_factory() as s:
        result = await s.execute(
            text("""
                SELECT id, current_quantity FROM ingredients
                WHERE id IN (CAST(:a AS uuid), CAST(:b AS uuid))
                ORDER BY ingredient_name
            """),
            {"a": str(ing_a), "b": str(ing_b)},
        )
        rows = result.all()
        qty_map = {str(row[0]): row[1] for row in rows}
        assert abs(qty_map[str(ing_a)] - 990.0) < 1e-6, (
            f"ing_a current_quantity actual={qty_map.get(str(ing_a))} expected=990.0 "
            f"(1000 - 10 workers × 1.0). 若 < 990 表明 worker fail / lost update; "
            f"若 > 990 表明 worker 未真扣减"
        )
        assert abs(qty_map[str(ing_b)] - 990.0) < 1e-6, (
            f"ing_b current_quantity actual={qty_map.get(str(ing_b))} expected=990.0"
        )

        # 主断言 (consumption tx 全落库): ingredient_transactions count = 20 (10 worker × 2)
        result = await s.execute(
            text("""
                SELECT COUNT(*), COALESCE(SUM(ABS(quantity)), 0)
                FROM ingredient_transactions
                WHERE ingredient_id IN (CAST(:a AS uuid), CAST(:b AS uuid))
                  AND transaction_type = 'consume'
            """),
            {"a": str(ing_a), "b": str(ing_b)},
        )
        count, total_consumed = result.one()
        assert count == 20, (
            f"ingredient_transactions consume count actual={count} expected=20 "
            f"(10 worker × 2 ingredients per dish)"
        )
        assert abs(total_consumed - 20.0) < 1e-6, (
            f"transactions abs(quantity) sum actual={total_consumed} expected=20.0"
        )

    # 主断言 (Issue #643 P2-A distinct-set — worker_idx 维度):
    # 10 worker 各独立 idx, sum deducted = 20 (10 × 2 BOM lines/dish), 无 missing/insufficient
    deducted_results = [r for r in results if isinstance(r, dict)]
    assert len(deducted_results) == 10, (
        f"deduct_for_dish 应返回 dict, actual {len(deducted_results)}/10"
    )
    distinct_indices = {r["worker_idx"] for r in deducted_results}
    assert len(distinct_indices) == 10, (
        f"Issue #643 P2-A: distinct worker_idx actual={len(distinct_indices)} expected=10. "
        f"重复 idx 表明 workers_lock 串行化 fail"
    )
    total_deducted = sum(r["deducted_count"] for r in deducted_results)
    assert total_deducted == 20, (
        f"sum deducted_count actual={total_deducted} expected=20 (10 worker × 2 BOM lines/dish). "
        f"若 < 20 表明 BOM 加载不全; 若 > 20 表明重复扣减"
    )
    missing_count = sum(1 for r in deducted_results if r["missing_bom"])
    assert missing_count == 0, (
        f"missing_bom 应为 0 (monkeypatch _get_bom_for_dish 总返回非空 BOM): "
        f"actual {missing_count}/10 missing"
    )
    total_insufficient = sum(r["insufficient_count"] for r in deducted_results)
    assert total_insufficient == 0, (
        f"insufficient_stock 应为 0 (1000 库存远超 10 worker × 1.0 消耗): "
        f"actual sum={total_insufficient}"
    )
