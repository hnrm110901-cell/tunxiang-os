#!/usr/bin/env bash
# release-gate.sh — 屯象OS 发布闸门检查脚本
#
# Usage:
#   ./scripts/release-gate.sh [--env prod|staging|demo] [--merchant czyz|zqx|sgc|all]
#
# Exit codes:
#   0 = GATE PASS   (所有检查通过)
#   1 = GATE FAIL   (有 CRITICAL 检查失败)
#   2 = DEGRADED    (仅 WARNING 检查失败，可强制发布)

set -uo pipefail

# ── ANSI 颜色 ─────────────────────────────────────────────────────────────────
RED='\033[0;31m'
YELLOW='\033[1;33m'
GREEN='\033[0;32m'
CYAN='\033[0;36m'
BOLD='\033[1m'
RESET='\033[0m'

# ── 默认参数 ──────────────────────────────────────────────────────────────────
ENV="demo"
MERCHANT="all"
ANALYTICS_URL="http://localhost:8009"
GATEWAY_URL="http://localhost:8000"
DATA_QUALITY_MIN_SCORE=70

# ── 解析参数 ──────────────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
    case "$1" in
        --env)
            ENV="$2"
            shift 2
            ;;
        --merchant)
            MERCHANT="$2"
            shift 2
            ;;
        *)
            echo -e "${RED}未知参数: $1${RESET}" >&2
            exit 1
            ;;
    esac
done

# ── 计数器 ────────────────────────────────────────────────────────────────────
CRITICAL_FAILURES=0
WARNING_FAILURES=0

# ── 输出辅助函数 ──────────────────────────────────────────────────────────────
print_header() {
    echo ""
    echo -e "${BOLD}${CYAN}══════════════════════════════════════════════════════${RESET}"
    echo -e "${BOLD}${CYAN}  屯象OS 发布闸门检查  ENV=${ENV}  MERCHANT=${MERCHANT}${RESET}"
    echo -e "${BOLD}${CYAN}══════════════════════════════════════════════════════${RESET}"
    echo ""
}

pass() {
    echo -e "  ${GREEN}[PASS]${RESET} $1"
}

fail_critical() {
    echo -e "  ${RED}[CRITICAL FAIL]${RESET} $1"
    CRITICAL_FAILURES=$((CRITICAL_FAILURES + 1))
}

warn() {
    echo -e "  ${YELLOW}[WARNING]${RESET} $1"
    WARNING_FAILURES=$((WARNING_FAILURES + 1))
}

section() {
    echo ""
    echo -e "${BOLD}── $1 ──${RESET}"
}

# ── 展开商户列表 ──────────────────────────────────────────────────────────────
if [[ "$MERCHANT" == "all" ]]; then
    MERCHANTS=("czyz" "zqx" "sgc")
else
    MERCHANTS=("$MERCHANT")
fi

# ══════════════════════════════════════════════════════════════════════════════
print_header

# ── CRITICAL 检查 ─────────────────────────────────────────────────────────────

section "CRITICAL 检查（任何失败 = NO-GO）"

# C-1: git-secrets 扫描
echo -e "\n  ${BOLD}C-1. git-secrets 安全扫描${RESET}"
if command -v git-secrets &>/dev/null || git secrets --help &>/dev/null 2>&1; then
    if git secrets --scan 2>&1; then
        pass "git-secrets 扫描通过，未发现敏感信息"
    else
        fail_critical "git-secrets 扫描失败：发现潜在敏感信息，请清除后重试"
    fi
else
    warn "git-secrets 未安装，跳过扫描（建议运行 scripts/setup-git-secrets.sh 安装）"
    # WARNING not CRITICAL — gate 不因工具缺失而阻断
fi

# C-2: 新文件中无 except Exception
echo -e "\n  ${BOLD}C-2. 检查新增文件中的 broad except${RESET}"
CHANGED_PY_FILES=$(git diff origin/main --name-only 2>/dev/null | grep '\.py$' || true)
if [[ -z "$CHANGED_PY_FILES" ]]; then
    pass "无新增 Python 文件变更"
else
    BROAD_EXCEPT_FILES=$(echo "$CHANGED_PY_FILES" | xargs grep -l "except Exception" 2>/dev/null || true)
    if [[ -z "$BROAD_EXCEPT_FILES" ]]; then
        pass "新增文件中无 broad except Exception"
    else
        fail_critical "以下新增文件包含 'except Exception'（违反审计约束）:\n$(echo "$BROAD_EXCEPT_FILES" | sed 's/^/    /')"
    fi
fi

# C-3: 所有新迁移文件已设置 down_revision
echo -e "\n  ${BOLD}C-3. 检查新迁移文件 down_revision${RESET}"
MIGRATION_DIR="shared/db-migrations/versions"
if [[ -d "$MIGRATION_DIR" ]]; then
    NEW_MIGRATION_FILES=$(git diff origin/main --name-only 2>/dev/null | grep "^${MIGRATION_DIR}/.*\.py$" || true)
    if [[ -z "$NEW_MIGRATION_FILES" ]]; then
        pass "无新增迁移文件"
    else
        MISSING_DOWN=()
        while IFS= read -r f; do
            if [[ -f "$f" ]]; then
                if ! grep -q "down_revision" "$f"; then
                    MISSING_DOWN+=("$f")
                elif grep -q "down_revision = None" "$f" 2>/dev/null; then
                    # down_revision=None 仅允许初始迁移（版本号 001）
                    if ! echo "$f" | grep -q "001_\|_001"; then
                        MISSING_DOWN+=("$f (down_revision = None，非初始迁移)")
                    fi
                fi
            fi
        done <<< "$NEW_MIGRATION_FILES"

        if [[ ${#MISSING_DOWN[@]} -eq 0 ]]; then
            pass "所有新迁移文件均已设置 down_revision"
        else
            fail_critical "以下迁移文件未正确设置 down_revision:\n$(printf '    %s\n' "${MISSING_DOWN[@]}")"
        fi
    fi
else
    warn "迁移目录 ${MIGRATION_DIR} 不存在，跳过检查"
fi

# C-4: 健康检查
echo -e "\n  ${BOLD}C-4. 服务健康检查 (GET ${GATEWAY_URL}/health)${RESET}"
if command -v curl &>/dev/null; then
    HEALTH_RESP=$(curl -sf --max-time 5 "${GATEWAY_URL}/health" 2>/dev/null || true)
    if echo "$HEALTH_RESP" | grep -q '"ok":.*true'; then
        pass "Gateway 健康检查通过: ${HEALTH_RESP}"
    else
        fail_critical "Gateway 健康检查失败 (无响应或 ok != true)。响应: ${HEALTH_RESP:-<无响应>}"
    fi
else
    warn "curl 未安装，跳过健康检查"
fi

# C-5: 数据质量评分 ≥ 70
echo -e "\n  ${BOLD}C-5. 数据质量评分检查 (≥${DATA_QUALITY_MIN_SCORE})${RESET}"
if command -v curl &>/dev/null; then
    for mc in "${MERCHANTS[@]}"; do
        DQ_RESP=$(curl -sf --max-time 10 \
            "${ANALYTICS_URL}/api/v1/analytics/data-quality/${mc}" 2>/dev/null || true)
        if [[ -z "$DQ_RESP" ]]; then
            fail_critical "商户 ${mc}: 数据质量接口无响应 (${ANALYTICS_URL})"
        else
            # 提取 total_score（使用 python3 或 grep 降级）
            if command -v python3 &>/dev/null; then
                SCORE=$(python3 -c "
import json, sys
try:
    d = json.loads(sys.argv[1])
    print(d['data']['total_score'])
except Exception:
    print(-1)
" "$DQ_RESP" 2>/dev/null || echo "-1")
            else
                SCORE=$(echo "$DQ_RESP" | grep -o '"total_score":[0-9.]*' | cut -d: -f2 || echo "-1")
            fi

            if [[ "$SCORE" == "-1" ]]; then
                fail_critical "商户 ${mc}: 无法解析数据质量评分。响应: ${DQ_RESP}"
            else
                # 比较浮点数（用 python3）
                PASS_SCORE=$(python3 -c "print('yes' if float('$SCORE') >= $DATA_QUALITY_MIN_SCORE else 'no')" 2>/dev/null || echo "no")
                if [[ "$PASS_SCORE" == "yes" ]]; then
                    pass "商户 ${mc}: 数据质量评分 ${SCORE} ≥ ${DATA_QUALITY_MIN_SCORE}"
                else
                    fail_critical "商户 ${mc}: 数据质量评分 ${SCORE} < ${DATA_QUALITY_MIN_SCORE}（需补充数据后重试）"
                fi
            fi
        fi
    done
else
    warn "curl 未安装，跳过数据质量检查"
fi

# ── WARNING 检查 ──────────────────────────────────────────────────────────────

section "WARNING 检查（失败 = DEGRADED，可强制发布）"

# W-1: 交付记分卡评分 ≥ 75（预留接口，当前跳过）
echo -e "\n  ${BOLD}W-1. 交付记分卡评分 ≥ 75${RESET}"
warn "交付记分卡接口暂未实现，跳过检查（计划 v233+ 接入）"

# W-2: 新文件缺少 tenant_id
echo -e "\n  ${BOLD}W-2. 检查新迁移文件是否包含 tenant_id${RESET}"
if [[ -d "$MIGRATION_DIR" ]]; then
    NEW_MIGRATION_FILES_ALL=$(git diff origin/main --name-only 2>/dev/null | grep "^${MIGRATION_DIR}/.*\.py$" || true)
    if [[ -z "$NEW_MIGRATION_FILES_ALL" ]]; then
        pass "无新增迁移文件需检查"
    else
        MISSING_TENANT=()
        while IFS= read -r f; do
            if [[ -f "$f" ]] && ! grep -q "tenant_id" "$f"; then
                MISSING_TENANT+=("$f")
            fi
        done <<< "$NEW_MIGRATION_FILES_ALL"

        if [[ ${#MISSING_TENANT[@]} -eq 0 ]]; then
            pass "所有新迁移文件均包含 tenant_id"
        else
            warn "以下新迁移文件可能缺少 tenant_id:\n$(printf '    %s\n' "${MISSING_TENANT[@]}")"
        fi
    fi
else
    pass "迁移目录不存在，跳过检查"
fi

# W-3: pytest（非慢速模式时运行）
echo -e "\n  ${BOLD}W-3. pytest 单元测试${RESET}"
SLOW_MODE="${SLOW_MODE:-false}"
if [[ "$SLOW_MODE" == "true" ]]; then
    warn "SLOW_MODE=true，跳过 pytest"
else
    if command -v pytest &>/dev/null; then
        CHANGED_SERVICES=$(git diff origin/main --name-only 2>/dev/null \
            | grep '^services/' \
            | cut -d/ -f2 \
            | sort -u || true)
        if [[ -z "$CHANGED_SERVICES" ]]; then
            pass "无服务变更，跳过 pytest"
        else
            ALL_PYTEST_PASS=true
            for svc in $CHANGED_SERVICES; do
                SVC_DIR="services/${svc}"
                if [[ -d "$SVC_DIR" ]]; then
                    echo -e "    运行 pytest ${SVC_DIR}..."
                    if pytest "$SVC_DIR" -q --tb=no --no-header 2>&1 | tail -3; then
                        pass "pytest ${svc} 通过"
                    else
                        warn "pytest ${svc} 失败"
                        ALL_PYTEST_PASS=false
                    fi
                fi
            done
        fi
    else
        warn "pytest 未安装，跳过测试"
    fi
fi

# ── 最终判决 ──────────────────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}${CYAN}══════════════════════════════════════════════════════${RESET}"
echo -e "  CRITICAL 失败: ${CRITICAL_FAILURES}  |  WARNING 失败: ${WARNING_FAILURES}"
echo -e "${BOLD}${CYAN}══════════════════════════════════════════════════════${RESET}"

if [[ $CRITICAL_FAILURES -gt 0 ]]; then
    echo -e "\n${RED}${BOLD}[GATE FAIL] ❌ 发布闸门未通过 — ${CRITICAL_FAILURES} 个 CRITICAL 检查失败${RESET}"
    echo -e "${RED}  请修复以上问题后重新运行此脚本。${RESET}\n"
    exit 1
elif [[ $WARNING_FAILURES -gt 0 ]]; then
    echo -e "\n${YELLOW}${BOLD}[GATE DEGRADED] ⚠️  发布闸门降级通过 — ${WARNING_FAILURES} 个 WARNING 检查未通过${RESET}"
    echo -e "${YELLOW}  可强制发布，但建议修复以上警告。${RESET}\n"
    exit 2
else
    echo -e "\n${GREEN}${BOLD}[GATE PASS] ✅ 发布闸门通过 — 所有检查均通过${RESET}\n"
    exit 0
fi
