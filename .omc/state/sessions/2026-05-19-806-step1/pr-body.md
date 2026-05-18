# [T2邻接] feat(gateway): #806 Step 1 — 关 gateway scheduler (sync_router 留 gateway)

Closes part of #806 (Phase 2 Step 1 only; Step 2 = 独立 PR after 24h hold).

## Scope

- 删 `services/gateway/src/main.py`:
  - apscheduler imports (2 行 EVENT_JOB_* + AsyncIOScheduler)
  - `from .apscheduler_metrics import apscheduler_job_listener`
  - `from .sync_scheduler import create_sync_scheduler`
  - `_scheduler = AsyncIOScheduler(...)` 整 init 块 + add_job + add_listener + start/shutdown 整 block
  - 残留 imports asyncio / structlog + logger 绑定 (round-2 code review C-P1-1)
- 删 `services/gateway/src/apscheduler_metrics.py` + 4 unit tests (round-2 critic K-P1-1: Phase C.1 #820 Counter post-cutover 无 producer → 删 model 而非保留死代码)
- 加 `services/gateway/src/sync_scheduler.py` `create_sync_scheduler()` + 4 cron 入口函数 DO NOT CALL banner (防 silent 复活 dual-fire P0 risk per K-P1-3)
- 保留 `from .sync_scheduler import sync_router as sync_health_router` (Q2 决议)
- 保留 `app.include_router(sync_health_router)` (Q2 决议)
- main.py: 255 → ~150 lines (-105)

## ⚠️ Step 2 ship lockdown (per critic K-P1-5)

**Step 2 PR (RUN_MODE=live 翻) MUST NOT merge before:** `<this-PR-merge-timestamp + 24h>` (具体时间填本 PR squash merge 完成的 UTC 时间 + 24h, 由 admin-merger 在 follow-up issue 评论补上)

Step 2 reviewer 必须在 approve 前验证:
```bash
gh pr view 806 --json mergedAt | jq -r '.mergedAt'  # 取此 PR merge time
# 当前时间 - merge_time 必须 ≥ 24h
```

Step 2 follow-up issue 将立 (admin-merge 后), label `do-not-merge`, 标题: `[Tier 1 邻接][T2] #806 Step 2 — 翻 RUN_MODE=live + sync_scheduler.py cron half 删 + apscheduler dep 删 (DO NOT MERGE before <ts>)`.

## Reconciliation observation window 偏离声明

决议 SoT (`docs/governance/decisions/2026-05-18-tx-sync-worker-shadow-approval.md` §5) 要求 Phase 1 dry_run + Phase 2 dual-data 共 7-day SQL 对账观察期.

实际状态:
- Phase 1 dry_run ship: 5/18 (PR #805)
- Step 1 ship (本 PR): 5/19 → gateway 不再写 sync_logs `status='success'` 行
- Dual-data window: 24-48h (5/18→5/19)

接受偏离原因: W4 5/24 cutover deadline (战略 plan §23) + 战略 plan §6 真 Outbox 接入路线 W11 全切 — Step 1/2 不能再推. Step 2 PR (5/20+) reconciliation gate 改用 row-count threshold 标准: 每 (day, merchant_code, sync_type) cell 必须 ≥3 success rows AND ≥3 dry_run rows 才计算 drift %, 不足量直接 skip cell.

Founder explicit-ack: 待 PR 开启时 user 明确接受 (本 PR body 落地后, user 通过 admin-merge 即视为 ack).

## §19 round-1 reviewer 结果

| reviewer | P0 | P1 | P2 | round-2 状态 |
|---|---|---|---|---|
| code | 0 | 1 (asyncio/structlog 残留) | 2 | ✅ 修 |
| security | 0 | 0 | 3 (apscheduler_metrics dead + DEVLOG + asyncio overlap) | ✅ 修 (overlap) |
| critic | 0 | 5 (K-P1-1...5) | 4 | ✅ 4 修, 1 推 Step 2 (K-P1-2), 1 用 banner 兜底 (K-P1-3 Option B) |

**Round-2 fix coverage:**
- ✅ C-P1-1: 残留 imports 删
- ✅ K-P1-1: apscheduler_metrics 模块 + 4 tests 删 (Fix A)
- ⏸️ K-P1-2: apscheduler dep 保留 (sync_scheduler.py 仍 module-level import 依赖, Step 2 PR scope)
- ✅ K-P1-3: sync_scheduler.py DO NOT CALL banner (Option B 兜底, full split Step 2 PR)
- ✅ K-P1-4: DEVLOG/progress prepend
- ✅ K-P1-5: PR body lockdown 段 + Step 2 follow-up issue (admin-merge 后立)

## 5 项前置稳定模式 (per CLAUDE.md §25)

1. §19 reviewer APPROVE — round-2 critic-only re-verify 待
2. CI 真门禁 — gateway main.py import smoke (`scripts/gateway-import-smoke.sh`) 触发; Tier 1 path glob 不触 (T2 邻接, §25 豁免)
3. 重 fetch 无并发 — base HEAD `49837a14` (round-1 baseline); 推送前再 fetch verify
4. 重 search 无同主题 — `gh pr list --search "scheduler OR sync-worker OR 806 OR sync_scheduler OR APScheduler" --state open` 0 结果 (round-1 verify, 推送前重 verify)
5. §17 红线 0 touch — `git diff --name-only origin/main..HEAD | grep -E "cashier_engine|order_service|payment_saga|wine_storage|invoice_service|emitter\.py|pinzhi_pos|aoqiwei|meituan_adapter"` 0 match

## Tier 1 邻接 explicit-ask 累计

本 PR = 第 44 或 45 例 (取决于 PR #846 #737 Phase A hold 是否先 merge)

## 关联

- 父 issue: #806 (Phase 2 cutover)
- 父父 issue: #758 (Gateway 瘦身 抽 tx-sync-worker)
- Predecessor PR: #805 (Phase 1 shadow ship), #819 (hotfix), #820 (Prometheus scrape audit), #826 (MetricsAuthMiddleware)
- Escape anchor: tag `pre-scheduler-removal-v1.0` (49837a14, 已 push origin)
- 战略 plan W4 节点 (战略 plan §23 5/24 deadline)
