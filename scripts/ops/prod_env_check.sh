#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ENV_FILE="${1:-$ROOT_DIR/.env.prod}"
API_ENV_FILE="${2:-$ROOT_DIR/apps/api-gateway/.env.production}"

log() { printf '[ops-env-check] %s\n' "$1"; }
err() { printf '[ops-env-check][ERROR] %s\n' "$1" >&2; }

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || {
    err "missing command: $1"
    exit 1
  }
}

check_required_var() {
  local key="$1"
  local value="${!key:-}"
  if [[ -z "$value" ]]; then
    err "required variable is empty: $key"
    return 1
  fi
  if [[ "$value" == *"CHANGE_ME"* ]] || [[ "$value" == *"replace_with"* ]] || [[ "$value" == *"placeholder"* ]]; then
    err "required variable uses placeholder value: $key"
    return 1
  fi
  return 0
}

log "root=$ROOT_DIR"
require_cmd docker

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

set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
# shellcheck disable=SC1090
source "$API_ENV_FILE"
set +a

FAILED=0
for key in POSTGRES_PASSWORD REDIS_PASSWORD SECRET_KEY JWT_SECRET_KEY API_DATABASE_URL; do
  if ! check_required_var "$key"; then
    FAILED=1
  fi
done

if ! "${COMPOSE_BIN[@]}" --env-file "$ENV_FILE" -f "$ROOT_DIR/docker-compose.prod.yml" config >/dev/null; then
  err "compose config validation failed"
  FAILED=1
fi

if [[ $FAILED -ne 0 ]]; then
  err "production environment check failed"
  exit 1
fi

log "production environment check passed"
