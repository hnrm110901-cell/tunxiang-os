# tx-sync-worker Phase 2 切换 Rollback Procedure (2026-05-19)

**状态**: ACTIVE — W4 (5/24-5/31) Phase 2 切换窗口有效  
**关联 issue**: #821 `[W4 P1] tx-sync-worker Phase 2 切换 rollback procedure 显式文档化`  
**关联 PR**: 本文档 PR  
**父决议**: `docs/governance/decisions/2026-05-18-tx-sync-worker-shadow-approval.md` §6 / §7  
**Tier**: T3 docs  

---

## §1 背景与前置条件

PR #805 (#758) ship Phase 1 — tx-sync-worker 新服务 :8021 以 `RUN_MODE=dry_run` 双轨并行运行.  
Gateway 仍跑 5 个 APScheduler cron job (4 pinzhi POS 同步 + 1 企微 daily SOP).  
PR #819 hotfix 修了 4 P0 + 1 P1 (wecom_sop ImportError BLOCKER 已解除).

Phase 2 切换路径 (**严格顺序, 不可颠倒** — 详 #806):

| Step | 操作 | 前置 |
|------|------|------|
| **PR-A** | 关 gateway scheduler (删 APScheduler block) | `git tag pre-scheduler-removal v1.0` 必做 |
| **24h 间隔** | 验证 gateway 单纯 API gateway 无 cron | sync_logs dry_run 行持续新增 |
| **PR-B** | 翻 `RUN_MODE=live` (Helm values + compose envs) | PR-A merge 后 24h 才 ship |

**本文档服务于**: 当 Phase 2 任一步骤出现异常时, 快速、有序、无 dup 地回退到安全状态.

---

## §2 触发条件

### §2.1 P0 立即触发 (5 分钟内启动 rollback)

满足任一条件立即触发:

| 指标 | 阈值 | 数据来源 |
|------|------|---------|
| 5 jobs 任一连续 fail count | > 2 次 (status='error' 或 'failed') | `sync_logs` 表 / Prometheus |
| 数据处理延迟 | > 30 min (`finished_at - started_at`) | `sync_logs.finished_at` |
| 品智 POS API 限流 | 429 rate limit 持续 > 2 次 job cycle | 服务日志 structlog |
| Prometheus 错误增量 | `tx_sync_worker_executions_total{status="error"}` > 0 | Grafana dashboard |
| RUN_MODE 配置漂移 | status='dry_run' 行在 PR-B 翻 live 后仍出现 | `sync_logs` 表 |

### §2.2 P1 升级观察 (24h 内升级为 rollback)

| 指标 | 阈值 |
|------|------|
| sync_logs delta_pct 异常 | 同 (day, merchant_code, sync_type) success vs dry_run 差异 > 10% 持续 ≥ 2 天 |
| wecom SOP 企微消息缺失 | Prometheus `tx_sync_worker_executions_total{job=wecom_group_daily_sop}` 零增量 > 24h |
| 数据 dup 告警 | 同一 (tenant_id, merchant_code, sync_type, day) 多行 status='success' (Phase 2 PR-B 后应单源) |

### §2.3 不触发 rollback 的预期现象

- **Phase 1 观察期**: `success_rate` dashboard tank — 预期现象 (dry_run 行污染分母, 详 #806 FU-6)
- **Phase 2 PR-A 后 24h 窗口**: sync_logs 仅有 dry_run 行 (gateway cron 已关, tx-sync-worker 仍 dry_run) — 预期空洞, 不触发 rollback
- **wecom_sop 无 sync_logs 行** — wecom dry_run 不入 sync_logs (详 #806 FU-8), 走 Prometheus 监控

---

## §3 两种回滚路径

### §3.1 路径 A — PR-A (关 gateway scheduler) ship 后 24h 内

**场景**: gateway cron 已关, tx-sync-worker 仍 dry_run, 发现 gateway 关闭导致的意外问题.  
**风险**: 这段窗口 5 jobs 不真执行 (dry_run 只 log). 回退后 gateway cron 恢复双轨.

```bash
# Step 1: 找 PR-A 的 merge commit OID
git log origin/main --oneline --grep="gateway" -n 10

# Step 2: revert 整个 PR-A merge commit (保留所有子 commit 反转)
git revert -m 1 <PR-A-merge-commit-OID> --no-edit

# Step 3: push + 走 admin-merge (T2 explicit-ask — §25 五项稳定模式)
git push origin HEAD:hotfix/revert-gateway-scheduler-removal-<date>
gh pr create --title "hotfix: revert gateway scheduler removal (rollback path A)" \
  --body "Emergency rollback path A. Trigger: <描述触发条件>. Reverts PR-A."

# Step 4: redeploy gateway (APScheduler 恢复)
# (走正常 CD 流程 或 kubectl rollout restart deployment/gateway)

# Step 5: 验证
# 期望: gateway cron 重新 fire, sync_logs 出现 status='success' 行
# tx-sync-worker 保持 dry_run, 不产生 dup (RUN_MODE=dry_run 不调 pinzhi adapter)
```

**回退后状态**: 双轨 (gateway 真跑 + tx-sync-worker dry_run), 与 Phase 1 初始状态相同.  
**无 dup 原因**: tx-sync-worker `RUN_MODE=dry_run` 不调 pinzhi adapter, 仅写 sync_logs status='dry_run'.

### §3.2 路径 B — PR-B (翻 RUN_MODE=live) ship 后

**场景**: tx-sync-worker 已为 live 模式, 发现同步错误 / 数据 dup / 配置漂移.  
**风险**: 切回 dry_run 后 5 jobs 暂停真执行 (品智 POS 同步 / 企微 SOP 暂停), 直到修复再翻 live.

#### 快速路径 (5-15 min) — Helm env override

```bash
# Step 1: 修 Helm values (RUN_MODE: live → dry_run)
# 文件: infra/helm/tx-sync-worker/values.yaml
# 将 RUN_MODE: "live" 改回 RUN_MODE: "dry_run"

# Step 2: rolling restart tx-sync-worker (不中断服务, 滚动重启)
kubectl rollout restart deployment/tx-sync-worker -n <namespace>
kubectl rollout status deployment/tx-sync-worker -n <namespace>

# Step 3: 验证 env 已生效
kubectl exec -n <namespace> deployment/tx-sync-worker -- env | grep RUN_MODE
# 期望: RUN_MODE=dry_run

# Step 4: 验证 sync_logs 不再出现 status='success' 新行
# (已有 success 行保留, 看新 fire 的 cron 写入 dry_run)
```

#### 完整回滚路径 (若 env override 不够) — revert PR-B + 恢复 gateway

```bash
# Step 1: revert PR-B (翻 live 的 values PR)
git revert -m 1 <PR-B-merge-commit-OID> --no-edit
git push origin HEAD:hotfix/revert-sync-worker-live-<date>

# Step 2: 如需恢复 gateway cron (当前 PR-A 已关 scheduler)
# 同时 revert PR-A (路径 A 步骤), 让 gateway 重新接管 5 jobs
git revert -m 1 <PR-A-merge-commit-OID> --no-edit

# Step 3: 合并两个 revert 为一个 hotfix PR, admin-merge
```

**副作用说明** (明确告知业务方):
- 这段时间 5 cron jobs 不真执行 (pinzhi POS 当日数据同步 + 企微 daily SOP 暂停)
- 不产生数据 dup (tx-sync-worker dry_run 不写 pinzhi adapter)
- 企微 SOP 消息当日不发送, 次日恢复后补发不可回溯 → 需 oncall 手动通知相关门店

---

## §4 数据一致性检查

回滚后必跑以下 SQL 对账 (per #806 W4 验收的 sync_logs SQL 主轨方案).  
**RLS 约束**: 跑前需 `SET LOCAL app.tenant_id = '<uuid>';` per merchant (BYPASSRLS prod role 跑多租户汇总).

### §4.1 回滚前后双边对账

```sql
-- 双边对账: revert 前后同一时间窗 sync_logs 来源比对
-- 期望:
--   revert 前 (Phase 2 live 运行期): 双源 0 行 gateway + N 行 sync-worker status='success'
--   revert 后 (路径 A): 双源各有 status='success' 行 (gateway 真跑) + status='dry_run' 行 (sync-worker)
--   revert 后 (路径 B fast): 仅 status='dry_run' 新增行, status='success' 新增=0
SELECT
    tenant_id,
    merchant_code,
    sync_type,
    status,
    COUNT(*) AS fire_count,
    MIN(started_at) AS first_fire,
    MAX(started_at) AS last_fire
FROM sync_logs
WHERE started_at BETWEEN '<revert_time>'::timestamptz - INTERVAL '1 hour'
                     AND '<revert_time>'::timestamptz + INTERVAL '1 hour'
  AND tenant_id = current_setting('app.tenant_id', true)::uuid
GROUP BY 1, 2, 3, 4
ORDER BY tenant_id, merchant_code, sync_type, status;
```

### §4.2 路径 A 专项 — 双轨恢复确认

```sql
-- 路径 A 回退后: 验证 gateway 真路径恢复 (status='success' 出现新行)
-- 若 30 分钟内无 status='success' 新行 → gateway cron 未成功恢复 → escalate
SELECT
    DATE_TRUNC('minute', started_at AT TIME ZONE 'Asia/Shanghai') AS minute,
    merchant_code,
    sync_type,
    status,
    COUNT(*) AS fire_count
FROM sync_logs
WHERE started_at >= '<revert_complete_time>'::timestamptz
  AND tenant_id = current_setting('app.tenant_id', true)::uuid
GROUP BY 1, 2, 3, 4
ORDER BY 1 DESC, 2, 3, 4;
```

### §4.3 路径 B 专项 — dup 检查

```sql
-- 路径 B 场景: 检查是否有 dup (同 tenant + merchant + sync_type 同 5 min 窗口多行 success)
-- 期望: 任何组合的 COUNT(*) ≤ 1 (cron 单 pod 不 dup)
-- ≥ 2 行 = P0 数据 dup → 联系 oncall + 立 issue
SELECT
    tenant_id,
    merchant_code,
    sync_type,
    DATE_TRUNC('hour', started_at) AS hour_bucket,
    COUNT(*) FILTER (WHERE status = 'success') AS success_count
FROM sync_logs
WHERE started_at >= NOW() - INTERVAL '6 hours'
  AND status = 'success'
  AND tenant_id = current_setting('app.tenant_id', true)::uuid
GROUP BY 1, 2, 3, 4
HAVING COUNT(*) FILTER (WHERE status = 'success') > 1
ORDER BY 4 DESC, 2, 3;
-- 0 行 = 无 dup (正常)
-- ≥ 1 行 = dup 存在 → 核查 gateway + sync-worker 是否同时 fire live 路径
```

### §4.4 异常判定与处置

| 查询 | 异常 | 处置 |
|------|------|------|
| §4.1 revert 后 1h 无任何新行 | 数据停流 | 检查 gateway pod / tx-sync-worker pod 状态; kubectl describe |
| §4.2 路径 A revert 后 30min 无 success 新行 | gateway cron 未恢复 | kubectl rollout restart deployment/gateway; 检查 APScheduler log |
| §4.3 success_count > 1 | 数据 dup | 立即确认 RUN_MODE; kubectl exec -- env | grep RUN_MODE; 若 gateway + sync-worker 双跑 live 立即 rollback 一侧 |

---

## §5 通讯计划

### §5.1 角色与责任

| 角色 | 职责 | 联系方式 |
|------|------|---------|
| **Oncall** (执行者) | 触发 rollback, 跑 §3 步骤, 做 §4 SQL 对账 | 值班群 |
| **创始人 (未了已)** | P0 告知 + explicit sign-off rollback 决定 | 微信 / 企微直接 @ |
| **供应链业务方** | 知晓同步暂停时间窗, 接收恢复通知 | 企微供应链群 |
| **财务结算方** | 知晓日结数据是否有影响 (路径 B 同步暂停期间) | 企微财务群 |
| **客户 SOP 接收方** | 知晓企微 daily SOP 当日不发 (路径 B) | 企微客服群 |

### §5.2 通知模板

**P0 触发后 5 分钟内 (oncall → 创始人)**:

```
[P0 tx-sync-worker rollback 触发]
触发条件: <描述 §2.1 哪条触发>
当前状态: <gateway/sync-worker 运行状态>
执行路径: 路径 A / 路径 B
预计恢复时间: <ETA>
SQL 对账状态: 进行中
```

**Rollback 完成后 (oncall → 业务方群)**:

```
[tx-sync-worker 切换已回滚]
回滚完成时间: <时间>
影响范围:
  - 路径 A: 无数据暂停 (双轨恢复), 对账差异 <X%>
  - 路径 B: 同步暂停约 <N> 分钟, 已恢复 dry_run 模式
后续: 24h 监控期, 修复后重新评估 Phase 2 切换时间窗
```

### §5.3 时间窗预期

| 阶段 | 预期时长 |
|------|---------|
| 触发 → 开始 rollback 操作 | ≤ 5 min (P0) / ≤ 30 min (P1 升级) |
| Helm env override rolling restart | 5-15 min |
| git revert + admin-merge | 15-30 min |
| §4 SQL 对账验证 | 15-30 min |
| 创始人确认 + 24h 监控宣布稳定 | 24h |

---

## §6 Pre-flight Checklist (Phase 2 PR-A 之前必做)

per #821 issue DOD §1:

- [ ] `git tag pre-scheduler-removal v1.0` — 留逃生 anchor (无 tag = 严禁 ship PR-A)
- [ ] verify tx-sync-worker `/metrics` 5 Prometheus metrics 全在 (`tx_sync_worker_executions_total` + 4 job metrics)
- [ ] verify Phase 1 一周 SQL 对账主轨通过 (见 `docs/governance/runbooks/tx-sync-worker-reconciliation.sql` Query 5: 0 行)
- [ ] verify §17/G10 Tier 1 路径 (cashier_engine / order_service / payment_saga / invoice / inventory_io) 无任何 staging 异动
- [ ] FU-7 prod DB role BYPASSRLS verify (wecom_sop.py:79-82 跨租户 SELECT 前提)
- [ ] FU-5 wecom except 范围 broaden (路径 B 翻 live 前)

---

## §7 演练计划

**W3 内做 1 次 staging 演练** (revert in dev compose):

1. dev compose 启动 gateway (APScheduler 运行) + tx-sync-worker (dry_run)
2. 模拟 PR-A: 注释掉 gateway APScheduler block + restart gateway
3. 等待 1 个 cron cycle, 验证 sync_logs 仅有 dry_run 行 (无 success)
4. 执行路径 A rollback: revert gateway + restart
5. 验证 sync_logs 恢复 success 行
6. 落盘演练结果: `docs/governance/decisions/2026-05-19-tx-sync-worker-rollback-drill.md`
   (该文件演练完成后另立, 不在本 PR scope)

---

## §8 关联文档 / Issues / PRs

| 资源 | 说明 |
|------|------|
| PR #805 | Phase 1 tx-sync-worker ship (dry_run 双轨) |
| PR #819 | Phase 1 hotfix — 4 P0 + 1 P1 (wecom_sop ImportError 解除 Phase 2 BLOCKER) |
| Issue #806 | Phase 2 cutover 完整 DOD (关 gateway scheduler + 翻 live + 对账验收) |
| Issue #821 | 本文档 issue (W4 P1 rollback procedure 显式文档化) |
| 父决议 §6 / §7 | `docs/governance/decisions/2026-05-18-tx-sync-worker-shadow-approval.md` |
| 对账 SQL Runbook | `docs/governance/runbooks/tx-sync-worker-reconciliation.sql` |
| 战略 plan | §23 W4 deliverable / §24 举措 #1 服务收敛 |

---

*文档有效期: W4 (5/24-5/31) Phase 2 切换窗口. Phase 2 成功 ship 后归档.*
