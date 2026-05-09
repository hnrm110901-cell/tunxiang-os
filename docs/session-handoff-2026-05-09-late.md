# 5/9 深夜接力 starter prompt（Phase 3/4/5 收尾后）

## 上一 session 终态（2026-05-09 21:00）

main HEAD: `9f0ca7d4`
我侧 OPEN：**4 PR**（#335 Phase 3 / #336 RBAC follow-up / #338 Phase 4 / #341 Phase 5）

### 战绩（5/9 一日 4 PR）

| PR | 内容 | base | Tier | 状态 |
|---|---|---|---|---|
| #335 | Phase 3 tx-trade 22/57 + patch fix 11 | main | T1 | OPEN, MERGEABLE, CodeRabbit 评估贴 |
| #336 | RBAC follow-up — test_trade_promotions 10/10 | #335 | T2 | OPEN（stacked） |
| #338 | Phase 4 tx-member 30/112 + conftest 新建 + 21 drift | main | T1 | OPEN |
| #341 | Phase 5 tx-org 39/102 + 24 drift | main | T1 | OPEN |

### 决策登记（5/9 新增 4 项）
- 77（codemod 撤 band-aid 时序）/ 78（codex 不是唯一门禁）/ 79（pre-existing 单独 PR）/ 80（AST 守门优于 mock）/ 81（architect 是 BUG 范围纠错）/ 82（context >80% 拆 session）
- **83**：每服务首接入 codemod chain 需建 conftest（namespace package magic）
- **84**：scanner 漏抓 from-NS-import-module 形式

---

## 起手命令

```bash
cd /Users/lichun/tunxiang-os
git fetch git@github.com:hnrm110901-cell/tunxiang-os.git main:refs/remotes/origin/main
git rev-parse origin/main HEAD
gh pr list --state open --limit 20
gh pr view 335 --json mergeStateStatus
gh pr view 336 --json mergeStateStatus
gh pr view 338 --json mergeStateStatus
gh pr view 341 --json mergeStateStatus
git worktree list
cat docs/session-handoff-2026-05-09-late.md
head -150 DEVLOG.md
find services -maxdepth 2 -name "conftest.py" | sort  # 决策 83 状态
```

---

## 候选任务（按 ROI / 风险 排序）

### A. **等 admin merge → #298 Phase 6 (tx_supply 96 裸)**（~3h，T1）
- conftest 已存在 → 决策 83 前置免
- 模板（已固化经 5 PR）：
  1. RED — AST 守门 fixture (test_codemod_phase6_bare_imports_tier1.py)
  2. GREEN — codemod --apply --service tx-supply
  3. fix — patch drift（grep `"(api|services)\."` 全模式扫）+ from-NS-import-module 修
  4. 本地 pytest 实跑（决策 78）
  5. PR base = main
- 也可考虑 Phase 6 选 tx_growth 70 / tx_finance 62（需先建 conftest，决策 83）

### B. **决策 79 Phase 2 — scan_order + ontology**（1.5h，T1，触 §18）
- 需创始人确认（§18 Ontology 冻结）

### C. **#341 暴露 follow-up — tx_org 5 测试 fixture 修**（~1h，T2）
- test_org_core 3（shared.security 缺失诊断）
- test_attendance_leave 1 / test_patrol_module 1（mock 未调用）
- 决策 79 follow-up 模式

### D. **#338 暴露 follow-up — tx_member 24 测试**（~2-3h，T2）
- test_members_routes 4（真 DB 调用未 mock）
- test_stamp_card_routes 5（async mock 问题）
- test_gdpr 1（错误响应格式）
- 11 collection error 文件诊断
- 可拆多 PR

### E. **shared.security / shared.events 包缺失诊断**（~2h，T2）
- 影响多服务（tx_trade test_trade_webhook 6 / test_trade_extended 10 / tx_org test_org_core 3）
- 可能是 PYTHONPATH / __init__.py / namespace package 问题

### F. **#298 Phase 6 选项 2：tx_growth 70（需先建 conftest）**（~3h，T1）
- 需先建 services/tx-growth/conftest.py（决策 83，~53 行 boilerplate）
- 然后同 Phase 5 模板

---

## 阻塞中（不要 touch）

- #271 invoice fen + RLS（DBA staging 等）
- #272 wine_storage fen（stack on #271）
- #240 v4 architecture sprint（长链 OPEN）

---

## 推荐起手

**A**（Phase 6 tx_supply）— conftest 已存在，决策 83 前置免，3h 内 PR
**OR C**（tx_org 5 测试 follow-up）— 小步快跑，1h 闭环 #341 暴露
**OR E**（shared.security 诊断）— 解决多 PR 暴露的根因，~2h

按"A/B/C 三选一格式 + 预计 commit/文件/Tier，user confirm 再开 worktree"格式给方案。

---

## 守约清单（必读）

- Co-authored-by 占位 `你的名字 <noreply@anthropic.com>`
- SSH 显式 push（git@github.com）
- Tier 1 强制 TDD 双 commit + AST 守门（决策 80）
- 原子化 commit（CLAUDE.md §21）
- 每 PR 后清 worktree
- 每 session 尾 DEVLOG + progress + handoff 更新
- §17 §18 §19 §20 §21 全文必备
- 决策 77：codemod 撤 band-aid 必须等 production 端覆盖
- 决策 78 + 84：codex/scanner 不是唯一门禁，本地 pytest 必跑
- 决策 79：暴露的 pre-existing prod BUG 不混入 codemod PR，独立 follow-up PR
- 决策 80：Tier 1 修复优先 AST 静态扫
- 决策 82：context >80% 主动拆 session
- 决策 83：每服务首接入 codemod chain 需建 services/<svc>/conftest.py（≤53 行 boilerplate）

## conftest 状态（决策 83）

| 服务 | conftest | 状态 |
|---|---|---|
| tx-trade | ✓ | 已有（旧） |
| tx-member | ✓ | #338 新建 |
| tx-org | ✓ | 已有（旧） |
| tx-pay | ✓ | 已有（旧） |
| tx-supply | ✓ | 已有（旧） — Phase 6 可直起 |
| 其他 11 服务 | ✗ | Phase 推到时需新建 |

## 累计 #298 chain 数据快照

| Phase | PR | 服务 | 文件 | import |
|---|---|---|---|---|
| 1-3 | #322 #335 | tx-trade | 42 | ~305 |
| 4 | #338 | tx-member | 30 | 112 |
| 5 | #341 | tx-org | 39 | 102 |
| **累计** | | **3 服务** | **111** | **~519** |
| 余待清 | | 11 服务 | ~? | ~149 |
