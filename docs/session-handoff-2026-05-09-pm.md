# 5/9 下午接力 starter prompt（context 拆 session）

## 上一 session 终态（2026-05-09 13:00）

main HEAD: `bd4b3c44`（含 #327 + 并发 v404/v405 NLQ readonly views migrations）

**本 session 战绩**：7 PR 全 admin merged
| PR | 内容 | merge sha |
|---|---|---|
| #310 | scan_decimal r3 启发式收紧 [T1] | `b8af4bb8` |
| #305 | docs/channel pinjin → pinzhi_pos 漂移收尾 [T3] | `6d74c1b3` |
| #307 | cleanup pinjin 残余 [T3] | `4ac952aa` |
| #318 | #298 codemod Phase 1 — scanner + baseline [T1] | `50af4929` |
| #320 | #298 Phase 2 batch 1 — 2 真凶 + revert band-aid [T1] | `4c5cf55b` |
| #322 | #298 Phase 2 batch 2 — tx_trade 248 import + 8 patch fix [T1] | `789c31a5` |
| **#327** | **决策 79 Phase 1 — Order(sales_channel=) 5 处修 [T1]** | **`ccfb8b9e`** |

**决策登记**：77（codemod 撤 band-aid 时序）/ 78（codex review 不是唯一门禁）/ 79（sales_channel prod BUG 三阶段）/ 80（AST 守门优于 mock）/ 81（architect 是 BUG 范围纠错）/ 82（context >80% 拆 session）

---

## 起手命令

```bash
cd /Users/lichun/tunxiang-os
git fetch git@github.com:hnrm110901-cell/tunxiang-os.git main:refs/remotes/origin/main
git rev-parse origin/main HEAD
gh pr list --state open --limit 20
git worktree list
cat docs/session-handoff-2026-05-09-pm.md  # 本文件
cat DEVLOG.md | head -80   # 5/9 上/下午两个 wave + 决策 80-82
```

---

## 候选任务（按 ROI / 风险 排序）

### A. **决策 79 Phase 2 — scan_order + ontology**（1.5h，触 §18 Ontology 冻结）
- scan_order_service.py:153/611/634 + scan_order_routes.py:172（4 处 fix）
- shared/ontology/src/sales_channel.py 加 `ch_scan_order` channel
- **必须先征得创始人确认**才能动 ontology（CLAUDE.md §18）— 起 session 头先问
- TDD 双 commit + 文件名含 tier1 触发 Tier 1 Gate
- 预计 1 PR ≤30 行 diff

### B. **#298 codemod Phase 3 — tx_trade 余 21 文件 / 51 裸 import**（~2h）
- 续 #298 chain（5/9 上午 #318/#320/#322 落地）
- 按 #322 模式 + 决策 78 强制本地 pytest 守门
- 决策 77 提醒：**不要撤 #287 band-aid**（codemod 未覆盖 production short-path import 前不能撤）
- 预计 1 PR ~22 文件 / TDD 双 commit

### C. **#298 codemod Phase 4 — tx_member 31 文件 / 107 裸**（~3h，跨服务最大头）
- 可独立从 main 起 PR（不堆 stack）
- 决策 78 + 79 经验：每 codemod 文件本地 pytest 验证
- 预计 1-2 PR

### D. **#318 P1 follow-up — scanner 抓 `import xxx`**（30min，债清）
- baseline 报告偏小，加 `ast.Import` 节点处理
- 重跑 baseline 数据对账
- 1 PR / 1 commit / ~20 行

### E. **决策 79 残留 prod BUG 调查**（~1h，T2/T3）
- cashier_engine 4 个 pre-existing test 失败：payment_methods_config / shouqianba_trade_no_format / shouqianba_refund_trade_no_format / route_methods
- main 同款 pre-existing，与 sales_channel 无关，需独立诊断
- 可能 v500+ 后续待办

### F. **决策 79 Phase 3 — v500 drop 物理 sales_channel 列**（~1d，需 PR4a 前置）
- 前置：tx-analytics + tx-finance 读 SQL 全切到 sales_channel_id（PR4a）
- 数据回填脚本 + COALESCE 兼容期
- 风险：高（drop 列不可逆，回滚靠 v501 + 数据备份）

---

## 阻塞中（不要 touch）

- #271 invoice fen + RLS（DBA staging dry-run 等）
- #272 wine_storage fen（stack on #271）
- #240 v4 architecture sprint（长链 OPEN）

---

## 推荐起手

**A**（决策 79 Phase 2）— 接力上一 session 直接续做，闭环决策 79 主链
**OR D**（#318 follow-up）— 暖手 30min，不触 ontology

按"A/B 二选一格式 + 预计 commit/文件/Tier，user confirm 再开 worktree"格式给方案，等用户拍板。

---

## 守约清单（必读）

- Co-authored-by 占位 `你的名字 <noreply@anthropic.com>`
- SSH 显式 push（git@github.com）
- Tier 1 强制 TDD 双 commit
- 原子化 commit（CLAUDE.md §21）
- 每 PR 后清 worktree
- 每 session 尾 DEVLOG + progress.md 更新
- §17 §18 §19 §20 §21 全文必备
- 决策 77：codemod 撤 band-aid 必须等 production 端覆盖
- 决策 78：codex 不是 codemod PR 唯一门禁，本地 pytest 必跑
- 决策 80：Tier 1 修复优先 AST 静态扫
- 决策 82：context >80% 主动拆 session
