#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
BASE_URL="${BASE_URL:-${1:-http://127.0.0.1}}"
TOKEN="${TOKEN:-${2:-}}"
REPORT_DIR="${REPORT_DIR:-$ROOT_DIR/logs/ops}"
TIMEOUT="${TIMEOUT_SECONDS:-8}"
PROM_URL="${PROMETHEUS_URL:-http://127.0.0.1:9090}"
ALERT_URL="${ALERTMANAGER_URL:-http://127.0.0.1:9093}"
GRAFANA_URL="${GRAFANA_URL:-http://127.0.0.1:3000}"
WEBHOOK_URL="${OPS_REPORT_WEBHOOK_URL:-}"

mkdir -p "$REPORT_DIR"

now="$(date '+%Y-%m-%d %H:%M:%S %z')"
stamp="$(date '+%Y%m%d_%H%M%S')"
report_md="$REPORT_DIR/ops_report_${stamp}.md"

check_http_contains() {
  local url="$1"
  local expected="$2"
  local body
  if ! body="$(curl -sS --max-time "$TIMEOUT" "$url" 2>/dev/null)"; then
    echo "down"
    return 0
  fi
  if [[ "$body" == *"$expected"* ]]; then
    echo "ok"
  else
    echo "degraded"
  fi
}

check_http_code() {
  local url="$1"
  local code
  code="$(curl -sS -o /dev/null --max-time "$TIMEOUT" -w "%{http_code}" "$url" 2>/dev/null || true)"
  if [[ "$code" == "200" ]]; then
    echo "ok"
  elif [[ -n "$code" ]]; then
    echo "http_$code"
  else
    echo "down"
  fi
}

app_health="$(check_http_contains "$BASE_URL/api/v1/health" '"status":"healthy"')"
app_live="$(check_http_contains "$BASE_URL/api/v1/live" '"status":"alive"')"
app_ready="$(check_http_contains "$BASE_URL/api/v1/ready" '"status":"ready"')"

prom_status="$(check_http_code "$PROM_URL/-/ready")"
alert_status="$(check_http_code "$ALERT_URL/-/ready")"
grafana_status="$(check_http_code "$GRAFANA_URL/api/health")"

scheduler_summary="skipped (TOKEN not provided)"
if [[ -n "$TOKEN" ]]; then
  schedule_json="$(curl -sS --max-time "$TIMEOUT" -H "Authorization: Bearer $TOKEN" "$BASE_URL/api/v1/scheduler/schedule" 2>/dev/null || true)"
  if [[ -n "$schedule_json" ]]; then
    scheduler_summary="$(python3 - <<'PY' "$schedule_json"
import json
import sys

required = ["daily-workforce-advice", "daily-auto-workforce-schedule", "nightly-action-dispatch"]
try:
    data = json.loads(sys.argv[1]).get("beat_schedule", {})
except Exception:
    print("error (invalid schedule response)")
    raise SystemExit(0)
missing = [k for k in required if k not in data]
if missing:
    print("missing: " + ", ".join(missing))
else:
    print("ok")
PY
)"
  else
    scheduler_summary="error (schedule endpoint unreachable)"
  fi
fi

overall="ok"
for s in "$app_health" "$app_live" "$app_ready" "$prom_status" "$alert_status" "$grafana_status"; do
  if [[ "$s" != "ok" ]]; then
    overall="degraded"
  fi
done
if [[ "$scheduler_summary" == missing:* ]] || [[ "$scheduler_summary" == error* ]]; then
  overall="degraded"
fi

cat > "$report_md" <<EOF_REPORT
# Daily Ops Report

- generated_at: $now
- overall: $overall
- base_url: $BASE_URL

## App Health
- /api/v1/health: $app_health
- /api/v1/live: $app_live
- /api/v1/ready: $app_ready

## Scheduler Patrol
- status: $scheduler_summary

## Monitoring Stack
- prometheus ($PROM_URL/-/ready): $prom_status
- alertmanager ($ALERT_URL/-/ready): $alert_status
- grafana ($GRAFANA_URL/api/health): $grafana_status

EOF_REPORT

printf '[ops-report] report written: %s\n' "$report_md"

if [[ -n "$WEBHOOK_URL" ]]; then
  payload="$(python3 - <<'PY' "$overall" "$report_md"
import json,sys
overall = sys.argv[1]
path = sys.argv[2]
with open(path, 'r', encoding='utf-8') as f:
    content = f.read()
text = f"[DailyOps] status={overall}\n\n{content}"
print(json.dumps({"text": text}, ensure_ascii=False))
PY
)"
  curl -sS --max-time "$TIMEOUT" -X POST "$WEBHOOK_URL" -H 'Content-Type: application/json' -d "$payload" >/dev/null || true
  printf '[ops-report] webhook pushed\n'
fi
