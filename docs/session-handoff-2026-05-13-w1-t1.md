# Session Handoff — 2026-05-13 W1-T1 完工

> 上一 session 在 2026-05-13 完成 W1-T1 修复 + 2 个独立 issue 落盘。本文档是 fresh session cold-start 完整上下文，**不要靠对话历史，靠这个 + DEVLOG 顶部 + progress.md 顶部**。

---

## 起手必跑（顺序执行）

```bash
cd /Users/lichun/tunxiang-os
git fetch origin main
git log -n 5 origin/main --oneline

# PR #489 状态（W1-T1，等独立 reviewer）
gh pr view 489 --json state,mergeable,reviewDecision,statusCheckRollup \
  | python3 -c "import json,sys; d=json.load(sys.stdin); print('state:',d['state'],'/ mergeable:',d['mergeable'],'/ review:',d['reviewDecision']); [print(' ',(c.get('conclusion') or c.get('state','?')),c.get('name') or c.get('context','?')) for c in d['statusCheckRollup']]"

# PR #487 状态（W1-T2/T3/T4/T5 治理批，等 reviewer）
gh pr view 487 --json state,mergeable,reviewDecision

# PR #489 是否有 reviewer 评论（上 session 派的 code-reviewer agent 可能落 PR comment）
gh pr view 489 --comments | tail -50
```

---

## 状态快照（2026-05-13 收尾）

### W1 任务清单（12 周升级战略）

| 任务 | PR | 状态 | 备注 |
|---|---|---|---|
| W1-T1 tx-trade payment_event_consumer fail-loud | #489 | **OPEN，round-1 reviewer REQUEST_CHANGES 已修，等 round-2 或 user merge** | 5 commit：`2d61fe24` fix + `019c9962` docs + `9dbebff6` follow-up + `84151f70` round-1 fix (P0 tuple + P1 finally) + `4522b6ca` round-2 docs |
| W1-T2 tx-agent fail-loud | #487 | OPEN，等 reviewer | 跟 T3/T4/T5 同 PR |
| W1-T3 CLAUDE.md V3.0 → V3.1 | #487 | 同上 | |
| W1-T4 服务冻结令 pre-commit hook | #487 | 同上 | 30 天，2026-06-11 失效 |
| W1-T5 服务健康度 baseline + 周扫脚本 | #487 | 同上 | `docs/service-health/2026-W20.md` |

### 独立 issue（baseline 失败分流）

- **#490** [test-debt][T3] test_banquet_payment.py 19 errors — `5c49e3d7` mock 消除后 dead test code，建议方案 A 删除文件
- **#492** [test-debt][T2] test_payment_idempotency.py 3 fail — 双层根因（idempotent hit 早返回绕过 rollback 断言 + SQLAlchemy 元数据碰撞）

### 持续阻塞

- **5/13 deal-breaker（channel-aggregation 资质）**: 3 平台企业资质未启动，创始人级别非技术 task，倒计时已过
- **B**: dev-plan-60d 5/7 旧计划被 30+ commit 推翻，需 user 新 demo 故事核心方向
- **C**: DailySummary / Header export（#351 xfail）需 user 创始人 §18 ontology 对齐

---

## PR #489 决策树（fresh session 起手）

```
gh pr view 489 --json state,mergeable,reviewDecision

state = MERGED:
  → W2 起手（删 indonesia/malaysia/vietnam + Gateway 瘦身）

state = OPEN, reviewDecision = APPROVED:
  → user explicit 授权后 merge（normal merge，§19 资金路径不 admin-merge）
  → 然后起 W2

state = OPEN, reviewDecision = CHANGES_REQUESTED:
  → 读 PR comment + 反馈
  → 修完 push 新 commit（保 branch）
  → 重派 code-reviewer

state = OPEN, reviewDecision = "":
  → 上 session round-1 reviewer 已审（REQUEST_CHANGES → P0+P1 修了）
  → 现在等 user 拍板：是否派 round-2 reviewer 复审 P0+P1 fix（推荐——
    P0 真 BUG，验 fix 正确性合理），或 user explicit 接受现状 merge
  → 看 PR #489 最新 comment（应有 commit `84151f70` 的回复 + `4522b6ca`
    的 docs 沉淀）
```

### round-1 reviewer findings 摘要（已修，存档）

reviewer agent verdict **REQUEST_CHANGES**：

| # | 等级 | 内容 | 状态 |
|---|---|---|---|
| 1 | **P0** | T4 AST 守护对 tuple 形式 `except (Exception, ...):` 失明（绕过路径） | ✅ 修 (`84151f70`)：抽 `_exception_handler_is_broad` helper + 新增 T5 专项测 + 注入式验证通过 |
| 2 | **P1** | `audit_outbox_flusher_stop.set()` 在 `try/finally` 块外，fail-loud raise 路径下不执行 | ✅ 修 (`84151f70`)：移 4 行进 finally 块末尾 |
| 3 | P2 | `start_payment_event_consumer(consumer, session_factory)` 不用 session_factory | ❌ 不修 — pre-existing API（PR #128），超 W1-T1 surgical scope，留 audit P3 |
| 4 | 遗漏 | T1/T2 应断言 `registered == []` | ✅ 修 (`84151f70`) |
| 5 | 运维前置 | readinessProbe initialDelaySeconds ≥30s + redis PDB | ⚠️ 不在 PR scope，运维/SRE 配置侧前置 |
| 6 | 遗漏 | tx-pay producer 侧 stream 积压 cross-service 测试缺 | 已知技术债，本 PR 不能解 |
| 7 | 遗漏 | audit_outbox_flusher 异常路径测试缺 | 见 #5 P1 修补 — 现在 finally 内会跑 |

---

## W2 任务（PR #489 merge 后启动）

按上 session user 的 prompt：
- **W2 预告: 删 indonesia/malaysia/vietnam + Gateway 瘦身**

W2-A 调研起手清单（merge 后即可执行）：
```bash
# 1. 三国引用面 grep
grep -rln "indonesia\|malaysia\|vietnam\|印尼\|马来西亚\|越南" services/ shared/ docs/ infra/ apps/ 2>&1 | head -30

# 2. Gateway 当前路由
grep -rn "@router\.\(get\|post\|put\|delete\)\|@app\." services/gateway/src/ | head -30

# 3. 引入三国国际化的 commit
git log --oneline --all -S "indonesia" | head -5
# 应该能看到 1f9e592b feat(regional): 马来西亚/印尼/越南国际化 + PDPA合规 + Phase 4开放API (#129)
```

**预期产出**: W2 调研文档落 `docs/w2-deprecate-regional-plan.md`，列删除清单 + 影响面 + 迁移路径（如果有 caller），然后开 PR。

---

## 上下文锚点（不变量）

- **canonical 仓库路径**: `/Users/lichun/tunxiang-os`（唯一开发盘，main 截止 5/13 是 `b2b1fb7a` 或更新）
- **WorkBuddy `tunxiang-os` 是 Claude-3p 实验场**，不要碰
- **服务冻结令**: `.omc/policy/service-freeze.yml`（PR #487 还未 merge 时本地不存在；merge 后存在，until 2026-06-11）
- **baseline**: `docs/service-health/2026-W20.md`（PR #487 中）

### 关键 memory 规则（高频踩）

- **feedback_tunxiang_ci_gates** — `python-lint-test (*)` / `Ruff` / `frontend-build` / `Test Changed Services` 全 PR 一律失败是预存漂移，**可忽略**；真门禁 = `Tier 1 门禁判定` + `Run Tier 1 ...` + `源改动必须配对测试改动`
- **feedback_self_review_blind_spots** — T2+ infra / 安全 改动必须 explicit ask review；不自评 + 不 admin-merge
- **feedback_concurrent_pr_race** — PR create / push 前必须 `fetch origin main && log -n 5` 检查同主题；user 多 tty 并发，5/13 已撞 PR #491 (codemod 同时开)
- **feedback_handoff_finding_ids** — handoff 引用抽象 finding ID 必须验证落盘，不能脑补
- **feedback_proactive_session_split** — 4+ PR / 跨夜 / 连续"继续" 主动给 starter prompt（这个文档就是产物）

### 6 服务 codemod 资源占用

5/13 白天 user 在另一些 tty 跑 codemod #408 系列（PR #486 tx-growth / #488 tx-finance / #491 tx-member），都是 test-端 import 重写。**注意 cross-PR 冲突**：本 W1-T1 PR #489 改 tx-trade，**与 codemod 无文件冲突**，可独立 land。

---

## 意外发现（值得 surface 给 user）

**Tier 1 资金路径 idempotency 测试覆盖率虚高** — 见 #492 根因 1：
- `test_payment_idempotency.py` 的 3 个"并发 IntegrityError → rollback" case 由于 mock fixture 同时设了 existing record + IntegrityError side-effect，实际走 production code 的 idempotent_hit 早返回路径，从未触发 flush/rollback 代码分支
- production code 本身正确，但 contract 锁失效 → Tier 1 路径 audit 覆盖率虚假
- 建议下个 session 跟 user 单独抬一下（不是急事，但 audit 影响）

---

## 不要做的事

- ❌ 不要直接 push 到 main
- ❌ 不要 admin-merge PR #489（§19 Tier 1 资金链路必须独立 reviewer）
- ❌ 不要修 `shared/ontology/` 任何文件（§18 创始人确认）
- ❌ 不要重新引入 `except Exception:` 静吞 lifespan 任何启动 task（§14 + §17 联合约束，PR #489 T4 测试会抓）
- ❌ 不要在主 worktree checkout 其他 PR（memory `feedback_pr_rebase_worktree_pattern` — 独立 worktree + 独立 branch）

---

## End-state checklist

下个 session 结束前必须：

- [ ] PR #489 决策落地（merge / fix / ping）
- [ ] 如果 merge → W2 起手（调研 doc 或直接开 W2 PR）
- [ ] 如果 fix → reviewer 第二轮
- [ ] DEVLOG.md + docs/progress.md 顶部追加新段
- [ ] 这份 handoff 文档如果信息过时 → 新建 `docs/session-handoff-2026-05-XX-*.md` 而不是改本文件
