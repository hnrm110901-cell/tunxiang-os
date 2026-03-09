#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
MONITORING_DIR="$ROOT_DIR/apps/api-gateway/monitoring"
PROM_YML="$MONITORING_DIR/prometheus/prometheus.yml"
RULES_YML="$MONITORING_DIR/prometheus/alerts/api_alerts.yml"
AM_YML="$MONITORING_DIR/alertmanager/alertmanager.yml"

log() { printf '[ops-monitoring-lint] %s\n' "$1"; }
err() { printf '[ops-monitoring-lint][ERROR] %s\n' "$1" >&2; }

require_file() {
  [[ -f "$1" ]] || { err "missing file: $1"; exit 1; }
}

require_file "$PROM_YML"
require_file "$RULES_YML"
require_file "$AM_YML"

# Guard against outdated internal host alias.
if rg -n "'api:8000'|http://api:8000" "$PROM_YML" "$AM_YML" >/dev/null 2>&1; then
  err "found outdated host alias 'api:8000' in monitoring config; use 'zhilian-api:8000'"
  exit 1
fi

if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
  log "checking prometheus config"
  docker run --rm \
    -v "$MONITORING_DIR/prometheus:/etc/prometheus:ro" \
    prom/prometheus:latest \
    promtool check config /etc/prometheus/prometheus.yml >/dev/null

  log "checking prometheus rules"
  docker run --rm \
    -v "$MONITORING_DIR/prometheus/alerts:/etc/prometheus/alerts:ro" \
    prom/prometheus:latest \
    promtool check rules /etc/prometheus/alerts/api_alerts.yml >/dev/null

  log "checking alertmanager config"
  docker run --rm \
    -v "$MONITORING_DIR/alertmanager:/etc/alertmanager:ro" \
    prom/alertmanager:latest \
    amtool check-config /etc/alertmanager/alertmanager.yml >/dev/null
else
  log "docker daemon unavailable; fallback to YAML parse checks"
  if ! command -v ruby >/dev/null 2>&1; then
    err "ruby is required for fallback YAML parse checks"
    exit 1
  fi
  ruby -e "require 'yaml'; YAML.load_file('$PROM_YML'); YAML.load_file('$RULES_YML'); YAML.load_file('$AM_YML')" >/dev/null
fi

log "monitoring lint passed"
