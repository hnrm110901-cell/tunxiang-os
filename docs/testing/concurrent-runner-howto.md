# `concurrent_runner` Howto — 真 PG N 路并发反测

| 字段 | 值 |
|------|------|
| 状态 | LIVE — PR-1 infra ship (5/14) |
| 关联 proposal | [`concurrent-row-lock-test-framework-proposal.md`](./concurrent-row-lock-test-framework-proposal.md) |
| 关联 CI | `.github/workflows/tier1-row-lock-concurrent.yml` |
| 适用范围 | Tier 1 行锁真行为反测（FOR UPDATE / SKIP LOCKED / 死锁防护） |

---

## 1. 何时用本框架

**用本框架**（真 PG concurrent）:
- 验证 `FOR UPDATE` 真持锁串行化（如 cashier_engine 双结算防泄漏）
- 验证 `FOR UPDATE SKIP LOCKED` 真跨 worker 路由（如 payment_saga recover_pending）
- 验证跨 dish 锁排序真防 ABBA 死锁（如 auto_deduction.deduct_for_order，ADR 0002）
- 验证 §22 Week 8 "P99 < 200ms 200 桌并发" 行为门槛

**不用本框架**（继续用 mock）:
- SQL 表层断言（`FOR UPDATE` 字符串是否出现 — 现有 `_select_has_for_update` mock 测试覆盖）
- 业务逻辑单元测试（无并发依赖）
- helper function unit test

**两套并行维护，不替换**（详 proposal §7 + §9 trade-off 表）。

---

## 2. 本地开发跑法

### 2.1 起 test-pg 容器

```bash
docker compose -f infra/compose/test-pg.yml up -d
```

### 2.2 Bootstrap + Migrate

```bash
DATABASE_URL=postgresql://tunxiang_test:test_password_dev_only@localhost:5433/tunxiang_os_test \
    ./scripts/db-bootstrap.sh --skip-create
DATABASE_URL=postgresql://tunxiang_test:test_password_dev_only@localhost:5433/tunxiang_os_test \
    ./scripts/migrate-all.sh --include-legacy
```

### 2.3 跑 concurrent tests

```bash
INTEGRATION_PG_DSN=postgresql://tunxiang_test:test_password_dev_only@localhost:5433/tunxiang_os_test \
    pytest tests/concurrent/ -v
```

未设 `INTEGRATION_PG_DSN` → 全部 skip（opt-in 模式）。

### 2.4 销毁

```bash
docker compose -f infra/compose/test-pg.yml down -v
```

---

## 3. 写一个 concurrent test（PR-2+ 模板）

### 3.1 文件路径与命名

```
tests/concurrent/test_<service>_concurrent_tier1.py
```

`_tier1.py` 后缀语义关联 CLAUDE.md §22 Week 8 验收门槛；pyproject `testpaths` 不含
`tests/concurrent/`，pytest 默认 collect 不会 import 本目录, 仅
`tier1-row-lock-concurrent.yml` workflow 显式 `pytest tests/concurrent/` 触发。

### 3.2 基本骨架

```python
"""<service> 真 PG 并发 row-lock 反测 — <issue/PR 关联>"""
from __future__ import annotations

import uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.test_utils.concurrent_runner import (
    assert_final_consistency,
    run_concurrent,
)
from shared.test_utils.integration_pg import requires_integration_pg

pytestmark = [requires_integration_pg]


async def test_settle_order_no_double_payment(session_factory):
    """N=10 workers 同时 settle 同一订单 — FOR UPDATE 应只让 1 成功"""
    tenant_a = uuid.uuid4()
    order_id = uuid.uuid4()

    # Setup: 初始 order + items (用 default superuser session, 不进 runner)
    async with session_factory() as s:
        # ... INSERT initial state
        await s.commit()

    async def _settle(s: AsyncSession) -> str:
        # 业务调用（用 service container 或直接调函数）
        from services.tx_trade.src.services.cashier_engine import CashierEngine

        eng = CashierEngine(db=s, tenant_id=str(tenant_a))
        return await eng.settle_order(
            order_id=str(order_id),
            payments=[{"method": "cash", "amount_fen": 10000}],
        )

    results = await run_concurrent(
        session_factory, tenant_a, n=10, operation=_settle
    )

    # 1 成功，9 抛"订单已结算" / 锁竞争分支
    successes = [r for r in results if not isinstance(r, BaseException)]
    assert len(successes) == 1, f"双结算泄漏：{len(successes)} 笔成功"

    # 最终一致性: 表内只有 1 笔 payment
    async with session_factory() as s:
        await assert_final_consistency(
            s, "payments", {"order_id": str(order_id)},
            {"count": 1, "sum_amount_fen": 10000},
        )
```

### 3.3 扩展 `_CONCURRENT_TABLES`

`tests/concurrent/conftest.py` 的 `_CONCURRENT_TABLES` 决定 cleanup 范围。PR-1 默认仅
`stores`。新业务表需:

**方式 A — 主 conftest 直接加入**（推荐 PR-2/3/4/5 简单场景）:

```python
# tests/concurrent/conftest.py
_CONCURRENT_TABLES: tuple[str, ...] = (
    "payments",          # PR-2 新增
    "orders",            # PR-2 新增
    "stores",            # PR-1
)
```

**FK 拓扑顺序**: 子表 → 父表（payments → orders → stores）。当前 `_cleanup` 用
`session_replication_role=replica` 绕 FK 触发器, 即使乱序 DELETE 不 fail, 但若
后续切回 `TRUNCATE ... CASCADE` 模式则要求严格拓扑顺序 — 建议从一开始就维护正确顺序。

**方式 B — 子目录 conftest 覆盖**（需将 module-level 变量重构为 fixture）:

⚠️ **重要**: `_CONCURRENT_TABLES` 当前是 conftest.py 的 **module-level 变量**，**不是 pytest
fixture**。子目录 conftest.py 定义同名 `_CONCURRENT_TABLES` **不会** 被父 conftest 的
`_cleanup` 看到（这是 Python 模块作用域规则, 与 pytest 无关）。要支持子目录覆盖, 需先把
`_CONCURRENT_TABLES` 重构为 fixture, 让 `_cleanup` 通过 fixture 注入接收:

```python
# tests/concurrent/conftest.py  — 重构步骤 (留给 PR-N 实施)
@pytest_asyncio.fixture
def concurrent_tables() -> tuple[str, ...]:
    return ("stores",)


@pytest_asyncio.fixture(autouse=True)
async def _cleanup(engine, concurrent_tables):  # ← 接收 fixture
    async def _do_cleanup():
        async with engine.begin() as conn:
            await conn.execute(text("SET LOCAL row_security = off"))
            await conn.execute(text("SET LOCAL session_replication_role = replica"))
            for tbl in concurrent_tables:
                # ... (to_regclass 守卫 + DELETE FROM)
    await _do_cleanup()
    yield
    await _do_cleanup()


# tests/concurrent/cashier/conftest.py — 子目录 fixture override
@pytest_asyncio.fixture
def concurrent_tables() -> tuple[str, ...]:
    return ("payments", "orders", "order_items", "stores")
```

PR-1 暂未做此重构（YAGNI — 方式 A 足够覆盖 PR-2/3/4/5）；当首次需要"同 workflow 内
分服务测试隔离不同表集"时再做（属 PR-N follow-up）。

### 3.4 扩展 workflow paths

`.github/workflows/tier1-row-lock-concurrent.yml` `on.pull_request.paths` 列已
预含 6 row-lock 源文件（cashier/order/payment_saga/delivery/inventory_io/auto_deduction）。
新服务文件请 PR 内加入 paths。

---

## 4. 常见陷阱

### 4.1 不要共享 session

❌ 错误：

```python
async def _op(s):
    return await some_service.method(s)

# 多 worker 共享同一 s? 不！run_concurrent 为每 worker 独立开 session
```

✅ 正确：`operation` 接收的 `s` 已是该 worker 独立 session。worker 间天然隔离。

### 4.2 别在 setup 阶段进 runner

setup（初始数据写入）应用 `session_factory()` default superuser session（绕 RLS, 跑前置数据准备），
不进 `run_concurrent`。`run_concurrent` 内部 SET LOCAL ROLE 非 superuser + set_tenant_guc,
适合业务路径模拟「runtime 真请求」。

### 4.3 timeout_sec 默认 10s

死锁场景应抛 PG `DeadlockDetected` 异常，被 `gather(return_exceptions=True)` 收回。
若 timeout 抛 `asyncio.TimeoutError` → 业务卡死或锁未释放，应排查。N=200 桌并发场景
可放宽到 30-60s（业务测试自行决定）。

### 4.4 调用方保证 `role` 字面安全

`run_concurrent(..., role=...)` 默认 `tunxiang_rls_app` 已锁定安全；传非默认 role
名需自行保证 SQL 字面安全（不接受用户输入, 白名单字符串）。`SET LOCAL ROLE $1` PG
不支持参数绑定, f-string 拼接是必要权衡。

### 4.5 表名/列名也是字面拼接

`assert_final_consistency(table=..., where={col: val}, expected={...})`: `table` 与
`where` key 串入 SQL（白名单字符串）, `where` value + 参数绑定。调用方传入需保证字面安全。

---

## 5. 与现有 mock 测试的边界

| 维度 | mock `*_row_lock_tier1.py` | concurrent `*_concurrent_tier1.py` |
|------|---------------------------|--------------------------------------|
| 触发 workflow | tier1-gate（~30s） | tier1-row-lock-concurrent（~5min） |
| 跑法 | 本地 0.01s/test | 本地需 docker compose + DSN |
| 验证范围 | SQL 含 `FOR UPDATE` 字符串（编译表层） | 真 PG 持锁/释放/串行化行为终态 |
| 抓 bug 范围 | helper signature 错配 / SQL 缺锁 | runtime 行为 / 死锁 / lost update |
| 维护策略 | 永久共存, 不替换 | 横向扩展 |

详 proposal §9 trade-off 表。

---

## 6. 关联文档

- [`concurrent-row-lock-test-framework-proposal.md`](./concurrent-row-lock-test-framework-proposal.md) — 设计提案（13 节 / 6-PR roadmap）
- [`../security/tier1-row-lock-audit-2026-05.md`](../security/tier1-row-lock-audit-2026-05.md) §8.3 — 正面/负面测试模式（本框架实施 §8.3）
- [`../adr/0002-cross-dish-row-lock-abba.md`](../adr/0002-cross-dish-row-lock-abba.md) §6.2 — auto_deduction 死锁防护真测（PR-4 实施）
- `shared/test_utils/integration_pg.py` — 共享 DSN/skipif/set_tenant_guc helper
- `tests/tier1/test_rls_runtime_p0_tier1.py` — service-level multi-session 范本（互补，测 USING/CHECK 非 FOR UPDATE）
- `.github/workflows/rls-runtime-p0-pg-tests.yml` — 同款骨架 workflow（本 workflow 派生）
