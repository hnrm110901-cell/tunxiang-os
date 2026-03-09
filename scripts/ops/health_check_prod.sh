#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${1:-http://127.0.0.1}"
TOKEN="${TOKEN:-${2:-}}"
TIMEOUT="${TIMEOUT_SECONDS:-8}"

log() { printf '[ops-health] %s\n' "$1"; }
err() { printf '[ops-health][ERROR] %s\n' "$1" >&2; }

request() {
  local method="$1"
  local path="$2"
  local auth_header=()
  if [[ -n "$TOKEN" ]]; then
    auth_header=(-H "Authorization: Bearer $TOKEN")
  fi

  if [[ "$method" == "GET" ]]; then
    curl -sS --max-time "$TIMEOUT" "${auth_header[@]}" "$BASE_URL$path"
  else
    curl -sS --max-time "$TIMEOUT" -X "$method" "${auth_header[@]}" -H 'Content-Type: application/json' "$BASE_URL$path"
  fi
}

check_public() {
  local endpoint="$1"
  local expected="$2"
  local body
  if ! body="$(curl -sS --max-time "$TIMEOUT" "$BASE_URL$endpoint")"; then
    err "request failed: $endpoint"
    return 1
  fi
  if [[ "$body" != *"$expected"* ]]; then
    err "unexpected response: $endpoint -> $body"
    return 1
  fi
  log "ok $endpoint"
  return 0
}

FAILED=0
check_public "/api/v1/health" '"status":"healthy"' || FAILED=1
check_public "/api/v1/live" '"status":"alive"' || FAILED=1
check_public "/api/v1/ready" '"status":"ready"' || FAILED=1

if [[ -n "$TOKEN" ]]; then
  if ! request GET "/api/v1/scheduler/schedule" >/dev/null; then
    err "scheduler schedule check failed"
    FAILED=1
  else
    log "ok /api/v1/scheduler/schedule"
  fi

  if ! request GET "/api/v1/monitoring/scheduler/health" >/dev/null; then
    err "scheduler health check failed"
    FAILED=1
  else
    log "ok /api/v1/monitoring/scheduler/health"
  fi
else
  log "skip auth endpoints (TOKEN not provided)"
fi

if [[ "$FAILED" -ne 0 ]]; then
  err "health checks failed"
  exit 1
fi

log "all checks passed"
