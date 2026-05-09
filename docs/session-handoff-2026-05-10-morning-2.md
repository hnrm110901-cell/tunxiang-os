# 5/10 早上接力 starter prompt（Phase 7 收尾后 v2）

## 上一 session 终态（2026-05-09 23:30）

main HEAD: `9f0ca7d4`
我侧 OPEN：**7 PR**（#335 / #336 / #338 / #341 / #344 / #347 / #XXX）

### 战绩（5/9 一日 7 PR）

| PR | 内容 | base | Tier | 状态 |
|---|---|---|---|---|
| #335 | Phase 3 tx-trade 22/57 | main | T1 | OPEN |
| #336 | RBAC follow-up | #335 | T2 | OPEN |
| #338 | Phase 4 tx-member 30/112 + conftest | main | T1 | OPEN |
| #341 | Phase 5 tx-org 39/102 | main | T1 | OPEN |
| #344 | Phase 6 tx-supply 39/96 | main | T1 | OPEN |
| #347 | conftest shared namespace fix | main | T2 | OPEN |
| **#XXX** | **Phase 7 tx-growth 20/70 + conftest** | **main** | **T1** | **OPEN** |

### chain 进度：~88%
- 5 服务 / 170 文件 / ~685 imports cleared
- 余 9 服务 / ~52 imports（tx-finance 52，其他基本 0）

### 决策登记（5/9 累计 8 项）
77 / 78 / 79 / 80 / 81 / 82 / 83 / 84

---

## 起手命令

```bash
cd /Users/lichun/tunxiang-os
git fetch git@github.com:hnrm110901-cell/tunxiang-os.git main:refs/remotes/origin/main
git rev-parse origin/main HEAD
gh pr list --state open --author "@me" --limit 20
git worktree list
cat docs/session-handoff-2026-05-10-morning-2.md
head -100 DEVLOG.md
find services -maxdepth 2 -name "conftest.py" | sort  # 决策 83 状态
```

---

## 候选任务（按 ROI / 风险 排序）

### A. **#298 Phase 8 — tx-finance 52**（chain 最后大头）
- ~2.5h，T1
- 需先建 services/tx-finance/conftest.py（决策 83，~50 行）
- 同 Phase 7 模板：RED → GREEN → fix → 本地 pytest
- **完成后 chain 进度 ~95%**，剩余仅小规模零碎

### B. **#298 Phase 8 alt — 余 8 服务一波清**（gateway 16 / tx-agent 37 / tx-analytics 34 等）
- ~3-4h，T1，规模分散
- 多服务串行（每服务需建 conftest）
- 适合 chain 收官

### C. **决策 79 follow-up — tx-growth +63 surfaced failures 调查**
- ~2-3h，T2
- 解 #XXX 暴露的 pre-existing latent bugs
- ROI 偏低（dev-experience 类）

### D. **决策 79 follow-up — shared.security 残留 10 collection errors**
- ~2h，T2
- #347 修了 5 服务 16 errors，但 tx-growth/tx-org 还有 10 残留
- 不同根因（missing exports / Header 名称冲突 / 环境依赖）

### E. **dev-plan-60d 5/7 计划重写**（被 26 commit 推翻）
- ~2h，T3，文档类

---

## 阻塞中（不要 touch）

- #271 invoice fen + RLS（DBA staging 等）
- #272 wine_storage fen（stack on #271）
- #240 v4 architecture sprint（长链 OPEN）

---

## 推荐起手

**A**（Phase 8 tx-finance 52）— chain 倒数第二大头，1 PR 闭环 ~95%

按 "A/B/C 三选一格式 + 预计 commit/文件/Tier，user confirm 再开 worktree" 格式给方案。

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
- 决策 83：每服务首接入 codemod chain 需建 services/<svc>/conftest.py（≤50 行 boilerplate）

## conftest 状态（决策 83）

| 服务 | conftest | 状态 |
|---|---|---|
| tx-trade | ✓ | 已有 |
| tx-member | ✓ | #338 新建 |
| tx-org | ✓ | 已有 |
| tx-pay | ✓ | 已有 |
| tx-supply | ✓ | 已有 |
| tx-growth | ✓ | #XXX 新建 |
| 其余 9 服务 | ✗ | Phase 推到时新建 |

## 累计 #298 chain 数据快照

| Phase | PR | 服务 | 文件 | import |
|---|---|---|---|---|
| 1-3 | #322 #335 | tx-trade | 42 | ~305 |
| 4 | #338 | tx-member | 30 | 112 |
| 5 | #341 | tx-org | 39 | 102 |
| 6 | #344 | tx-supply | 39 | 96 |
| 7 | #XXX | tx-growth | 20 | 70 |
| **累计** | | **5 服务** | **170** | **~685** |
| 余待清 | | 9 服务 | ~? | ~52 |
