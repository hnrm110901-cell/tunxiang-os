# B'-X PR Stack 处置建议 (2026-05-10)

> 路线 a 选定 + 4 个 PR (#337/#346/#352/#354) 落地后，B'-X 5 PR stack 状态分析 + close 建议。

## TL;DR

**所有 5 PR 建议 CLOSE 不 merge**。理由：fix 全部针对 `shared/db-migrations/versions/` 的历史 migration 文件，路线 a Phase 4a-7 完成后这些文件移至 `_archive/`，fix 失效。**唯一安全关注点（PR #343 类 F RLS helper bug）已被 PR #346 schema linter `test_class_f2_no_insert_policy_using_clause`（baseline=0）防回归覆盖**。

## B'-X stack 5 PR 现状

| PR | state | 改动 | 路线 a 后状态 |
|---|---|---|---|
| #339 | **CLOSED** (auto, conflict) | 5 SQL bug 修（类 B/C/D/E）| 已 closed |
| #340 | OPEN | v288 / v236 / v208b（类 C/A/E chain）| 路线 a baseline squash 后冗余 |
| #342 | OPEN | banquet partial (v315/v267/v331) | 同上 |
| #343 | OPEN | banquet 全链 + **类 F RLS** | 同上（含 1 个 security 关注点 — 已被 linter 覆盖） |
| #345 | OPEN | 类 G v378 + 类 A 残留 + chain skip | 同上 |

## 详细分析（按 PR）

### #339 (B'-2 一锅端 5 SQL bug) — **CLOSED 已决议**

CLOSED 状态由 PR #337 squash merge + branch delete 触发的 conflict 自动转。
内容：5 SQL 修（类 B JSONB / 类 C bind / 类 D PK / 类 E index）。
处置：**已 closed，不动**。

### #340 (B'-3) — **建议 CLOSE (obsolete)**

改动 4 文件：
- v288 `_seed_system_templates` 用 `op.get_bind().exec_driver_sql` 替代 `op.execute`（JSON `:N` 解析）
- v236 `down_revision` 改 `("v235b", "v235c")` merge tuple（chain 漏依赖）
- v208b employee_transfers no-op（副本）
- DEVLOG / progress 同步

路线 a 后：3 个 migration 文件全部进 `_archive/`，不再 alembic upgrade。修无价值。

无 security 关注 — 都是 chain integrity 修。

### #342 (B'-4 banquet partial) — **建议 CLOSE (obsolete)**

改动 4 文件：
- v267_banquet_leads.py 仅留 ENUM 创建（删 banquet_leads CREATE TABLE）
- v331_banquet_leads.py 全 no-op（v315 副本）
- v332_banquet_quotes.py 全 no-op（v316 副本）
- v315_banquet_leads.py 加 DROP CASCADE 覆盖 v004 老 schema

路线 a 后：banquet 表由 services/tx-trade/db-migrations/ 的 baseline 文件创建（一次性，不含历史副本问题）。修无价值。

无 security 关注 — schema 重组类。

### #343 (B'-5 banquet 全链 + RLS 类 F) — **建议 CLOSE (obsolete) + 验证 linter 覆盖**

改动 14 文件 含 2 类：

**类 A residual (8 files)**：v316/v317/v318/v319 + v336/v344 banquet DROP CASCADE。同 #342 — 路线 a 后冗余。

**类 F RLS helper fix (6 files)** — **safety critical**：
- v377/v378/v379/v380/v381/v391 的 `_enable_rls()` helper
- 原代码：`CREATE POLICY ... FOR INSERT TO PUBLIC USING ({tenant_id_expr})` — PG 拒绝
- 修后：`if action == "INSERT": "WITH CHECK" else "USING"` 区分
- **CLAUDE.md §17 Tier 1 多租户隔离硬约束**

是否仍需要 merge？

**No** —理由：
1. **PG 拒绝原 syntax** — 这些 migration 的 CREATE POLICY 语句 PG 端 syntax error，alembic transaction 回滚 → **production 从未真应用过这些 POLICY**。POLICY DB 端实际不存在，不是"buggy POLICY 在线运行"。受影响表（customer_journey_timings / daily_scorecards / dynamic_pricing_logs / invoice_ocr_results / delivery_disputes / delivery_dispatches）很可能在 production 也不存在（chain 历史断裂未跑到 v377+）。
2. **PR #346 schema linter `test_class_f2_no_insert_policy_using_clause` baseline=0** 已 merge main，**新 PR 引入 `FOR INSERT TO PUBLIC USING` 模式立即 CI fail**。未来 dev 在 per-service migration 中复制这个 helper 就触发 lint。
3. **Phase 4a-4 baseline 来源是 production pg_dump** — production 真实 RLS 状态（含 / 不含 / buggy）会被 1:1 dump 到 baseline。production 此刻是何状态就是 baseline 何状态。

→ 唯一 residual 安全担心：**production 是否有这些表 + 这些表 RLS 状态**。需独立 audit（`pg_policies` 查询）回答，不在 B'-X stack scope。

### #345 (B'-6 partial) — **建议 CLOSE (obsolete)**

改动 13 文件：
- 类 G：v378 store_lifecycle_stages 生成列改普通 INT / v264 索引去 date_trunc → **PR #346 review e1bc448f 已修 v378（同 PR）+ PR #352 review 48ec7482 已修 v264**
- 类 A 残留：v235c approval_instances / v391 delivery_dispatches DROP CASCADE — 路线 a 后冗余
- 类 F 续：v311 IF NOT EXISTS / v395 三 action 子句 — 同 #343 reasoning，linter 覆盖
- chain 结构：v310 skip / v383 tuple 清理 / v388 skip — 路线 a 后冗余

最关键的 v378 / v264 修复**已在 main**（PR #346 + #352）。其余无价值。

## 推荐处置矩阵

| PR | action | 原因 |
|---|---|---|
| #339 | （已 closed）| 自动 closed |
| #340 | CLOSE with note | 路线 a 后 chain 修复全冗余 |
| #342 | CLOSE with note | banquet schema 重组路线 a 自然解决 |
| #343 | CLOSE with note | RLS Tier 1 已被 PR #346 linter 防回归覆盖 |
| #345 | CLOSE with note | 关键修复（v378/v264）已 in main |

## CLOSE 模板 comment

每个 PR close 时建议附 comment：

```
该 PR 在路线 a 选定（PR #346 founder 决策）+ baseline squash plan 落地后 obsolete。

修复内容详细分析见 docs/migration-bx-stack-disposition.md。

关键 fix 落入 main 状态：
- 类 F RLS helper bug：PR #346 schema linter test_class_f2 (baseline=0) 防回归覆盖
- 类 G v378 生成列：PR #346 review fix (commit e1bc448f) 已修
- 类 G v264 索引：PR #352 review fix (commit 48ec7482) 已修
- chain dangling：PR #337 已修

shared/db-migrations/ 整体在 Phase 4a-7 移至 _archive/，本 PR 改动不再生效。
```

## 残留 follow-up

CLOSE 后仍需独立 issue 跟进 1 项：

**Production RLS 状态 audit** — 6 张受 类 F 影响的表（customer_journey_timings / daily_scorecards / dynamic_pricing_logs / invoice_ocr_results / delivery_disputes / delivery_dispatches）：
- 在 production 是否存在？
- 若存在，是否有 RLS POLICY？
- POLICY 是否有 INSERT 跨租户漏洞？

查询模板（生产 PG 跑）：
```sql
SELECT
    schemaname, tablename,
    rowsecurity AS rls_enabled,
    forcerowsecurity AS rls_forced
FROM pg_tables
WHERE tablename IN (
    'customer_journey_timings', 'daily_scorecards', 'dynamic_pricing_logs',
    'invoice_ocr_results', 'delivery_disputes', 'delivery_dispatches'
);

-- 含 INSERT POLICY 的检查
SELECT polname, polrelid::regclass, polcmd, polqual, polwithcheck
FROM pg_policy
WHERE polrelid::regclass::text IN (...上面的表...)
  AND polcmd IN ('a', 'w');  -- INSERT(a) / UPDATE(w)
```

若发现 POLICY 缺失或 INSERT WITH CHECK 不带 tenant_id 校验 → 单独 hotfix PR（不通过 alembic，直接 RLS POLICY apply）。这与 B'-X stack 无关，是独立 security audit。

## 时间线

```
B'-X stack 起源 (5/8-5/9): chain 修通后逐 SQL bug 修复，发现工作量不可预测
路线 a 选定 (5/10): founder 决策架构治理，PR #346/#352/#354 落地
本文 disposition (5/10): 推荐 close 5 PR + 独立 production RLS audit issue
```

## 决策点（待 founder 批准）

1. ✓ / ✗ CLOSE PR #340/#342/#343/#345（4 PR）
2. ✓ / ✗ 建 production RLS audit issue（独立 task）
