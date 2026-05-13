# Audit — 全 N 表 RLS 真行为 CI 验证 gap

**日期**：2026-05-13
**类型**：独立调研 / issue 候选
**起源**：CLAUDE memory `MEMORY.md` → 持续技术债条目
**Tier 影响**：Tier 1（RLS 多租户隔离，CLAUDE.md § 13 / § 17）

---

## TL;DR

| 维度 | 数字 |
|---|---|
| 仓库 migration 总数 | **511** |
| migration source 中出现的 `CREATE TABLE` 名 | **485** |
| migration source 中出现的 `ALTER TABLE … ENABLE RLS` 名 | **647**（含 v311/v382/v408 chain 补齐 + 重复条目） |
| 在 CI 真 PG 上验证 RLS USING **运行时**生效的业务表 | **3**（channel-aggregation：`channel_oauth_tokens` / `raw_channel_events` / `member_identity_map`） |
| 本地 opt-in 可跑、CI 0 执行的真 PG RLS 表 | **7 P0 表**（orders / payments / customers / ingredients / store_daily_settlements / dishes / employees） |
| **CI 真 PG RLS 表覆盖率** | **3 / 485 ≈ 0.6%** |

**结论**：全仓 ~485 业务表中，CI 每 PR 实际跑真 PG cross-tenant 反测的只有 3 张（channel-aggregation 域）。其余 482 张表的 RLS USING 子句在 PR 阶段**只被 regex 静态扫描验证语法存在**，不验证运行时行为。Tier 1 § 20 `test_rls_cross_tenant_isolation` 契约在 CI 层**仅以 mock 形态满足**。

---

## 1. 现状证据集（实证）

### 1.1 Tier 1 RLS test suite 实际清单

`tests/tier1/test_rls_*.py` 共 4 个文件：

| 文件 | 类型 | 验证什么 | 是否真 PG |
|---|---|---|---|
| `test_rls_all_tables_tier1.py` | 静态 regex 扫 | migration source 中是否存在 `ENABLE RLS` + `CREATE POLICY` 语法 | ❌ |
| `test_rls_audit_cli_tier1.py` | 静态 + CLI subprocess | `scripts/check_rls_policies.py` 的 DSN 解析、exit code、JSON 输出 — 不连真 DB | ❌（自述：「不测试：真实 DB 查询（需 PG 实例）」） |
| `test_v382_rls_debt_tier1.py` | 静态 regex 扫 | v382 历史 14 表 RLS 补齐的 migration 内容 | ❌（自述：「真实行为验证需要 DB：见 `scripts/check_rls_policies.py`」） |
| `test_rls_runtime_p0_tier1.py` | 真 PG 反测 | 7 P0 表 × cross-tenant + same-tenant = 14 test | ✅ 但 **opt-in via `INTEGRATION_PG_DSN`** |

### 1.2 service-level RLS tier1 test 形态

抽样 5 个 `services/tx-*/test_*rls*_tier1.py`：

| 文件 | 形态 | 备注 |
|---|---|---|
| `services/tx-trade/tests/test_rls_isolation_tier1.py` | **MagicMock / AsyncMock** | 「模拟DB返回混合数据，确认service层过滤或DB层RLS生效」— 实际只验证了 mock 自己的 filter 逻辑 |
| `services/tx-trade/src/tests/test_rls_set_local_no_injection_pk0_tier1.py` | 静态 + UUID 校验 | 防 SQL injection，不连 DB |
| `services/tx-trade/src/tests/test_v395_delivery_dispatches_rls_tier1.py` | 静态扫 migration source | 自述：「不需要真连 DB」 |
| `services/tx-trade/src/tests/test_trade_audit_cross_tenant_tier1.py` | MagicMock / AsyncMock | mock SQLAlchemy session |
| `services/tx-trade/src/tests/test_set_config_canonical_pk01_tier1.py` | 静态 + UUID 校验 | 同上 |

**结论**：service-level RLS tier1 测试**全部是 mock 或静态扫**，没有任何一个连真 PG。

### 1.3 真 PG opt-in consumer 全集（6 个文件，来自 `shared/test_utils/integration_pg.py` docstring + grep 验证）

| 文件 | CI 是否跑 | 覆盖表 |
|---|---|---|
| `tests/tier1/test_rls_runtime_p0_tier1.py` | ❌ 默认 skip，无 workflow 触发 | 7 P0 表 |
| `shared/db-migrations/tests/test_v411_oauth_tokens_tier1.py` | ✅ `integration-pg-tests.yml` | channel_oauth_tokens |
| `shared/db-migrations/tests/test_v412_raw_channel_events_tier1.py` | ✅ 同上 | raw_channel_events |
| `shared/db-migrations/tests/test_v413_member_identity_map_tier1.py` | ✅ 同上 | member_identity_map |
| `services/tx-brain/src/tests/test_nlq_pg_integration_tier1.py` | ❌ 默认 skip | NLQ readonly role |
| `services/tx-analytics/src/tests/test_pinned_dashboard_integration_tier1.py` | ❌ 默认 skip | dashboard pin |

### 1.4 CI workflow 真 PG 触发面

`.github/workflows/integration-pg-tests.yml` 只在以下 paths 触发：

```yaml
paths:
  - 'shared/db-migrations/versions/v41*.py'
  - 'shared/db-migrations/versions/v40*.py'
  - 'shared/db-migrations/tests/test_v41*_tier1.py'
  - 'shared/db-migrations/tests/test_v40*_tier1.py'
  - 'shared/db-migrations/tests/conftest.py'
  - 'services/tx-member/src/services/channel_identity_resolver.py'
  - 'shared/adapters/base/src/oauth_token_store.py'
  - '.github/workflows/integration-pg-tests.yml'
  - 'infra/compose/test-pg.yml'
```

**漏洞**：

1. **不监听 `tests/tier1/test_rls_runtime_p0_tier1.py`** — 7 P0 表的真 PG 测试在 CI 永不执行。
2. **不监听 7 P0 表对应的服务源码** — orders/payments 等核心业务表的 RLS-relevant 改动（route / service / repository）不触发真 PG 反测。
3. **migration paths 锁死在 v40x / v41x** — 新 migration（v414+）的 RLS 行为没有任何 CI 真 PG 验证。
4. **workflow 内 step 也只跑 v411/v412/v413 三个文件** — 即使触发，也不会跑其他 opt-in 真 PG 测试。

### 1.5 `rls-gate.yml` 实际作用

严格门禁但**只针对本 PR 新增的 migration**，且：

- 内部 Python script 是 regex 静态扫（与 `test_rls_all_tables_tier1.py` 同款逻辑，复制粘贴）。
- 末尾 step 再次跑 `test_rls_all_tables_tier1.py`，**仍是静态**。
- 完全不连 PG。

---

## 2. Gap 定量化

### 2.1 业务表数量级

```
CREATE TABLE 总数:            485（含 partition / MV / false-positive）
ENABLE RLS 总数（去重前）:    647
RLS_EXEMPT_TABLES 白名单条数: 65（含 v311 补齐的 26 张历史表）
```

按 `test_rls_all_tables_tier1.py` self-regex（**已知 false-positive 风险**，见 `MEMORY.md` "自写 regex 容易误报"）：

- 历史 RLS 未覆盖表 advisory 上限：100（当前实测 ~50）
- 业务表（含 partition / MV）真实表数：**≈ 400 张**

### 2.2 CI 真 PG 覆盖率

| 类别 | 表数 | 占比 |
|---|---|---|
| 每 PR 跑真 PG（channel-aggregation） | 3 | 0.6% |
| 本地 opt-in（7 P0 表 + nlq + dashboard） | ~10 | 2.5% |
| **CI 0 触及，仅静态 + mock** | **~390** | **97% +** |

### 2.3 假阳性 / 假阴性风险

- **假阴性**（最危险）：migration 写了 `ENABLE RLS` + `CREATE POLICY USING (...)`，但 USING 子句逻辑错误（如 `tenant_id::text = current_setting(...)` 但 tenant_id 是 `uuid`，cast 失败默认 fail-open 或漏过滤）。静态扫**完全测不出**。
- **假阴性 2**：`FORCE ROW LEVEL SECURITY` 未开 → superuser bypass。`test_rls_runtime_p0_tier1.py` 注释明示「屯象 7 P0 表无 FORCE RLS」— 这本身就是一类已知风险。
- **假阴性 3**：v311/v382/v408 补齐的 26+ 张历史表，**没有任何**真 PG 反测验证补齐生效。

---

## 3. 已有基建（不是从零起）

修复 gap 的成本低，因为 channel-aggregation S5 已建好全部基础设施：

| 基建 | 路径 | 用途 |
|---|---|---|
| 真 PG fixture compose | `infra/compose/test-pg.yml` | PG 16 + pgvector，端口 5433 |
| DSN/skipif/GUC helper | `shared/test_utils/integration_pg.py` | 跨 service 共享 |
| bootstrap 脚本 | `scripts/db-bootstrap.sh --skip-create` | apply init-rls.sql / init-pgvector.sql |
| 全 chain migrate 脚本 | `scripts/migrate-all.sh --include-legacy` | alembic upgrade head |
| CI workflow 模板 | `.github/workflows/integration-pg-tests.yml` | PG service container + init-rls + alembic stamp/upgrade |
| RLS 反测 helper 全套 | `tests/tier1/test_rls_runtime_p0_tier1.py` | role / GRANT / cleanup / set_tenant_guc / 多 session |

**缺的只有**：扩面（更多表）+ CI 触发面（让它真跑）+ 跑频率策略（per-PR vs nightly）。

---

## 4. 建议方案（3 选 1）

### Option A：扩 `integration-pg-tests.yml` paths + step（最小动作）

把 7 P0 表纳入每 PR 跑：

```yaml
paths:
  + 'tests/tier1/test_rls_runtime_p0_tier1.py'
  + 'services/tx-trade/src/services/cashier_engine.py'      # orders/payments 主路径
  + 'services/tx-trade/src/services/order_service.py'
  + 'services/tx-member/src/**'                              # customers
  + 'services/tx-supply/src/services/inventory*.py'          # ingredients
  + 'services/tx-org/src/services/employee*.py'              # employees
  + 'services/tx-trade/src/services/dish_service.py'         # dishes (实际在 tx-menu)
  + 'services/tx-ops/src/services/daily_settlement_routes.py' # store_daily_settlements

steps:
  + run: python -m pytest tests/tier1/test_rls_runtime_p0_tier1.py -v --tb=short
```

**成本**：~10 行 YAML 改动 + 已有 fixture 复用。
**收益**：每 PR 14 个真 PG 反测 — 覆盖率 3 → 10 表（**+233%**）。
**风险**：CI 时间 +1~2 min（已有 PG service container，只是多跑 14 test）。

### Option B：新 workflow `rls-runtime-all-tables-nightly.yml`（深度覆盖）

`schedule: cron '0 18 * * *'` + manual dispatch + 改动核心 service 时触发。

跑 **全 N 表 RLS 真行为反测**：

- 扩 `test_rls_runtime_p0_tier1.py` 到全部业务表（参数化）。
- 复用 `_INSERTERS` 模式，新增每张表的最小 INSERT helper（NOT NULL 列填占位）。
- 自动从 `RLS_EXEMPT_TABLES` + MV/partition 黑名单导出"该跑"清单。

**成本**：1 周工作量（写 ~100 个 INSERT helper + parameterize）。
**收益**：CI 真 PG RLS 表覆盖率 0.6% → **>95%**。
**风险**：nightly 失败排查成本（但已知噪音可白名单）；helper 维护负担（新表新加 helper）。

### Option C：opt-in via PR label（务实折中）

加 `pr-check.yml` step：if PR has label `needs-pg-validation` → 跑 `integration-pg-tests.yml` 的全 PG 套件，**包括** `test_rls_runtime_p0_tier1.py`。

**成本**：~30 行 workflow + 文档。
**收益**：Tier 1 / RLS 改动 PR 强制（reviewer 加 label），日常 PR 不付费。
**风险**：依赖人工加 label；忘记加是常态。

---

## 5. 推荐顺序

1. **立即 Option A** — 几行 YAML，零额外基建，把 7 P0 表纳入 per-PR。这是把 `test_rls_runtime_p0_tier1.py` 从「写了不跑」变成「写了就跑」的最小成本动作。
2. **6 周内 Option B** — Week 8 DEMO 门槛 § 22「Tier 1 全绿」必须包括"全 N 表 RLS 真行为"。nightly 是性价比最高的形态。
3. **Option C 可选** — A + B 后这条作用降低，但对偶发的"改了核心 service / 担心 RLS 影响"PR 仍有价值。

---

## 6. 验收标准（acceptance criteria）

任一选项落地后：

- [ ] CI 上 `test_rls_runtime_p0_tier1.py` 状态 **从「never executed」变成「每次 / 每晚 PASS」**
- [ ] 7 P0 表 cross-tenant + same-tenant 14 test 全绿
- [ ] PR 改动 `cashier_engine.py` / 任何含 `set_config('app.tenant_id')` 的代码时**自动触发**真 PG 反测
- [ ] （Option B 完成后）`docs/security/INDEX.md` 加一行「全 N 表 RLS 真 PG 覆盖率 ≥ 95% — nightly verified」
- [ ] 失败时**实际 fail PR**（不是 informational）

---

## 7. 反对意见 / 反驳

| 反对 | 反驳 |
|---|---|
| 静态扫已经够强 | 静态扫只验证语法存在；不验证 `tenant_id::text = current_setting(...)` 在 `uuid` 列上 cast 失败的真实行为。 |
| 真 PG 测试贵、慢 | 已有 `test-pg.yml` + S5 CI workflow 模板，每次跑 ~30 秒（已实测在 `integration-pg-tests.yml`）。 |
| 7 P0 表已覆盖最关键的 | 但 v311/v382/v408 chain 补齐的 **26+ 历史表**完全没 runtime 验证；其中含 `store_lifecycle_stages` / `warehouse_locations` / `inventory_by_location` 等 store-scope 表。 |
| 全 N 表 helper 维护太重 | Option B 工作量集中在一次性写 helper；之后新表加测仅需 1 个新 INSERT helper（~10 行）。 |

---

## 8. 建议 issue body（草稿）

```markdown
**Title**：[Tier1] CI 真 PG RLS 覆盖率仅 0.6%（3/485 表）— 扩 `test_rls_runtime_p0_tier1.py` 到 per-PR

**Why now**：Week 8 DEMO 门槛要求 Tier 1 全绿；当前 `tests/tier1/test_rls_runtime_p0_tier1.py` 写了 14 test 但 CI 永不执行，因 `integration-pg-tests.yml` paths 未监听该文件 + 7 P0 表对应的 service 源码。

**Acceptance**：
- [ ] `integration-pg-tests.yml` paths 新增 `tests/tier1/test_rls_runtime_p0_tier1.py` + 7 P0 表对应 service 路径
- [ ] workflow step 新增 `pytest tests/tier1/test_rls_runtime_p0_tier1.py -v`
- [ ] PR 改动 `cashier_engine.py` 时观察到 `Run integration PG tests` job 跑 14 test 且全绿
- [ ] DEVLOG.md 记录 CI 真 PG RLS 表覆盖率 3 → 10

**Detail**：详见 `docs/audit/rls-pg-fixture-gap-2026-05-13.md`

**Tier**：1（CLAUDE.md § 13 / § 17 RLS 多租户隔离）
**Scope**：CI workflow 改动，零业务代码改动。
```

---

## 附录 A — verify 起手命令

```bash
# 跑 P0 7 表真 PG 反测（确认本地基建可用）
docker compose -f infra/compose/test-pg.yml up -d
DATABASE_URL=postgresql://tunxiang_test:test_password_dev_only@localhost:5433/tunxiang_os_test \
    ./scripts/db-bootstrap.sh --skip-create
DATABASE_URL=postgresql://tunxiang_test:test_password_dev_only@localhost:5433/tunxiang_os_test \
    ./scripts/migrate-all.sh --include-legacy
INTEGRATION_PG_DSN=postgresql://tunxiang_test:test_password_dev_only@localhost:5433/tunxiang_os_test \
    pytest tests/tier1/test_rls_runtime_p0_tier1.py -v --tb=short

# 期望 14 PASS（7 表 × 2 scenarios）

# 销毁
docker compose -f infra/compose/test-pg.yml down -v
```

## 附录 B — 关键文件锚点

| 用途 | 路径 |
|---|---|
| 静态 RLS 扫 | `tests/tier1/test_rls_all_tables_tier1.py` |
| 真 PG 反测（核心） | `tests/tier1/test_rls_runtime_p0_tier1.py` |
| DSN/skipif/GUC helper | `shared/test_utils/integration_pg.py` |
| 真 PG fixture | `infra/compose/test-pg.yml` |
| CI workflow（要扩） | `.github/workflows/integration-pg-tests.yml` |
| CI workflow（静态） | `.github/workflows/rls-gate.yml` |
| Bootstrap 脚本 | `scripts/db-bootstrap.sh` |
| Migrate 脚本 | `scripts/migrate-all.sh` |

## 附录 C — 自写 regex 的 caveat

按 `MEMORY.md` "Claude 注意：自写 regex 容易误报"：

- 本 audit 的 485 / 647 / 50 三个数字来自 self-regex 扫描，**仅作为数量级参考**。
- 真权威数字应跑：
  ```bash
  python3 scripts/check_alembic_chain.py --versions-dir shared/db-migrations/versions
  ```
  以及 PG 实例上的：
  ```bash
  SELECT COUNT(*) FROM pg_class c
  JOIN pg_namespace n ON n.oid = c.relnamespace
  WHERE n.nspname = 'public' AND c.relkind = 'r' AND c.relrowsecurity;
  ```
- 数量级判断（CI 真覆盖 < 1%）不依赖精确数字 — 即便用 200 作为业务表分母，3/200 = 1.5% 仍然是同一结论。
