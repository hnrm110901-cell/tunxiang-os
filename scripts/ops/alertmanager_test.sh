#!/usr/bin/env bash
set -euo pipefail

ALERTMANAGER_URL="${1:-${ALERTMANAGER_URL:-http://127.0.0.1:9093}}"
ALERT_NAME="${ALERT_NAME:-OpsSyntheticAlert}"
SEVERITY="${SEVERITY:-warning}"
SERVICE="${SERVICE:-ops}"
INSTANCE="${INSTANCE:-manual-test}"
SUMMARY="${SUMMARY:-Synthetic alert from scripts/ops/alertmanager_test.sh}"
DESCRIPTION="${DESCRIPTION:-Manual alert injection for pipeline validation}"

log() { printf '[ops-alert-test] %s\n' "$1"; }
err() { printf '[ops-alert-test][ERROR] %s\n' "$1" >&2; }

starts_at="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
ends_at="$(date -u -v+10M +"%Y-%m-%dT%H:%M:%SZ" 2>/dev/null || date -u -d '+10 minutes' +"%Y-%m-%dT%H:%M:%SZ")"

payload=$(cat <<JSON
[
  {
    "labels": {
      "alertname": "$ALERT_NAME",
      "severity": "$SEVERITY",
      "service": "$SERVICE",
      "instance": "$INSTANCE"
    },
    "annotations": {
      "summary": "$SUMMARY",
      "description": "$DESCRIPTION"
    },
    "startsAt": "$starts_at",
    "endsAt": "$ends_at"
  }
]
JSON
)

http_code="$(curl -sS -o /tmp/ops_alert_test_resp.txt -w "%{http_code}" \
  -X POST "$ALERTMANAGER_URL/api/v2/alerts" \
  -H 'Content-Type: application/json' \
  -d "$payload")"

if [[ "$http_code" != "200" && "$http_code" != "202" ]]; then
  err "alert injection failed (http=$http_code)"
  err "response: $(cat /tmp/ops_alert_test_resp.txt)"
  rm -f /tmp/ops_alert_test_resp.txt
  exit 1
fi

log "alert injected successfully (http=$http_code)"
log "check: $ALERTMANAGER_URL/#/alerts"
rm -f /tmp/ops_alert_test_resp.txt
