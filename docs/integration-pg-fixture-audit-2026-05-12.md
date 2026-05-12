# Integration-PG Fixture 扩面调研结论（#449）

> 2026-05-12 — 承接 D2b' (#440) 公共子集抽取 + D2c (#460) baseline 落地后的 audit。
> 关联 issue：[#449 docker-compose-pg fixture 扩面到所有 *_rls_*_tier1.py](https://github.com/hnrm110901-cell/tunxiang-os/issues/449)。

---

## TL;DR

**0 in-place 残留** — issue 预期的"扩面"工作实质上已经完成。所有 4 个真 PG fixture
consumer 都已统一使用 `shared.test_utils.integration_pg`，没有任何 in-place 复制
需要迁移。Issue #449 标题的隐含假设（"所有 `*_rls_*_tier1.py` 都需要真 PG fixture"）
与代码现实不符 — 大部分 `*_rls_*_tier1.py` 是静态扫描 / mock 类，本质上不需要
真 PG 入口。

本 audit 落盘判定结果以避免未来 session 再开同类型 issue。

---

## 调研方法

### Step 1：列 `*_rls_*_tier1.py` 全集

```bash
find . -type f -name "*_rls_*_tier1.py" \
  -not -path "*/.tunxiang-p0-worktrees/*" \
  -not -path "*/.claude/*"
```

6 个候选文件（主仓库内）：
- `tests/tier1/test_rls_runtime_p0_tier1.py`
- `tests/tier1/test_rls_all_tables_tier1.py`
- `tests/tier1/test_rls_audit_cli_tier1.py`
- `tests/tier1/test_v382_rls_debt_tier1.py`
- `services/tx-trade/tests/test_rls_isolation_tier1.py`
- `services/tx-trade/src/tests/test_rls_set_local_no_injection_pk0_tier1.py`

### Step 2：扫真 `INTEGRATION_PG_DSN` consumer（不局限于 `*_rls_*` 命名）

```bash
grep -rn "INTEGRATION_PG_DSN" --include="*.py" \
  --exclude-dir=".tunxiang-p0-worktrees" --exclude-dir=".claude"
```

直接 import `shared.test_utils.integration_pg` 的文件（4 个，**不限 `*_rls_*` 命名**）：
- `tests/tier1/test_rls_runtime_p0_tier1.py` ← D2c #460
- `shared/db-migrations/tests/conftest.py` ← D2b' #440（channel-aggregation 3 表 fixture 源）
- `services/tx-analytics/src/tests/test_pinned_dashboard_integration_tier1.py` ← D2b' #440
- `services/tx-brain/src/tests/test_nlq_pg_integration_tier1.py` ← D2b' #440

间接 consumer（通过 `shared/db-migrations/tests/conftest.py` fixture 注入）：
- `shared/db-migrations/tests/test_v411_oauth_tokens_tier1.py`
- `shared/db-migrations/tests/test_v412_raw_channel_events_tier1.py`
- `shared/db-migrations/tests/test_v413_member_identity_map_tier1.py`

仅 docstring 引用、本身是纯单元测试（不需要 fixture）：
- `services/tx-member/src/tests/test_channel_identity_resolver.py`
- `shared/adapters/base/tests/test_oauth_token_store.py`

---

## 6 候选文件性质判定 Matrix

| 文件 | 测试类型 | 用真 PG？ | 状态 |
|---|---|---|---|
| `tests/tier1/test_rls_runtime_p0_tier1.py` | asyncpg + SET LOCAL ROLE + 多 session | ✅ | **D2c #460 已迁移** |
| `tests/tier1/test_rls_all_tables_tier1.py` | regex 静态扫 `shared/db-migrations/versions/*.py` 源码 | ❌ | N/A — 非 integration-pg 类 |
| `tests/tier1/test_rls_audit_cli_tier1.py` | subprocess + 故意 connect-fail DSN 测 CLI 契约 | ❌ | N/A — 测 `scripts/check_rls_policies.py` CLI |
| `tests/tier1/test_v382_rls_debt_tier1.py` | AST 静态扫 v382 migration 源码 | ❌ | N/A — 静态契约 |
| `services/tx-trade/tests/test_rls_isolation_tier1.py` | `unittest.mock` 假 DB + glob 扫 ORM 模型 | ❌ | N/A — mock 类 |
| `services/tx-trade/src/tests/test_rls_set_local_no_injection_pk0_tier1.py` | source grep + regex 扫 `services/` `edge/` | ❌ | N/A — SCA 类 |

**结论**：6 个文件中只有 1 个（`test_rls_runtime_p0_tier1.py`）是真 PG 类，且已通过 D2c #460
迁移到 `shared.test_utils.integration_pg`。其余 5 个 `*_rls_*_tier1.py` 文件本质上不需要 fixture。

---

## 4 个真 consumer 兼容性 Matrix（issue #449 body 框架）

| 假设维度 | D2b' 公共子集 | D2c `test_rls_runtime_p0_tier1.py` | conftest channel-aggregation | tx-analytics `test_pinned_dashboard_integration_tier1.py` | tx-brain `test_nlq_pg_integration_tier1.py` |
|---|---|---|---|---|---|
| Scope | function-scoped | function-scoped engine | function-scoped engine | module-scoped engine | module-scoped engine |
| Transaction | 单事务 + 禁 commit | 多 session + commit-required（POS runtime 真场景） | 单事务 rollback | 多 session + commit + autouse 清理 | 多 session + role 切换 |
| Tenant 切换 | `set_tenant_guc` per-session | ✅ 用公共子集 helper | ✅ 包装 fixture 转 callable | ✅ 用公共子集 helper | ✅ 用公共子集 helper |
| 表覆盖 | channel-aggregation 3 表（DSN/skipif/helper 抽离即可） | 7 P0 业务域 + stores prereq（独立 GRANT） | channel-aggregation 3 表（GRANT 在 conftest） | dashboard_pinned 单表 | 8 reports 视图 + mv_daily_settlement |
| 共享哪些 export | DSN / skipif / `set_tenant_guc` | DSN / skipif / `set_tenant_guc`（自滚 engine/session/cleanup） | DSN / skipif / `set_tenant_guc`（独占 `integration_pg_engine`/`_session` fixture） | DSN / skipif / `set_tenant_guc`（自滚 engine/session/cleanup） | DSN / skipif / `set_tenant_guc`（自滚 engine/session/cleanup） |

**结构性不兼容点**（D2b' 已论证）：
- `integration_pg_engine` / `integration_pg_session` 两个 fixture **不抽到公共子集** — 其
  function-scoped + 单事务 rollback + 仅 channel-aggregation 3 表 GRANT 设计与
  service-level 多 session + commit-required 测试模式不兼容。
- 公共子集**只抽 DSN/skipif/set_tenant_guc 三个最小开销 export**，每个 consumer
  自滚 engine/session/cleanup —— 这是已设计意图，不是技术债。

---

## Issue #449 完成判定

**已完成**。原 issue body 框架（4 假设 Matrix）的隐含目标已经满足：

> 把所有 `tests/tier1/*_rls_*_tier1.py` 系列文件逐个判定 fixture 设计假设是否
> 与 D2b' 公共子集兼容。

逐个判定结果：6 个 `*_rls_*_tier1.py` 中 1 个真 PG（已迁移），5 个非 integration-pg 类（N/A）。
另扫到 3 个非 `*_rls_*` 命名但真 PG 的 consumer，也全部已迁移（D2b' #440 联动）。

后续相关工作的边界：
- **#448** D2c 长尾扩面（更多 P0 业务表的 vertical slice 反测） → 真扩展工作量在这里
- **#450** AST 升级 codemod source-test pairing 检测 → 独立 Tier 3 重构
- **未来**新加 `*_tier1.py` 真 PG 反测：直接 `from shared.test_utils.integration_pg import …`
  即可，无需再读本 audit

---

## 历史溯源

- **2026-05-10 (S5)** `docs/integration-pg-fixture.md` 落地 — 第一次提供 `integration_pg_*`
  fixture 三件套（channel-aggregation 专用）。
- **2026-05-11 (D2b' #440)** 抽公共子集 `shared/test_utils/integration_pg.py`，统一
  conftest / tx-analytics / tx-brain 共 3 处 in-place DSN 读取。
- **2026-05-11 夜深 (#449)** 拆 issue 跟踪持续扩面（本 audit 关闭）。
- **2026-05-12 凌晨 (D2c #460)** D2c vertical slice 落地，`test_rls_runtime_p0_tier1.py`
  接入公共子集，4 consumer 全统一。
- **2026-05-12 (本 audit)** 扫描确认 0 in-place 残留，关闭 #449。
