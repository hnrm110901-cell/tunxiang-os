# 5/10 早上接力 starter prompt（Phase 6 收尾后）

## 上一 session 终态（2026-05-09 23:00）

main HEAD: `9f0ca7d4`
我侧 OPEN：**5 PR**（#335 Phase 3 / #336 RBAC follow-up / #338 Phase 4 / #341 Phase 5 / **#XXX Phase 6**）

### 战绩（5/9 一日 5 PR）

| PR | 内容 | base | Tier | 状态 |
|---|---|---|---|---|
| #335 | Phase 3 tx-trade 22/57 + patch fix 11 | main | T1 | OPEN, MERGEABLE, CodeRabbit 评估贴 |
| #336 | RBAC follow-up — test_trade_promotions 10/10 | #335 | T2 | OPEN（stacked） |
| #338 | Phase 4 tx-member 30/112 + conftest 新建 + 21 drift | main | T1 | OPEN |
| #341 | Phase 5 tx-org 39/102 + 24 drift | main | T1 | OPEN |
| **#XXX** | **Phase 6 tx-supply 39/96 + 20 drift** | **main** | **T1** | **OPEN** |

### 决策登记（5/9 累计 8 项）
- 77 / 78 / 79 / 80 / 81 / 82 / 83 / 84

### chain 进度
**150 文件 / ~615 处 / 4 服务 / ~85% 完成**
余待清：10 服务 ~108 处（tx-growth 95 / tx-finance 52 已扫；其他服务实测 0-2 处）

---

## 起手命令

```bash
cd /Users/lichun/tunxiang-os
git fetch git@github.com:hnrm110901-cell/tunxiang-os.git main:refs/remotes/origin/main
git rev-parse origin/main HEAD
gh pr list --state open --author "@me" --limit 20
git worktree list
cat docs/session-handoff-2026-05-10-morning.md
head -150 DEVLOG.md
find services -maxdepth 2 -name "conftest.py" | sort  # 决策 83 状态
```

---

## 候选任务（按 ROI / 风险 排序）

### A. **#298 Phase 7 — tx-growth 95**（~3h，T1，决策 83 前置：新建 conftest）
- bare-import 95 处（scanner 实测）
- 需先建 services/tx-growth/conftest.py（决策 83，~53 行 boilerplate）
- 然后同 Phase 5/6 模板：RED → GREEN → fix → 本地 pytest

### B. **#298 Phase 7 alt — tx-finance 52**（~2.5h，T1，决策 83 前置：新建 conftest）
- bare-import 52 处
- 同 A 路径，conftest 新建 → 模板套用

### C. **shared.security / shared.events / Header 跨服务根因诊断**（~2h，T2）
- 影响 22+ test 文件 collection error（tx-supply / tx-org / tx-trade 都触及）
- 可能是 PYTHONPATH / namespace package / __init__.py 问题
- 修复后多服务 collection 一次性恢复 → ROI 高

### D. **决策 79 follow-up — pytest 测试隔离污染**（~1.5h，T2）
- test_warehouse_and_trace_routes 2 处单跑通批跑挂
- 可能是 sys.modules 残留 / fixture scope 问题
- 仅影响 tx-supply 单服务

### E. **#341 暴露 follow-up — tx-org 5 测试 fixture 修**（~1h，T2）
- test_org_core 3（shared.security 缺失诊断 — 与 C 重叠）
- test_attendance_leave 1 / test_patrol_module 1（mock 未调用）
- 决策 79 follow-up

### F. **#338 暴露 follow-up — tx-member 24 测试**（~2-3h，T2）
- test_members_routes 4（真 DB 调用未 mock）
- test_stamp_card_routes 5（async mock 问题）
- 11 collection error 文件诊断（与 C 重叠）

---

## 阻塞中（不要 touch）

- #271 invoice fen + RLS（DBA staging 等）
- #272 wine_storage fen（stack on #271）
- #240 v4 architecture sprint（长链 OPEN）

---

## 推荐起手

**C**（shared.security 跨服务根因诊断）— 一锅端解 22+ collection error，多 PR 暴露的根因
**OR A**（Phase 7 tx-growth 95）— 推 chain 进度，1 PR 闭环
**OR B**（Phase 7 tx-finance 52）— 同 A 思路，规模略小

按 "A/B/C 三选一格式 + 预计 commit/文件/Tier，user confirm 再开 worktree"格式给方案。

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
| tx-supply | ✓ | 已有（旧），Phase 6 直用 |
| 其他 11 服务 | ✗ | Phase 推到时需新建 |

## 累计 #298 chain 数据快照

| Phase | PR | 服务 | 文件 | import |
|---|---|---|---|---|
| 1-3 | #322 #335 | tx-trade | 42 | ~305 |
| 4 | #338 | tx-member | 30 | 112 |
| 5 | #341 | tx-org | 39 | 102 |
| 6 | #XXX | tx-supply | 39 | 96 |
| **累计** | | **4 服务** | **150** | **~615** |
| 余待清 | | 10 服务 | ~? | ~108（tx-growth 95 / tx-finance 52）|
