#!/usr/bin/env bash
# check_signoffs.sh — 验收签字文件计数
#
# Week 8 Go/No-Go 第 5 项 "收银员零培训（3 位签字）"
# Week 8 Go/No-Go 第 10 项 "三套演示话术打印就位"
#
# 数据源：
#   docs/cashier-signoff/*.md   ≥ 3 个文件视为通过
#   docs/demo-script-signoff.md 文件存在视为通过
#
# 退出码：
#   0  通过（具体哪一项由 --check 参数决定）
#   1  未达标
#
# 用法：
#   scripts/check_signoffs.sh --check cashier
#   scripts/check_signoffs.sh --check demo-script

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CHECK=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --check) CHECK="$2"; shift 2 ;;
        *) echo "未知参数: $1" >&2; exit 2 ;;
    esac
done

case "${CHECK}" in
    cashier)
        DIR="${REPO_ROOT}/docs/cashier-signoff"
        if [[ ! -d "${DIR}" ]]; then
            echo "[FAIL] 收银员签字目录不存在: ${DIR}（需 3 位签字）"
            exit 1
        fi
        COUNT=$(find "${DIR}" -maxdepth 1 -type f -name "*.md" ! -name "README.md" | wc -l | tr -d ' ')
        if [[ "${COUNT}" -ge 3 ]]; then
            echo "[PASS] 收银员签字: ${COUNT}/3"
            exit 0
        else
            echo "[FAIL] 收银员签字: ${COUNT}/3（不足）"
            exit 1
        fi
        ;;
    demo-script)
        FILE="${REPO_ROOT}/docs/demo-script-signoff.md"
        if [[ -f "${FILE}" ]]; then
            echo "[PASS] 三套演示话术签字到位: ${FILE}"
            exit 0
        else
            echo "[FAIL] 缺少演示话术签字文件: ${FILE}"
            exit 1
        fi
        ;;
    *)
        echo "用法: $0 --check {cashier|demo-script}" >&2
        exit 2
        ;;
esac
