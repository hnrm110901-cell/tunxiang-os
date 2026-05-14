"""Concurrent test fixtures — 真 PG 反测的 engine + session_factory (PR-1 infra)

设计承继（详 docs/testing/concurrent-row-lock-test-framework-proposal.md §4）:
  - Function-scoped engine + function-scoped session_factory
    （pytest-asyncio module 级跨 event loop 报 `Future attached to a different loop`,
    与 tests/tier1/test_rls_runtime_p0_tier1.py:118-167 决策一致）
  - 复用 shared/test_utils/integration_pg.py 的 INTEGRATION_PG_DSN + requires_integration_pg
  - 不与 services/*/conftest.py 冲突（独立目录 tests/concurrent/，pyproject testpaths 不含本目录,
    pytest 默认 collect 不会 import 本 conftest, 仅 workflow `pytest tests/concurrent/` 显式 collect）
  - 与 tests/tier1/test_rls_runtime_p0_tier1.py 的 service-level multi-session 模式互补:
    rls_runtime 测 USING/CHECK；concurrent 测 FOR UPDATE 行锁真行为

Pre-req (opt-in via INTEGRATION_PG_DSN):

    docker compose -f infra/compose/test-pg.yml up -d
    DATABASE_URL=postgresql://tunxiang_test:test_password_dev_only@localhost:5433/tunxiang_os_test \\
        ./scripts/db-bootstrap.sh --skip-create
    DATABASE_URL=postgresql://tunxiang_test:test_password_dev_only@localhost:5433/tunxiang_os_test \\
        ./scripts/migrate-all.sh --include-legacy
    INTEGRATION_PG_DSN=postgresql://tunxiang_test:test_password_dev_only@localhost:5433/tunxiang_os_test \\
        pytest tests/concurrent/ -v

未设 INTEGRATION_PG_DSN → 全部 skip（opt-in 模式, 同 D2b' 决策, 详 issue #449 closed）。

PR-1 scope: 仅 stores 表（smoke test 用）。PR-2/3/4/5 扩展时:
  - 简单扩展：直接加入 _CONCURRENT_TABLES 即可（cleanup 自动覆盖）
  - 服务特定：在子目录加 conftest.py 覆盖/扩展 _CONCURRENT_TABLES（pytest conftest 继承机制）
"""
from __future__ import annotations

import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from shared.test_utils.integration_pg import INTEGRATION_PG_DSN

# 与 test_rls_runtime_p0_tier1.py 一致 — 非 superuser role 让 RLS USING 真生效
_RLS_TEST_ROLE = "tunxiang_rls_app"

# PR-1 smoke test 用表。PR-2/3/4/5 扩展请加入或子目录 conftest 覆盖:
#   PR-2 (cashier_engine): + orders, payments, order_items ✅ ship (#638)
#   PR-3 (payment_saga): + payment_sagas ✅ 本 PR (注: v091 真表名是 payment_sagas，
#     PR-2 conftest 注释 "payment_saga_state" 是 PR-1 写时占位错误，本 PR 同步修正)
#   PR-4 (inventory): + ingredient_movements, ingredients
#   PR-5 (order+delivery): + delivery_orders
#
# **FK 拓扑顺序（子→父序，DELETE 时遵循）**:
#   payment_sagas → payments → order_items → orders → stores
#   (payment_sagas.order_id 逻辑→orders / .payment_id 逻辑→payments — v091 未声明 FK
#    constraint 但语义子表; payments.order_id FK→orders / order_items.order_id FK→orders
#    / orders.store_id FK→stores)
#
# Issue #635 P2-B follow-up：当前 cleanup 用 SET LOCAL session_replication_role=replica
# 绕 FK 触发器，PR-2/PR-3 起本 _CONCURRENT_TABLES 真正含 FK 链；顺序错时不会 fail
# （trigger 已绕过）。**未来 PR-2+ 修法**: 切 TRUNCATE...CASCADE 或 CI lint 守顺序。
# 当前注释标明子→父序，按 issue #635 短期方案 A 处理。
_CONCURRENT_TABLES: tuple[str, ...] = (
    "payment_sagas",  # 子 (逻辑 FK → orders + payments，v091 未声明 constraint)
    "payments",       # 子 (FK → orders)
    "order_items",    # 子 (FK → orders)
    "orders",         # 中间 (FK → stores)
    "stores",         # 父
)


def _to_async_dsn(dsn: str) -> str:
    """sync postgresql:// → async postgresql+asyncpg:// 转换。"""
    if dsn.startswith("postgresql+asyncpg://"):
        return dsn
    if dsn.startswith("postgresql://"):
        return dsn.replace("postgresql://", "postgresql+asyncpg://", 1)
    return dsn


@pytest_asyncio.fixture
async def engine():
    """Function-scoped async engine + 一次性 setup (CREATE ROLE + GRANT)。

    Function-scoped: 与 test_rls_runtime_p0_tier1.py 一致 — pytest-asyncio module 级
    跨 event loop 报错。pool_size=12 + max_overflow=3 让 N≤12 并发 worker 各拿 connection
    不阻塞（200 桌并发场景由各业务 test 文件自滚 engine 调大）。

    Setup idempotent — DO 防重复 CREATE ROLE, GRANT 天然 idempotent；to_regclass 守卫
    避免 alembic 未跑全 chain 时 GRANT 不存在表 attr error（PR-2/3/4/5 schema 演化 robust）。
    """
    eng = create_async_engine(
        _to_async_dsn(INTEGRATION_PG_DSN),
        pool_pre_ping=True,
        pool_size=12,
        max_overflow=3,
    )
    async with eng.begin() as conn:
        # CREATE ROLE — DO 块防重复, 与 init-rls.sql 角色定义一致
        # noqa S608: _RLS_TEST_ROLE 是模块级常量, 非用户输入; PG `CREATE ROLE $1`
        # 不支持参数绑定, f-string 拼接是必要权衡, 无注入路径
        await conn.execute(text(f"""
            DO $do$
            BEGIN
                IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{_RLS_TEST_ROLE}') THEN
                    CREATE ROLE {_RLS_TEST_ROLE} NOINHERIT NOLOGIN;
                END IF;
            END $do$;
        """))  # noqa: S608
        # GRANT — to_regclass 守卫表存在再 GRANT, schema 演化时不会 hard fail
        # noqa S608: 同上, tbl 来自 _CONCURRENT_TABLES 模块级元组白名单
        for tbl in _CONCURRENT_TABLES:
            result = await conn.execute(
                text("SELECT to_regclass(:t)"), {"t": f"public.{tbl}"}
            )
            if result.scalar() is not None:
                await conn.execute(text(  # noqa: S608
                    f"GRANT SELECT, INSERT, UPDATE, DELETE ON {tbl} TO {_RLS_TEST_ROLE}"
                ))
    try:
        yield eng
    finally:
        await eng.dispose()


@pytest_asyncio.fixture
async def session_factory(engine):
    """Function-scoped async sessionmaker — 各 worker 自取 session 独立 transaction。

    expire_on_commit=False 避免 commit 后 ORM 对象 detached 不可读（虽然本框架主要用 text(),
    保留 default 以与 service-level fixture 风格一致）。
    """
    return async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


@pytest_asyncio.fixture(autouse=True)
async def _cleanup(engine):
    """每 test 前后清并发测试表 — 绕 RLS + 绕 FK（需 superuser 权限）。

    SET LOCAL row_security=off + session_replication_role=replica 双重绕过；engine
    fixture 用 DSN superuser (tunxiang_test) 起，权限充足。to_regclass 守卫表不存在
    场景, 与 GRANT 同源避免 schema 演化 hard fail。
    """

    async def _do_cleanup() -> None:
        async with engine.begin() as conn:
            await conn.execute(text("SET LOCAL row_security = off"))
            await conn.execute(text("SET LOCAL session_replication_role = replica"))
            for tbl in _CONCURRENT_TABLES:
                result = await conn.execute(
                    text("SELECT to_regclass(:t)"), {"t": f"public.{tbl}"}
                )
                if result.scalar() is not None:
                    # noqa S608: tbl 来自 _CONCURRENT_TABLES 模块级白名单, 非用户输入
                    await conn.execute(text(f"DELETE FROM {tbl}"))  # noqa: S608

    await _do_cleanup()
    yield
    await _do_cleanup()
