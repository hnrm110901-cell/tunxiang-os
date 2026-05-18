# tx-sync-worker Cutover Rollback Runbook

> **范围**: W4 起手 Phase 2 切换 (PR-A 删 gateway scheduler → 24h 间隔 → PR-B 翻 `RUN_MODE=live`) 真起手 + 真翻车时的紧急回退 procedure
>
> **关联**: PR #805 (Phase 1 ship) / PR #819 (4 P0 + 1 P1 hotfix) / issue #806 (Phase 2 DOD) / issue #821 (W4 P1 rollback procedure 显式文档化) / issue #820 (Prometheus scrape audit) / issue #822 (OMC team 流程改进)
>
> **配套**: `scripts/cutover/rollback-sync-worker.sh` (bash dry-run 默认 + 二次确认才真执行)
>
> **Tier**: T2 (品智 POS 同步路径 §17 Tier 2 — 部署纪律 W4 deliverable)

---

## 1. 切换概览

Phase 2 cutover 走两个独立 PR + 强制 24h 间隔, 不可颠倒:

| 步骤 | PR | 改动 | 风险 | 间隔 |
|------|-----|------|------|------|
| Step 1 | PR-A | `services/gateway/src/main.py` 删除 scheduler 块 (line 7 / line 31 / line 68-156) | 5 cron jobs 失效几小时 (可接受) | — |
| 等待 | — | gateway 纯 API gateway 单跑 verify | sync-worker dry_run 继续跑 | **必 24h** |
| Step 2 | PR-B | `infra/helm/tx-sync-worker/values.yaml` `RUN_MODE: "live"` + `infra/compose/envs/{dev,gray,prod}.yml` 同步 | sync-worker 真路径接管 | — |

**禁止颠倒**: 翻 live 先 → 5 cron 双跑 (gateway + sync-worker) → 数据 dup, pinzhi API 429 (P0). 详见 issue #806 上下文段.

**前置 anchor**: PR-A merge 前必 `git tag pre-scheduler-removal v1.0` 留逃生 anchor (issue #821 §1 DOD).

---

## 2. 回退原语对比

回退动作分三 layer, 工具不可混用:

### 2.1 Helm rollback (推荐, 5 分钟内)

```bash
helm history tx-sync-worker -n prod
# 找出 PR-B 前一个 REVISION (例: 5 → 当前 6 翻 live, 5 是 dry_run)
helm rollback tx-sync-worker 5 -n prod
# verify
kubectl -n prod get pod -l app=tx-sync-worker -w
helm get values tx-sync-worker -n prod | grep RUN_MODE  # 期望 "dry_run"
```

**适用**: PR-B 翻 live 后 5/10 分钟内发现异常. Helm rollback 不动 git, 不影响后续 fix-and-roll-forward. 故障窗口预估 **5-10 分钟**.

### 2.2 `git revert` (推荐, 保留历史链)

```bash
# revert 不破坏 commit history, 创建新 commit 撤销前一个
git revert <PR-B-merge-sha> --no-edit
git push origin main
# CI 走完后 helm upgrade 自动拉回 dry_run
```

**适用**: PR-B 已 ship 但未发 helm release / 或同 PR 修了多个文件需 atomic 撤销. **保留 PR-B commit + 新增 revert commit**, 后续 cherry-pick 修复仍可 reference 原改动. 故障窗口预估 **20-40 分钟** (含 CI + helm upgrade).

### 2.3 `git reset --hard` (危险, 仅 PR-A 误删 sync_scheduler.py 时)

```bash
# ⚠️ 仅紧急 — 局部 ops repo 操作, 不 push --force
git checkout pre-scheduler-removal -- services/gateway/src/sync_scheduler.py
# 或 cherry-pick 整 scheduler 块回 main.py
git checkout pre-scheduler-removal -- services/gateway/src/main.py
git commit -m "[Emergency] revert gateway scheduler removal — sync_scheduler.py P0"
```

**严禁**: `git reset --hard origin/main~1 && git push --force` — 这会丢失 PR-A 之后 main 上的所有合入 (含其它服务 PR), 数据丢失级 P0. **本 runbook 永不使用 `reset --hard` 翻 main**.

### 2.4 决策矩阵

| 触发条件 | 首选 rollback | 备选 | 故障窗口 |
|----------|---------------|-------|----------|
| PR-B 翻 live 后 < 10 分钟内监控告警 | Helm rollback (2.1) | — | 5-10 分钟 |
| PR-B 翻 live 后 > 10 分钟, 已发 helm release 多次 | `git revert` PR-B merge (2.2) | Helm rollback + 后续 git revert | 20-40 分钟 |
| PR-A 误删 `sync_scheduler.py` 或 main.py 改坏 | `git checkout pre-scheduler-removal -- <file>` (2.3) + 紧急 hotfix PR + admin-merge | — | 30-60 分钟 |
| 不可逆数据 corruption (sync_logs 双写) | Helm rollback (2.1) + 数据修复脚本 + postmortem | — | > 1h, 需 standup |

---

## 3. sync_logs 真路径切回 gateway 后 7d 观察期

PR-B 翻 live 后 sync-worker 真路径接管, gateway scheduler 已删 (PR-A). 若 rollback 到 dry_run, sync-worker 继续写 sync_logs `status='dry_run'`, gateway 不再写真路径.

**7d 观察期 SQL 对账** (per issue #806 W4 验收 §SQL):

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

**通过标准**: 4 pinzhi jobs × 3 merchants (czyz/zqx/sgc) × ~5 sync_types × 7d ≈ 30 组合, 任一组 `status='success'` (gateway 真路径) 与 `status='dry_run'` (sync-worker) count 差异 > 10% → 调查不切.

**wecom 例外**: 1 job 无 merchant_code 维度 → 仅 Prometheus `tx_sync_worker_executions_total{job=wecom_group_daily_sop}` 监控 (per issue #806 FU-8).

**FU-6 已知失真**: Phase 1 一周观察期 `sync_health_scores` view `success_rate` 因 dry_run 行进分母而 tank (per issue #806 FU-6); 这是预期, 不触发 rollback. Phase 2 切单轨 24h 后真实数据复位.

---

## 4. 五个真实失败场景演练

### 4.1 场景 A: PR-A merge 后 gateway 无 scheduler, 5 cron 立刻全停

**检测**:
```bash
# 检 sync_logs 最近 1h 是否有 status='success' (gateway 真路径)
psql -c "SELECT count(*) FROM sync_logs WHERE started_at >= NOW() - INTERVAL '1 hour' AND status = 'success';"
# 期望: > 0 (5 jobs 至少有 hourly_orders_incremental 每小时跑); 实际 = 0 → 场景 A
```

**rollback 命令**:
```bash
# 立即翻 sync-worker live (虽违反 24h 间隔, 但比 gateway 单跑空窗好)
# ⚠️ 仅在 sync-worker Phase 1 dry_run 持续运行验证过的前提下
helm upgrade tx-sync-worker infra/helm/tx-sync-worker \
  --set env.RUN_MODE=live -n prod
# 或者: cherry-pick scheduler 块回 gateway (per §2.3)
```

**验证**:
```bash
# 5 分钟后查 sync_logs status='success' 出现 (sync-worker live 真路径)
psql -c "SELECT count(*) FROM sync_logs WHERE started_at >= NOW() - INTERVAL '5 minutes' AND status = 'success';"
# 期望: > 0
kubectl -n prod logs -l app=tx-sync-worker --tail 50 | grep -E "(pinzhi_sync_job_complete|status=success)"
```

**故障窗口预估**: 10-20 分钟 (期间业务侧最多丢失 1h 增量数据, 下一个 hourly cron 补齐).

---

### 4.2 场景 B: PR-B 翻 live 后 cron 双跑 dup (违反 24h 间隔)

**检测**:
```bash
# 同 (day, merchant_code, sync_type) 组 status='success' count 翻倍
psql -c "
SELECT date_trunc('hour', started_at) AS hr, merchant_code, sync_type, count(*) AS fires
FROM sync_logs
WHERE started_at >= NOW() - INTERVAL '2 hours' AND status = 'success'
GROUP BY 1, 2, 3
HAVING count(*) > 1
ORDER BY 1 DESC;"
# 任一组 fires > 1 在同 hour → 双跑 (期望每小时单 fire)

# 同时检 pinzhi API 429
kubectl -n prod logs -l app=tx-sync-worker --tail 200 | grep -E "(429|rate.?limit)"
kubectl -n prod logs -l app=gateway --tail 200 | grep -E "(429|rate.?limit)"
```

**rollback 命令**:
```bash
# Step 1: 立即 helm rollback sync-worker 回 dry_run (5 min, §2.1)
helm rollback tx-sync-worker $(helm history tx-sync-worker -n prod -o json | jq -r '.[-2].revision') -n prod
# Step 2: verify gateway scheduler 仍跑 (PR-A 未 ship 才会双跑)
# 若 PR-A 已 ship, gateway 不应有 scheduler — 这是 P0 config drift, 立即 standup
```

**验证**:
```bash
# 1h 后查 sync_logs 同 (hour, merchant, type) count 恢复 1
psql -c "
SELECT date_trunc('hour', started_at) AS hr, merchant_code, sync_type, count(*) AS fires
FROM sync_logs
WHERE started_at >= NOW() - INTERVAL '1 hour' AND status = 'success'
GROUP BY 1, 2, 3
HAVING count(*) > 1;"
# 期望: 0 行
```

**故障窗口预估**: 5-15 分钟 helm rollback; pinzhi API 429 可能持续 1h 限流冷却.

---

### 4.3 场景 C: PR-B 翻 live 后 wecom_sop ImportError fail-loud

**背景**: PR #819 修了 wecom_sop.py:66 ImportError (FU-1 已 closed), 但若 prod 配置漂移或新依赖未装, 可能复现.

**检测**:
```bash
kubectl -n prod logs -l app=tx-sync-worker --tail 100 | grep -E "(ImportError|ModuleNotFoundError|wecom_sop)"
# 期望: 0; 实际有 → 场景 C

# Prometheus 检 wecom job fail
curl -s http://tx-sync-worker:8021/metrics | grep -E 'tx_sync_worker_executions_total\{.*wecom.*status="error"'
```

**rollback 命令**:
```bash
# Step 1: helm rollback dry_run (P0 wecom 不能跑空)
helm rollback tx-sync-worker $(helm history tx-sync-worker -n prod -o json | jq -r '.[-2].revision') -n prod
# Step 2: 立 P0 issue, 复用 #819 修复模板 (shared.ontology.src.database.async_session_factory)
```

**验证**:
```bash
# 5 分钟后检 logs 不再 ImportError
kubectl -n prod logs -l app=tx-sync-worker --since=5m | grep -cE "(ImportError|ModuleNotFoundError)"
# 期望: 0
```

**故障窗口预估**: 5-10 分钟 helm rollback + P0 issue 修复链 (可能 24h+ 真 fix).

---

### 4.4 场景 D: PR-B 翻 live 后 sync_logs 写 status='success' 但真 pinzhi API 429

**背景**: status='success' 是 sync_logs 行写入成功语义 (record 落盘), 不代表 pinzhi API 实际返 200. 若 adapter 吞了 429 写 success → 数据空但 metric 假阳性.

**检测**:
```bash
# sync_logs status='success' 但 records_synced=0 异常多
psql -c "
SELECT date_trunc('hour', started_at) AS hr, merchant_code, sync_type,
       count(*) AS total, count(*) FILTER (WHERE records_synced = 0) AS zero_rec
FROM sync_logs
WHERE started_at >= NOW() - INTERVAL '2 hours' AND status = 'success'
GROUP BY 1, 2, 3
HAVING count(*) FILTER (WHERE records_synced = 0) > count(*) / 2
ORDER BY 1 DESC;"
# 任一组 zero_rec > total/2 → 真路径吞 429

# adapter 层 retry 计数
kubectl -n prod logs -l app=tx-sync-worker --tail 500 | grep -cE "(retry|429|rate.?limit)"
```

**rollback 命令**:
```bash
# Step 1: helm rollback dry_run (数据不准比无数据坏)
helm rollback tx-sync-worker $(helm history tx-sync-worker -n prod -o json | jq -r '.[-2].revision') -n prod
# Step 2: 立 P0 issue, root-cause: adapter swallow 429 vs propagate (类 FU-4 partial-success metric semantics)
```

**验证**:
```bash
# 1h 后查 records_synced 分布恢复正常 (sync-worker dry_run 不真请求, 但 gateway scheduler 已删 — 这窗口 5 jobs 失效)
# 实际更稳: rollback 后立即 cherry-pick scheduler 块回 gateway (§2.3 + 场景 A)
```

**故障窗口预估**: 10-30 分钟; FU-4 partial-success 修同 PR 走 (per issue #806 DOD), Phase 2 PR-B 自带.

---

### 4.5 场景 E: PR-A merge 但 sync_scheduler.py 误删

**背景**: per Q2 决议, `sync_router` 留 gateway, 仅删 scheduler 块. 若 reviewer 漏审 PR-A 删了整个 `sync_scheduler.py` 文件, gateway `app.include_router(sync_health_router)` 启动 ImportError.

**检测**:
```bash
kubectl -n prod logs -l app=gateway --tail 100 | grep -E "(ImportError|sync_scheduler|sync_router)"
# 期望: 0; 实际有 → 场景 E

kubectl -n prod get pod -l app=gateway
# 期望: Running; 实际 CrashLoopBackOff → 场景 E
```

**rollback 命令** (per §2.3 git checkout from tag):
```bash
git checkout pre-scheduler-removal -- services/gateway/src/sync_scheduler.py
git add services/gateway/src/sync_scheduler.py
git commit -m "[Emergency] restore sync_scheduler.py — gateway sync_router import P0 (场景 E)

per docs/governance/procedures/tx-sync-worker-cutover-rollback.md §4.5
"
# 紧急 hotfix PR + admin-merge (走 Tier 1 邻接 explicit-ask)
gh pr create --title "[Emergency] restore sync_scheduler.py — gateway sync_router import P0" \
  --body "场景 E rollback (per docs/governance/procedures/tx-sync-worker-cutover-rollback.md §4.5)"
```

**验证**:
```bash
# helm upgrade gateway 后检
kubectl -n prod logs -l app=gateway --since=5m | grep -cE "ImportError"
# 期望: 0
curl -s http://gateway:8000/api/v1/sync/health | jq .  # 期望 200
```

**故障窗口预估**: 20-40 分钟 (含紧急 PR + admin-merge + helm upgrade gateway).

---

## 5. rollback 后续修复路径

1. **立 P0 issue**: 标签 `P0` + `tx-sync-worker` + reference 本 runbook 章节号; 含触发条件 / rollback 命令 / 故障窗口.
2. **召集 standup** (任一场景 B/C/D, 或 A/E 持续 > 30 分钟): tech lead + 运维 + 关联服务 owner.
3. **postmortem 模板**: `docs/governance/decisions/<date>-postmortem-tx-sync-worker-<scenario>.md`, 含 timeline / root cause / 5-whys / preventive action.
4. **回滚后 re-cutover** 触发条件: P0 issue closed + Phase 1 dry_run 重跑 1 周对账绿 + Tier 1 邻接 explicit-ask 重新走流程.

---

## 6. 关联文档

- PR #805 (Phase 1 ship `7e5f27ae`)
- PR #819 (4 P0 + 1 P1 hotfix)
- issue #806 (Phase 2 整体 DOD + FU-4/5/6/7/8)
- issue #820 (Prometheus scrape 系统性 audit — W3-Prep-2 依赖, scrape stale port 漂移会让本 runbook 检测命令失效)
- issue #821 (W4 P1 rollback procedure 显式文档化 — 本 runbook 是本 issue §5 §1 主 deliverable)
- issue #822 (OMC team 流程改进)
- `docs/governance/decisions/2026-05-18-tx-sync-worker-shadow-approval.md` (Phase 1 ship 决议)
- 战略 plan §23 W4 节点 / §24 举措 #1 服务收敛
- 配套脚本 `scripts/cutover/rollback-sync-worker.sh` (default dry-run, `--no-dry-run` + `--confirm` 才真执行)
