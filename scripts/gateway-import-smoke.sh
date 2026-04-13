#!/usr/bin/env bash
# Gateway 包路径导入烟测（与 Dockerfile: uvicorn services.gateway.src.main:app 一致）
# 需在仓库根执行；勿依赖 PYTHONPATH=src 优先（会与 gateway/src/services 包名冲突）。
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

export PYTHONPATH="$ROOT"
export TX_JWT_SECRET_KEY="${TX_JWT_SECRET_KEY:-pytest-smoke-gateway-jwt-secret-min-32-chars!}"
export TX_MFA_ENCRYPT_KEY="${TX_MFA_ENCRYPT_KEY:-$(python3 -c 'print("00"*32)')}"

exec python3 -m pytest services/gateway/src/tests/test_main_import_smoke.py -q --tb=short "$@"
