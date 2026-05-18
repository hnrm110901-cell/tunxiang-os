# 守门会决议 — tx-sync-worker Phase 1 dry_run 部署批准 (2026-05-18)

**状态**: APPROVED (创始人 explicit-ack 2026-05-18 4/4 = A 推荐)
**关联 issue**: #758 `[W2 P1 Gateway 瘦身] 抽出 tx-sync-worker 接管品智POS同步 + 企微 daily SOP`
**关联 PR**: 本 PR (feat/gateway-slim-tx-sync-worker-2026-05-18)
**策略文件**: `.omc/policy/service-freeze.yml:27` (planned_additions 已含 `tx-sync-worker`)
**Plan SoT**: `.omc/plans/2026-05-18-gateway-slim-plan.md` (830 行)

---

## §1 背景

战略 plan §23 W2 + §24 举措 #1 服务收敛 (Phase 1 临时态 20 → 21, 终态 W12 = 17):

Gateway 现状 `services/gateway/src/main.py` (line 70-156) + `services/gateway/src/sync_scheduler.py`
(712 行) 自带 5 个 cron job (4 pinzhi POS 同步 + 1 企微 daily SOP), 与 Gateway 路由代理职责
混杂. W2 P1 issue #758 抽到新服务 tx-sync-worker (端口 8021), Phase 1 dry_run 双轨并行
验证一周后, Phase 2 follow-up **严格顺序切换** (gateway PR 先 merge → 24h 间隔 → tx-sync-worker
values PR 后 merge 翻 RUN_MODE=live) — 见 §6 / §7 详述.

CLAUDE.md §26 服务冻结令 (frozen_until: 2026-06-12) 范围内, `tx-sync-worker` 已列入
`planned_additions` 例外列表 (W1 末段 5/17 落); 本决议同 PR 落盘归档.

**handoff 描述修正** (per plan §0.3 verify): issue #758 原描述说 "2 个定时任务" 但 gateway 实际
跑 5 个 cron job (4 pinzhi sync_scheduler.py + 1 wecom main.py:73 _run_daily_sop).
`pinzhi_pos_sync` 是 4 个独立 APScheduler job 不是 1 个.

---

## §2 创始人 explicit-ask 4 问决议 (2026-05-18, 4/4 = A 推荐)

| Q | 决议 | 决策依据 |
|---|------|----------|
| **Q1**: Job 命名 prefix (tx-sync-worker 包内) | **A: 保持原 5 个 id 不动** | 与 gateway 现行 metrics / 日志 ID 100% 一致, Phase 2 切换时 monitoring dashboard 0 改动; metric label `job=daily_dishes_sync` 在双轨期通过 `service="tx-sync-worker"` vs `service="gateway"` 区分; APScheduler job id 不接受 `.` 命名空间 (会被 misfire_grace_time check 解析错). |
| **Q2**: sync_router (/api/v1/sync/health) Phase 2 是否迁 | **A: Phase 2 follow-up 迁** | Phase 1 留 gateway sync_router 不动 (§3 OUT-OF-SCOPE), Phase 2 评估迁 scheduler + 健康 API 同服务边界清晰; 客户端 (web-admin / DEMO 巡检) 需 1 行 URL 改 (8021/api/v1/sync/health). |
| **Q3**: Phase 1 cron 时间是否完全复制 gateway | **A: 完全复制 + dry_run=true 默认** | Asia/Shanghai 02:00/03:00/hourly/15min/09:00 完全一致, 避免 timezone drift (plan §7.2). **`RUN_MODE=dry_run` env 默认 true** (env unset = dry_run), Phase 1 cron fire 时仅 log + metric 不调 pinzhi adapter, 与 tx-event-relay `shadow_mode=true` 模式同构. Phase 2 follow-up **严格顺序**: 先 ship gateway PR 关 scheduler → 间隔 24h verify 单跑 → 后 ship tx-sync-worker values PR 翻 `RUN_MODE=live` (详 §6 / §7). |
| **Q4**: Helm chart Tier | **A: T2 maxU=1 PDB enabled** | Phase 2 切单轨后 tx-sync-worker 是唯一同步入口, scheduler 不能 disruption 致 cron miss (品智 POS 当日订单丢失); PDB maxU=1 防 K8s 蓝绿部署期间剪掉单 pod; replicaCount 永久=1 (cron 不能 scale, 双 pod fire dup); 一开始就 T2 避免 Phase 2 切换时再改一轮 PR. Phase 1 dry_run 期间 PDB 实际不触发 (无 disruption). |

---

## §3 范围与边界 (强红线)

### 本 PR 包含

1. `services/tx-sync-worker/` 新服务 (11 文件 — Dockerfile / requirements / conftest / src/ 5 文件 + tests 3 文件)
2. `infra/helm/tx-sync-worker/` 11 文件 (Chart.yaml + values.yaml + 9 templates, T2 maxU=1 enabled)
3. `infra/compose/base.yml` 注册 :8021 + healthcheck (复用 svc-defaults / build-defaults / common-env anchors)
4. `infra/compose/envs/dev.yml` 注册 :8021 hot-reload + RUN_MODE=dry_run
5. `docs/infra/port-allocation-2026-05.md` 加 8021 行
6. 本守门会决议文档
7. `DEVLOG.md` + `docs/progress.md` 顶部 prepend 2026-05-18 块

### OUT-OF-SCOPE (严禁本 PR 触, 任何一项触发 = PR 作废)

| 文件 | 原因 | Phase |
|------|------|------|
| `services/gateway/src/main.py` | Phase 1 双轨并行, gateway scheduler 仍跑 | Phase 2 关 (独立 follow-up issue) |
| `services/gateway/src/sync_scheduler.py` | **copy 不 modify**, sync_router 留 gateway | Phase 2 评估迁 |
| `services/gateway/src/wecom_group_service.py` | 仅被 tx-sync-worker 跨服务 import, 0 修改 | Phase 2 follow-up 拆 shared/wecom/ |
| `services/tx-trade/cashier_engine.py` | §17/G10 双红线 Tier 1 零容忍 | 永不本 PR |
| `services/tx-trade/order_service.py` | §17/G10 双红线 | 永不本 PR |
| `services/tx-trade/payment_saga_service.py` | §17 红线 | 永不本 PR |
| `services/tx-trade/invoice.py` | §17 红线 | 永不本 PR |
| `services/tx-supply/inventory_io.py` | §17 红线 | 永不本 PR |
| `shared/events/src/emitter.py` | Tier 1 邻接事件总线 | 永不本 PR |
| `shared/adapters/pinzhi_pos/` | 仅 import, 0 修改 | 永不本 PR |
| Migration v447+ | 本 PR 无 DB schema 改动 | 永不本 PR |
| `shared/ontology/` | §18 创始人确认门禁 | 永不本 PR |

### dry_run 模式实现细节 (Q3 决议强红线)

Phase 1 `RUN_MODE=dry_run` 默认 (env unset = dry_run, 严格小写比较, "live" 才走真路径):

```python
# services/tx-sync-worker/src/jobs/pinzhi_sync.py 顶部
def _is_dry_run() -> bool:
    return os.environ.get("RUN_MODE", "dry_run").strip().lower() != "live"

async def _run_dishes_sync() -> None:
    if _is_dry_run():
        # log "would_call_pinzhi_adapter" + metric status=dry_run + 提前 return
        return
    # ... 真路径 (Phase 2 翻 live 才走)
```

5 jobs 全部 dry_run gate 在 entry point (4 pinzhi + 1 wecom). dry_run 路径不调 pinzhi
adapter / WecomGroupService, 不写 sync_logs, 仅 log + Prometheus metric.

---

## §4 与服务冻结令 (CLAUDE.md §26) 关系

- `.omc/policy/service-freeze.yml:27` `planned_additions` 已含 `tx-sync-worker   # W2 issue #758`
- 本决议同 PR 归档至 `docs/governance/decisions/`
- 例外申请流程 4 步 (per CLAUDE.md §26):
  1. ✅ 创始人 explicit approval (本文档 §2 4 问决议 4/4 A)
  2. ✅ 架构守门会决议记录 (本文档)
  3. ✅ planned_additions 列表已含 (W1 末段 5/17 落)
  4. ✅ 实施 (本 PR: services/tx-sync-worker/ + infra/compose/base.yml 注册)

---

## §5 5 项验收 (本 PR ship 必满足)

| # | 验收项 | 验证方法 |
|---|--------|----------|
| 1 | `tx-sync-worker /health` 返 5 jobs registered + scheduler.running=true + run_mode=dry_run | `curl http://localhost:8021/health` |
| 2 | `/metrics` 暴露 5 Prometheus metrics (executions_total / last_run_timestamp / duration / retry / dry_run_active) | `curl http://localhost:8021/metrics | grep tx_sync_worker_` |
| 3 | gateway 0 改动 (Phase 1 双轨边界严守) | `git diff origin/main -- services/gateway/` → 空 |
| 4 | 5 jobs 业务函数与 gateway 0 业务 line diff | `diff services/gateway/src/sync_scheduler.py:128-577 services/tx-sync-worker/src/jobs/pinzhi_sync.py` → 仅 import path / metric / dry_run gate / module logger 改, 业务 0 diff |
| 5 | 单元测试全 PASS (19 cases) | `pytest services/tx-sync-worker/src/tests/ -v` |

### Phase 1 观察期对账信号 (hotfix #819 P0-2 重设计)

⚠️ **dry_run 路径 `pinzhi_sync.py:_record_dry_run` 写 sync_logs 表 status='dry_run'** (与真路径 status='success' 区分), Phase 1 一周观察期 sync_logs 表双方都有行 — **对账主轨基于 SQL 双边 join, Prometheus 仅监控不对账**.

**原因 (P0-2 hotfix)**: 原方案 PromQL `apscheduler_jobs_executed_total{service="gateway"}` 是**凭空 metric** — gateway/src/main.py 用 `prometheus_fastapi_instrumentator.Instrumentator` 只 export HTTP request metrics, APScheduler 0 add_listener(EVENT_JOB_EXECUTED) 桥接 prometheus_client; 任何对账依赖此 metric 永远查不到数据.

**对账主轨 (SQL, hotfix #819 后)**:

```sql
SELECT
  date_trunc('day', started_at) AS day,
  merchant_code,
  sync_type,
  status,
  count(*) AS fire_count
FROM sync_logs
WHERE started_at >= NOW() - INTERVAL '7 days'
GROUP BY 1, 2, 3, 4
ORDER BY 1 DESC, 2, 3;
```

**通过标准**:
- 同 (day, merchant_code, sync_type) 组, status='success' (gateway 真路径) count vs status='dry_run' (sync-worker) count 差异 ≤ 10% (允许 5min cron drift + 网络重试)
- 4 pinzhi jobs × 3 merchants (czyz/zqx/sgc) × 5+ sync_types × 7 days = ~30 (day, merchant, type) 组合, 任一组 differ > 10% → 调查

**Prometheus 辅助监控 (不对账)**:
- `tx_sync_worker_executions_total{job, status}` — sync-worker dry_run / success / error / failed 计数
- `tx_sync_worker_dry_run_active` — gauge, 1=on / 0=off, 用 alert
- gateway APScheduler 监控延后补 (今后 add_listener 桥接, follow-up #809)

**wecom_sop dry_run 特殊**: 单 job 0 merchant_code 维度 — 留 Prometheus metric-only, 不入 sync_logs 对账主轨.

---

## §6 风险与缓解

| 风险 | 严重度 | 缓解 |
|------|------|------|
| dry_run 误关 (RUN_MODE=live) → dup pinzhi API 调用 致 429 + sync_logs 双倍 | **P0** | 1) env unset = dry_run hardcode; 2) Helm values.yaml 显式注释 "Phase 2 follow-up 翻 live 前必须先关 gateway scheduler"; 3) tx_sync_worker_dry_run_active gauge monitoring alert; 4) Phase 2 follow-up issue 标题 + DOD explicit "**严格顺序**: 先关 gateway PR merge → 24h 间隔 → 后翻 RUN_MODE=live" (颠倒 = P0 dup fire) |
| timezone drift (容器 TZ ≠ Asia/Shanghai) | P1 | 1) Dockerfile `ENV TZ=Asia/Shanghai`; 2) APScheduler 显式 `timezone="Asia/Shanghai"`; 3) test_scheduler_timezone_asia_shanghai 验证 |
| dup task firing (Phase 1 双轨期 gateway + tx-sync-worker 同时 fire) | P0 if dry_run 误关 | 与上一行重叠, dry_run=true 强制下 0 风险 |
| metric collision (gateway + tx-sync-worker 共存) | P2 | metric 名 prefix `tx_sync_worker_` 强制不冲突, label `service="tx-sync-worker"` 区分 |
| 跨服务 import (services.gateway.src.wecom_group_service) | P2 | Phase 1 接受 (Dockerfile COPY services/gateway/); Phase 2 follow-up 拆 shared/wecom/ |
| Alembic 双 head (本 PR 0 migration, 风险 0) | N/A | 本 PR 不立 migration v447+ |

---

## §7 后续审议 (Phase 2 follow-up — 本 PR 立 issue 不实施)

### Issue #806: `[W4 P1] 关 gateway scheduler + 翻 RUN_MODE=live + 跑满一周对账`

**Scope** (~2 人日, W4 demo 轨 deliverable). **严格顺序** (不可颠倒 — 颠倒 = P0 dup fire):

**Step 1** — PR-A 关 gateway scheduler (先 merge):
1. 删 `services/gateway/src/main.py` line 7 `import apscheduler...`
2. 删 line 31 `from .sync_scheduler import create_sync_scheduler`
3. 删 line 68-156 `_scheduler = AsyncIOScheduler(...)` block
4. 保留 `sync_router as sync_health_router` (Q2 决议留 gateway)
5. ship + verify gateway 单纯 API gateway 无 cron (24h 间隔观察)

**Step 2** — PR-B 翻 RUN_MODE=live (PR-A 已 merge **24h 后**才 merge):
1. 改 `infra/helm/tx-sync-worker/values.yaml` `RUN_MODE: "live"` (原 `"dry_run"`)
2. 同时翻 `infra/compose/envs/{dev,gray,prod}.yml` 一致

**顺序错的代价**:
- 翻 live 先 → 5 cron jobs 双跑 (gateway + sync-worker) → 数据 dup, pinzhi API 429 (P0)
- 关 gateway 先 → 24h 间隔窗 dry_run 仍跑, 5 jobs 失效几小时 (可接受)

**对账验收** (PR-A merge 后 1 周观察, SQL 双边 join — hotfix #819 P0-2 重设计):
- SQL 主轨: `SELECT date_trunc('day', started_at), merchant_code, sync_type, status, count(*) FROM sync_logs WHERE started_at >= NOW() - INTERVAL '7 days' GROUP BY 1,2,3,4`
- 通过标准: 同 (day, merchant_code, sync_type) 组的 success count (gateway) vs dry_run count (sync-worker) 差异 ≤ 10% (允许 5min cron drift)
- Prometheus 辅助监控: `tx_sync_worker_executions_total{job, status}` (仅监控不对账)
- Phase 1 测试集 (20 cases, hotfix +1 P0-3 case) 全绿
- PR-B 切单轨当晚 02:00 daily_dishes_sync fire 真路径成功

**Phase 2 后续 follow-up** (issue #806 DOD 第 3-4 项):
- 拆 `services/gateway/src/wecom_group_service.py` → `shared/wecom/group_service.py`
- 评估迁 `sync_router` 到 tx-sync-worker

### 下次守门会

W23 (2026-06-01) — 验收 Phase 1 dry_run 一周观察 + 立 Phase 2 切单轨 follow-up issue

---

## §8 References

- 战略 plan §23 W2 / §24 举措 #1 服务收敛
- CLAUDE.md §17 Tier 1 / §19 独立验证 / §25 Tier 1 邻接 / §26 服务冻结令
- `.omc/plans/2026-05-18-gateway-slim-plan.md` (本 PR planner SoT, 830 行)
- `.omc/plans/open-questions.md` (4 问 lock + W2 残留 P1)
- `.omc/policy/service-freeze.yml` (planned_additions verify line 27)
- 参考决议: `docs/governance/decisions/2026-05-17-tx-event-relay-shadow-mode-approval.md` (#757 模板)
- Memory:
  - `feedback_planner_verified_claims_must_regrep.md` (数字 self-regrep, plan §0)
  - `feedback_projector_asyncpg_pool_model.md` (Phase 2 真路径 DB pool 模型)
  - `feedback_devlog_edit_anchor_drift.md` (DEVLOG/progress prepend anchor verify)
  - `feedback_carveout_admin_merge_pattern.md` (5 项裁决)
  - `feedback_tier1_test_filename_workflow_trigger.md` (T2 标准 _tier1.py 后缀豁免)
  - `feedback_graceful_degradation_pattern.md` (Phase 2 adapter 失败 fail-open + 监控)

---

**决议人**: 创始人 (2026-05-18 explicit-ack 4/4 = A 推荐)
**归档时间**: 2026-05-18
**Tier 1 邻接 explicit-ask 累计**: T2 服务 (品智 POS 同步 Phase 2 切单轨后属 §17 Tier 2 路径); §19 三 reviewer 流程走但不强制 Tier 1 邻接 5 项 explicit-ask
