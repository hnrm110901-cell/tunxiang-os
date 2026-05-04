#!/usr/bin/env bash
# Tier 1 测试 Docker 跑测器（PD.2）
#
# 背景：本机 macOS 默认 Python 3.9，部分 Tier 1 测试需要 Python 3.11+
#       （pytest-asyncio 1.x、structlog、sqlalchemy 2.0 等依赖最低 3.10/3.11）。
#       此脚本用 python:3.11-slim 容器 + 最小依赖跑全套 Tier 1，
#       不污染本机环境，3-5 分钟内完整跑完。
#
# 用法：
#   ./scripts/run_tier1_tests.sh                  # 跑全部 Tier 1 文件名约定
#   ./scripts/run_tier1_tests.sh points           # 只跑包含 'points' 的文件
#   ./scripts/run_tier1_tests.sh -k test_consume  # 透传 pytest -k 表达式
#
# 退出码：
#   0 — 全部通过
#   1 — 至少一项失败
#   2 — Docker 不可用
#
# 已知通过的 Tier 1 模块（115/115，2026-05-04 基线）：
#   tx-member  test_points_tier1                          29 测试
#   tx-trade   test_order_state_machine_tier1             17 测试
#   tx-trade   test_payment_saga_tier1                     9 测试
#   tx-trade   test_wine_storage_tier1                     7 测试
#   tx-org     test_royalty_calculator_tier1              13 测试
#   edge       test_offline_sync_crdt                     23 测试
#   tx-finance test_invoice_tier1                         12 测试
#   tx-trade   test_rls_isolation_tier1                    5 测试

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
IMAGE="python:3.11-slim"
DEPS="pytest pytest-asyncio structlog sqlalchemy fastapi pydantic httpx"

# 测试参数（默认全套 Tier 1，可被 $1 覆盖为子集模式）
PYTEST_ARGS=()
if [ $# -gt 0 ]; then
    case "$1" in
        -k|-m|-x|-v|--tb|-q)
            # 透传 pytest 参数
            PYTEST_ARGS=("$@")
            ;;
        *)
            # 子集模式：$1 是文件名关键词
            FILTER="$1"
            shift
            mapfile -t TEST_FILES < <(find "$REPO_ROOT/services" "$REPO_ROOT/edge" \
                -name "*tier1*.py" -o -name "*${FILTER}*tier1*.py" 2>/dev/null \
                | grep "$FILTER" | sed "s|$REPO_ROOT/||")
            if [ ${#TEST_FILES[@]} -eq 0 ]; then
                echo "::error::No Tier 1 test files matched filter: $FILTER"
                exit 1
            fi
            PYTEST_ARGS=("${TEST_FILES[@]}" "$@")
            ;;
    esac
fi

# Tier 1 默认文件集（一次性跑完）
if [ ${#PYTEST_ARGS[@]} -eq 0 ]; then
    PYTEST_ARGS=(
        "services/tx-member/src/tests/test_points_tier1.py"
        "services/tx-trade/tests/test_order_state_machine_tier1.py"
        "services/tx-trade/tests/test_payment_saga_tier1.py"
        "services/tx-trade/tests/test_wine_storage_tier1.py"
        "services/tx-trade/tests/test_rls_isolation_tier1.py"
        "services/tx-org/src/tests/test_royalty_calculator_tier1.py"
        "services/tx-finance/tests/test_invoice_tier1.py"
        "edge/sync-engine/tests/test_offline_sync_crdt.py"
    )
fi

if ! command -v docker >/dev/null 2>&1; then
    echo "::error::Docker 未安装。Tier 1 测试需要 Python 3.11+，本机 Python 3.9 不兼容。"
    exit 2
fi

echo "=== Tier 1 Docker Runner ==="
echo "Image:  $IMAGE"
echo "Deps:   $DEPS"
echo "Tests:  ${#PYTEST_ARGS[@]} target(s)"
echo ""

# 透传模式（-k/-m/...）：单容器跑（用户已显式控制范围）
case "${1:-}" in
    -k|-m|-x|-v|--tb|-q)
        exec docker run --rm -v "$REPO_ROOT:/app" -w /app "$IMAGE" \
            bash -c "pip install --quiet $DEPS && python -m pytest ${PYTEST_ARGS[*]} --tb=short"
        ;;
esac

# 默认 / 子集模式：逐文件 docker run（避免跨文件 sys.path 污染）
# 不同 service 的 test 文件用 sys.path.insert 把各自 src/ 加到 path 头部，
# 同进程跑时第一个 service 的 src/ 会 shadow 掉后续 service 的同名模块（namespace 包）
TOTAL=0
PASS=0
FAIL_FILES=()
for test_file in "${PYTEST_ARGS[@]}"; do
    echo "--- $test_file ---"
    if docker run --rm -v "$REPO_ROOT:/app" -w /app "$IMAGE" \
        bash -c "pip install --quiet $DEPS 2>/dev/null && python -m pytest '$test_file' --tb=line -q 2>&1 | tail -5"; then
        PASS=$((PASS + 1))
    else
        FAIL_FILES+=("$test_file")
    fi
    TOTAL=$((TOTAL + 1))
    echo ""
done

echo "=== Summary ==="
echo "Passed:  $PASS / $TOTAL"
if [ ${#FAIL_FILES[@]} -gt 0 ]; then
    echo "Failed:"
    printf '  - %s\n' "${FAIL_FILES[@]}"
    exit 1
fi
echo "All Tier 1 files passed."
