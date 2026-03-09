#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ENV_FILE="${1:-$ROOT_DIR/.env.prod}"
API_ENV_FILE="${2:-$ROOT_DIR/apps/api-gateway/.env.production}"

log() { printf '[ops-deploy] %s\n' "$1"; }
err() { printf '[ops-deploy][ERROR] %s\n' "$1" >&2; }

if docker compose version >/dev/null 2>&1; then
  COMPOSE_BIN=(docker compose)
elif command -v docker-compose >/dev/null 2>&1; then
  COMPOSE_BIN=(docker-compose)
else
  err "missing docker compose / docker-compose"
  exit 1
fi

[[ -f "$ROOT_DIR/docker-compose.prod.yml" ]] || { err "missing docker-compose.prod.yml"; exit 1; }
[[ -f "$ENV_FILE" ]] || { err "missing env file: $ENV_FILE"; exit 1; }
[[ -f "$API_ENV_FILE" ]] || { err "missing api env file: $API_ENV_FILE"; exit 1; }

log "1/5 preflight checks"
"$ROOT_DIR/scripts/ops/prod_env_check.sh" "$ENV_FILE" "$API_ENV_FILE"

log "2/5 pulling latest images"
"${COMPOSE_BIN[@]}" --env-file "$ENV_FILE" -f "$ROOT_DIR/docker-compose.prod.yml" pull

log "3/5 starting core dependencies"
"${COMPOSE_BIN[@]}" --env-file "$ENV_FILE" -f "$ROOT_DIR/docker-compose.prod.yml" up -d postgres redis redis-replica redis-sentinel-1 redis-sentinel-2 redis-sentinel-3 qdrant

log "4/5 deploying app + workers + web + nginx"
"${COMPOSE_BIN[@]}" --env-file "$ENV_FILE" -f "$ROOT_DIR/docker-compose.prod.yml" up -d --build api-gateway celery-worker celery-beat web nginx

log "5/5 checking health"
"$ROOT_DIR/scripts/ops/health_check_prod.sh" "${BASE_URL:-http://127.0.0.1}"

log "deploy success"
log "next: run migration if schema changed"
log "command: ${COMPOSE_BIN[*]} --env-file $ENV_FILE -f $ROOT_DIR/docker-compose.prod.yml exec api-gateway alembic upgrade head"
