"""Tier 1 — D2c (#448) 真 PG runtime RLS 反测 — 7 P0 业务域表

Scope (A+α per #448 校准):
  - 7 P0 业务域 × 2 scenarios = 14 tests
  - Tables: orders / payments / customers / ingredients / store_daily_settlements / dishes / employees
  - Scenarios:
      1. Cross-tenant isolation: tenant_A 写入 → tenant_B 读不到（USING 子句生效）
      2. Same-tenant visibility: tenant_A 写入 → tenant_A 自己另开 session 必须能读到
        （USING 不过度过滤；commit + new session 模拟"店长结账 → 收银员另开界面看账"真业务场景）

Scenario 3 (NULL rejection) deferred:
  - 原 issue #448 提"NULL tenant_id 应被 RLS policy 拒绝（v500 FORCE ROW LEVEL SECURITY 后）"
  - v500 不存在；屯象 7 P0 表 FORCE RLS 未统一开启（FORCE 现仅在 v140/v147/v254/v310 4 处）
  - α 校准：本 PR 不补 v500 migration；NULL 防护测试留待未来 FORCE RLS migration PR

Pre-req (opt-in via INTEGRATION_PG_DSN):

    docker compose -f infra/compose/test-pg.yml up -d
    DATABASE_URL=postgresql://tunxiang_test:test_password_dev_only@localhost:5433/tunxiang_os_test \\
        ./scripts/db-bootstrap.sh --skip-create
    DATABASE_URL=postgresql://tunxiang_test:test_password_dev_only@localhost:5433/tunxiang_os_test \\
        ./scripts/migrate-all.sh --include-legacy
    INTEGRATION_PG_DSN=postgresql://tunxiang_test:test_password_dev_only@localhost:5433/tunxiang_os_test \\
        pytest tests/tier1/test_rls_runtime_p0_tier1.py -v

未设 INTEGRATION_PG_DSN 时全部 skip → CI 自然忽略；本地有库 / nightly 可手跑。

Test isolation 设计:
  - Function-scoped engine（pytest-asyncio module 级跨 loop 报 `Future attached to a
    different loop`，对齐 shared/db-migrations/tests/conftest.py 决策）
  - 多 session 模式：每个 phase 一个独立 session（A 写 commit 关 → B 读关 → A 读关）
    模拟 production runtime "收银员一次请求一个 session" 真场景；与 tx-analytics 同款
  - SET LOCAL ROLE tunxiang_rls_app：切到非 superuser，让 RLS USING 真生效。屯象 7 P0
    表无 FORCE ROW LEVEL SECURITY，superuser 默认 bypass RLS — 不切角色测的 RLS 都假
  - autouse cleanup：每 test 前后用 row_security=off + session_replication_role=replica
    清 7 表（绕 RLS + 绕 FK），防 cross-test 污染

D2b' (2026-05-11) 设计承继:
  service-level 多 session 模式 与 shared/db-migrations/tests/conftest.py 的 function-scoped
  单事务 fixture 结构性不兼容（详见 shared/test_utils/integration_pg.py docstring）。
  本文件继续 service-level 模式，仅 import DSN/skipif/set_tenant_guc helper from
  shared.test_utils.integration_pg；自己滚 engine / session / cleanup。

REVIEWER 关注点（feedback_self_review_blind_spots.md / T1 explicit ask review）:
  1. role + GRANT 设置是否正确（非 superuser，让 RLS USING 真生效）
  2. cleanup 是否真清（row_security=off + session_replication_role=replica 双重绕过）
  3. 单元测试 INSERT 是否触发 RLS WITH CHECK（同 tenant 写入，应 pass）
  4. 跨 session commit 模型是否正确（A 写 commit → B 读看不到 → A 另开 session 必须看到）
  5. UUID / VARCHAR 类型注入是否一致（::uuid 显式 cast 防 implicit 转换错误）
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from shared.test_utils.integration_pg import (
    INTEGRATION_PG_DSN,
    requires_integration_pg,
    set_tenant_guc,
)

pytestmark = [requires_integration_pg]


# ─────────────────────────────────── 配置 ───────────────────────────────────

# 非 superuser role — 与 shared/db-migrations/tests/conftest.py 一致；
# RLS USING 子句在 superuser 默认 bypass，必须切到非 superuser 才能真生效
_RLS_TEST_ROLE = "tunxiang_rls_app"

# Cleanup 顺序（FK 拓扑：子表 → 父表 → stores prereq）
# - payments → orders（payments.order_id FK）
# - orders / ingredients / store_daily_settlements / employees → stores（store_id FK）
# - customers / dishes 无 FK 到 stores
_P0_TABLES = (
    "payments",
    "orders",
    "customers",
    "ingredients",
    "store_daily_settlements",
    "dishes",
    "employees",
    "stores",                   # prereq for 5/7 P0 tables（FK target）
)

# Test parameter 用的表名（cleanup 顺序无关；7 P0 业务域，stores 是 prereq 不入测）
_TEST_TABLES = (
    "orders",
    "payments",
    "customers",
    "ingredients",
    "store_daily_settlements",
    "dishes",
    "employees",
)

# GRANT 表（含 stores prereq；non-superuser role 需 explicit grant 才能写）
_GRANT_TABLES = _P0_TABLES


def _to_async_dsn(dsn: str) -> str:
    """sync postgresql:// → async postgresql+asyncpg:// 转换。"""
    if dsn.startswith("postgresql+asyncpg://"):
        return dsn
    if dsn.startswith("postgresql://"):
        return dsn.replace("postgresql://", "postgresql+asyncpg://", 1)
    return dsn


# ─────────────────────────────────── fixtures ───────────────────────────────────


@pytest_asyncio.fixture
async def engine():
    """Function-scoped async engine + 一次性 setup（CREATE ROLE + GRANT on 7 表）。

    Function-scoped：pytest-asyncio module 级跨 event loop 报错（同 shared conftest 决策）。
    Setup 是 idempotent — DO $do$ 防重复 CREATE ROLE，GRANT 天然 idempotent，
    重复跑无副作用。开销 ~50ms × 14 test ≈ 700ms 总，可接受。
    """
    eng = create_async_engine(
        _to_async_dsn(INTEGRATION_PG_DSN),
        pool_pre_ping=True,
        pool_size=2,
        max_overflow=1,
    )
    # Setup 全程在 superuser (tunxiang_test) 身份执行；以下 f-string 嵌入仅模块级硬编码常量
    # （_RLS_TEST_ROLE / _GRANT_TABLES / _P0_TABLES），DDL & 角色控制 PG 不支持参数绑定
    # （`SET LOCAL ROLE $1` / `GRANT ... $2` 均非法），故 f-string 是必要权衡，无注入路径。
    async with eng.begin() as conn:
        await conn.execute(text(f"""
            DO $do$
            BEGIN
                IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{_RLS_TEST_ROLE}') THEN
                    CREATE ROLE {_RLS_TEST_ROLE} NOINHERIT NOLOGIN;
                END IF;
            END $do$;
        """))
        for tbl in _GRANT_TABLES:
            await conn.execute(text(
                f"GRANT SELECT, INSERT, UPDATE, DELETE ON {tbl} TO {_RLS_TEST_ROLE}"
            ))
        # RLS-ENABLED guard：reviewer round-1 medium suggestion — pre-req (alembic migrate)
        # 没跑时，GRANT 仍成功但 RLS 未开 → 跨租户测试可能因 "查询者没数据" 而非 "RLS 过滤"
        # 误 PASS，调试时失败消息会指向 "RLS 失效" 假象。本 assert 把"前置不满足"显式化。
        result = await conn.execute(text(f"""
            SELECT c.relname
            FROM pg_class c
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = 'public'
              AND c.relname = ANY(:tables)
              AND NOT c.relrowsecurity
        """), {"tables": list(_GRANT_TABLES)})
        not_rls_enabled = [row[0] for row in result.fetchall()]
        assert not not_rls_enabled, (
            f"RLS 未在以下表 ENABLE：{not_rls_enabled} — 先跑 "
            f"./scripts/migrate-all.sh --include-legacy 应用 v056 NULLIF guard 升级"
        )
    try:
        yield eng
    finally:
        await eng.dispose()


@pytest_asyncio.fixture
async def session_factory(engine):
    return async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


@pytest_asyncio.fixture(autouse=True)
async def _cleanup(engine):
    """每 test 前后清 7 表 — 绕 RLS + 绕 FK（双重 set 都需 superuser 权限）。

    用 `SET LOCAL` 防污染 connection（pool 复用），用 DELETE 顺序按 FK 拓扑
    （payments → orders 优先；其余 5 表独立）。session_replication_role=replica
    bypass FK 是兜底（若有其他表 FK 到 7 P0 表本测试未覆盖到）。
    """
    async def _do_cleanup():
        async with engine.begin() as conn:
            await conn.execute(text("SET LOCAL row_security = off"))
            await conn.execute(text("SET LOCAL session_replication_role = replica"))
            for tbl in _P0_TABLES:
                await conn.execute(text(f"DELETE FROM {tbl}"))
    await _do_cleanup()
    yield
    await _do_cleanup()


async def _open_session_with_tenant(session_factory, tenant_id: str) -> AsyncSession:
    """开 session + SET LOCAL ROLE 非 superuser + 设 app.tenant_id GUC（事务级）。

    SET LOCAL ROLE: 必须在第一个业务 SQL 前；事务级 rollback 时自动清理。
    set_tenant_guc: 设事务级 app.tenant_id，与 init-rls.sql policy 模板对齐。

    返回未提交 session — 调用方负责 commit + close（context manager 友好）。
    """
    session = session_factory()
    await session.execute(text(f"SET LOCAL ROLE {_RLS_TEST_ROLE}"))
    await set_tenant_guc(session, tenant_id)
    return session


# ──────────────────────────── 7 P0 表 INSERT helpers ────────────────────────────


async def _insert_store(s: AsyncSession, tenant_id: str) -> str:
    """stores: 7 P0 表中 5 表的 FK target — 必须先插入再插入子表。

    用 CAST(:p AS uuid) 而非 :p::uuid — SQLAlchemy text() 跟 `::` cast 语法冲突
    （:name::type 被截断 param 名）；CAST 是标准 SQL，asyncpg 也接。
    """
    store_id = str(uuid.uuid4())
    await s.execute(text("""
        INSERT INTO stores (id, tenant_id, store_name, store_code)
        VALUES (CAST(:id AS uuid), CAST(:tid AS uuid), :name, :code)
    """), {
        "id": store_id,
        "tid": tenant_id,
        "name": f"门店-{uuid.uuid4().hex[:8]}",
        "code": f"STR-{uuid.uuid4().hex[:12]}",
    })
    return store_id


async def _insert_order(s: AsyncSession, tenant_id: str) -> str:
    """orders: NOT NULL 业务列 = order_no UNIQUE / store_id FK→stores / total_amount_fen"""
    store_id = await _insert_store(s, tenant_id)
    order_id = str(uuid.uuid4())
    await s.execute(text("""
        INSERT INTO orders (id, tenant_id, order_no, store_id, total_amount_fen)
        VALUES (CAST(:id AS uuid), CAST(:tid AS uuid), :no, CAST(:sid AS uuid), 8800)
    """), {
        "id": order_id,
        "tid": tenant_id,
        "no": f"ORD-{uuid.uuid4().hex[:12]}",
        "sid": store_id,
    })
    return order_id


async def _insert_payment(s: AsyncSession, tenant_id: str) -> str:
    """payments: FK to orders.id（必须同 tenant 先建 order）"""
    order_id = await _insert_order(s, tenant_id)
    payment_id = str(uuid.uuid4())
    await s.execute(text("""
        INSERT INTO payments (id, tenant_id, order_id, payment_no, method, amount_fen)
        VALUES (CAST(:id AS uuid), CAST(:tid AS uuid), CAST(:oid AS uuid), :no, 'cash', 8800)
    """), {
        "id": payment_id,
        "tid": tenant_id,
        "oid": order_id,
        "no": f"PAY-{uuid.uuid4().hex[:12]}",
    })
    return payment_id


async def _insert_customer(s: AsyncSession, tenant_id: str) -> str:
    """customers: primary_phone UNIQUE"""
    customer_id = str(uuid.uuid4())
    await s.execute(text("""
        INSERT INTO customers (id, tenant_id, primary_phone)
        VALUES (CAST(:id AS uuid), CAST(:tid AS uuid), :phone)
    """), {
        "id": customer_id,
        "tid": tenant_id,
        "phone": f"139{uuid.uuid4().hex[:8]}",
    })
    return customer_id


async def _insert_ingredient(s: AsyncSession, tenant_id: str) -> str:
    """ingredients: store_id FK→stores / ingredient_name / unit / min_quantity 全 NOT NULL"""
    store_id = await _insert_store(s, tenant_id)
    ingredient_id = str(uuid.uuid4())
    await s.execute(text("""
        INSERT INTO ingredients (id, tenant_id, store_id, ingredient_name, unit, min_quantity)
        VALUES (CAST(:id AS uuid), CAST(:tid AS uuid), CAST(:sid AS uuid), :name, 'kg', 1.0)
    """), {
        "id": ingredient_id,
        "tid": tenant_id,
        "sid": store_id,
        "name": f"食材-{uuid.uuid4().hex[:8]}",
    })
    return ingredient_id


async def _insert_settlement(s: AsyncSession, tenant_id: str) -> str:
    """store_daily_settlements: store_id FK→stores / biz_date / settlement_no UNIQUE"""
    store_id = await _insert_store(s, tenant_id)
    settlement_id = str(uuid.uuid4())
    await s.execute(text("""
        INSERT INTO store_daily_settlements (id, tenant_id, store_id, biz_date, settlement_no)
        VALUES (CAST(:id AS uuid), CAST(:tid AS uuid), CAST(:sid AS uuid), CURRENT_DATE, :no)
    """), {
        "id": settlement_id,
        "tid": tenant_id,
        "sid": store_id,
        "no": f"SET-{uuid.uuid4().hex[:12]}",
    })
    return settlement_id


async def _insert_dish(s: AsyncSession, tenant_id: str) -> str:
    """dishes: dish_name / dish_code UNIQUE / price_fen NOT NULL"""
    dish_id = str(uuid.uuid4())
    await s.execute(text("""
        INSERT INTO dishes (id, tenant_id, dish_name, dish_code, price_fen)
        VALUES (CAST(:id AS uuid), CAST(:tid AS uuid), :name, :code, 3800)
    """), {
        "id": dish_id,
        "tid": tenant_id,
        "name": f"菜品-{uuid.uuid4().hex[:8]}",
        "code": f"DSH-{uuid.uuid4().hex[:12]}",
    })
    return dish_id


async def _insert_employee(s: AsyncSession, tenant_id: str) -> str:
    """employees: store_id FK→stores / emp_name / role NOT NULL"""
    store_id = await _insert_store(s, tenant_id)
    employee_id = str(uuid.uuid4())
    await s.execute(text("""
        INSERT INTO employees (id, tenant_id, store_id, emp_name, role)
        VALUES (CAST(:id AS uuid), CAST(:tid AS uuid), CAST(:sid AS uuid), :name, 'server')
    """), {
        "id": employee_id,
        "tid": tenant_id,
        "sid": store_id,
        "name": f"员工-{uuid.uuid4().hex[:8]}",
    })
    return employee_id


# Table → INSERT helper 映射（test parameter id 与 _TEST_TABLES 对齐）
_INSERTERS = {
    "orders": _insert_order,
    "payments": _insert_payment,
    "customers": _insert_customer,
    "ingredients": _insert_ingredient,
    "store_daily_settlements": _insert_settlement,
    "dishes": _insert_dish,
    "employees": _insert_employee,
}


# ─────────────────────────────────── tests ───────────────────────────────────


@pytest.mark.parametrize("table", _TEST_TABLES)
class TestRlsRuntimeCrossTenantIsolationTier1:
    """7 P0 表 × cross-tenant 真 PG 反测 — 防止跨租户数据泄露 (USING 子句)。"""

    @pytest.mark.asyncio
    async def test_tenant_b_cannot_see_tenant_a_writes(self, session_factory, table):
        """{table}: 徐记海鲜 (tenant_A) 写入 → 老北京涮肉 (tenant_B) 完全看不到。

        真业务场景：徐记海鲜店长在 POS 录单后，另一加盟商账号登录看不到任何徐记数据。
        失败语义：RLS USING 失效 → 跨租户数据泄露 → 严重安全事件 (Tier 1 零容忍)。
        """
        tenant_a = str(uuid.uuid4())
        tenant_b = str(uuid.uuid4())

        # tenant_A 写入并提交
        async with await _open_session_with_tenant(session_factory, tenant_a) as s_a:
            await _INSERTERS[table](s_a, tenant_a)
            await s_a.commit()

        # tenant_B 另开 session 读：必须 0 行 (USING 子句过滤)
        async with await _open_session_with_tenant(session_factory, tenant_b) as s_b:
            result = await s_b.execute(text(f"SELECT COUNT(*) FROM {table}"))
            count = result.scalar()

        assert count == 0, (
            f"RLS USING 失效：{table} 的 tenant_B SELECT 返了 {count} 行 — "
            f"跨租户数据泄露 (tenant_A={tenant_a}, tenant_B={tenant_b})"
        )


@pytest.mark.parametrize("table", _TEST_TABLES)
class TestRlsRuntimeSameTenantVisibilityTier1:
    """7 P0 表 × same-tenant 反测 — 防止 USING 过度过滤 (自己写自己读不到 → 业务路径中断)。"""

    @pytest.mark.asyncio
    async def test_tenant_a_sees_own_writes_in_new_session(self, session_factory, table):
        """{table}: 徐记海鲜店长录单 commit → 同店收银员另开界面必须读到。

        真业务场景：店长在管理台改菜价 commit 后，前台收银员的 POS 界面立刻能查到。
        失败语义：USING 过滤过严 (例：GUC 未设 / role mismatch) → 自家数据看不见 → POS 失能。
        """
        tenant_a = str(uuid.uuid4())

        # 第一个 session：写入并提交
        async with await _open_session_with_tenant(session_factory, tenant_a) as s1:
            await _INSERTERS[table](s1, tenant_a)
            await s1.commit()

        # 第二个 session：同 tenant 读 — 必须能看到
        async with await _open_session_with_tenant(session_factory, tenant_a) as s2:
            result = await s2.execute(
                text(f"SELECT COUNT(*) FROM {table} WHERE tenant_id = CAST(:tid AS uuid)"),
                {"tid": tenant_a},
            )
            count = result.scalar()

        assert count >= 1, (
            f"RLS USING 过度过滤：{table} 的 tenant_A 看不到自己刚提交的行 — "
            f"业务路径中断 (tenant_A={tenant_a})"
        )
