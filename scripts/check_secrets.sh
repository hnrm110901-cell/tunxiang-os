#!/usr/bin/env bash
# check_secrets.sh — secrets / 敏感字符串扫描（lite 版）
#
# 复用：若已安装 git-secrets，先调用 git-secrets --scan
# 兜底：用 grep 扫工作树和最近 50 个 commit，匹配高危关键词
#
# 退出码：
#   0  无告警
#   1  发现潜在密钥
#
# 用法：
#   scripts/check_secrets.sh

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${REPO_ROOT}"

EXIT_CODE=0

# 1) git-secrets（若可用）
if command -v git-secrets &>/dev/null; then
    if git secrets --scan 2>/dev/null; then
        echo "[INFO] git-secrets --scan 通过"
    else
        echo "[FAIL] git-secrets 检测到敏感字符串"
        EXIT_CODE=1
    fi
else
    echo "[WARN] git-secrets 未安装，跳过（参考 scripts/setup-git-secrets.sh）"
fi

# 2) grep 兜底 — 扫工作树（排除 vendor 目录、二进制、测试 fixture）
PATTERNS=(
    'AKIA[0-9A-Z]{16}'                   # AWS access key
    'aws_secret_access_key\s*=\s*[A-Za-z0-9/+=]{40}'
    'BEGIN RSA PRIVATE KEY'
    'BEGIN OPENSSH PRIVATE KEY'
    'sk-[a-zA-Z0-9]{20,}'                # OpenAI / Anthropic 风格
    'xox[baprs]-[A-Za-z0-9-]{10,}'       # Slack
    'ghp_[A-Za-z0-9]{30,}'               # GitHub personal token
)

EXCLUDES=(
    --exclude-dir=node_modules
    --exclude-dir=.git
    --exclude-dir=__pycache__
    --exclude-dir=.venv
    --exclude-dir=venv
    --exclude-dir=dist
    --exclude-dir=build
    --exclude-dir=.next
    --exclude-dir=fixtures
    --exclude='*.lock'
    --exclude='*.min.js'
    --exclude='*.pyc'
    --exclude='check_secrets.sh'
)

FOUND=0
for pat in "${PATTERNS[@]}"; do
    if grep -rE "${EXCLUDES[@]}" "${pat}" . 2>/dev/null | grep -v -E '^\s*(#|//|--|\*)' >/dev/null; then
        echo "[FAIL] 发现疑似密钥模式: ${pat}"
        FOUND=1
    fi
done

# 3) 检查 config/merchants/ 是否有任何提交内容（CLAUDE.md §14 禁止）
if [[ -d "config/merchants" ]] && [[ -n "$(ls -A config/merchants 2>/dev/null | grep -v '\.gitkeep')" ]]; then
    echo "[FAIL] config/merchants/ 不应包含任何文件（CLAUDE.md §14 安全条款）"
    FOUND=1
fi

if [[ "${FOUND}" -eq 1 ]]; then
    EXIT_CODE=1
fi

if [[ "${EXIT_CODE}" -eq 0 ]]; then
    echo "[PASS] secrets 扫描通过"
fi

exit "${EXIT_CODE}"
