"""Integration PG fixtures — opt-in via INTEGRATION_PG_DSN env

S5（channel-aggregation 基建）提供，统一 *_tier1.py 真 PG 反测的 fixture 入口。

提供：
  - integration_pg_engine    — function-scoped async engine（首次 setup 创建 RLS role + GRANT）
  - integration_pg_session   — function-scoped，事务 rollback 隔离 + SET LOCAL ROLE
  - set_tenant_guc           — 设 app.tenant_id GUC 的 helper
  - requires_integration_pg  — pytest.mark.skipif 装饰器（统一 reason）

DSN 来源：
  os.environ["INTEGRATION_PG_DSN"]
  必须指向已 bootstrap 完成的 PG（init-rls + alembic upgrade head 已跑过）。

本地用法：
  docker compose -f infra/compose/test-pg.yml up -d
  cd shared/db-migrations
  DATABASE_URL=postgresql://tunxiang_test:test_password_dev_only@localhost:5433/tunxiang_os_test \\
    python3 -m alembic stamp v409_fund_settlement_revive
  DATABASE_URL=postgresql://tunxiang_test:test_password_dev_only@localhost:5433/tunxiang_os_test \\
    python3 -m alembic upgrade head
  INTEGRATION_PG_DSN=postgresql://tunxiang_test:test_password_dev_only@localhost:5433/tunxiang_os_test \\
    python3 -m pytest shared/db-migrations/tests/ -k real_pg -v

CI 用法：
  .github/workflows/integration-pg-tests.yml 在 PR 触发时自动配置 PG service container。

详见 docs/integration-pg-fixture.md。
"""

from __future__ import annotations

from typing import AsyncGenerator, Callable, Coroutine
from uuid import UUID

import pytest

# D2b' (2026-05-11)：DSN 读取 + skipif 装饰器 + set_tenant_guc helper 抽到
# shared.test_utils.integration_pg，service-level 测试也共用同一份。
# 本 conftest 仅保留 channel-aggregation fixture 专属的 role/table GRANT + 两个
# fixture（与 service-level 多 session 模式不兼容）。
#
# 顶层 import：仅取不依赖 sqlalchemy 的 export（常量 + 装饰器）。set_tenant_guc
# helper 在 shared module 内被 `if _SQLA_AVAILABLE:` 守卫，sqlalchemy 缺失时未定义；
# 故移到下方 try 块内一起 import，与本 conftest 的 _ASYNC_DEPS_AVAILABLE 守卫对齐。
from shared.test_utils.integration_pg import (
    INTEGRATION_PG_DSN,
    requires_integration_pg,
)

# pytest_asyncio + sqlalchemy[asyncio] 仅 integration PG 反测需要。
# migration-ci.yml 等 workflow 仅装 pytest（不带 asyncio extras），import 时
# 守护一下 — 缺失时整套 integration fixture 不注册，对结构测试无影响。
try:
    import pytest_asyncio
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import (
        AsyncEngine,
        AsyncSession,
        create_async_engine,
    )
    # set_tenant_guc helper 与 sqlalchemy 联绑（shared module 内同样守卫）。
    from shared.test_utils.integration_pg import set_tenant_guc as _set_tenant_guc_helper
    _ASYNC_DEPS_AVAILABLE = True
except ImportError:
    _ASYNC_DEPS_AVAILABLE = False


# 测试 RLS 必须用非 superuser 角色（superuser 即便 FORCE ROW LEVEL SECURITY 也能绕过）。
# 本 role 在 fixture 首次 setup 时创建并 GRANT 必要权限。
_RLS_TEST_ROLE = "tunxiang_rls_app"

# channel-aggregation 三表 — fixture setup 时 GRANT 给 _RLS_TEST_ROLE
_RLS_TEST_TABLES = ("channel_oauth_tokens", "raw_channel_events", "member_identity_map")


# pytest_asyncio + sqlalchemy[asyncio] 缺失时（migration-ci 等仅装 pytest 的 workflow），
# 跳过整套 async fixture 注册 — 仅 import 守护，未影响结构测试 + decorator 导出。
if _ASYNC_DEPS_AVAILABLE:

    def _to_async_dsn(dsn: str) -> str:
        """sync postgresql:// → async postgresql+asyncpg:// 转换。"""
        if dsn.startswith("postgresql+asyncpg://"):
            return dsn
        if dsn.startswith("postgresql://"):
            return dsn.replace("postgresql://", "postgresql+asyncpg://", 1)
        return dsn

    @pytest_asyncio.fixture
    async def integration_pg_engine() -> AsyncGenerator[AsyncEngine, None]:
        """function-scoped async engine —— 每 test 独立 engine。

        为何不 session-scoped：pytest-asyncio auto 模式下每 test 独立 event loop，
        session-scoped async engine 会跨 loop 报 `Future attached to a different loop`。
        function-scoped 每 test 一个 engine，开销 ~50ms 可接受。

        一次性 setup（每 engine 创建时跑一次）：
          - 创建非 superuser role `tunxiang_rls_app`（NOINHERIT NOLOGIN，仅 SET ROLE 用）
          - GRANT SELECT/INSERT/UPDATE/DELETE 给 channel-aggregation 三表
          - DDL idempotent，重复跑无副作用

        DSN 缺失时 skip 而非 error — 配合 requires_integration_pg 装饰器
        给出一致的 opt-in 体验。
        """
        if not INTEGRATION_PG_DSN:
            pytest.skip("INTEGRATION_PG_DSN 未配置")
        engine = create_async_engine(
            _to_async_dsn(INTEGRATION_PG_DSN),
            pool_pre_ping=True,
            pool_size=2,
            max_overflow=1,
        )
        # 一次性创建 non-superuser role + GRANT。
        # CREATE ROLE / GRANT 是 DDL，用 engine.begin() 显式事务包裹（每 fixture 一个 txn）。
        # 不用 `connect() + execution_options(AUTOCOMMIT)`（已知 SQLAlchemy 2.x async
        # 对此不修改原 conn，依赖 driver 隐式行为，post-review 已修）。
        async with engine.begin() as conn:
            await conn.execute(text(f"""
                DO $do$
                BEGIN
                    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{_RLS_TEST_ROLE}') THEN
                        CREATE ROLE {_RLS_TEST_ROLE} NOINHERIT NOLOGIN;
                    END IF;
                END $do$;
            """))
            for tbl in _RLS_TEST_TABLES:
                await conn.execute(text(
                    f"GRANT SELECT, INSERT, UPDATE, DELETE ON {tbl} TO {_RLS_TEST_ROLE}"
                ))
        try:
            yield engine
        finally:
            await engine.dispose()

    @pytest_asyncio.fixture
    async def integration_pg_session(
        integration_pg_engine: AsyncEngine,
    ) -> AsyncGenerator[AsyncSession, None]:
        """test-scoped session — 显式事务包裹，teardown 自动 rollback。

        切换到 _RLS_TEST_ROLE non-superuser 角色（让 RLS 真生效）。

        不污染 DB：所有 INSERT/UPDATE 在 fixture teardown 时被 rollback。
        跨 test 隔离强：每 test 独立事务，互不影响。

        注意：调用 session.commit() 会破坏隔离 — 反测中**避免**显式 commit。
        """
        async with integration_pg_engine.connect() as conn:
            trans = await conn.begin()
            async_session = AsyncSession(bind=conn, expire_on_commit=False)
            # SET LOCAL ROLE — 事务级生效，rollback 时自动清理
            # 必须在任何业务 SQL 之前，让 RLS policy 真生效
            await async_session.execute(text(f"SET LOCAL ROLE {_RLS_TEST_ROLE}"))
            try:
                yield async_session
            finally:
                await async_session.close()
                await trans.rollback()

    @pytest.fixture
    def set_tenant_guc() -> Callable[
        [AsyncSession, "UUID | str"], Coroutine[None, None, None]
    ]:
        """返回 helper：对 session 设 app.tenant_id GUC（事务 scope）。

        用法：
            async def test_x(integration_pg_session, set_tenant_guc):
                await set_tenant_guc(integration_pg_session, tenant_id)
                # 后续查询自动 RLS 隔离

        D2b' 后实现已抽到 shared.test_utils.integration_pg.set_tenant_guc；
        本 fixture 仅做 callable 注入的薄包装，保留 v411/v412/v413 既有签名。
        """
        return _set_tenant_guc_helper
