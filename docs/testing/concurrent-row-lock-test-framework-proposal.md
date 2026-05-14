# 真 PG 并发 Tier 1 测试框架设计提案 (DRAFT)

| 字段 | 值 |
|------|------|
| 状态 | DRAFT — 待 architect / 创始人评审 |
| 日期 | 2026-05-14 |
| 提议者 | Claude Code (architect agent 分析 + 主代理整合) |
| 关联 audit | `docs/security/tier1-row-lock-audit-2026-05.md` §8.3（正面/负面测试模式） |
| 关联 issues | #532（audit parent，已 closed）/ #535 / #537 / #549 / #557 / #559 / #562 |
| 关联 PR roadmap | PR #544（tx-finance）/ #547（tx-supply）/ #553（payment_saga）/ #556（cashier）/ #560（order）/ #563（delivery） |
| 触发 | 6-PR row-lock fix roadmap 全 mock，无任何真 PG race 验证；CLAUDE.md §22 Week 8 "P99 < 200ms (200 桌并发)" 行为门槛 missing |

---

## 1. 背景与问题

CLAUDE.md §17 把 8 条 Tier 1 路径标"零容忍"，§22 把 Week 8 验收门槛锁在"P99 < 200ms / 支付成功率 > 99.9% / 200 桌并发"。但**现有 Tier 1 测试 100% mock-driven**：

- 6-PR row-lock fix roadmap 的全部断言形如 `_select_has_for_update(stmt)`（`services/tx-trade/tests/test_cashier_engine_row_lock_tier1.py:54-69`）— 编译 SQL grep "FOR UPDATE" 字符串，**不进 PG，无 race**
- audit doc `docs/security/tier1-row-lock-audit-2026-05.md` §8.3 已点明"用 `pytest-postgresql` + asyncio.gather 模拟 N 路并发"，**6-PR roadmap 一条都没实施**
- grep 全仓 `asyncio.gather.*\d{2,}` / `pytest_postgresql` / `pytest-postgresql` 均 0 hit。`asyncio.gather` 仅用于业务并发，非测试

**核心 gap**：FOR UPDATE 行锁的真行为（持锁串行化 / 死锁 / SKIP LOCKED 跨 worker 路由）**从未真 PG 验证**。`feedback_smoke_test_must_verify_functionality.md` 的教训直接套用：mock 全绿 ≠ runtime 正确。

**关键发现（架构师调研 callout）**：仓库**已经有真 PG 反测的基建** — `shared/test_utils/integration_pg.py` + `infra/compose/test-pg.yml` + `integration-pg-tests.yml` + `rls-runtime-p0-pg-tests.yml` + `tests/tier1/test_rls_runtime_p0_tier1.py`（413 行 service-level multi-session 范本）。本提案应在此基建上**横向扩展到行锁**，而非另起炉灶。

---

## 2. 现状分析

### 2.1 现有 mock 模式（4 个 row-lock test 文件）

| 文件 | 行数 | 模式 |
|------|------|------|
| `services/tx-trade/tests/test_cashier_engine_row_lock_tier1.py` | 307 | `_build_db_capture` capture stmt + SQL grep |
| `services/tx-trade/tests/test_order_service_row_lock_tier1.py` | 360 | 同上（含 #559 XFAIL 守护） |
| `services/tx-trade/tests/test_payment_saga_row_lock_tier1.py` | 264 | raw SQL `text()` Call 参数 grep |
| `services/tx-trade/tests/test_delivery_adapter_row_lock_tier1.py` | 395 | 同上 + IntegrityError race 兜底 |
| `services/tx-supply/tests/test_inventory_io_row_lock_tier1.py` | ~200 | `_build_db_mock` + Select grep |
| `services/tx-supply/tests/test_auto_deduction_row_lock_tier1.py` | 489 | 同上（含 #549 跨 dish ABBA 守护） |

**共性**（见 `services/tx-trade/tests/test_cashier_engine_row_lock_tier1.py:109-145` `_build_db_capture`）：

- `AsyncMock()` 包 `execute` → `captured.append(stmt)` → `scalar_one_or_none` 返回 mock Order
- 断言 `_select_has_for_update(stmt)` — SQLAlchemy postgresql dialect compile grep "FOR UPDATE"
- **优点**：本地 0.01s/test、CI tier1-gate ~10 包 minimal install 直接跑、无 PG 依赖
- **缺点**：**不证明锁真生效**。SQL 含 `FOR UPDATE` 字符串 ≠ 两 worker 真串行化。`_calc_order_cost`、`_release_table` 都被 AsyncMock 桩掉，业务因果链断（见 `services/tx-trade/tests/test_cashier_engine_row_lock_tier1.py:224, 260`）

### 2.2 现有真 PG 基建（已 ship，未被 row-lock 复用）

- `shared/test_utils/integration_pg.py:39-78` — 导出 `INTEGRATION_PG_DSN` + `requires_integration_pg` skipif + `set_tenant_guc()` 事务级 GUC
- `infra/compose/test-pg.yml` — pgvector/pg16 起在 :5433 不撞主 PG，自动 mount `init-rls.sql` + `init-pgvector.sql`
- `tests/tier1/test_rls_runtime_p0_tier1.py:1-100` — 413 行 service-level multi-session 范本，**每 phase 独立 session**（A 写 commit 关 → B 读关 → A 另开看），`SET LOCAL ROLE tunxiang_rls_app` 切非 superuser 让 RLS USING 真生效。**这正是行锁测试需要的模式 — 已经写好**
- `.github/workflows/rls-runtime-p0-pg-tests.yml:46-77` — PG service container + alembic upgrade head from v001 base 完整 chain（~3-5 min）+ verify 7 P0 表 RLS enabled

### 2.3 conftest 复杂度

`services/tx-trade/conftest.py:24-51` 已设 ROOT/SRC sys.path + 三 namespace pkg (`services.tx_trade`, `services.tx_trade.src`, `services.tx_trade.src.<sub>`)。**新框架 fixture 必须与此共存，不能引入 conftest 二次冲突**（`feedback_pytest_stub_setdefault_pitfall.md` 教训）— 这是为什么 `shared/test_utils/integration_pg.py:1-25` 的 docstring 故意**不导出 engine/session fixture**，留给各 test 自己滚。本提案沿用该约束。

---

## 3. Library 选型对比

| 选项 | 优 | 劣 | CI 兼容 | 评级 |
|------|----|----|---------|------|
| **复用现有 `infra/compose/test-pg.yml` + service container**（已 ship） | 0 新依赖；已有 2 个 CI workflow + 1 个 service-level 范本 413 行；本机 docker compose up + DSN env var 即可 | 需要 docker / PG service container；冷启 alembic upgrade head ~3-5 min | ✅ 与 `integration-pg-tests.yml` / `rls-runtime-p0-pg-tests.yml` 同模式 | **推荐** |
| `pytest-postgresql` | 自动起 ephemeral PG fixture；脚本化 init | 加 1 个依赖；与现有 service container 模式 fragmentation；需 PG binary 在 CI runner 上（ubuntu-latest 自带 PG，但版本可能漂） | 需扩 tier1-gate 安装 | 弃用（fragmentation） |
| `testcontainers-python` | docker 起容器；隔离强 | docker-in-docker 复杂；启动慢 (~10s/container)；CI runner 必须开 docker；与 service container 重复 | 复杂 | 弃用 |
| `pgmock` | 纯 Python，无 PG 依赖 | 不支持 FOR UPDATE / 真锁语义 — 直接 disqualified | n/a | 弃用（不满足需求） |

**结论：复用 service container 模式**。`pgvector/pgvector:pg16` image + `init-rls.sql` 自动 mount + alembic upgrade head 全 chain — 已经验证可行（`rls-runtime-p0-pg-tests.yml` round-3 ship）。**0 新依赖**。

---

## 4. Fixture 架构设计

5 维度设计：

### 4.1 生命周期 — module-scoped engine + function-scoped session

参照 `tests/tier1/test_rls_runtime_p0_tier1.py`（D2b' docstring 已论证）。**function-scoped engine 在 pytest-asyncio 跨 loop 会 `Future attached to a different loop`**（D2b' 实战教训）。但本框架是行锁测，需要**多并发 session 同时跑**，所以：

- `engine`：module-scoped，全 module test 共用
- `sessionmaker`：module-scoped
- 并发场景：**N 个独立 session**（`async_sessionmaker.begin()` per worker），让真 transaction 隔离触发 FOR UPDATE 互斥

### 4.2 Alembic migrations

**两套策略**：

- **CI**：`alembic upgrade head` from v001 base，cache PG data volume（actions/cache 给 `$PGDATA`）。冷启 ~3-5 min，缓存命中 ~30s。同 `rls-runtime-p0-pg-tests.yml:113-117`
- **本地**：`scripts/db-bootstrap.sh --skip-create && scripts/migrate-all.sh --include-legacy`（已有），首次 ~5 min，后续 reuse 容器卷秒级

**Trade-off**：targeted subset (only T1 tables) 不可行 — FK 拓扑跨 ~50 表（orders/payments/order_items/dishes/ingredients/stores/employees/wine_storage_records/biz_wine_storage/invoices/...），裁剪比全 upgrade 维护成本高。

### 4.3 RLS setup

每 session 进入前调 `await set_tenant_guc(session, TENANT_A)`（`shared/test_utils/integration_pg.py:66-78`，事务级 GUC，rollback 自动清）。**`SET LOCAL ROLE tunxiang_rls_app` 切非 superuser**（`tests/tier1/test_rls_runtime_p0_tier1.py:90` `_RLS_TEST_ROLE`）— Tier 1 行锁测必须这样切，否则 superuser 默认 bypass RLS，FOR UPDATE 锁的语义因 RLS USING 子句不生效会失真。

### 4.4 Seed 数据 — 直接 INSERT 不走 ORM

- factory_boy / SQLAlchemy ORM `add()` 会走业务 model 的 `__init__` 验证，对 row-lock 测试加噪声
- 直接 `session.execute(text("INSERT INTO orders ..."))` 最稳，参照 `tests/tier1/test_rls_runtime_p0_tier1.py` autouse cleanup 模式 + autouse `seed_phase` fixture
- Cleanup：`SET row_security = off; SET session_replication_role = replica; TRUNCATE ... CASCADE`（绕 RLS + 绕 FK）

### 4.5 异步 session 桥接

`create_async_engine(dsn, pool_size=20, max_overflow=10)` — pool_size 必须 >= 测试并发 N（默认 10 桌并发够，扩到 200 桌时 pool_size=50 + max_overflow=200）。`async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)`。

---

## 5. Concurrent Runner API

新增 `shared/test_utils/concurrent_runner.py`（~80 行）：

```python
async def run_concurrent(
    sessionmaker: async_sessionmaker,
    tenant_id: UUID,
    n: int,
    operation: Callable[[AsyncSession], Awaitable[T]],
    *,
    timeout_sec: float = 10.0,
    role: str = "tunxiang_rls_app",
) -> list[T | BaseException]:
    """N 路并发跑 operation，各 worker 独立 session + 独立 transaction.

    每 worker:
      1. async with sessionmaker() as session:
      2. await session.execute(text(f"SET LOCAL ROLE {role}"))
      3. await set_tenant_guc(session, tenant_id)
      4. result = await operation(session)
      5. await session.commit()  # 故意 commit 让 FOR UPDATE 持锁 + 释放真触发

    返回 list[result | Exception]，asyncio.gather(return_exceptions=True).
    """

async def assert_final_consistency(
    session: AsyncSession,
    table: str,
    where: dict,
    expected: dict,  # {"count": int, "sum_fen": int, "status_set": set[str]}
) -> None:
    """最终一致性断言 — 跑完并发后单 session 查实际状态比对预期"""
```

**典型使用**（200 桌并发结账）：

```python
async def settle(session):
    eng = CashierEngine(db=session, tenant_id=str(TENANT_A))
    return await eng.settle_order(
        order_id=str(ORDER_ID),
        payments=[{"method": "cash", "amount_fen": 10000}],
    )

results = await run_concurrent(sessionmaker, TENANT_A, n=10, operation=settle)
# 期望：1 成功，9 抛"订单已结算" / 锁竞争分支
successes = [r for r in results if not isinstance(r, Exception)]
assert len(successes) == 1, f"双结算泄漏：{len(successes)} 笔成功 (期望 1)"
async with sessionmaker() as s:
    await assert_final_consistency(
        s, "payments", {"order_id": ORDER_ID},
        {"count": 1, "sum_fen": 10000},
    )
```

---

## 6. CI 集成

### 6.1 新 workflow（推荐）`tier1-row-lock-concurrent.yml`

**不扩 tier1-gate** — 现 tier1-gate 故意 ~10 包 minimal install（`feedback_tier1_ci_minimal_deps_trap.md`），加 PG service / alembic / asyncpg / psycopg2-binary 会拖慢全部 tier1 PR 的关键路径。

直接抄 `rls-runtime-p0-pg-tests.yml` 骨架：

- `services: postgres: image: pgvector/pgvector:pg16`（已用过的 image）
- `Install deps`: 同 rls-runtime workflow，加 `pytest-asyncio>=0.23 asyncpg structlog cryptography pyyaml`
- `Apply init-rls.sql + init-pgvector.sql`：复用现有 `infra/docker/init-*.sql`
- `Alembic upgrade head`：v001 base 起完整 chain（**接受 ~3-5 min**，是行锁真验证的必要成本）
- `paths` trigger：6 个 row-lock 源文件（cashier/order/payment_saga/wine_storage/inventory_io/auto_deduction）+ `tests/concurrent/**`（新目录）+ `shared/test_utils/concurrent_runner.py`

### 6.2 Cache 策略

`actions/cache@v5` 加两层：

- `~/.cache/pip` (现有)
- **`/tmp/pg-cache`** — alembic upgrade 完后 `pg_dump` 全 schema + INSERT 0 数据，下次 PR `pg_restore` 跳 alembic chain（从 ~3-5 min 降到 ~30s）。Key: `pg-snapshot-${{ hashFiles('shared/db-migrations/versions/**') }}`。**第 2 期优化**，第 1 期接受 ~5 min

### 6.3 PG binary

GitHub Actions `ubuntu-latest` 自带 PG 14（client），不用 service container 也能跑 client，但 server 需要 service container — 已在 `rls-runtime-p0-pg-tests.yml:46-65` 验证可用。

---

## 7. Adoption 路径

| 顺序 | 文件 | 估时 | 标志性 milestone |
|------|------|------|------------------|
| **1** | `test_cashier_engine_concurrent_tier1.py` （新建，不替换 mock 版） | 1 day | 框架打通端到端：3 P0 路径 (add_item / apply_discount / settle_order) 真 PG 跑 N=10 并发；docker compose 本地通；CI workflow 绿 |
| **2** | `test_payment_saga_concurrent_tier1.py` | 0.5 day | 验证 `FOR UPDATE SKIP LOCKED` 真行为（多 worker 真路由）— payment_saga 唯一用 SKIP LOCKED 的服务 |
| **3** | `test_inventory_io_concurrent_tier1.py` | 0.5 day | 跨服务（tx-supply）验证；加权平均 race 真验证 |
| **4** | `test_auto_deduction_concurrent_tier1.py` | 0.5 day | 死锁防护真验证（`sorted(key=str(ingredient_id))` 在 deduct_for_dish 跨 dish 锁顺序，audit P1 #549 / ADR 0002 已实施） |
| **5** | `test_order_service_concurrent_tier1.py` + `test_delivery_adapter_concurrent_tier1.py` | 1 day | 收尾全 row-lock 路径 |

**Milestone gate**：第 1 步 ship 后，audit doc §8.3 "正面/负面测试模式"标 ✅ 实施完成，6-PR row-lock fix roadmap 后置验证关闭。

**关键设计**：**并行维护，不替换 mock 版**。mock-based `*_row_lock_tier1.py` 留在 tier1-gate 跑（快、稳、本地友好）；concurrent 版进 `tests/concurrent/` 单独 workflow（慢、真、CI-only）。Trade-off 见 §9。

---

## 8. API 范本 — `test_apply_discount_uses_for_update_row_lock` BEFORE / AFTER

### BEFORE（现状 — `services/tx-trade/tests/test_cashier_engine_row_lock_tier1.py:209-238`）

```python
@pytest.mark.asyncio
async def test_apply_discount_uses_for_update_row_lock(self):
    from shared.ontology.src.enums import OrderStatus
    order = _make_order(status=OrderStatus.confirmed.value, total_amount_fen=10000)
    db, captured = _build_db_capture(order)
    eng = _make_engine(db)
    eng._calc_order_cost = AsyncMock(return_value=3000)  # ← 桩掉真业务

    await eng.apply_discount(
        order_id=str(ORDER_ID), discount_type="amount_off",
        discount_value=1000, reason="VIP", approval_id="manual",
    )

    locked_selects = [s for s in captured if _select_has_for_update(s)]
    assert locked_selects, "apply_discount 必须含 FOR UPDATE"
```

**问题**：断言只是"SQL 含 FOR UPDATE 字符串"，不是"两路并发真串行化"。

### AFTER（新框架）

```python
# tests/concurrent/test_cashier_engine_concurrent_tier1.py
import asyncio, uuid, pytest
from shared.test_utils.integration_pg import requires_integration_pg
from shared.test_utils.concurrent_runner import (
    run_concurrent, assert_final_consistency,
)
from .conftest_pg import sessionmaker, seed_order  # 新框架 fixture

pytestmark = [requires_integration_pg, pytest.mark.asyncio]

async def test_apply_discount_serializes_under_n_way_race(sessionmaker, seed_order):
    """收银员打折 + 经理改折扣 — N=10 并发，必须只 1 笔生效，毛利底线 9 次都基于最新数据."""
    order_id = await seed_order(total_amount_fen=10000, status="confirmed")

    async def discount_worker(session):
        from services.tx_trade.src.services.cashier_engine import CashierEngine
        eng = CashierEngine(db=session, tenant_id=str(TENANT_A))
        return await eng.apply_discount(
            order_id=str(order_id), discount_type="amount_off",
            discount_value=1000, reason="并发测试", approval_id="manual",
        )

    results = await run_concurrent(
        sessionmaker, TENANT_A, n=10, operation=discount_worker,
    )

    # 真行为断言（mock 版做不到）：
    successes = [r for r in results if not isinstance(r, Exception)]
    failures = [r for r in results if isinstance(r, Exception)]

    # 1) FOR UPDATE 串行化 → 只 1 笔进 SQL，9 笔可能成功或抛业务异常但顺序确定
    # 2) 最终 discount_amount_fen 必须 = 1000（非 10000，证明无丢更新）
    async with sessionmaker() as s:
        await assert_final_consistency(
            s, "orders", {"id": order_id},
            expected={"discount_amount_fen": 1000, "final_amount_fen": 9000},
        )
    # 3) 折扣明细表只 1 条入库（防双计折扣）
    async with sessionmaker() as s:
        await assert_final_consistency(
            s, "order_discount_logs", {"order_id": order_id},
            expected={"count": 1},
        )
```

**新增能力**：

- 验证 final_amount_fen 真终态（mock 版无法）
- 验证折扣明细表只 1 条（mock 版 `db.add` 是 MagicMock 不计数）
- 验证 9 路并发 worker 真进 PG 真争 FOR UPDATE 锁

---

## 9. 风险 + Tradeoffs

| 维度 | mock-based（现） | real-PG（新） | 决策 |
|------|------------------|---------------|------|
| 单 test 耗时 | 0.01s | 1-3s (N=10) / 10-30s (N=200) | 分两 tier：mock 留 tier1-gate，real-PG 独立 workflow |
| 本地启动 | 零依赖 | docker compose + DSN env | 接受；`infra/compose/test-pg.yml` 已有 |
| CI 资源 | 1 Python job ~30s | + PG service container + alembic upgrade ~5 min | 接受；与 `rls-runtime-p0-pg-tests.yml` 同水位 |
| Flaky 风险 | 0 | 锁超时 / 并发调度抖动可能 sporadic fail | `timeout_sec=10` 默认；超时归 FAIL（不静默 retry）；CI runner 同 box pg + python，延迟稳定 |
| 死锁误报 | 0 | PG 真检测出 deadlock 是 feature 不是 bug | 期望行为：deadlock 抛 `DeadlockDetected`，断言至少 N-1 路应失败 |
| Tier 1 资金回归覆盖 | 部分（仅 SQL 字符串） | 真终态 + 真并发 | real-PG 框架是 §22 Week 8 验收门槛"P99 < 200ms 200 桌"的前置 |
| 维护成本 | 1 套 mock | 2 套并行 | 接受 — 替换 mock 风险更高（mock 已 ship，tier1-gate 信任锚） |

**与 mock 共存策略**：**永久共存**。mock 版回归保护 SQL 含锁；real-PG 版回归保护行为正确。两套语义互补，类比 unit test + integration test 标准分层。

---

## 10. PR 拆分预案

| # | PR 主题 | 范围 | 估时 | 依赖 |
|---|---------|------|------|------|
| **本** | docs(testing): 真 PG 并发 Tier 1 测试框架 proposal | 仅本文档落盘 `docs/testing/concurrent-row-lock-test-framework-proposal.md` | 0.5h | — |
| 1 | infra(test): concurrent_runner + tier1-row-lock-concurrent.yml workflow | `shared/test_utils/concurrent_runner.py` 新增 + `tests/concurrent/conftest_pg.py` engine/sessionmaker/seed fixture + `.github/workflows/tier1-row-lock-concurrent.yml` workflow + `docs/testing/concurrent-runner-howto.md` | 1 day | proposal merged |
| 2 | test(tx-trade): cashier_engine 真 PG 并发 row-lock 反测 — 框架打通示范 | `tests/concurrent/test_cashier_engine_concurrent_tier1.py` 3 P0 路径 N=10 并发；**不删 mock 版** | 1 day | PR 1 |
| 3 | test(tx-trade): payment_saga SKIP LOCKED 跨 worker 路由真测 | `tests/concurrent/test_payment_saga_concurrent_tier1.py` | 0.5 day | PR 1 |
| 4 | test(tx-supply): inventory_io + auto_deduction 并发死锁防护真测 | `tests/concurrent/test_inventory_io_concurrent_tier1.py` + `test_auto_deduction_concurrent_tier1.py`（验证 ADR 0002 #549 跨 dish 锁顺序 + audit P1） | 1 day | PR 1 |
| 5 | test(tx-trade): order_service + delivery_adapter 收尾 | 2 文件 | 1 day | PR 1 |
| 6（可选） | infra(test): PG schema snapshot cache 加速 CI | `pg_dump` schema 缓存，alembic upgrade 从 ~5 min 降到 ~30s | 0.5 day | PR 1-5 ship 后 |

**Carve-out 分类**：infra PR(#1) 走 explicit-ask（动 workflow + 测试基建，超出 11 类 carve-out 范围）；test PR(#2-5) 走 *tier1* 后缀触发 tier1-gate（已涵盖）。

---

## 11. 关联

- **audit 锚点**：`docs/security/tier1-row-lock-audit-2026-05.md` §8.3「正面测试模式」/ §4.1 cashier 全裸 / §4.3 inventory_io 全裸 / §8 6-PR roadmap / §11 §17 决策跟踪表 (PR #628)
- **ADR 0002 关联**：`docs/adr/0002-cross-dish-row-lock-abba.md` §6.2 "follow-up 真 PG 并发 e2e 测" — 本框架第 4 步 PR 实施
- **CLAUDE.md 锚点**：§17（Tier 1 零容忍 + TDD）/ §20（Tier 1 测试标准）/ §22（Week 8 验收 P99 < 200ms 200 桌并发）
- **已有真 PG 基建**：`shared/test_utils/integration_pg.py:39-78` / `tests/tier1/test_rls_runtime_p0_tier1.py:1-100` / `infra/compose/test-pg.yml` / `infra/docker/init-rls.sql` / `.github/workflows/rls-runtime-p0-pg-tests.yml` / `.github/workflows/integration-pg-tests.yml`
- **mock 范本（候选迁移目标）**：`services/tx-trade/tests/test_cashier_engine_row_lock_tier1.py` / `test_order_service_row_lock_tier1.py` / `test_payment_saga_row_lock_tier1.py` / `test_delivery_adapter_row_lock_tier1.py` / `services/tx-supply/tests/test_inventory_io_row_lock_tier1.py` / `test_auto_deduction_row_lock_tier1.py`
- **baseline 严谨范本**：`services/tx-member/src/services/stored_value_service.py`（11 处 `.with_for_update()` 全仓最严谨服务）
- **历史教训**：`feedback_pytest_stub_setdefault_pitfall.md`（不引入 conftest 二次冲突）/ `feedback_smoke_test_must_verify_functionality.md`（mock 全绿 ≠ runtime 正确）/ `feedback_tier1_ci_minimal_deps_trap.md`（不扩 tier1-gate install 列表）

---

## 12. Consensus Addendum

**Antithesis (steelman)**：mock 已覆盖编译 SQL 含 FOR UPDATE 串字符串，FOR UPDATE 在 PG 内部语义是 well-known + 久经考验，"真行为"验证可能只是测试 PG 自己而非业务。CI 5 min × 每 PR 触发是不小的成本。

**反驳**：真要测的不是 PG FOR UPDATE 实现，是**业务代码的事务边界 + helper kwarg 路径 + 死锁排序**。`feedback_post_rebase_caller_audit.md` PR #227 实战：`_get_order` signature 改 `lock=False` 默认后，PR 范围外的 caller 静默从"强制锁"变"无锁"silent P0 — mock 测看 `_select_has_for_update` 全绿但行为破。这就是 real-PG 才能抓的 class of bug。

**Tradeoff tension**：CI 时间 vs 真行为覆盖。**不可两全**。本提案的 reconcile 是 fast/slow 双 tier，不强制全 PR 跑 concurrent workflow（独立 paths filter，仅 row-lock 源文件 + concurrent test 改动触发）。

**Synthesis**：mock 守 SQL 表层（每 PR 跑），real-PG 守行为终态（仅 row-lock 路径 PR 跑）。两层互补，无替换。**这是 §22 Week 8 "P99 < 200ms 200 桌并发"门槛唯一可信的前置验证路径**。

---

## 13. 当前阻塞 + 下一步

**本 proposal merge 后下一步**：

1. **PR-1 (infra)** 起 `shared/test_utils/concurrent_runner.py` + `tests/concurrent/conftest_pg.py` + `.github/workflows/tier1-row-lock-concurrent.yml` — **不动业务源**，纯基建 ship
2. **PR-2 (cashier)** 是框架打通的金标准 — 跑通即 §22 Week 8 验收门槛第一根桩
3. PR-3 / PR-4 / PR-5 按 §7 估时迭代

**不阻塞 §17 桌台并发对齐 PR** — §17 PR 仍可走 mock 路线 ship，real-PG 验证可在 §17 ship 后追溯加固（与 ADR 0002 PR #567 + ADR 文档化 PR #629 同模式）。

**Proposal 状态**：DRAFT，待 architect / 创始人评审签字 → 翻 ACCEPTED → PR-1 启动。
