"""delivery_adapter 真 PG 并发 Tier 1 测试 (PR-5 — delivery_adapter P1+P2 paths)

PR-5 of PR #631 proposal §10 6-PR roadmap — 与 test_order_service_concurrent_tier1.py
同 PR ship. 验证 audit doc §4.1.5 delivery_adapter.py 1 P1 + 4 P2 路径**真行为**:

  - T3: N=10 concurrent receive_order 同 platform_order_id → IntegrityError catch
        + re-SELECT 兜底 (PR #563 PR-F INSERT race fix 真行为). 1 worker INSERT 成功
        + 9 worker 见 duplicate=True (走 L161 existing 分支或 L256-277 IntegrityError-
        recovered 分支). 终态 delivery_orders 仅 1 行该 platform_order_id.
        **应用 Issue #643 P2-A distinct-set assertion**: workers 返回 (worker_idx,
        was_duplicate, returned_order_id), 断言 distinct workers + 唯一 order_id 集
        + duplicate=True 数 == 9.

  - T4: N=10 concurrent confirm_order 同 delivery_order → FOR UPDATE 串行化
        state machine confirmed → preparing transition (PR #563 PR-F state machine
        fix 真行为). 1 worker 成功 (status=preparing) + 9 worker raise ValueError
        ("订单状态 preparing，无法确认" 业务层守卫). 终态 delivery_orders.status='preparing'
        单点写入. **distinct-set assertion**: 1 success + 9 ValueError, 各 worker_idx distinct.

业务场景（真餐厅, audit doc §4.1.5）:
  - T3: 美团/饿了么/抖音 webhook 重试 + 商家管理后台手动同步 → 同 platform_order_id
        多路 race INSERT → unique constraint 触发 → IntegrityError catch 兜底 →
        无重复订单 (P1, audit doc §4.1.5 L150 模式)
  - T4: webhook 自动确认 + 收银员手动确认 + 后厨平板 race confirm 同 delivery_order →
        FOR UPDATE 串行化 → 仅 1 worker transition (P2 state machine, PR #563 PR-F)

跑法 (opt-in via INTEGRATION_PG_DSN):

    docker compose -f infra/compose/test-pg.yml up -d
    DATABASE_URL=postgresql://tunxiang_test:test_password_dev_only@localhost:5433/tunxiang_os_test \\
        ./scripts/db-bootstrap.sh --skip-create
    DATABASE_URL=postgresql://tunxiang_test:test_password_dev_only@localhost:5433/tunxiang_os_test \\
        ./scripts/migrate-all.sh --include-legacy
    INTEGRATION_PG_DSN=postgresql://tunxiang_test:test_password_dev_only@localhost:5433/tunxiang_os_test \\
        pytest tests/concurrent/test_delivery_adapter_concurrent_tier1.py \\
        --confcutdir tests/concurrent --override-ini asyncio_mode=auto -v

未设 INTEGRATION_PG_DSN → 全部 skip (opt-in 模式)。

关联:
  - PR #631 proposal §10 PR-5 (本 PR)
  - PR #634 PR-1 / #638 PR-2 / #642 PR-3 / #644 PR-4
  - docs/security/tier1-row-lock-audit-2026-05.md §4.1.5 (delivery_adapter 1 P1 + 4 P2)
  - PR #563 PR-F (源 fix: receive_order IntegrityError catch + 4 state machine
    `_get_order(lock=True)`)
  - shared/db-migrations/versions/v058_delivery_platforms.py (delivery_orders 表 +
    UNIQUE(tenant_id, platform, platform_order_id) 复合约束 + RLS)
  - Issue #643 P2-A 应用：distinct-set assertion (worker_idx + was_duplicate tuple)
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

# **CI/local 兼容 fix** (round-1 §19 P2-3 fix 副作用 + first-push CI 已暴露同问题):
# `delivery_adapter.py` L19 顶层 import `shared.ontology.src.database` →
# database.py L14 `create_async_engine(DATABASE_URL, ...)` 触发 module-level engine 创建.
# CI workflow 设 DATABASE_URL=postgresql://... (sync 前缀) → SQLAlchemy InvalidRequestError
# "asyncio extension requires async driver, loaded 'psycopg2' is not async".
# 业务源不改 (per cold-start prompt scope), 在测试模块顶端 rewrite env 为 async DSN.
# 必须在 ANY business import 前执行 (Python 模块加载顺序保证).
_db_url = os.environ.get("DATABASE_URL", "")
if _db_url.startswith("postgresql://") and not _db_url.startswith("postgresql+"):
    os.environ["DATABASE_URL"] = "postgresql+asyncpg://" + _db_url[len("postgresql://"):]

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
# delivery_adapter 顶层 import shared.ontology.src.database; ontology base 用
# dataclass(slots=True) 仅 3.10+; sys.version_info gate 而非 sys.modules stub
# (feedback_pytest_stub_setdefault_pitfall.md 跨 test 文件污染教训)
if sys.version_info < (3, 10):
    pytest.skip(
        "需 Python 3.10+ (shared.ontology 用 dataclass slots=True); CI Python 3.11 跑通",
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
    """INSERT 1 store, 返回 store_id (delivery_orders.store_id 无 FK constraint
    v058 但保留 stores 行让租户 GUC 链路完整)."""
    store_id = _new_uuid()
    await session.execute(
        text("""
            INSERT INTO stores (id, tenant_id, store_name, store_code)
            VALUES (CAST(:id AS uuid), CAST(:tid AS uuid), :name, :code)
        """),
        {
            "id": str(store_id),
            "tid": str(tenant_id),
            "name": f"deliv-{uuid.uuid4().hex[:8]}",
            "code": f"DLV-{uuid.uuid4().hex[:12]}",
        },
    )
    return store_id


async def _seed_delivery_order(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    store_id: uuid.UUID,
    *,
    platform: str = "meituan",
    platform_order_id: str | None = None,
    status: str = "confirmed",
    total_fen: int = 5000,
) -> tuple[uuid.UUID, str]:
    """INSERT 1 delivery_order, 返回 (order_id, platform_order_id).

    最小列: id/tenant_id/store_id/brand_id/order_no/platform/platform_order_id/
    status/total_fen + commission_rate/commission_fen/merchant_receive_fen
    (NOT NULL with default 0 in v058).

    注: items_json 列 (JSON, default list) 在 v058 默认 NULL 允许; 测试不传.
    sales_channel 列 (String 50, NOT NULL default '') 同上.
    """
    order_id = _new_uuid()
    p_order_id = platform_order_id or f"PT-{uuid.uuid4().hex[:16]}"
    commission_rate = 0.18
    commission_fen = int(total_fen * commission_rate)
    merchant_receive_fen = total_fen - commission_fen
    await session.execute(
        text("""
            INSERT INTO delivery_orders (
                id, tenant_id, store_id, brand_id,
                order_no, platform, platform_name, platform_order_id,
                sales_channel, status, total_fen,
                commission_rate, commission_fen, merchant_receive_fen
            )
            VALUES (
                CAST(:id AS uuid), CAST(:tid AS uuid), CAST(:sid AS uuid), :brand,
                :order_no, :platform, :platform_name, :p_order_id,
                :sales_channel, :status, :total_fen,
                :commission_rate, :commission_fen, :merchant_receive_fen
            )
        """),
        {
            "id": str(order_id),
            "tid": str(tenant_id),
            "sid": str(store_id),
            "brand": "test-brand",
            "order_no": f"MT{uuid.uuid4().hex[:14].upper()}",
            "platform": platform,
            "platform_name": "美团外卖" if platform == "meituan" else platform,
            "p_order_id": p_order_id,
            "sales_channel": f"delivery_{platform}",
            "status": status,
            "total_fen": total_fen,
            "commission_rate": commission_rate,
            "commission_fen": commission_fen,
            "merchant_receive_fen": merchant_receive_fen,
        },
    )
    return order_id, p_order_id


@pytest_asyncio.fixture(autouse=True)
async def _silence_notify_platform(monkeypatch):
    """**§19 round-1 P2-3 fix (defensive)**: monkeypatch DeliveryPlatformAdapter
    `_notify_platform` 为 no-op coroutine. 当前 source L706-716 仅是 logger.info stub
    (TODO: 注入 MeituanClient 实现真实通知), 无 HTTP 调用 → 测试不会 fail on network.

    但本 fixture 防御性 patch 防未来 source 引入真 HTTP client (e.g., MeituanClient
    .post)致 CI test fail on network unreachable. 与 _silence_emit_event /
    _silence_attribution 同模式.
    """
    from services.tx_trade.src.services.delivery_adapter import DeliveryPlatformAdapter

    async def _noop_notify(self, platform, event, data):
        return None

    monkeypatch.setattr(DeliveryPlatformAdapter, "_notify_platform", _noop_notify)
    yield


# ───────────────────────────────────────────────────────────────────
# T3: N=10 concurrent receive_order 同 platform_order_id — IntegrityError catch
# ───────────────────────────────────────────────────────────────────
async def test_delivery_adapter_receive_order_concurrent_n10_no_duplicate(
    session_factory,
):
    """T3 — 多平台 webhook 重试 + 商家手动同步 race, IntegrityError catch 防重复订单.

    setup: 1 store + delivery_orders 表空 (本测试不预 seed delivery_order)
    runner: N=10 workers 各 receive_order(platform="meituan", platform_order_id=同一值)
            **§19 round-1 P2-1 fix**: 不用 workers_lock 串行 idx 分配 — 改用
            uuid.uuid4() 现场生成 distinct identifier, 让 10 worker 真并发 SELECT
            existing 最大化 IntegrityError catch path 触发概率 (workers_lock 串行
            会让多 worker 走 L161 existing 早返回路径而非 L256-277 race-recovered).
    断言（核心 P1 + Issue #643 P2-A distinct-set 升级版）:
      - 10 worker 全部成功（无 exception — IntegrityError 被 L246 catch 兜底）
      - 1 worker 见 duplicate=False (or absent) — 真创建那一笔
      - 9 worker 见 duplicate=True — 走 L161 existing 分支 (后到者) 或
        L256-277 IntegrityError-recovered 分支 (并发 race 都过 existing 检查者)
      - delivery_orders 表内 platform_order_id 仅 1 行 (UNIQUE constraint 真生效)
      - **distinct-set assertion**: 9 worker 返回的 order_id 与 1 真创建 worker
        相同 (即所有 worker 看到同一 existing 的 id)
      - 10 worker 各自 distinct uuid worker_id

    若 IntegrityError catch 未生效 (audit §4.1.5 P1 — PR #563 PR-F fix 回归):
      - 10 worker 并发 SELECT existing → None (空表)
      - 10 worker 都 INSERT → 后 9 笔 raise IntegrityError → 业务层未 catch →
        BaseException 透传 worker → 9 worker 抛异常 → run_concurrent results 含 9 BaseException
      - **本测试主断言 `not exceptions` 直接抓**

    若 unique constraint 失效 (schema 漂移 — v058 UNIQUE 被未来 migration 误删):
      - 10 笔 INSERT 全成功 → delivery_orders 内 10 行同 platform_order_id
      - 平台对账时 1 真单变成 10 张商户实收, 财务月报错 +900% (P0 financial)
      - **本测试 assert_final_consistency count==1 直接抓**
    """
    from services.tx_trade.src.services.delivery_adapter import DeliveryPlatformAdapter

    tenant_id = _new_uuid()
    async with session_factory() as s:
        store_id = await _seed_store(s, tenant_id)
        await s.commit()

    # 所有 worker 用同一 platform_order_id 触发 UNIQUE constraint race
    shared_platform_order_id = f"MT-RACE-{uuid.uuid4().hex[:16]}"

    async def _receive(session: AsyncSession) -> dict:
        """单 worker receive_order, 返回 (worker_id, was_duplicate, order_id).

        **§19 P2-1 fix**: 不用 workers_lock 串行 idx 分配 — 用 uuid 现场生成,
        让 10 worker 真并发 SELECT existing → 最大化 IntegrityError catch path
        (L256-277) 触发概率.
        """
        worker_id = str(uuid.uuid4())[:8]
        # 注入 worker 自己的 session (DeliveryPlatformAdapter._get_session 优先用
        # 注入的 session 不创建新; _close_session 注入的不关; receive_order 内部
        # session.commit() 触发 UNIQUE → run_concurrent 外层 commit 是 no-op)
        adapter = DeliveryPlatformAdapter(
            store_id=str(store_id),
            brand_id="test-brand",
            tenant_id=str(tenant_id),
            menu_items=[],  # 不映射菜品 → 全部 unmapped, 不影响 INSERT 路径
            db_session=session,
        )
        result = await adapter.receive_order(
            platform="meituan",
            platform_order_id=shared_platform_order_id,
            items=[{"name": "test-dish", "quantity": 1, "price_fen": 5000}],
            total_fen=5000,
            customer_phone="138****1234",
            delivery_address="测试地址",
        )
        return {
            "worker_id": worker_id,
            "was_duplicate": result.get("duplicate", False),
            "order_id": result["order_id"],
        }

    results = await run_concurrent(
        session_factory, tenant_id, n=10,
        operation=_receive,
        timeout_sec=30.0,
    )

    # 全部成功 — IntegrityError catch 兜底, 无 worker 透传 BaseException
    exceptions = [r for r in results if isinstance(r, BaseException)]
    assert not exceptions, (
        f"P1 INSERT race 防护回归: receive_order concurrent unexpected exceptions "
        f"({len(exceptions)}/{len(results)}): {exceptions[:3]}. "
        f"PR #563 PR-F IntegrityError catch (delivery_adapter L246-277) 未生效, "
        f"audit §4.1.5 P1 path 回归"
    )

    # 终态: delivery_orders 仅 1 行 (UNIQUE constraint v058 真生效)
    async with session_factory() as s:
        await assert_final_consistency(
            s, "delivery_orders",
            {"platform_order_id": shared_platform_order_id},
            {"count": 1},
        )

    # 主断言 (worker 返回率): 10 worker 全部完成应均返回 dict
    # **§19 round-1 P2-1 fix**: 不用 workers_lock idx 串行 — 用 uuid4 worker_id 现场
    # 生成 (天然 distinct, 不强 assert; 真信号是下方 duplicate_count/distinct_order_ids)
    dict_results = [r for r in results if isinstance(r, dict)]
    assert len(dict_results) == 10, (
        f"worker 应返回 dict, actual {len(dict_results)}/10. "
        f"non-dict: {[r for r in results if not isinstance(r, dict)][:3]}"
    )
    duplicate_count = sum(1 for r in dict_results if r["was_duplicate"])
    assert duplicate_count == 9, (
        f"P1 duplicate=True 数 actual={duplicate_count} expected=9 "
        f"(1 worker 真创建 + 9 worker existing 命中). 若 ≠ 9 表明:"
        f" (a) 多 worker 真创建 → IntegrityError catch 失效 (但 UNIQUE constraint 兜底"
        f"应 → 终态 count > 1, 已被前断言抓);"
        f" (b) 0 duplicate → 业务返回 dict 缺 'duplicate' key 漏标 → result.get default False 误判"
    )
    # 所有 worker 返回的 order_id 必须一致 (即同一真创建那笔的 id)
    distinct_order_ids = {r["order_id"] for r in dict_results}
    assert len(distinct_order_ids) == 1, (
        f"P1 数据一致性: 10 worker 返回的 order_id 应全相同 (同一真创建笔), "
        f"actual {len(distinct_order_ids)} distinct: {distinct_order_ids}. "
        f"若 ≠ 1 表明 IntegrityError-recovered 分支 (L256-277) re-SELECT 命中"
        f"不同行 (UNIQUE 失效或 RLS 跨 worker 不一致)"
    )


# ───────────────────────────────────────────────────────────────────
# T4: N=10 concurrent confirm_order — state machine FOR UPDATE 串行化
# ───────────────────────────────────────────────────────────────────
async def test_delivery_adapter_confirm_order_concurrent_n10_state_machine_serial(
    session_factory,
):
    """T4 — 平台 webhook 自动确认 + 收银员手动确认 + 后厨平板 race confirm, FOR UPDATE
    防多次 transition.

    setup: 1 store + 1 delivery_order (status='confirmed', platform=meituan)
    runner: N=10 workers 各 adapter.confirm_order(order_id, estimated_ready_min=20)
    断言:
      - 1 worker 成功 (status confirmed → preparing)
      - 9 worker raise ValueError ("订单状态 preparing，无法确认" L321 业务守卫)
      - delivery_orders.status='preparing' (transition 1 次)
      - estimated_ready_min=20 (单点写入)
      - **distinct-set assertion**: 1 success_idx + 9 fail_idx, 集合 == {0..9}

    若 FOR UPDATE 未真生效（audit §4.1.5 P2 — PR #563 PR-F fix 回归）:
      - 10 worker 并发 SELECT delivery_order.status='confirmed'
      - 10 worker 都判 status ∈ ('confirmed', 'pending'), 继续 transition + commit
      - 10 次 _notify_platform 调用 → 平台收 10 次确认通知 → 平台限流封号风险 +
        商家信誉受损 (audit §4.1.5 P2)
      - **本测试主断言 successes==1 直接抓**

    与 T3 互补:
      - T3: receive_order INSERT 路径 (IntegrityError catch 兜底)
      - T4: state machine UPDATE 路径 (FOR UPDATE 串行化 + 业务层守卫)
    """
    from services.tx_trade.src.services.delivery_adapter import DeliveryPlatformAdapter

    tenant_id = _new_uuid()
    async with session_factory() as s:
        store_id = await _seed_store(s, tenant_id)
        delivery_order_id, _ = await _seed_delivery_order(
            s, tenant_id, store_id,
            platform="meituan", status="confirmed", total_fen=5000,
        )
        await s.commit()

    workers_count = [0]
    workers_lock = asyncio.Lock()

    async def _confirm(session: AsyncSession) -> dict:
        async with workers_lock:
            idx = workers_count[0]
            workers_count[0] += 1
        adapter = DeliveryPlatformAdapter(
            store_id=str(store_id),
            brand_id="test-brand",
            tenant_id=str(tenant_id),
            menu_items=[],
            db_session=session,
        )
        result = await adapter.confirm_order(
            order_id=str(delivery_order_id),
            estimated_ready_min=20,
        )
        return {"worker_idx": idx, **result}

    results = await run_concurrent(
        session_factory, tenant_id, n=10,
        operation=_confirm,
        timeout_sec=30.0,
    )

    # 分流结果: 成功 vs ValueError vs 其他异常
    successes = [r for r in results if isinstance(r, dict)]
    value_errors = [r for r in results if isinstance(r, ValueError)]
    other_errors = [
        r for r in results
        if isinstance(r, BaseException) and not isinstance(r, ValueError)
    ]

    # 主断言 (P2 state machine 串行化核心): 仅 1 worker 成功
    assert len(successes) == 1, (
        f"P2 state machine 串行化失败: 成功 confirm 数 {len(successes)} ≠ 1. "
        f"FOR UPDATE 未真生效, audit §4.1.5 P2 path 回归. "
        f"results: successes={len(successes)} value_errors={len(value_errors)} "
        f"other_errors={len(other_errors)}"
    )
    # 辅助断言: 剩余 9 worker 全部是预期 ValueError (业务层守卫拒绝 confirm)
    assert len(value_errors) == 9, (
        f"剩余 worker 应抛 ValueError (delivery_adapter.confirm_order L321 "
        f"'订单状态 X，无法确认' 守卫), actual {len(value_errors)}/9. "
        f"other_errors={other_errors[:3]}"
    )

    # 终态: status='preparing', estimated_ready_min=20 (单点写入)
    async with session_factory() as s:
        await assert_final_consistency(
            s, "delivery_orders", {"id": str(delivery_order_id)},
            {"count": 1, "status_set": {"preparing"}},
        )
        result = await s.execute(
            text("""
                SELECT estimated_ready_min FROM delivery_orders
                WHERE id = CAST(:id AS uuid)
            """),
            {"id": str(delivery_order_id)},
        )
        ready_min = result.scalar_one()
        assert ready_min == 20, (
            f"estimated_ready_min 应为成功 worker 写入值, actual={ready_min} "
            f"expected=20. 若 ≠ 20 表明非 worker 写入或被覆盖"
        )

    # 主断言 (Issue #643 P2-A distinct-set):
    # 1 success worker + 9 ValueError worker, idx 集合 == {0..9}
    success_indices = {r["worker_idx"] for r in successes}
    # ValueError 不携带 worker_idx (Python exception 不返回 worker context),
    # 通过 successes + 总数推断: distinct success_idx = 1, total runs = 10
    assert len(success_indices) == 1, (
        f"distinct success worker_idx actual={len(success_indices)} expected=1. "
        f"重复 success_idx 表明 workers_lock 失效"
    )
    # 总 worker 跑 10 次 (success + fail 之和)
    assert len(successes) + len(value_errors) == 10, (
        f"总 worker run 数 actual={len(successes) + len(value_errors)} expected=10"
    )
