# 5/10 fresh session 起手 prompt（拆 session 后用）

> 5/9-5/10 跨日 session 已交付 11 PR，chain 100% test 端 + 决策 77 起步。
> 本文件给新会话一个 cold-start 完整上下文，**整段贴入新 fresh Claude session**。

---

## 上一 session 终态（2026-05-10 02:30）

main HEAD: `8256d102`
当前 worktree HEAD: `8dbc0e35`（fix/tx-org-production-codemod）
我侧 OPEN：**11+ PR**（#335 / #336 / #338 / #341 / #344 / #347 / #348 / #349 / #350 / #351 / #353）

### 战绩（5/9-5/10 跨日 11 PR + 决策起步）

| PR | 内容 | base | Tier | 状态 |
|---|---|---|---|---|
| #335 | Phase 3 tx-trade 22/57 | main | T1 | OPEN |
| #336 | RBAC follow-up | #335 | T2 | OPEN |
| #338 | Phase 4 tx-member 30/112 + conftest 新建 | main | T1 | OPEN |
| #341 | Phase 5 tx-org 39/102 | main | T1 | OPEN |
| #344 | Phase 6 tx-supply 39/96 | main | T1 | OPEN |
| #347 | conftest shared/shared.adapters namespace fix | main | T2 | OPEN |
| #348 | Phase 7 tx-growth 20/70 + conftest | main | T1 | OPEN |
| #349 | Phase 8 tx-finance 23/62 + conftest | main | T1 | OPEN |
| #350 | Phase 9 chain closer 7 服务 65/159 + 7 conftest | main | T1 | OPEN |
| #351 | A2 — 14 服务 main.py 容器布局 smoke 网立 | main | T1 | OPEN |
| #353 | **决策 77 production 第 1 步 — tx-org 26/114** | main | T1 | OPEN |

### #298 chain 100%（test 端）
- 13 服务 / 258 文件 / ~906 imports 全清
- 余 tx-civic / tx-pay / tx-expense（0 bare imports）

### 决策 77 production codemod 进度：tx-org ✅，余 ~94 处
- tx-growth 61
- tx-finance 20
- tx-intel 13
- tx-member 3
- tx-supply 1

---

## 起手命令（fresh session 第一步必跑）

```bash
cd /Users/lichun/tunxiang-os
git fetch git@github.com:hnrm110901-cell/tunxiang-os.git main:refs/remotes/origin/main
git rev-parse origin/main HEAD
gh pr list --state open --author "@me" --limit 20
git worktree list
cat docs/session-handoff-2026-05-10-fresh.md  # 本文件
head -200 DEVLOG.md  # 5/9-5/10 跨日完整记录
find services -maxdepth 2 -name "conftest.py" | sort  # 决策 83 状态（应 14 全有）
```

---

## 决策登记（5/9-5/10 累计 8 项，全文背诵）

- **77** codemod 撤 #287 band-aid 时序：test 端 ✅ + production 端 ⏳（5/14 预计完成）
- **78** codex/coderabbit 不是唯一门禁，本地 pytest 必跑（实测对比 pre/post）
- **79** 暴露的 pre-existing prod BUGs → 独立 follow-up PR，不混入 codemod PR
- **80** Tier 1 修复优先 AST 静态扫，不写脆弱 mock
- **81** architect agent 是 BUG 范围纠错（不全盘重写）
- **82** context >80% 主动拆 session（本 fresh session 即此规则启用）
- **83** 每服务首接入 codemod chain 需建 services/<svc>/conftest.py（已 14 服务全建）
- **84** scanner 漏抓 from-NS-import-module 形式，本地 pytest 必跑捕捉

---

## 候选任务（A/B/C/D/E 五选一）

### A. 决策 77 续 — tx-growth production codemod 61 处（次大头）
- ~1.5h，T1
- 模板沿用 #353 tx-org（bulk regex script + grep 验证 + 容器布局测试）
- 完成后 #351 smoke 中 tx-growth xfail → XPASS（若有，本服务 #351 是 skip 状态）
- 注：tx-growth 在 #351 是 **skip**（apscheduler 缺依赖），不是 xfail；本 codemod 不直接翻 marker

### B. 决策 77 续 — tx-finance / tx-intel / tx-member / tx-supply 4 服务一波清（37 处）
- ~2h，T1
- 单 PR 闭 4 服务（含 tx-finance 20 + tx-intel 13 + tx-member 3 + tx-supply 1）
- tx-intel xfail 翻 + tx-finance xfail 翻（#351 marker）

### C. 决策 79 follow-up — tx-ops `DailySummary` + tx-supply `Header` 缺失导出修复
- ~1.5h，T2
- 不是 codemod，是真业务代码补导出
- 解 #351 中 2 个 xfail
- shared/ontology/* 修改需创始人确认（CLAUDE.md §18）— ⚠️ 询问 user 先

### D. alembic chain integrity 收尾（v310/v311/v388 已修，仍可能有残留）
- ~1.5h，T1
- 检查 #337 (5/9 早合并) 是否完全解决
- 重跑 `alembic upgrade head` 验证

### E. dev-plan-60d 5/7 重写（被 30+ commit 推翻）
- ~2h，T3，文档类
- 5/9 凌晨 progress 更新提到此项

---

## 阻塞中（不要 touch）

- #271 invoice fen + RLS（DBA staging 等）
- #272 wine_storage fen（stack on #271）
- #240 v4 architecture sprint（长链 OPEN）

---

## 推荐起手

**B**（决策 77 续 — 4 服务一波清 37 处）— 1 PR 闭 4 服务，模板已 9 PR 验证收敛，blast radius 小

**OR A**（tx-growth 61 处）— 单服务模板沿用 #353，规模适中

按 "A/B/C 三选一格式 + 预计 commit/文件/Tier，user confirm 再开 worktree" 格式给方案。

---

## 守约清单（必读，每 PR 自检）

- Co-authored-by 占位 `你的名字 <noreply@anthropic.com>`
- SSH 显式 push（`git push -u git@github.com:hnrm110901-cell/tunxiang-os.git <branch>`）
- Tier 1 强制 TDD 双 commit + AST 守门（决策 80）
- 原子化 commit（CLAUDE.md §21）
- 每 PR 后清 worktree
- 每 session 尾 DEVLOG + progress + handoff 更新
- §17 §18 §19 §20 §21 全文必备
- 决策 77：codemod 撤 band-aid 还差 production 端 4 服务 ~94 处
- 决策 78 + 84：codex/scanner 不是唯一门禁，本地 pytest 必跑
- 决策 79：暴露的 pre-existing prod BUG 不混入 codemod PR
- 决策 80：Tier 1 修复优先 AST 静态扫
- 决策 82：context >80% 主动拆 session（本 fresh session 即此规则启用）
- 决策 83：每服务首接入 codemod chain 需建 conftest（14 服务已全建）

---

## conftest 状态（决策 83）— 全 14 服务覆盖

| 服务 | conftest | 来源 |
|---|---|---|
| tx-trade / tx-org / tx-pay / tx-supply | ✓ | 历史已有 |
| tx-member | ✓ | #338 新建 |
| tx-growth | ✓ | #348 新建 |
| tx-finance | ✓ | #349 新建 |
| gateway / tx-agent / tx-analytics / tx-brain / tx-civic / tx-intel / tx-menu / tx-ops | ✓ | #350 一波 7 个新建 |

---

## 累计 #298 chain 数据快照

| Phase | PR | 服务 | 文件 | import |
|---|---|---|---|---|
| 1-3 | #322 #335 | tx-trade | 42 | ~305 |
| 4 | #338 | tx-member | 30 | 112 |
| 5 | #341 | tx-org | 39 | 102 |
| 6 | #344 | tx-supply | 39 | 96 |
| 7 | #348 | tx-growth | 20 | 70 |
| 8 | #349 | tx-finance | 23 | 62 |
| 9 | #350 | 7 服务一波 | 65 | 159 |
| **chain test 端** |  | **13 服务** | **258** | **~906（100%）** |
| 决策 77 production 第 1 步 | #353 | tx-org | 26 | 114 |
| **决策 77 余下** | | 4-5 服务 | ~? | ~94 |

---

## #351 smoke 网状态（PR 合并后基线）

合并顺序假设：#351 → #353 → 后续 production codemod PRs

| 服务 | 当前 #351 状态 | #353 后状态 | 待 codemod 翻 xfail |
|---|---|---|---|
| tx-menu / tx-civic | PASS | PASS | n/a |
| tx-trade | xfail | xfail | tx-trade `services.permission_service` 修 |
| tx-finance | xfail | xfail | tx-finance codemod |
| tx-intel | xfail | xfail | tx-intel codemod |
| **tx-org** | xfail | **XPASS** | 已修（删 marker → required） |
| tx-ops | xfail | xfail | DailySummary 导出修 |
| tx-supply | xfail | xfail | Header 导出修 |
| tx-member / tx-growth / tx-agent / tx-analytics / tx-brain | skip | skip | dev venv 装齐后转 PASS |
| gateway | 既有 fail | 既有 fail | apscheduler 装齐后转 PASS |

---

## 仓库布局关键事实（context 重建）

- **2 clones + 50+ worktrees**：canonical `/Users/lichun/tunxiang-os`（main HEAD），WorkBuddy `/Users/lichun/WorkBuddy/...`（claude-3p 实验）
- **多 worktree active**：`/Users/lichun/.tunxiang-p0-worktrees/codemod-batch{1-9}`、`tx-org-prod-codemod`、`main-import-smoke` 等
- **并发 session 风险**：user 经常多 tty tab 同时跑 vanilla `claude`，commit/stash 前必跑 `git status` + reflog
- **CI 噪音 vs 真门禁**：`Tier 1 门禁判定` / `Run Tier 1 *` / `RLS 严格门禁` / `源改动必须配对测试改动` 是真 required；`python-lint-test (*)` / `Ruff` / `frontend-build` / `TypeScript Check (*)` 全 PR 一律失败的预存漂移可忽略

---

## 时间格式

今天 2026-05-10。本 fresh session 起手时间预计 09:00 之后。
