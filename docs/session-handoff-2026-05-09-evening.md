# 5/9 傍晚接力 starter prompt（#298 Phase 3 收尾后）

## 上一 session 终态（2026-05-09 17:30）

main HEAD: `c305ab3b`（含 #331 NLQ sql_generator 接真 ModelRouter）
我侧 OPEN：**PR #335**（Phase 3，3 commit / 26 文件 / 69 改动行）

**本 session 战绩**：1 PR 开
| PR | 内容 | 状态 |
|---|---|---|
| #335 | #298 codemod Phase 3 — tx_trade 22 文件 / 57 import + 11 patch drift + 1 typo | OPEN |

**决策登记**（不变）：77（codemod 撤 band-aid 时序）/ 78（codex 不是唯一门禁）/ 79（sales_channel 三阶段）/ 80（AST 守门优于 mock）/ 81（architect 是 BUG 范围纠错）/ 82（context >80% 拆 session）

---

## 起手命令

```bash
cd /Users/lichun/tunxiang-os
git fetch git@github.com:hnrm110901-cell/tunxiang-os.git main:refs/remotes/origin/main
git rev-parse origin/main HEAD
gh pr list --state open --limit 20
gh pr view 335 --json mergeStateStatus,statusCheckRollup,reviews | head -30
git worktree list
cat docs/session-handoff-2026-05-09-evening.md  # 本文件
head -60 DEVLOG.md  # 5/9 傍晚 + 下午 + 中午 + 上午 4 wave
```

---

## 候选任务（按 ROI / 风险 排序）

### A. **等 #335 admin merge → 起 Phase 4** (~2-3h)
- #335 通过 codex/CI 后 admin merge
- 之后起 codemod-batch4：tx_member 31 文件 / 112 裸（baseline 头号大头）
- 决策 78 强制本地 pytest 守门
- 决策 79 提醒：tx_member 内可能有同 sales_channel 类预存 prod BUG，独立 flag

### B. **决策 79 Phase 2 — scan_order + ontology**（1.5h，触 §18）
- scan_order_service.py 4 处 + scan_order_routes.py 字面量 + ontology 加 `ch_scan_order`
- **必须先征得创始人确认**才能动 ontology（CLAUDE.md §18）— 起 session 头先问
- TDD 双 commit + Tier 1 Gate
- 预计 1 PR ≤30 行 diff

### C. **新发现 follow-up：test_trade_promotions 7 RBAC setup PR**（1h，T2）
- codemod 修了 collection error 后暴露的 pre-existing 测试 setup 缺口
- `_make_app_discount(db)` 没注入 RBAC 用户上下文 → 401 Unauthorized
- 修法：fixture 加 mock UserContext / require_role_audited
- 7 测试一次修 / 单独 follow-up PR / 决策 79 同例处理

### D. **新发现 follow-up：shared.security 包缺失诊断**（~2h，T2）
- test_trade_webhook 6 / test_trade_extended 10 失败根因（main 同款）
- 错误：`ModuleNotFoundError: No module named 'shared.security'; 'shared' is not a package`
- 看 PYTHONPATH / conftest namespace package 设置 / `shared/security/src/error_handler` 实际位置
- 影响 webhook + booking_api 路由全跑不通

### E. **#298 Phase 4 — tx_member 31 文件 / 112 裸**（~3h）
- A 通过后自然进入；可在 #335 OPEN 期并发独立从 main 起 PR
- 决策 78 + 79 经验：每文件本地 pytest 验证 + flag 暴露的 prod BUG

### F. **决策 79 残留 — cashier_engine 4 pre-existing**（~1h）
- payment_methods_config / shouqianba_trade_no_format / shouqianba_refund_trade_no_format / route_methods
- main 同款 pre-existing，与 sales_channel 无关，独立诊断

---

## 阻塞中（不要 touch）

- #271 invoice fen + RLS（DBA staging dry-run 等）
- #272 wine_storage fen（stack on #271）
- #240 v4 architecture sprint（长链 OPEN）

---

## 推荐起手

**A** — 看 #335 状态，等 merge 后无缝接 Phase 4（最大化 chain 推进）
**OR C** — #335 OPEN 期独立修 RBAC follow-up（不堆 stack，直接 follow-up #335 暴露的债）
**OR B** — 主推决策 79 主链续做（创始人 OK 即可启动）

按"A/B/C 三选一格式 + 预计 commit/文件/Tier，user confirm 再开 worktree"格式给方案，等用户拍板。

---

## 守约清单（必读）

- Co-authored-by 占位 `你的名字 <noreply@anthropic.com>`
- SSH 显式 push（git@github.com）
- Tier 1 强制 TDD 双 commit + AST 守门优先（决策 80）
- 原子化 commit（CLAUDE.md §21）
- 每 PR 后清 worktree
- 每 session 尾 DEVLOG + progress.md 更新
- §17 §18 §19 §20 §21 全文必备
- 决策 77：codemod 撤 band-aid 必须等 production 端覆盖
- 决策 78：codex 不是 codemod PR 唯一门禁，本地 pytest 必跑
- 决策 79：暴露的 pre-existing prod BUG 不混入 codemod PR，独立 follow-up
- 决策 80：Tier 1 修复优先 AST 静态扫
- 决策 82：context >80% 主动拆 session
