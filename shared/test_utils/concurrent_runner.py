"""跨 service 共享：N 路并发跑业务 operation 的最小 runner（PR-1 infra）

设计意图：屯象 Tier 1 行锁 6-PR fix roadmap (PR #544/#547/#553/#556/#560/#563) 全
mock-driven（`_select_has_for_update` SQL 字符串 grep），无任何真 PG race 验证。本
runner 让 *_concurrent_tier1.py 测试能 N 路并发跑业务 operation + 各 worker 独立
session/transaction + SET LOCAL ROLE 非 superuser + 事务级 tenant GUC，让 FOR UPDATE
真行为（持锁串行化 / 死锁检测 / SKIP LOCKED 跨 worker 路由）真验证。

设计承继（详 docs/testing/concurrent-row-lock-test-framework-proposal.md §4-5）:
  - 复用 shared/test_utils/integration_pg.py 的 set_tenant_guc helper（事务级 GUC）
  - 不导出 engine/sessionmaker fixture — 留各 test conftest 自滚（避免与
    services/*/conftest.py 二次冲突，feedback_pytest_stub_setdefault_pitfall.md 教训）
  - 每 worker 独立 session + 独立 transaction + 自 commit，让 FOR UPDATE 持锁/释放真触发
  - asyncio.gather(return_exceptions=True) 收齐结果（含成功/异常），调用方自行分流断言

不在本模块的（按设计）：
  - fixture：conftest.py 自滚（tests/concurrent/conftest.py 提供 engine + session_factory）
  - dummy/seed 数据：业务 test 文件自带
  - 业务断言：本 runner 只跑 + 收结果，断言留给 test 文件

跑法示例（典型 200 桌并发结账）：

    async def settle(session):
        eng = CashierEngine(db=session, tenant_id=str(TENANT_A))
        return await eng.settle_order(
            order_id=str(ORDER_ID),
            payments=[{"method": "cash", "amount_fen": 10000}],
        )

    results = await run_concurrent(session_factory, TENANT_A, n=10, operation=settle)
    # 期望：1 成功，9 抛"订单已结算" / 锁竞争分支
    successes = [r for r in results if not isinstance(r, BaseException)]
    assert len(successes) == 1, f"双结算泄漏：{len(successes)} 笔成功 (期望 1)"

    async with session_factory() as s:
        await assert_final_consistency(
            s, "payments", {"order_id": str(ORDER_ID)},
            {"count": 1, "sum_amount_fen": 10000},
        )
"""
from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any, Awaitable, Callable, TypeVar

from sqlalchemy import text

from shared.test_utils.integration_pg import set_tenant_guc

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

T = TypeVar("T")


async def run_concurrent(
    session_factory: "async_sessionmaker[AsyncSession]",
    tenant_id: "UUID | str",
    n: int,
    operation: "Callable[[AsyncSession], Awaitable[T]]",
    *,
    timeout_sec: float = 10.0,
    role: str = "tunxiang_rls_app",
) -> "list[T | BaseException]":
    """N 路并发跑 operation，各 worker 独立 session + 独立 transaction。

    每 worker:
      1. async with session_factory() as session   # 独立 session
      2. SET LOCAL ROLE <role>                     # 切非 superuser 让 RLS USING 真生效
      3. set_tenant_guc(session, tenant_id)        # 事务级 app.tenant_id GUC
      4. result = await operation(session)         # 业务调用
      5. await session.commit()                    # 故意 commit 让 FOR UPDATE 持锁/释放真触发
         异常时 context manager 自动 rollback

    超时 timeout_sec 后整体取消（防 deadlock 永挂）；timeout 抛 asyncio.TimeoutError，
    所有未完成 worker cancel + asyncio.gather(return_exceptions=True) 收回。

    Args:
        session_factory: SQLAlchemy async_sessionmaker（test conftest 自滚）
        tenant_id: RLS 租户 GUC 值（事务级 SET, rollback 自动清理）
        n: 并发数（典型 5/10/200）
        operation: async callable, 接收 session, 返回任意 T；可抛任意异常
        timeout_sec: 整体超时（默认 10s, 业务测试可放宽）
        role: PG role 名，默认 tunxiang_rls_app（与 init-rls.sql / test_rls_runtime 一致）

    Returns:
        长度 n 的 list, 元素 T 或 BaseException（gather return_exceptions=True 透传）

    Raises:
        asyncio.TimeoutError: 整体执行超过 timeout_sec（典型死锁未释放或业务卡死）
    """

    async def _worker() -> T:
        async with session_factory() as session:
            # SET LOCAL ROLE 必须在第一个业务 SQL 前；事务级 rollback 时自动清理。
            # role 是模块级硬编码默认值（"tunxiang_rls_app"）或调用方显式传入；PG 不支持
            # `SET LOCAL ROLE $1` 参数绑定，f-string 拼接是必要权衡，调用方传非默认值
            # 需自行保证字面安全（白名单字符串，非用户输入）。
            await session.execute(text(f"SET LOCAL ROLE {role}"))
            await set_tenant_guc(session, tenant_id)
            result = await operation(session)
            await session.commit()
            return result

    coros = [_worker() for _ in range(n)]
    return await asyncio.wait_for(
        asyncio.gather(*coros, return_exceptions=True),
        timeout=timeout_sec,
    )


async def assert_final_consistency(
    session: "AsyncSession",
    table: str,
    where: dict[str, Any],
    expected: dict[str, Any],
) -> None:
    """最终一致性断言 — 跑完并发后查表实际终态比对预期。

    用单 session 在并发跑完后查实际状态，避免污染并发 worker session。

    Args:
        session: 查询 session（调用方自滚, 通常 session_factory() 独立开）
        table: 表名（白名单字符串, 调用方保证 — 串入 SQL）
        where: {col: val} dict, AND 拼接 — col 串入 SQL（白名单字符串）, val 参数绑定
        expected: 期望终态 dict — 支持 keys（任选组合）:
          - "count": int — COUNT(*) 应等于此值
          - "sum_<col>": int/float — SUM(<col>) 应等于此值（如 sum_amount_fen）
          - "status_set": set[str] — 所有 status 列值集合应等于此 set

    Raises:
        AssertionError: 任一期望不满足
    """
    where_sql = " AND ".join(f"{k} = :{k}" for k in where)
    base_sql = f"FROM {table} WHERE {where_sql}" if where else f"FROM {table}"

    if "count" in expected:
        result = await session.execute(text(f"SELECT COUNT(*) {base_sql}"), where)
        actual = result.scalar()
        assert actual == expected["count"], (
            f"count mismatch on {table} where {where}: "
            f"actual={actual} expected={expected['count']}"
        )

    for k, v in expected.items():
        if k.startswith("sum_"):
            col = k[len("sum_") :]
            result = await session.execute(
                text(f"SELECT COALESCE(SUM({col}), 0) {base_sql}"), where
            )
            actual = result.scalar()
            assert actual == v, (
                f"sum({col}) mismatch on {table} where {where}: "
                f"actual={actual} expected={v}"
            )

    if "status_set" in expected:
        result = await session.execute(text(f"SELECT status {base_sql}"), where)
        actual_set = {row[0] for row in result.fetchall()}
        assert actual_set == expected["status_set"], (
            f"status_set mismatch on {table} where {where}: "
            f"actual={actual_set} expected={expected['status_set']}"
        )
