#!/usr/bin/env bash
# tx-sync-worker cutover rollback driver
#
# 默认 dry-run (不真执行, 仅 echo 命令 + 期望 effect).
# 真执行需要 --no-dry-run + --confirm "I understand the impact" 二次确认.
#
# 配套 runbook: docs/governance/procedures/tx-sync-worker-cutover-rollback.md
# 关联 issue: #806 / #821 / #822 (W4 P1 deliverable)
# 关联 PR: #805 (Phase 1 ship) / #819 (hotfix)

set -euo pipefail

DRY_RUN=true
SCENARIO=""
TARGET_SHA=""
CONFIRM=""
NAMESPACE="${NAMESPACE:-prod}"

usage() {
  cat <<'EOF'
Usage: rollback-sync-worker.sh --scenario <a|b|c|d|e> [--target-sha <sha>] [--no-dry-run --confirm "I understand the impact"]

Options:
  --scenario <a|b|c|d|e>   Failure scenario per runbook §4
                           a: PR-A 后 gateway 无 scheduler 5 jobs 立停
                           b: PR-B 翻 live cron 双跑 dup
                           c: PR-B 翻 live wecom_sop ImportError
                           d: PR-B 翻 live status=success 但 pinzhi API 429
                           e: PR-A merge 但 sync_scheduler.py 误删
  --target-sha <sha>       Target SHA for git revert (场景 b/c/d 需要 PR-B merge sha)
  --no-dry-run             Actually execute (DEFAULT IS DRY-RUN)
  --confirm "<text>"       Required with --no-dry-run; exact text: "I understand the impact"
  -h, --help               Show this help

Examples (DRY-RUN, safe):
  ./rollback-sync-worker.sh --scenario a
  ./rollback-sync-worker.sh --scenario b --target-sha abc1234

Real execution (DANGEROUS):
  ./rollback-sync-worker.sh --scenario b --target-sha abc1234 --no-dry-run --confirm "I understand the impact"
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --scenario) SCENARIO="$2"; shift 2 ;;
    --target-sha) TARGET_SHA="$2"; shift 2 ;;
    --no-dry-run) DRY_RUN=false; shift ;;
    --confirm) CONFIRM="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown arg: $1" >&2; usage; exit 2 ;;
  esac
done

if [[ -z "$SCENARIO" ]]; then
  echo "ERROR: --scenario required" >&2; usage; exit 2
fi

if [[ "$DRY_RUN" == "false" && "$CONFIRM" != "I understand the impact" ]]; then
  echo "ERROR: --no-dry-run requires --confirm \"I understand the impact\" (exact text)" >&2
  exit 2
fi

run() {
  # Echo command; only execute if DRY_RUN=false
  local cmd="$*"
  if [[ "$DRY_RUN" == "true" ]]; then
    echo "[DRY-RUN] $cmd"
  else
    echo "[EXEC] $cmd"
    eval "$cmd"
  fi
}

helm_rollback() {
  local revision="${1:-prev}"
  if [[ "$revision" == "prev" ]]; then
    run "helm rollback tx-sync-worker \$(helm history tx-sync-worker -n $NAMESPACE -o json | jq -r '.[-2].revision') -n $NAMESPACE"
  else
    run "helm rollback tx-sync-worker $revision -n $NAMESPACE"
  fi
}

verify_gateway_scheduler_active() {
  echo "# Expected effect: gateway scheduler 5 jobs 跑 (last 1h status='success' count > 0)"
  run "psql -c \"SELECT count(*) FROM sync_logs WHERE started_at >= NOW() - INTERVAL '1 hour' AND status = 'success';\""
}

verify_sync_logs_path() {
  echo "# Expected effect: sync_logs 双边 (status='success' for真路径 / status='dry_run' for sync-worker dry_run)"
  run "psql -c \"SELECT status, count(*) FROM sync_logs WHERE started_at >= NOW() - INTERVAL '1 hour' GROUP BY status;\""
}

rollback_pr_a() {
  # Scenario E: PR-A merge but sync_scheduler.py 误删 → restore from tag
  echo "## Scenario E rollback: restore sync_scheduler.py from tag pre-scheduler-removal"
  run "git checkout pre-scheduler-removal -- services/gateway/src/sync_scheduler.py"
  run "git add services/gateway/src/sync_scheduler.py"
  run "git commit -m '[Emergency] restore sync_scheduler.py — gateway sync_router import P0 (场景 E)'"
  echo "# Next: gh pr create + admin-merge (Tier 1 邻接 explicit-ask)"
  echo "# Then: helm upgrade gateway"
  echo "# Verify: kubectl -n $NAMESPACE logs -l app=gateway --since=5m | grep -cE 'ImportError'  (expect 0)"
}

rollback_pr_b() {
  # Scenarios B/C/D: PR-B 翻 live 翻车 → helm rollback to dry_run
  echo "## Scenarios B/C/D rollback: helm rollback tx-sync-worker → dry_run"
  helm_rollback "prev"
  echo "# Verify: helm get values tx-sync-worker -n $NAMESPACE | grep RUN_MODE   (expect: dry_run)"
  run "helm get values tx-sync-worker -n $NAMESPACE | grep RUN_MODE"
  if [[ -n "$TARGET_SHA" ]]; then
    echo "## Optional: git revert PR-B merge for repo state consistency"
    run "git revert $TARGET_SHA --no-edit"
    echo "# Then: git push origin main"
  fi
}

case "$SCENARIO" in
  a)
    echo "===== Scenario A: PR-A 后 gateway 无 scheduler 5 jobs 立停 ====="
    echo "# Detection: psql sync_logs status='success' last 1h count = 0"
    verify_gateway_scheduler_active
    echo "# Rollback option 1 (preferred): 立即翻 sync-worker live (违反 24h 间隔, 但比空窗好)"
    run "helm upgrade tx-sync-worker infra/helm/tx-sync-worker --set env.RUN_MODE=live -n $NAMESPACE"
    echo "# Rollback option 2: cherry-pick scheduler 块回 gateway (per runbook §2.3 + 场景 E)"
    echo "# Verify (5 min after): status='success' rows appear"
    verify_sync_logs_path
    echo "# Estimated outage: 10-20 min (期间最多丢 1h 增量, 下个 hourly cron 补齐)"
    ;;
  b)
    echo "===== Scenario B: PR-B 翻 live cron 双跑 dup ====="
    echo "# Detection: psql sync_logs same (hour, merchant, type) fires > 1 + pinzhi 429 logs"
    run "psql -c \"SELECT date_trunc('hour', started_at) AS hr, merchant_code, sync_type, count(*) AS fires FROM sync_logs WHERE started_at >= NOW() - INTERVAL '2 hours' AND status = 'success' GROUP BY 1, 2, 3 HAVING count(*) > 1 ORDER BY 1 DESC;\""
    rollback_pr_b
    echo "# Verify (1h after): same query returns 0 rows"
    echo "# Estimated outage: 5-15 min helm rollback; pinzhi 429 cooldown ~1h"
    ;;
  c)
    echo "===== Scenario C: PR-B 翻 live wecom_sop ImportError fail-loud ====="
    echo "# Detection: kubectl logs grep ImportError + Prometheus tx_sync_worker_executions_total{job=wecom_*, status=error}"
    run "kubectl -n $NAMESPACE logs -l app=tx-sync-worker --tail 100 | grep -E '(ImportError|ModuleNotFoundError|wecom_sop)' || true"
    run "curl -s http://tx-sync-worker:8021/metrics | grep -E 'tx_sync_worker_executions_total\\{.*wecom.*status=\"error\"' || true"
    rollback_pr_b
    echo "# Next: P0 issue, 复用 #819 修复模板 (shared.ontology.src.database.async_session_factory)"
    echo "# Verify (5 min after): logs no ImportError"
    echo "# Estimated outage: 5-10 min helm rollback + 24h+ 真 fix 链"
    ;;
  d)
    echo "===== Scenario D: PR-B 翻 live status=success 但 pinzhi API 429 ====="
    echo "# Detection: sync_logs status='success' 但 records_synced=0 异常多"
    run "psql -c \"SELECT date_trunc('hour', started_at) AS hr, merchant_code, sync_type, count(*) AS total, count(*) FILTER (WHERE records_synced = 0) AS zero_rec FROM sync_logs WHERE started_at >= NOW() - INTERVAL '2 hours' AND status = 'success' GROUP BY 1, 2, 3 HAVING count(*) FILTER (WHERE records_synced = 0) > count(*) / 2 ORDER BY 1 DESC;\""
    run "kubectl -n $NAMESPACE logs -l app=tx-sync-worker --tail 500 | grep -cE '(retry|429|rate.?limit)' || true"
    rollback_pr_b
    echo "# Next: P0 issue, root-cause adapter swallow 429 vs propagate (类 FU-4 partial-success semantics)"
    echo "# Estimated outage: 10-30 min"
    ;;
  e)
    echo "===== Scenario E: PR-A merge 但 sync_scheduler.py 误删 ====="
    echo "# Detection: gateway CrashLoopBackOff + logs ImportError sync_scheduler"
    run "kubectl -n $NAMESPACE logs -l app=gateway --tail 100 | grep -E '(ImportError|sync_scheduler|sync_router)' || true"
    run "kubectl -n $NAMESPACE get pod -l app=gateway"
    rollback_pr_a
    echo "# Verify (after helm upgrade gateway): curl gateway/api/v1/sync/health → 200"
    echo "# Estimated outage: 20-40 min (含紧急 PR + admin-merge + helm upgrade)"
    ;;
  *)
    echo "ERROR: unknown scenario '$SCENARIO' (expect a|b|c|d|e)" >&2
    exit 2
    ;;
esac

echo ""
echo "===== Rollback step plan complete ====="
if [[ "$DRY_RUN" == "true" ]]; then
  echo "(DRY-RUN — no commands executed. Re-run with --no-dry-run --confirm \"I understand the impact\" to execute.)"
else
  echo "(EXECUTED — verify outcomes per runbook §4.<scenario> 验证段)"
fi
