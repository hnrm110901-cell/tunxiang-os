#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
MONITORING_DIR="$ROOT_DIR/apps/api-gateway/monitoring"
ENV_FILE="${1:-$ROOT_DIR/.env.prod}"
ACTION="${ACTION:-up}"  # up/down/status/logs

log() { printf '[ops-monitoring] %s\n' "$1"; }
err() { printf '[ops-monitoring][ERROR] %s\n' "$1" >&2; }

if docker compose version >/dev/null 2>&1; then
  COMPOSE_BIN=(docker compose)
elif command -v docker-compose >/dev/null 2>&1; then
  COMPOSE_BIN=(docker-compose)
else
  err "missing docker compose / docker-compose"
  exit 1
fi

[[ -d "$MONITORING_DIR" ]] || { err "missing monitoring dir: $MONITORING_DIR"; exit 1; }
[[ -f "$MONITORING_DIR/docker-compose.monitoring.yml" ]] || { err "missing docker-compose.monitoring.yml"; exit 1; }

if ! docker network inspect zhilian-network >/dev/null 2>&1; then
  log "creating docker network: zhilian-network"
  docker network create zhilian-network >/dev/null
fi

cmd=("${COMPOSE_BIN[@]}" -f "$MONITORING_DIR/docker-compose.monitoring.yml")
if [[ -f "$ENV_FILE" ]]; then
  cmd+=(--env-file "$ENV_FILE")
fi

case "$ACTION" in
  up)
    log "starting monitoring stack"
    "${cmd[@]}" up -d
    ;;
  down)
    log "stopping monitoring stack"
    "${cmd[@]}" down
    ;;
  status)
    log "monitoring stack status"
    "${cmd[@]}" ps
    ;;
  logs)
    log "tailing monitoring logs"
    "${cmd[@]}" logs -f --tail=200
    ;;
  *)
    err "unsupported ACTION=$ACTION (use up/down/status/logs)"
    exit 1
    ;;
esac
