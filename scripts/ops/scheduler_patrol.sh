#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${1:-http://127.0.0.1}"
TOKEN="${TOKEN:-${2:-}}"
TRIGGER_TASK="${TRIGGER_TASK:-}"

log() { printf '[ops-scheduler] %s\n' "$1"; }
err() { printf '[ops-scheduler][ERROR] %s\n' "$1" >&2; }

if [[ -z "$TOKEN" ]]; then
  err "TOKEN is required for scheduler patrol"
  err "usage: TOKEN=<jwt> $0 [base_url]"
  exit 1
fi

request() {
  local method="$1"
  local path="$2"
  local body="${3:-}"
  if [[ "$method" == "GET" ]]; then
    curl -sS -H "Authorization: Bearer $TOKEN" "$BASE_URL$path"
  else
    curl -sS -X "$method" -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" -d "$body" "$BASE_URL$path"
  fi
}

schedule_json="$(request GET /api/v1/scheduler/schedule)"
health_json="$(request GET /api/v1/monitoring/scheduler/health)"
queue_json="$(request GET /api/v1/monitoring/scheduler/queue)"

python3 - <<'PY' "$schedule_json" "$health_json" "$queue_json"
import json
import sys

schedule = json.loads(sys.argv[1]).get("beat_schedule", {})
health = json.loads(sys.argv[2])
queue = json.loads(sys.argv[3])

required_tasks = [
    "daily-workforce-advice",
    "daily-auto-workforce-schedule",
    "nightly-action-dispatch",
]

missing = [name for name in required_tasks if name not in schedule]
if missing:
    print(f"[ops-scheduler][ERROR] missing beat tasks: {', '.join(missing)}")
    sys.exit(2)

print("[ops-scheduler] required beat tasks found")
for name in required_tasks:
    entry = schedule[name]
    print(f"[ops-scheduler] {name}: {entry.get('schedule')} -> {entry.get('task')}")

health_obj = health.get("health", {})
queue_obj = queue.get("queue_stats", {})
print(f"[ops-scheduler] health: {health_obj}")
print(f"[ops-scheduler] queue: {queue_obj}")
PY

if [[ -n "$TRIGGER_TASK" ]]; then
  log "manual trigger task=$TRIGGER_TASK"
  request POST "/api/v1/scheduler/trigger/$TRIGGER_TASK" '{}' | sed 's/^/[ops-scheduler] /'
fi

log "scheduler patrol passed"
