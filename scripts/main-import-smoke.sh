#!/usr/bin/env bash
# 通用 main.py 顶层 import 烟测脚本 — issue #714 generic 版 gateway-import-smoke.sh.
#
# 用法:
#   bash scripts/main-import-smoke.sh <service-name>
# 示例:
#   bash scripts/main-import-smoke.sh tx-supply
#
# 行为:
#   在仓库根设 PYTHONPATH, 跑该服务的 test_main_import_smoke_tier1.py 单文件.
#   helper (shared/test_infra/main_import_smoke.py, PR #351 立网 + issue #714 PR 扩
#   mode B + extra_copies) 用 subprocess + tmpdir + shutil.copytree 模拟容器布局
#   (mode A services/tx_X/src/ 或 mode B src/) 验证 import 健康度.
#
# 与 gateway-import-smoke.sh 关系:
#   gateway 走 services.gateway.src.main 标准 import 路径直接跑, 不需要容器布局重建.
#   非-gateway 18 服务因目录名带连字符 (services/tx-X/) + Dockerfile 改名为下划线
#   (services/tx_X/) 需要 helper 做布局复刻.

set -euo pipefail

if [ "$#" -lt 1 ]; then
  echo "Usage: $0 <service-name>" >&2
  echo "  e.g. $0 tx-supply" >&2
  exit 2
fi

SERVICE="$1"
shift || true

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TEST_FILE="$ROOT/services/$SERVICE/src/tests/test_main_import_smoke_tier1.py"

if [ ! -f "$TEST_FILE" ]; then
  echo "Service smoke test not found: $TEST_FILE" >&2
  exit 2
fi

cd "$ROOT"
export PYTHONPATH="$ROOT"
export TX_JWT_SECRET_KEY="${TX_JWT_SECRET_KEY:-pytest-smoke-jwt-min-32-chars-padded!}"
export TX_MFA_ENCRYPT_KEY="${TX_MFA_ENCRYPT_KEY:-$(python3 -c 'print("00"*32)')}"

exec python3 -m pytest "$TEST_FILE" -q --tb=short "$@"
