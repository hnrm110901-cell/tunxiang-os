# Migration 架构治理 Rescue Plan (2026-05-10)

> 由 founder 确认后执行。本文档为长期方案的总览 + 阶段拆解 + 决策点登记。

## TL;DR

`shared/db-migrations/` 504 个 alembic migration 自 PR #128 起 chain 断裂，6 周来从未在空 PG 真跑通过。深度 recon (B'-1 至 B'-6, PR #337/#339/#340/#342/#343/#345) 修了 22 个 distinct bug，但**每修一个暴露下一个**，估计仍剩 30-50 个未修。这不是代码质量问题，是 **5 层架构治理缺失** 的复利症状。本计划用 4 阶段一次性偿付：(1) schema baseline squash 一锅端历史债 → (2) CI 硬门禁防新债 → (3) schema linter 静态拦截 → (4) 14 services 共享表名所有权治理（founder 决策 a/b 路线）。

---

## 一、根因诊断

### 1. 多 service 共享表名无所有权治理（最严重）

`approval_instances` 三服务用三种完全不同 schema：

| 服务 | 期望 schema | 来自 |
|---|---|---|
| `tx-org/approval_flow.py` | `flow_def_id + business_type` | v031 |
| `tx-org/approval_flow_engine.py` | `template_id + business_id` | v059 |
| `tx-expense/approval_engine.py` | `application_id + current_node_index` | v235c |

PG 一张表只能有一种 schema → **至多 1 服务能跑通，其他 2 个 runtime 必坏**。

同模式撞名：`banquet_leads` (4 schema) / `delivery_dispatches` (2) / `pos_crash_reports` (2) / `banquet_contracts` (2)。

**根因**：14 services 共用 `shared/db-migrations/` 但缺顶层 schema 治理。每个 service team 写 migration 时不知其他 team 在动什么。

### 2. 无 CI 硬门禁保证 migration 真跑

PR #128 起 chain 断裂，`Verify Migration Chain Integrity` job 一律失败，all migration PR 走 admin override 合并。500+ migration 从未真在空 DB 跑通过 — 这是 process 层面的"集体欺骗"。

证据：v151b PK 含 `COALESCE` / v288 JSON 数字 `:N` / v378 生成列非 IMMUTABLE — 这些 **PG 第一行就拒绝的 syntax bug**，存活了多个月。

### 3. Chain 治理用 copy-paste 替代正确 merge

`v331_banquet_leads.py` = `v315_banquet_leads.py` 字节级复制，仅 revision 元数据不同。v333=v317 / v334=v318 / v335=v319 同模式。alembic 有标准 merge migration（多元素 down_revision tuple，参考 v397/v398），但开发者用 copy-paste — 创造平行副本链。

500+ migrations / 6 周 = ~80 mig/周。**"ship 后忘"心态**：写完 migration 没人跑，下次需要时已 amnesia。

### 4. 单一 mono-repo migration 与 14 services 拓扑错配

alembic 设计给 monolithic app。屯象有 14 services × 9 product domains × parallel branches = 65 历史 head。`v398_merge_35_heads_to_single_chain.py` 是 35 head 一锅端的"绝望式" merge — 治标不治本。

### 5. ORM models 与 migrations 漂移无检测

production code 和 migrations 不强制对齐。v315 schema (`lead_no/status`) 是 ORM 期望的，但 v004 早建过完全不同 schema。**没有 test 检查 ORM model 字段都在 migration 中存在**。

---

## 二、4 阶段方案

### Phase 0: 共识对齐（**本文档**）

**输出**：本 plan + Phase 3 schema linter（同 PR）
**Owner**：你的名字
**时间**：~1 hr（已完成）
**验收**：founder review 本文档，决策 §三 中 3 个开放点

### Phase 1: Schema baseline squash

**目标**：用 production 真实 schema 取代 504 historical migrations 作为 alembic 基线。从此 alembic 在空 PG 上能 `upgrade head` 一次跑通。

**步骤**：
1. founder 用 `pg_dump --schema-only --no-owner --no-privileges` 从 production PG 导出 schema → `v500_baseline_schema.sql`
2. 写 `v500_production_baseline.py` migration：upgrade 跑 `op.execute(open(v500_baseline_schema.sql).read())`；revision 设 `v500`，down_revision 设 None（或某 stamp marker）
3. 历史 migration 文件移到 `shared/db-migrations/versions/_archive/v001_to_v406/` 子目录（alembic 不扫该子目录）
4. 在 alembic env.py 加 conditional：fresh DB → 直接 stamp v500 + 跑 v501+；老 DB（已含 v406 stamp）→ 兼容跳到 v500
5. 后续新 migration 从 v501 开始

**输出**：
- `shared/db-migrations/versions/v500_production_baseline.py`
- `shared/db-migrations/versions/v500_baseline_schema.sql`
- `shared/db-migrations/versions/_archive/` 目录
- `shared/db-migrations/env.py` 兼容老 DB stamp 逻辑

**Owner**：你的名字
**时间**：4-8 hr（含 founder 提供 prod pg_dump）
**前置**：founder 提供 production prod pg_dump（决策点 2）

**验收**：
- fresh pgvector PG 跑 `alembic upgrade head` 一次到 v500（或 head）全绿，<60 秒
- 现有 production DB 升级到 v500 不丢数据（可选 dry-run on staging）
- 解锁 A 任务（docker-compose-pg fixture for RLS 反测）

**风险**：
- production schema 可能包含 dev/test 残留表 — 需 audit
- 若已有未发布的 v407+ 计划改动，需在 baseline 上重做
- 历史 migration archive 后不可降级（alembic downgrade head 报错）— 需明确放弃 downgrade 兼容性

### Phase 2: CI 硬门禁

**目标**：每个新 migration PR 必须在 fresh PG 跑 `alembic upgrade head` 全绿才能合。Admin override 关闭（除非 founder 显式授权）。

**步骤**：
1. `.github/workflows/migration-ci.yml` 加 `fresh-pg-upgrade-test` job：
   - service: `pgvector/pgvector:pg16`
   - 跑 `alembic upgrade head` 在空 DB
   - timeout 5min（baseline squash 后真实运行 < 60s，5min 给充足 buffer）
   - fail 阻塞 PR（`required` status check）
2. 在 GitHub branch protection 配 main 分支 require this check
3. 移除 `KNOWN_BROKEN` allow-list（已在 PR #337 排空，本步固化）

**输出**：
- `.github/workflows/migration-ci.yml` 含 `fresh-pg-upgrade-test` job
- main 分支 branch protection 配置（GitHub UI 或 admin）

**Owner**：你的名字
**时间**：2-4 hr
**前置**：Phase 1 完成（baseline squash 后 chain 才能真跑通）

**验收**：
- 新建一个故意引入 PG syntax error 的 migration PR → CI fail，不可合
- 修复后 → CI pass，可合
- 现有未合 PR rebase 到 baseline 后 CI 全绿

### Phase 3: Schema linter（**本 PR**）

**目标**：静态扫描 migration 文件，检测 7 类 bug 模式（B'-1 至 B'-6 暴露），新 PR 引入这些模式直接 fail。**本 phase 在本 PR 中实现**，不依赖 Phase 1。

**检测规则**：

| 类 | 模式 | 检测 |
|---|---|---|
| A | 同名表多 schema 撞名 | 扫所有 `CREATE TABLE [IF NOT EXISTS] <name>`，按表名 group，>1 文件创建同表名 → fail |
| B | `server_default="'{}'"` JSONB 引号嵌套 | 正则 `server_default="'.*'"` |
| C | `sa.text("...:p::T")` cast 与命名参数歧义 | 正则 `sa\.text\(.*?:\w+::\w+` |
| D | `PRIMARY KEY (... 函数(`  表达式 PK | 正则 `PRIMARY KEY[^,]*,[^)]*[A-Z_]+\(` |
| F | `CREATE POLICY IF NOT EXISTS` (PG 不支持) | 正则 `CREATE POLICY IF NOT EXISTS` |
| F | `FOR INSERT TO PUBLIC USING` (无 WITH CHECK) | 正则匹配 |
| G | `GENERATED ALWAYS AS (... STABLE_FUNC ...) STORED` | 正则匹配 STABLE 函数（`age` `current_date` `now` `current_timestamp` `date_trunc`） |
| G | `CREATE INDEX ... ((STABLE_FUNC...))` | 同上 |

**输出**：
- `shared/db-migrations/tests/test_schema_lint_tier1.py` 含 7 个独立断言
- `docs/migration-schema-lint-rules.md` 详细规则说明 + 修复指引

**Owner**：你的名字
**时间**：2-4 hr（本 PR）
**前置**：无

**验收**：
- 现有 22 个已修 bug 的 violations grandfathered（已修复的不应触发）
- 新 PR 引入这些模式之一 → linter fail
- 整合到 `python -m pytest shared/db-migrations/tests/` 默认跑

### Phase 4: 架构去耦 — **路线 a 选定（2026-05-10）**

> founder 决策：**选 a — Per-service migrations**。

#### 路线 a 子阶段

##### Phase 4a-1: Table ownership audit（**已完成**，本 PR）

`docs/migration-architecture-route-a-ownership-audit.md`：471 张表 grep `services/*/src/` 推断 owner。

| Confidence | 数量 | 处理 |
|---|---|---|
| `clear`（单 service ≥3 文件命中）| 126 | 自动入册 |
| `weak`（单 service 1-2 文件命中）| 298 | 人工抽查 |
| `ambiguous`（多 service 同等命中）| 26 | **founder 决策** |
| `shared`（无 service 命中）| 21 | 入 `shared/db-migrations-core/` |
| `multi-creator`（类 A 撞名）| 25 | **founder 决策保留哪个** |

候选 owner 列表：13 个 service + `gateway` + `shared/core` + 数个 composite（待 disambiguate）。

##### Phase 4a-2: Founder review + ambiguity 决策

founder 必须在 Phase 4a-3 起手前 review audit 文档：
1. 26 个 ambiguous 表逐一选 owner
2. 25 个 multi-creator 撞名表选保留 schema
3. 298 个 weak 表抽查 ~30 个验证 owner 准确性
4. 21 个 shared 表确认是否真共享

**输出**：`docs/migration-architecture-route-a-ownership-audit.md` 增 founder 决策标注（每行加 ✓/重新 owner/拆表 etc.）

时间：1-2 day（founder 工作）

##### Phase 4a-3: Per-service alembic 骨架

为每个 service + shared/core 建独立 alembic 配置：

```
services/tx-trade/db-migrations/
  alembic.ini           # version_table_name = tx_trade_alembic_version
  env.py
  versions/             # 起始空
  tests/
services/tx-org/db-migrations/
  ...
[14 services × 1 alembic each]

shared/db-migrations-core/  # 跨 service 共享（tenants / RLS / ENUMs）
  alembic.ini           # version_table_name = core_alembic_version
  env.py
  versions/
```

每个 alembic 用独立 `version_table` 隔离 stamp。

时间：2-4 hr

##### Phase 4a-4: Per-service baseline schema

founder 提供 production `pg_dump --schema-only`（决策点 2）。
按 ownership audit 拆 dump 为 14 个服务 baseline + 1 core baseline：

```
services/tx-trade/db-migrations/versions/
  v_001_baseline.py      # 跑 v_001_baseline.sql，里面是 tx-trade 拥有的表
  v_001_baseline.sql
shared/db-migrations-core/versions/
  c_001_baseline.py      # tenants / brand_groups / RLS infra / ENUMs
  c_001_baseline.sql
```

时间：4-8 hr

##### Phase 4a-5: 部署 / fixture / CI orchestration

Fresh DB 启动顺序：
1. `shared/db-migrations-core` upgrade（infra）
2. 14 services 并发 upgrade（独立）

```bash
# scripts/db-migrate-all.sh
alembic -c shared/db-migrations-core/alembic.ini upgrade head
for svc in tx-trade tx-org tx-expense ...; do
  alembic -c services/$svc/db-migrations/alembic.ini upgrade head &
done
wait
```

更新：
- `infra/compose/base.yml` migrate 命令改并发
- `.github/workflows/migration-ci.yml` 14 services 各跑 upgrade head
- `scripts/db-bootstrap.sh` fresh PG 一键启动

时间：4-8 hr

##### Phase 4a-6: Production cutover

production DB 已含旧 `alembic_version` (v406 stamp)：
1. 创建新 `<svc>_alembic_version` 表（每 service）
2. stamp 各 service 的 `v_001_baseline`（不真跑 SQL，只 stamp）
3. 旧 `alembic_version` 标 deprecated（保留 reference 防回滚）
4. 后续 service migrations 从 `v_002+` 起

时间：2-4 hr（含 dry-run on staging）

##### Phase 4a-7: 旧 mono-repo migration archive

```
shared/db-migrations/_archive/v001_to_v406/
```

archive 后该目录不被任何 alembic 配置扫描；保留 git history 作为 reference。

时间：30 min

#### 路线 a 总时间表

| 子阶段 | 时间 | 触发 |
|---|---|---|
| 4a-1 audit | 已完成 | — |
| 4a-2 founder review | 1-2 day | founder 工作 |
| 4a-3 alembic 骨架 | 2-4 hr | 4a-2 完成 |
| 4a-4 baseline schema | 4-8 hr | 决策点 2 + production pg_dump |
| 4a-5 部署 orchestration | 4-8 hr | 4a-4 完成 |
| 4a-6 production cutover | 2-4 hr（+staging dry-run） | 4a-5 完成 |
| 4a-7 archive | 30 min | 4a-6 完成 |

**总计**：~3-4 天工程时间 + 1-2 天 founder review = ~1 周

#### 路线 a 风险

- **跨 service 表 owner 误判**：导致 service 自启时找不到自己依赖的表 → service crash。缓解：staging 全套 service smoke test，audit 文档严格 review
- **service 间 schema 不可见性**：tx-trade 改 orders 表，tx-analytics 不知 → ORM 漂移。缓解：定期 schema diff CI（独立 PR）
- **跨 service join 仍存在**：service A 的 ORM model 引用 service B 的表（虽然不该）。缓解：grep audit + 拆 service 边界（独立 PR）
- **Production cutover 风险**：stamp 错版本 → migration 重跑或漏跑。缓解：staging dry-run 全程，PITR snapshot 兜底
- **cross-cutting 表（如 RLS Policy）**：放 shared/core 但需各 service 在自己 baseline 中 ENABLE RLS — 边界需明确

#### 路线 a 不在范围

以下问题**route a 不解**，需独立 issue 跟进：

- `approval_instances` 三 schema 撞名 — Phase 4a-2 audit 决策保留哪个（实际意味着另两 service runtime 失败 → 重 schema 或 rename）
- ORM models 与 migrations 漂移检测 — 独立 PR (类似 alembic check 但 ORM-aware)
- Cross-service event bus / 事件源（CLAUDE.md §15）— 与 schema ownership 正交

---

### 路线 b — Shared DB + 强治理（**未选**，作 reference 保留）

保留 mono-repo，加 OWNERS.yml 治理：

- `shared/db-migrations/OWNERS.yml` 文件，每张表声明所属 service
- CI 检查每个 migration PR：改动非自己 owner 的表 → fail
- alembic 标准 merge migration 用法 enforce：禁止 copy-paste 副本

**优点**：改动小，符合现状
**缺点**：仍是单 alembic chain，复杂度依然高；service 独立部署/演进受限
**工作量**：~1 周

**未选原因**：founder 选 a — 长期正确（service 独立演进 / 多 PG 部署灵活）。Q3 投资 ~1 周架构治理换 Q4+ 多月 velocity。

---

## 三、决策点登记

### 决策点 1：架构路线 a vs b（Phase 4）— ✅ **founder 选 a (2026-05-10)**

a) **Per-service migrations** ✓ — 长期正确，14 services 各自独立 alembic
b) Shared + OWNERS 治理 — 未选（仍是单 chain 复杂度高）

### 决策点 2：Phase 1 baseline 来源

哪个 schema 作为 v500 baseline？

i) Production 真 schema — `pg_dump --schema-only` 从生产取（**最准**，但需 founder 操作）
ii) 我们 recon 跑通的 partial schema（不完整，部分表 schema 可能错）
iii) 手工 curate 一份（时间最长 / 最 control）

### 决策点 3：B'-7+ 续打补丁还是停下

我建议停下：每修一个 bug 暴露下一个，工作量不可预测；Phase 1 baseline squash 一锅端解决。已 ship 的 PR #337/#339/#340/#342/#343/#345 各自有独立价值（chain 整合 / SQL bug 修复 / RLS 安全），是否 review/merge 取决于路线选择：

- 若选路线 b + Phase 1：merged，作为 baseline 修复历史
- 若选路线 a：可不 merge，直接 archive 历史 + per-service 重做

---

## 四、时间表

| 阶段 | 时间 | 触发 |
|---|---|---|
| Phase 0 (本文档) + Phase 3 (linter) | **本 PR** | 立即 |
| founder review + 决策 1/2/3 | ~1 day | founder 反馈 |
| Phase 1 baseline squash | 4-8 hr | 决策 2 + production pg_dump |
| Phase 2 CI 硬门禁 | 2-4 hr | Phase 1 完成 |
| Phase 4 架构去耦 | 1-2 周 | 决策 1 |

**关键路径**：决策 1 + 2 是阻塞点。其他可并行。

---

## 五、风险登记

| 风险 | 可能性 | 影响 | 缓解 |
|---|---|---|---|
| Phase 1 baseline 漏 production 真实表 | 中 | 高（migration 跑通但 runtime 缺表） | dry-run on staging 全套 service smoke test |
| 历史 migration archive 后无法 downgrade | 高 | 中（alembic downgrade head 报错） | 明确放弃 downgrade 兼容性，改用 PITR + snapshot 回滚 |
| 选路线 b 后 OWNERS 治理仍被 admin override 绕过 | 中 | 中（重蹈 PR #128 覆辙） | branch protection 强 require + founder 个人 review 规则 |
| 多个团队并发对同一 table 改 schema | 高 | 中（PR conflict + 手工 merge） | OWNERS.yml + table 级 review 流程 |
| approval_instances 三 schema 用户决定保留哪个 | 中 | 中（其他 2 服务 runtime 坏） | 独立 issue rename / 拆表，本 plan 不解 |
| Week 8 demo 因架构治理 timing 卡死 | 低 | 高（demo 失败） | Phase 1 完成 = demo 解锁；Phase 4 留 Q3 |

---

## 六、本 PR 含

- `docs/migration-architecture-rescue-plan.md`（本文档）
- `shared/db-migrations/tests/test_schema_lint_tier1.py`（Phase 3 linter，7 类规则）
- `docs/migration-schema-lint-rules.md`（规则详解 + 修复指引）

**不含**：Phase 1 baseline squash / Phase 2 CI gate / Phase 4 架构去耦 — 等 founder 决策后独立 PR 起手。

---

## 七、终态承诺

执行完 4 phase 后：

- ✅ `alembic upgrade head` 在空 PG 上 < 60s 跑通
- ✅ 每个新 migration PR 必须 fresh PG 真跑（CI 硬门禁）
- ✅ 7 类常见 bug 模式无法引入（schema linter）
- ✅ 每张表有明确 owner service（OWNERS.yml 或 per-service 拆分）
- ✅ A 任务（docker-compose-pg fixture）解锁 + 真 RLS 反测在 CI 跑
- ✅ Week 8 demo 可在新机房 1 小时内从零部署

**ROI**：~3-4 周架构投资 → 解锁后续多月 velocity；不再每加 service / 表都触发架构债务循环。
