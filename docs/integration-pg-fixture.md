# Integration PG Fixture — 真 PG 反测基建

> S5（channel-aggregation 基建）2026-05-10 提供。统一 `*_tier1.py` 文件中
> opt-in via `INTEGRATION_PG_DSN` 的真 PG 反测入口。

---

## 解决什么问题

之前仓库里 `*_tier1.py` 含有大量"opt-in via INTEGRATION_PG_DSN"的反测 stub，
但**没有任何 fixture 配套** — 8+ 个反测靠 `pytest.skip("待 INTEGRATION_PG_DSN
fixture 配置后实施")` 占位。本基建提供：

1. `infra/compose/test-pg.yml` — 本地起 PG 16 + pgvector + RLS init 一键脚本
2. `shared/db-migrations/tests/conftest.py` — `integration_pg_session` /
   `integration_pg_engine` / `set_tenant_guc` 三 fixture
3. `.github/workflows/integration-pg-tests.yml` — PR 触发的 CI workflow
4. 8 个 channel-aggregation 真 PG 反测落地（v411 / v412 / v413 共 8 stub 全实测）

---

## 本地用法

### 1. 启动 PG container

```bash
docker compose -f infra/compose/test-pg.yml up -d
```

容器：
- 镜像：`pgvector/pgvector:pg16`
- 端口：`5433` 映射 `5432`（避免撞主机的 prod PG）
- 用户/密码/库：`tunxiang_test` / `test_password_dev_only` / `tunxiang_os_test`
- init scripts 自动跑：`init-rls.sql`（set_tenant_id 函数）+ `init-pgvector.sql`

### 2. 应用 migration

```bash
cd shared/db-migrations

# 跳过 pre-v409 历史 chain（v301 PRIMARY KEY COALESCE 历史 bug 阻塞 fresh upgrade，
# 属独立 issue 修复 scope；v411/v412/v413 down_revision = v409 不需要更早的）
DATABASE_URL=postgresql://tunxiang_test:test_password_dev_only@localhost:5433/tunxiang_os_test \
  python3 -m alembic stamp v409_fund_settlement_revive

DATABASE_URL=postgresql://tunxiang_test:test_password_dev_only@localhost:5433/tunxiang_os_test \
  python3 -m alembic upgrade head
```

### 3. 跑反测

```bash
INTEGRATION_PG_DSN=postgresql://tunxiang_test:test_password_dev_only@localhost:5433/tunxiang_os_test \
  python3 -m pytest shared/db-migrations/tests/ -v -k real_pg
```

预期：8 个 real_pg 测试全绿。

### 4. 销毁

```bash
docker compose -f infra/compose/test-pg.yml down -v
```

---

## CI 用法

PR 触发 `.github/workflows/integration-pg-tests.yml` — 对以下路径改动自动跑：

- `shared/db-migrations/versions/v40*.py` / `v41*.py`
- `shared/db-migrations/tests/test_v40*_tier1.py` / `test_v41*_tier1.py`
- `shared/db-migrations/tests/conftest.py`
- `services/tx-member/src/services/channel_identity_resolver.py`
- `shared/adapters/base/src/oauth_token_store.py`
- `infra/compose/test-pg.yml`
- 本 workflow 自身

CI 行为（~3 min total）：

1. 起 PG 16 service container
2. 应用 init-rls.sql + init-pgvector.sql
3. `alembic stamp v409 && alembic upgrade head`
4. 跑 v411/v412/v413 全部 tier1 测试
5. 失败时输出 pg_policies 视图便于 debug

---

## Fixtures API

### `integration_pg_engine` (function-scoped)

```python
@pytest_asyncio.fixture
async def integration_pg_engine() -> AsyncGenerator[AsyncEngine, None]:
```

每 test 独立 async engine（pytest-asyncio auto 模式 event loop 与 session-scoped
async fixture 冲突，function-scoped 是稳定方案）。

setup 行为（每 engine 跑一次）：
- `CREATE ROLE tunxiang_rls_app NOINHERIT NOLOGIN`（idempotent）
- GRANT SELECT/INSERT/UPDATE/DELETE 给 channel-aggregation 三表

### `integration_pg_session` (function-scoped)

```python
@pytest_asyncio.fixture
async def integration_pg_session(integration_pg_engine):
```

显式 BEGIN/ROLLBACK 事务包裹每 test，**自动 rollback**，不污染 DB。

关键设计：`SET LOCAL ROLE tunxiang_rls_app` 切到 non-superuser —
Postgres superuser 即便 FORCE ROW LEVEL SECURITY 也能绕过 RLS，
不切角色 RLS 反测会假绿。

### `set_tenant_guc` helper

```python
@pytest.fixture
def set_tenant_guc():
    async def _set(session, tenant_id) -> None:
        await session.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": str(tenant_id)},
        )
    return _set
```

事务级 GUC（`set_config(..., true)` 第三参数）— 事务 rollback 时自动清理。

> 屯象 init-rls.sql 的 `set_tenant_id()` 函数用 FALSE（session 级）—
> 应用 runtime 用法不同。fixture 必须用 TRUE 配合事务隔离。

### `requires_integration_pg` 装饰器

```python
requires_integration_pg = pytest.mark.skipif(
    not os.environ.get("INTEGRATION_PG_DSN"),
    reason=...,
)
```

无 DSN 时跳过反测，统一 reason 文案。fixture 自身也会 skip，
两层冗余防呆。

---

## 反测书写约定

### 1. `async def` + 接 fixture 参数

```python
async def test_real_pg_rls_cross_tenant(
    integration_pg_session, set_tenant_guc,
):
    session = integration_pg_session
    tenant_a = uuid4()
    await set_tenant_guc(session, tenant_a)
    # ... 业务 SQL
```

### 2. JSONB cast 用 `CAST(... AS jsonb)`，不用 `::jsonb`

```python
# ✅ Good
text("INSERT INTO ... VALUES (CAST(:payload AS jsonb))")

# ❌ Bad — SQLAlchemy bind param 与 :: cast 冲突，asyncpg 报 syntax error
text("INSERT INTO ... VALUES (:payload::jsonb)")
```

### 3. RLS 反测必须 `set_tenant_guc` 后再写 INSERT

```python
await set_tenant_guc(session, tenant_a)
await session.execute(insert_stmt, {"tenant_id": tenant_a, ...})
```

否则 `WITH CHECK (tenant_id = current_setting('app.tenant_id'))` 看到 NULL GUC 会拒绝。

### 4. 跨租户写入 → 期待 `pg_policies` 错误

```python
await set_tenant_guc(session, tenant_a)
with pytest.raises(Exception) as exc_info:
    await session.execute(insert_stmt, {"tenant_id": tenant_b, ...})
err = str(exc_info.value).lower()
assert "policy" in err or "row-level" in err or "with check" in err
```

错误关键字三选一容忍 SQLAlchemy 不同版本的包装格式。

---

## 已知限制

1. **完整 chain `alembic upgrade head` 当前不能 fresh PG 跑通** —
   v301 历史 migration 的 PRIMARY KEY COALESCE 表达式 PG 拒绝。
   workaround：`stamp v409 + upgrade` 仅跑 v411-v413 增量。
   完整修复属独立 issue。

2. **session-scoped 事件循环冲突** — pytest-asyncio auto 模式下每 test 独立 event loop，
   session-scoped async engine 跨 loop 报错。已用 function-scoped 规避，
   每 test ~50ms engine 创建开销可接受。

3. **超过 channel-aggregation 三表的反测需扩 conftest** —
   当前 `_RLS_TEST_TABLES` 仅含三表，新增需在 conftest 加表名 + GRANT。

---

## 关联

- S5 PR：（待提）
- Hot-fix 前置 PR #415：v411/v412/v413 RLS INSERT/DELETE policy 语法修复（已 merged）
- Issue 跟踪：alembic 历史 chain `fresh PG upgrade head` 修复（待起）
