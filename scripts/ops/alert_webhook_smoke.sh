#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${1:-${BASE_URL:-http://127.0.0.1}}"
ALERT_TOKEN="${ALERT_WEBHOOK_TOKEN:-${2:-}}"

log() { printf '[ops-alert-webhook-smoke] %s\n' "$1"; }
err() { printf '[ops-alert-webhook-smoke][ERROR] %s\n' "$1" >&2; }

payload='{
  "status": "firing",
  "alerts": [
    {
      "labels": {
        "alertname": "OpsSmokeAlert",
        "severity": "warning",
        "service": "ops",
        "instance": "smoke-check",
        "store_id": "STORE_SMOKE"
      },
      "annotations": {
        "summary": "Smoke alert for webhook verification",
        "description": "This is a synthetic alert from scripts/ops/alert_webhook_smoke.sh"
      }
    }
  ]
}'

headers=(-H 'Content-Type: application/json')
if [[ -n "$ALERT_TOKEN" ]]; then
  headers+=(-H "X-Alert-Token: $ALERT_TOKEN")
fi

resp="$(curl -sS -X POST "$BASE_URL/api/v1/alerts/webhook" "${headers[@]}" -d "$payload")" || {
  err "request failed"
  exit 1
}

if ! python3 - "$resp" <<'PY' >/dev/null
import json, sys
obj = json.loads(sys.argv[1])
assert obj.get("ok") is True
assert "received" in obj
print("ok")
PY
then
  err "unexpected response: $resp"
  exit 1
fi

log "smoke passed: $resp"
