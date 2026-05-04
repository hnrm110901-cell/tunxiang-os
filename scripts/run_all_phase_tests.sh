#!/usr/bin/env bash
# run_all_phase_tests.sh — 屯象OS Phase A+B+C 全量测试运行器
#
# 按顺序运行所有测试：服务测试 → Tier 1 测试 → 集成测试
# 汇总结果，输出测试通过/失败/跳过统计。
#
# Usage:
#   ./scripts/run_all_phase_tests.sh              # 运行所有测试
#   ./scripts/run_all_phase_tests.sh --service tx-civic  # 仅单服务
#   ./scripts/run_all_phase_tests.sh --skip-integration   # 跳过集成测试
#   ./scripts/run_all_phase_tests.sh --tier1-only         # 仅 Tier 1 测试
#   ./scripts/run_all_phase_tests.sh --slow                # 运行慢速测试
#
# Exit codes:
#   0           = 所有测试通过
#   1-254       = 失败测试数量（上限 254）
#   255         = 配置/环境错误
#
# 环境变量:
#   DATABASE_URL       — PostgreSQL 连接串（集成测试需要）
#   PYTEST_EXTRA       — 额外传递给 pytest 的参数
#   SKIP_SLOW          — 跳过标记为 slow 的测试

set -uo pipefail

# ── ANSI 颜色 ─────────────────────────────────────────────────────────────────

RED='\033[0;31m'
YELLOW='\033[1;33m'
GREEN='\033[0;32m'
CYAN='\033[0;36m'
BOLD='\033[1m'
RESET='\033[0m'

# ── 默认参数 ──────────────────────────────────────────────────────────────────

RUN_SERVICE_TESTS=true
RUN_TIER1_TESTS=true
RUN_INTEGRATION_TESTS=true
TARGET_SERVICE=""
SLOW_MODE=false
PYTEST_EXTRA="${PYTEST_EXTRA:-}"

# ── 解析参数 ──────────────────────────────────────────────────────────────────

while [[ $# -gt 0 ]]; do
    case "$1" in
        --service)
            TARGET_SERVICE="$2"
            RUN_TIER1_TESTS=false
            RUN_INTEGRATION_TESTS=false
            shift 2
            ;;
        --skip-integration)
            RUN_INTEGRATION_TESTS=false
            shift
            ;;
        --tier1-only)
            RUN_SERVICE_TESTS=false
            RUN_INTEGRATION_TESTS=false
            shift
            ;;
        --slow)
            SLOW_MODE=true
            shift
            ;;
        --help|-h)
            echo "Usage: $0 [--service NAME] [--skip-integration] [--tier1-only] [--slow]"
            echo ""
            echo "Options:"
            echo "  --service NAME         Run tests for a single service only"
            echo "  --skip-integration     Skip integration tests (no DB required)"
            echo "  --tier1-only           Only run Tier 1 tests"
            echo "  --slow                 Include tests marked as slow"
            exit 0
            ;;
        *)
            echo -e "${RED}未知参数: $1${RESET}" >&2
            exit 255
            ;;
    esac
done

# ── 检查依赖 ──────────────────────────────────────────────────────────────────

# Python 版本检测
PYTHON_BIN="${PYTHON_BIN:-python3}"

if ! command -v "$PYTHON_BIN" &>/dev/null; then
    echo -e "${RED}ERROR: 找不到 $PYTHON_BIN${RESET}" >&2
    exit 255
fi

PY_VERSION=$("$PYTHON_BIN" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
PY_MAJOR=$("$PYTHON_BIN" -c "import sys; print(sys.version_info.major)")
PY_MINOR=$("$PYTHON_BIN" -c "import sys; print(sys.version_info.minor)")

if [[ "$PY_MAJOR" -lt 3 ]] || { [[ "$PY_MAJOR" -eq 3 ]] && [[ "$PY_MINOR" -lt 10 ]]; }; then
    echo -e "${YELLOW}WARNING: Python $PY_VERSION < 3.10 — 部分测试可能因类型注解语法失败${RESET}" >&2
    echo -e "${YELLOW}  已知问题: tx-devforge 测试需 Python 3.10+ (PEP 604 联合类型)${RESET}" >&2
else
    echo -e "${GREEN}Python $PY_VERSION — OK${RESET}" >&2
fi

# pytest 检测
if ! command -v pytest &>/dev/null; then
    echo -e "${RED}ERROR: pytest 未安装. 运行: pip install pytest pytest-asyncio${RESET}" >&2
    exit 255
fi

echo -e "pytest $("$PYTHON_BIN" -m pytest --version 2>/dev/null | head -1)" >&2

# ── 获取仓库根目录 ────────────────────────────────────────────────────────────

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# ── 计数器 ────────────────────────────────────────────────────────────────────

TOTAL_TESTS=0
TOTAL_PASSED=0
TOTAL_FAILED=0
TOTAL_SKIPPED=0
TOTAL_ERRORS=0
FAILED_SERVICES=()

# ── 输出辅助函数 ──────────────────────────────────────────────────────────────

print_header() {
    echo ""
    echo -e "${BOLD}${CYAN}══════════════════════════════════════════════════════════════${RESET}"
    echo -e "${BOLD}${CYAN}  $1${RESET}"
    echo -e "${BOLD}${CYAN}══════════════════════════════════════════════════════════════${RESET}"
    echo ""
}

section() {
    echo ""
    echo -e "${BOLD}── $1 ──${RESET}"
}

parse_pytest_output() {
    # 从 pytest 输出的最后一行解析 passed/failed/skipped/errors
    # 格式: "= X passed, Y failed, Z skipped, W errors in N.Ns =="
    # 或者:   "= X passed in N.Ns =="
    local output="$1"
    local passed=0 failed=0 skipped=0 errors=0

    # 匹配最后的汇总行
    local summary
    summary=$(echo "$output" | grep -E "=[0-9]+.*(passed|failed)" | tail -1)

    if [[ -n "$summary" ]]; then
        passed=$(echo "$summary" | grep -oE '[0-9]+ passed' | grep -oE '[0-9]+' || echo "0")
        failed=$(echo "$summary" | grep -oE '[0-9]+ failed' | grep -oE '[0-9]+' || echo "0")
        skipped=$(echo "$summary" | grep -oE '[0-9]+ skipped' | grep -oE '[0-9]+' || echo "0")
        errors=$(echo "$summary" | grep -oE '[0-9]+ error' | grep -oE '[0-9]+' || echo "0")
    fi

    TOTAL_PASSED=$((TOTAL_PASSED + passed))
    TOTAL_FAILED=$((TOTAL_FAILED + failed))
    TOTAL_SKIPPED=$((TOTAL_SKIPPED + skipped))
    TOTAL_ERRORS=$((TOTAL_ERRORS + errors))
}

run_pytest_dir() {
    # 在指定目录运行 pytest，解析结果并更新全局计数器
    # 参数: $1=显示名称, $2=目录路径, $3=可选 pytest 额外参数
    local name="$1"
    local dir="$2"
    local extra="${3:-}"

    if [[ ! -d "$dir" ]]; then
        echo -e "  ${YELLOW}SKIP${RESET} $name — 目录不存在: $dir"
        return 0
    fi

    # 检查是否有测试文件
    local test_count
    test_count=$(find "$dir" -name 'test_*.py' -type f 2>/dev/null | wc -l | tr -d ' ')
    if [[ "$test_count" -eq 0 ]]; then
        echo -e "  ${YELLOW}SKIP${RESET} $name — 无测试文件"
        return 0
    fi

    echo -e "  ${BOLD}$name${RESET} ($test_count 个测试文件)"

    # 构建 pytest 参数
    local pytest_args="-v --tb=short --no-header"
    if [[ "$SLOW_MODE" != "true" ]]; then
        pytest_args="$pytest_args -m 'not slow'"
    fi
    if [[ -n "$PYTEST_EXTRA" ]]; then
        pytest_args="$pytest_args $PYTEST_EXTRA"
    fi

    # 运行 pytest，捕获输出
    local output
    local exit_code=0

    pushd "$dir" > /dev/null || return 1
    if [[ -d "src" ]]; then
        output=$(PYTHONPATH="src:.." python -m pytest $pytest_args $extra 2>&1) || exit_code=$?
    else
        output=$(python -m pytest $pytest_args $extra 2>&1) || exit_code=$?
    fi
    popd > /dev/null || true

    parse_pytest_output "$output"

    # 打印输出摘要（最后几行）
    echo "$output" | tail -8 | sed 's/^/    /'

    if [[ $exit_code -ne 0 ]]; then
        FAILED_SERVICES+=("$name")
        echo -e "    ${RED}FAILED${RESET} (exit=$exit_code)"
        echo ""
        return 1
    else
        echo -e "    ${GREEN}PASSED${RESET}"
        echo ""
        return 0
    fi
}

# ══════════════════════════════════════════════════════════════════════════════
# Phase 1: 服务单元测试
# ══════════════════════════════════════════════════════════════════════════════

if [[ "$RUN_SERVICE_TESTS" == "true" ]]; then
    print_header "Phase 1: 服务单元测试"

    # 所有有测试的服务（按字母序）
    ALL_SERVICES=(
        gateway mcp-server tunxiang-api
        tx-agent tx-analytics tx-brain
        tx-civic tx-devforge tx-expense
        tx-finance tx-forge tx-growth
        tx-intel tx-member tx-menu
        tx-ops tx-org tx-pay
        tx-predict tx-supply tx-trade
    )

    if [[ -n "$TARGET_SERVICE" ]]; then
        SERVICES=("$TARGET_SERVICE")
    else
        SERVICES=("${ALL_SERVICES[@]}")
    fi

    SERVICE_FAILURES=0

    for svc in "${SERVICES[@]}"; do
        svc_dir="$REPO_ROOT/services/$svc"
        if [[ ! -d "$svc_dir" ]]; then
            echo -e "  ${YELLOW}SKIP${RESET} $svc — 服务目录不存在"
            continue
        fi

        # 支持两种测试目录布局: tests/ 或 src/tests/
        for test_subdir in "tests" "src/tests"; do
            test_dir="$svc_dir/$test_subdir"
            if [[ -d "$test_dir" ]] && [[ -n "$(find "$test_dir" -name 'test_*.py' -type f 2>/dev/null)" ]]; then
                run_pytest_dir "$svc" "$svc_dir" "$test_subdir" || SERVICE_FAILURES=$((SERVICE_FAILURES + 1))
                break
            fi
        done
    done

    echo -e "  服务测试完成: ${SERVICE_FAILURES} 个服务失败"
fi

# ══════════════════════════════════════════════════════════════════════════════
# Phase 2: Tier 1 测试
# ══════════════════════════════════════════════════════════════════════════════

if [[ "$RUN_TIER1_TESTS" == "true" ]]; then
    print_header "Phase 2: Tier 1 测试 (CLAUDE.md § 17/§ 20)"

    TIER1_DIRS=()

    # services/*/tests/**/test_*tier1*.py
    while IFS= read -r -d '' dir; do
        TIER1_DIRS+=("$dir")
    done < <(find "$REPO_ROOT/services" -type f -name '*tier1*.py' -print0 2>/dev/null | xargs -0 dirname | sort -u)

    # tests/tier1/
    if [[ -d "$REPO_ROOT/tests/tier1" ]]; then
        TIER1_DIRS+=("$REPO_ROOT/tests/tier1")
    fi

    if [[ ${#TIER1_DIRS[@]} -eq 0 ]]; then
        echo -e "  ${YELLOW}未找到 Tier 1 测试文件${RESET}"
    else
        TIER1_FAILURES=0
        for td in "${TIER1_DIRS[@]}"; do
            rel_path=$(echo "$td" | sed "s|^$REPO_ROOT/||")
            run_pytest_dir "$rel_path" "$td" || TIER1_FAILURES=$((TIER1_FAILURES + 1))
        done
        echo -e "  Tier 1 测试完成: ${TIER1_FAILURES} 个目录失败"
    fi
fi

# ══════════════════════════════════════════════════════════════════════════════
# Phase 3: 集成测试
# ══════════════════════════════════════════════════════════════════════════════

if [[ "$RUN_INTEGRATION_TESTS" == "true" ]]; then
    print_header "Phase 3: 集成测试"

    INTEGRATION_DIR="$REPO_ROOT/tests/integration"

    if [[ ! -d "$INTEGRATION_DIR" ]]; then
        echo -e "  ${YELLOW}SKIP${RESET} — tests/integration/ 目录不存在"
    else
        # 检查 DATABASE_URL
        DB_URL="${DATABASE_URL:-${INTEGRATION_DATABASE_URL:-}}"
        if [[ -z "$DB_URL" ]]; then
            echo -e "  ${YELLOW}WARNING: DATABASE_URL 未设置${RESET}"
            echo -e "  ${YELLOW}集成测试需要 PostgreSQL 连接串${RESET}"
            echo -e "  ${YELLOW}设置方式: export DATABASE_URL='postgresql+asyncpg://...'${RESET}"
            echo -e "  ${YELLOW}或启动测试 DB: docker compose -f infra/docker/docker-compose.integration-test.yml up -d${RESET}"
            echo -e "  ${YELLOW}跳过集成测试...${RESET}"
        else
            # 尝试连接数据库
            echo -e "  测试数据库连接..."
            if "$PYTHON_BIN" -c "
import asyncpg, os, sys, re
dsn = os.environ.get('DATABASE_URL', os.environ.get('INTEGRATION_DATABASE_URL', ''))
# normalize SQLAlchemy-style DSNs
dsn = re.sub(r'^(postgres(?:ql)?)\+[a-z0-9_]+://', r'\1://', dsn, count=1, flags=re.IGNORECASE)
async def check():
    try:
        conn = await asyncpg.connect(dsn)
        ver = await conn.fetchval('SELECT version()')
        print(f'PostgreSQL: {ver.split(\",\")[0]}')
        await conn.close()
        return 0
    except Exception as e:
        print(f'连接失败: {e}', file=sys.stderr)
        return 1
import asyncio
sys.exit(asyncio.run(check()))
" 2>/dev/null; then
                echo -e "  ${GREEN}数据库连接成功${RESET}"
                run_pytest_dir "集成测试 (tests/integration/)" "$INTEGRATION_DIR" "-m integration"
            else
                echo -e "  ${YELLOW}WARNING: 无法连接数据库，跳过集成测试${RESET}"
            fi
        fi
    fi
fi

# ══════════════════════════════════════════════════════════════════════════════
# Phase 4: 覆盖率闸门检查
# ══════════════════════════════════════════════════════════════════════════════

print_header "Phase 4: 测试覆盖率闸门"

if [[ -f "$REPO_ROOT/scripts/check_test_coverage.py" ]]; then
    "$PYTHON_BIN" "$REPO_ROOT/scripts/check_test_coverage.py" --threshold 10 2>&1 || true
else
    echo -e "  ${YELLOW}SKIP${RESET} — check_test_coverage.py 不存在"
fi

# ══════════════════════════════════════════════════════════════════════════════
# 最终汇总
# ══════════════════════════════════════════════════════════════════════════════

TOTAL_TESTS=$((TOTAL_PASSED + TOTAL_FAILED + TOTAL_SKIPPED + TOTAL_ERRORS))

print_header "测试汇总报告"

echo -e "  ${BOLD}总计:${RESET}        ${TOTAL_TESTS}"
echo -e "  ${GREEN}通过:${RESET}        ${TOTAL_PASSED}"
echo -e "  ${RED}失败:${RESET}        ${TOTAL_FAILED}"
echo -e "  ${YELLOW}跳过:${RESET}        ${TOTAL_SKIPPED}"
echo -e "  ${RED}错误:${RESET}        ${TOTAL_ERRORS}"

if [[ ${#FAILED_SERVICES[@]} -gt 0 ]]; then
    echo ""
    echo -e "  ${RED}${BOLD}失败的服务/测试组:${RESET}"
    for svc in "${FAILED_SERVICES[@]}"; do
        echo -e "    ${RED}- $svc${RESET}"
    done
fi

# 计算通过率
if [[ $TOTAL_TESTS -gt 0 ]]; then
    PASS_RATE=$(( TOTAL_PASSED * 100 / TOTAL_TESTS ))
    echo ""
    echo -e "  ${BOLD}通过率:${RESET}      ${PASS_RATE}%"
fi

echo ""
echo -e "${BOLD}${CYAN}══════════════════════════════════════════════════════════════${RESET}"

if [[ $TOTAL_FAILED -eq 0 ]] && [[ $TOTAL_ERRORS -eq 0 ]]; then
    echo -e "${GREEN}${BOLD}  结论: 所有测试通过${RESET}"
    echo -e "${BOLD}${CYAN}══════════════════════════════════════════════════════════════${RESET}"
    echo ""
    exit 0
else
    EXIT_CODE=$((TOTAL_FAILED + TOTAL_ERRORS))
    if [[ $EXIT_CODE -gt 254 ]]; then
        EXIT_CODE=254
    fi
    echo -e "${RED}${BOLD}  结论: ${TOTAL_FAILED} 失败 + ${TOTAL_ERRORS} 错误${RESET}"
    echo -e "${BOLD}${CYAN}══════════════════════════════════════════════════════════════${RESET}"
    echo ""
    exit $EXIT_CODE
fi
