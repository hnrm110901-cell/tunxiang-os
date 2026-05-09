# 5/9 晚上接力 starter prompt（Phase 3/4 收尾后）

## 上一 session 终态（2026-05-09 19:40）

main HEAD: `9f0ca7d4`（含 #332/#333/#334 NLQ 闭环）
我侧 OPEN：**PR #335（Phase 3 tx-trade）/ #336（RBAC follow-up）/ #338（Phase 4 tx-member）**

**本 session 战绩**：3 PR 开
| PR | 内容 | base | Tier | 状态 |
|---|---|---|---|---|
| #335 | #298 Phase 3 — tx-trade 22 文件 / 57 import + 11 patch fix | main | T1 | OPEN, MERGEABLE, CodeRabbit 评估已贴 |
| #336 | RBAC follow-up — test_trade_promotions 10/10 | #335 | T2 | OPEN（stacked，依赖 #335） |
| #338 | #298 Phase 4 — tx-member 30 文件 / 112 import + conftest 新建 + 21 drift | main | T1 | OPEN |

**决策登记**（新增 83 84）：
- 77（codemod 撤 band-aid 时序）/ 78（codex 不是唯一门禁）/ 79（pre-existing 单独 PR）/ 80（AST 守门优于 mock）/ 81（architect 是 BUG 范围纠错）/ 82（context >80% 拆 session）
- **83（新）：每服务首接入 codemod chain 需建 conftest**
- **84（新）：scanner 漏抓 from-NS-import-module 形式（codex 不抓，本地 pytest 必跑）**

---

## 起手命令

```bash
cd /Users/lichun/tunxiang-os
git fetch git@github.com:hnrm110901-cell/tunxiang-os.git main:refs/remotes/origin/main
git rev-parse origin/main HEAD
gh pr list --state open --limit 20
gh pr view 335 --json mergeStateStatus,statusCheckRollup
gh pr view 336 --json mergeStateStatus
gh pr view 338 --json mergeStateStatus,statusCheckRollup
git worktree list
cat docs/session-handoff-2026-05-09-night.md  # 本文件
head -100 DEVLOG.md  # 5/9 4 wave 时间序
```

---

## 候选任务（按 ROI / 风险 排序）

### A. **等 admin merge → #298 Phase 5（下个服务）**（~3h，T1）
- #335 → #338 都 OPEN 等 admin merge；并发 session 也在推
- Phase 5 候选（按规模）：**tx_org 102 / tx_supply 96 / tx_growth 70 / tx_finance 62 / tx_menu 48**
- 流程模板（决策 83 已固化）：
  1. 建 services/<svc>/conftest.py（与 tx-trade/tx-member 同模板，~53 行 boilerplate）
  2. RED — AST 守门 fixture
  3. GREEN — codemod --apply --service <svc>
  4. fix — patch path drift（grep `"(api|services)\."` 全模式扫）+ from-NS-import-module 修
  5. 本地 pytest 实跑（决策 78）
  6. PR base = main（独立从 main 起，不 stack）
- 推荐起手：**tx_org**（102 裸最大头，按规模优先抓大头）

### B. **决策 79 Phase 2 — scan_order + ontology**（1.5h，T1，触 §18）
- scan_order_service.py 4 处 + scan_order_routes.py 字面量 + ontology 加 `ch_scan_order`
- **必须先征得创始人确认**（CLAUDE.md §18 Ontology 冻结）— 起 session 头先问

### C. **#338 暴露 follow-up 之 1：test_members_routes 4 fail**（~1h，T2）
- 4 测试因真 DB 调用未 mock 而 500（main collection-blocked 隐藏的 pre-existing）
- fixture 加 dependency_overrides 或 sqlalchemy mock context manager
- 决策 79 follow-up 模式（同 #336）

### D. **#338 暴露 follow-up 之 2：test_stamp_card_routes 5 fail**（~1h，T2）
- async mock fixture 问题（main 同款隐藏）
- 单独 PR follow-up

### E. **#338 暴露 follow-up 之 3：11 collection error 文件诊断**（~2h，T2/T3）
- test_card_engine / test_customer_depth / test_gamification / test_marketing_engine / test_marketing_routes / test_member_analytics / test_member_extended / test_member_lifecycle / test_member_core / test_member_insight_tier / test_premium_card 等
- 各种 ImportError / sys.modules 注入问题
- 单独 follow-up PR 集

### F. **shared.security 包缺失诊断**（~2h，T2）
- test_trade_webhook 6 / test_trade_extended 10 失败根因
- 错误：`ModuleNotFoundError: No module named 'shared.security'; 'shared' is not a package`
- 看 PYTHONPATH / shared/security/ 目录实际位置

---

## 阻塞中（不要 touch）

- #271 invoice fen + RLS（DBA staging dry-run 等）
- #272 wine_storage fen（stack on #271）
- #240 v4 architecture sprint（长链 OPEN）

---

## 推荐起手

**A**（Phase 5 tx_org）— 按规模抓大头，决策 83 模板已固化，3h 内可开 PR
**OR C**（test_members_routes follow-up）— 小步快跑闭环 #338 暴露的债，1h
**OR B**（决策 79 Phase 2）— 主链续做，需创始人 OK

按"A/B/C 三选一格式 + 预计 commit/文件/Tier，user confirm 再开 worktree"格式给方案，等用户拍板。

---

## 守约清单（必读）

- Co-authored-by 占位 `你的名字 <noreply@anthropic.com>`
- SSH 显式 push（git@github.com）
- Tier 1 强制 TDD 双 commit（RED→GREEN）+ AST 守门（决策 80）
- 原子化 commit（CLAUDE.md §21）
- 每 PR 后清 worktree
- 每 session 尾 DEVLOG + progress + handoff 更新
- §17 §18 §19 §20 §21 全文必备
- 决策 77：codemod 撤 band-aid 必须等 production 端覆盖
- 决策 78：codex 不是 codemod PR 唯一门禁，本地 pytest 必跑（决策 84 实证）
- 决策 79：暴露的 pre-existing prod BUG 不混入 codemod PR，独立 follow-up PR
- 决策 80：Tier 1 修复优先 AST 静态扫
- 决策 82：context >80% 主动拆 session
- **决策 83（新）**：每服务首接入 codemod chain 需建 services/<svc>/conftest.py（≤53 行 boilerplate，与 tx-trade/tx-member 同模板）
- **决策 84（新）**：scanner 漏抓 from-NS-import-module 形式，codex/coderabbit 不识别 namespace package magic，本地 pytest 是唯一真门禁

## 累计 #298 chain 数据快照

| 阶段 | PR | 服务 | 文件 | import | conftest |
|---|---|---|---|---|---|
| Phase 1-3 | #318/#320/#322/#335 | tx-trade | 42 | ~305 | 已有 |
| Phase 4 | #338 | tx-member | 30 | 112 | 本 PR 新建 ✓ |
| **累计** | | | **72** | **~417** | **2 服务** |
| 余待清 | | 12 服务 | ~? | ~499 | 待新建 12 |
