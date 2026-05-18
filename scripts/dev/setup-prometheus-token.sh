#!/usr/bin/env bash
# setup-prometheus-token.sh — dev Prometheus bearer token setup (issue #831)
#
# 用法:
#   source scripts/dev/setup-prometheus-token.sh     # 生成 token + 导出 env var
#   bash   scripts/dev/setup-prometheus-token.sh     # 仅生成 token 文件 (不 export 到父 shell)
#
# 决策:
#   - 首次运行生成 32-byte token; 每次覆盖 (用户拍板 5/18)
#   - chmod 600 防 group/other 读取
#   - 生成后自动 export PROMETHEUS_BEARER_TOKEN 供 docker compose env 注入
#   - token 文件绝对不入仓: infra/compose/envs/tx-metrics-token 已加 .gitignore
#
# 安全约束 (per CLAUDE.md §13 §14):
#   - 不使用 eval / $(curl) 等注入面
#   - set -euo pipefail: 任一命令失败即 abort
set -euo pipefail

# ── 路径 (相对仓库根) ────────────────────────────────────────
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TOKEN_FILE="${REPO_ROOT}/infra/compose/envs/tx-metrics-token"
EXAMPLE_FILE="${REPO_ROOT}/infra/compose/envs/tx-metrics-token.example"

# ── 生成 token (每次覆盖) ────────────────────────────────────
python3 -c 'import secrets; print(secrets.token_urlsafe(32))' > "${TOKEN_FILE}"
chmod 600 "${TOKEN_FILE}"

TOKEN="$(cat "${TOKEN_FILE}")"
TOKEN_LEN="${#TOKEN}"

# ── 更新 example 文件 (非 token 真值, 仅占位) ─────────────────
if [[ ! -f "${EXAMPLE_FILE}" ]]; then
    printf '# Prometheus dev bearer token placeholder.\n# Run: source scripts/dev/setup-prometheus-token.sh\n# This file is committed; the real token file (tx-metrics-token) is gitignored.\n' > "${EXAMPLE_FILE}"
fi

# ── export 给 docker compose ─────────────────────────────────
export PROMETHEUS_BEARER_TOKEN="${TOKEN}"

echo "PROMETHEUS_BEARER_TOKEN generated and exported (length=${TOKEN_LEN})"
echo "Token file: ${TOKEN_FILE} (chmod 600, gitignored)"
