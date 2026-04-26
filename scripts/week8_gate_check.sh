#!/usr/bin/env bash
# week8_gate_check.sh — 屯象OS Week 8 徐记 DEMO Go/No-Go 自动检查
#
# 来源：CLAUDE.md §22 + docs/sprint-plan-2026Q2-unified.md §3
#
# 10 项门槛：
#   1. Tier 1 测试 100% 通过
#   2. k6 P99 < 200ms
#   3. 支付成功率 > 99.9%
#   4. 断网 4h E2E 绿（nightly 连续 3 日）
#   5. 收银员零培训（3 位签字）
#   6. 三商户 scorecard ≥ 85
#   7. RLS / 凭证 / 端口 / CORS / secrets 零告警
#   8. scripts/demo-reset.sh 回退验证
#   9. 至少 1 个 A/B 实验 running 未熔断
#   10. 三套演示话术打印就位
#
# 退出码：全部通过=0，任一未达=1
#
# 用法：
#   scripts/week8_gate_check.sh [--strict]
#     --strict  人工签字项缺失也视为 NO-GO（默认开）
#
# 环境变量（可选覆盖）：
#   K6_RESULT_JSON      默认 build/k6-result.json
#   PAYMENT_METRIC_FILE 默认 build/payment-success-rate.txt
#   E2E_REPORT_DIR      默认 build/e2e-offline-reports
#   ADAPTER_SCORECARD   默认 docs/adapter-scorecard.md
#   EXPERIMENT_API      默认 http://localhost:8004/api/v1/experiments/health
#   TIER1_JUNIT_PATH    默认 build/junit-tier1.xml

set -euo pipefail

# ── 路径 ─────────────────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${REPO_ROOT}"

# ── 默认变量 ──────────────────────────────────────────────────────────────
STRICT=true
K6_RESULT_JSON="${K6_RESULT_JSON:-build/k6-result.json}"
PAYMENT_METRIC_FILE="${PAYMENT_METRIC_FILE:-build/payment-success-rate.txt}"
E2E_REPORT_DIR="${E2E_REPORT_DIR:-build/e2e-offline-reports}"
ADAPTER_SCORECARD="${ADAPTER_SCORECARD:-docs/adapter-scorecard.md}"
EXPERIMENT_API="${EXPERIMENT_API:-http://localhost:8004/api/v1/experiments/health}"
TIER1_JUNIT_PATH="${TIER1_JUNIT_PATH:-build/junit-tier1.xml}"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --strict) STRICT=true; shift ;;
        --no-strict) STRICT=false; shift ;;
        -h|--help)
            grep -E '^#' "$0" | sed 's/^# \{0,1\}//'
            exit 0
            ;;
        *) echo "未知参数: $1" >&2; exit 2 ;;
    esac
done

# ── 颜色与计数 ────────────────────────────────────────────────────────────
RED=$'\033[31m'; GREEN=$'\033[32m'; YELLOW=$'\033[33m'; RESET=$'\033[0m'
PASS_COUNT=0
FAIL_COUNT=0
RESULTS=()

emit_pass() {
    local id="$1" name="$2" detail="$3"
    RESULTS+=("${GREEN}✅${RESET} ${id}. ${name} — ${detail}")
    PASS_COUNT=$((PASS_COUNT + 1))
}

emit_fail() {
    local id="$1" name="$2" detail="$3"
    RESULTS+=("${RED}❌${RESET} ${id}. ${name} — ${detail}")
    FAIL_COUNT=$((FAIL_COUNT + 1))
}

emit_warn() {
    local id="$1" name="$2" detail="$3"
    RESULTS+=("${YELLOW}⚠️${RESET}  ${id}. ${name} — ${detail}")
    if [[ "${STRICT}" == "true" ]]; then
        FAIL_COUNT=$((FAIL_COUNT + 1))
    else
        PASS_COUNT=$((PASS_COUNT + 1))
    fi
}

# ── 项 1：Tier 1 测试 ─────────────────────────────────────────────────────
check_1_tier1() {
    if "${SCRIPT_DIR}/check_tier1_pass.sh" "${TIER1_JUNIT_PATH}" >/tmp/.gate1_t1.log 2>&1; then
        emit_pass 1 "Tier 1 测试 100% 通过" "$(grep -oE '[0-9]+/[0-9]+' /tmp/.gate1_t1.log | head -1) 全绿"
    else
        emit_fail 1 "Tier 1 测试 100% 通过" "$(tr -d '\n' </tmp/.gate1_t1.log | head -c 120)"
    fi
}

# ── 项 2：k6 P99 < 200ms ─────────────────────────────────────────────────
check_2_k6_p99() {
    if [[ ! -f "${K6_RESULT_JSON}" ]]; then
        emit_fail 2 "k6 P99 < 200ms" "未找到 k6 结果文件: ${K6_RESULT_JSON}"
        return
    fi
    local p99
    p99=$(python3 - "${K6_RESULT_JSON}" <<'PY'
import json, sys
try:
    with open(sys.argv[1]) as f:
        # k6 既支持 single-summary，也支持 NDJSON。这里抽 metrics.http_req_duration.values["p(99)"]
        data = json.load(f)
    metrics = data.get("metrics", {})
    dur = metrics.get("http_req_duration", {})
    values = dur.get("values", {})
    p99 = values.get("p(99)")
    if p99 is None:
        # k6 v0.50+ 用 percentiles
        p99 = values.get("p99")
    print("" if p99 is None else f"{p99:.2f}")
except Exception:
    print("")
PY
)
    if [[ -z "${p99}" ]]; then
        emit_fail 2 "k6 P99 < 200ms" "无法从 ${K6_RESULT_JSON} 解析 p99"
        return
    fi
    # 比较：bash 不支持浮点，用 python
    if python3 -c "import sys; sys.exit(0 if float('${p99}') < 200 else 1)"; then
        emit_pass 2 "k6 P99 < 200ms" "实测 ${p99}ms"
    else
        emit_fail 2 "k6 P99 < 200ms" "实测 ${p99}ms 未达标"
    fi
}

# ── 项 3：支付成功率 > 99.9% ──────────────────────────────────────────────
check_3_payment_rate() {
    # 数据来源：可由 prometheus query 落盘到 ${PAYMENT_METRIC_FILE}
    # 文件格式：单行 "success_rate=99.93"
    if [[ ! -f "${PAYMENT_METRIC_FILE}" ]]; then
        emit_warn 3 "支付成功率 > 99.9%" "缺少指标文件 ${PAYMENT_METRIC_FILE}（需人工填写或 prometheus 导出）"
        return
    fi
    local rate
    rate=$(grep -oE 'success_rate=[0-9.]+' "${PAYMENT_METRIC_FILE}" | head -1 | cut -d= -f2 || echo "")
    if [[ -z "${rate}" ]]; then
        emit_fail 3 "支付成功率 > 99.9%" "${PAYMENT_METRIC_FILE} 格式错误"
        return
    fi
    if python3 -c "import sys; sys.exit(0 if float('${rate}') > 99.9 else 1)"; then
        emit_pass 3 "支付成功率 > 99.9%" "实测 ${rate}%"
    else
        emit_fail 3 "支付成功率 > 99.9%" "实测 ${rate}% 未达标"
    fi
}

# ── 项 4：断网 4h E2E nightly 连续 3 日 ──────────────────────────────────
check_4_offline_e2e() {
    if [[ ! -d "${E2E_REPORT_DIR}" ]]; then
        emit_fail 4 "断网 4h E2E 绿（nightly 3 日）" "缺少报告目录 ${E2E_REPORT_DIR}"
        return
    fi
    # 找最近 3 天的报告，每个文件包含 "passed=true" 视为绿
    local cutoff
    cutoff=$(python3 -c "import time; print(int(time.time()) - 4*86400)")
    local green=0
    while IFS= read -r f; do
        local mtime
        mtime=$(stat -f %m "$f" 2>/dev/null || stat -c %Y "$f" 2>/dev/null || echo 0)
        if [[ "${mtime}" -gt "${cutoff}" ]] && grep -q "passed=true" "$f" 2>/dev/null; then
            green=$((green + 1))
        fi
    done < <(find "${E2E_REPORT_DIR}" -maxdepth 1 -type f \( -name "*.txt" -o -name "*.log" \) 2>/dev/null)

    if [[ "${green}" -ge 3 ]]; then
        emit_pass 4 "断网 4h E2E 绿（nightly 3 日）" "近 4 天内有 ${green} 个绿色报告"
    else
        emit_fail 4 "断网 4h E2E 绿（nightly 3 日）" "近 4 天仅 ${green}/3 个绿色报告"
    fi
}

# ── 项 5：收银员零培训签字 ≥ 3 位 ────────────────────────────────────────
check_5_cashier_signoff() {
    if "${SCRIPT_DIR}/check_signoffs.sh" --check cashier >/tmp/.gate5.log 2>&1; then
        emit_pass 5 "收银员零培训（3 位签字）" "$(tr -d '\n' </tmp/.gate5.log)"
    else
        emit_fail 5 "收银员零培训（3 位签字）" "$(tr -d '\n' </tmp/.gate5.log)"
    fi
}

# ── 项 6：三商户 scorecard ≥ 85 ──────────────────────────────────────────
check_6_scorecard() {
    if [[ ! -f "${ADAPTER_SCORECARD}" ]]; then
        emit_warn 6 "三商户 scorecard ≥ 85" "缺少 ${ADAPTER_SCORECARD}（应由 F1 产出）"
        return
    fi
    # 解析格式：每行形如 "czyz: 87" / "zqx: 92" / "sgc: 85"
    local fail_lines=""
    local count=0
    while IFS= read -r line; do
        local code score
        code=$(echo "$line" | awk -F: '{print $1}' | xargs)
        score=$(echo "$line" | awk -F: '{print $2}' | grep -oE '[0-9]+' | head -1)
        [[ -z "$score" ]] && continue
        count=$((count + 1))
        if [[ "${score}" -lt 85 ]]; then
            fail_lines+="${code}=${score} "
        fi
    done < <(grep -E '^(czyz|zqx|sgc)\s*:' "${ADAPTER_SCORECARD}" 2>/dev/null || true)

    if [[ "${count}" -eq 0 ]]; then
        emit_warn 6 "三商户 scorecard ≥ 85" "${ADAPTER_SCORECARD} 未找到 czyz/zqx/sgc 评分行"
    elif [[ -z "${fail_lines}" && "${count}" -ge 3 ]]; then
        emit_pass 6 "三商户 scorecard ≥ 85" "三商户全部 ≥ 85"
    else
        emit_fail 6 "三商户 scorecard ≥ 85" "未达标: ${fail_lines:-(数量不足 ${count}/3)}"
    fi
}

# ── 项 7：RLS / 凭证 / 端口 / CORS / secrets 零告警 ──────────────────────
check_7_security_zero() {
    local issues=()

    # 7a: secrets
    if ! "${SCRIPT_DIR}/check_secrets.sh" >/tmp/.gate7_secrets.log 2>&1; then
        issues+=("secrets")
    fi

    # 7b: RLS — 复用 scripts/check_rls_policies.py（若存在）
    if [[ -f "${SCRIPT_DIR}/check_rls_policies.py" ]]; then
        if ! python3 "${SCRIPT_DIR}/check_rls_policies.py" --check-only >/tmp/.gate7_rls.log 2>&1; then
            issues+=("RLS")
        fi
    fi

    # 7c: 端口冲突 — 用静态扫描所有 docker-compose ports 项
    local port_dups
    port_dups=$(grep -hE '^\s*-\s*"[0-9]+:[0-9]+"' infra/docker/docker-compose*.yml 2>/dev/null \
        | grep -oE '^\s*-\s*"[0-9]+' | grep -oE '[0-9]+' | sort | uniq -d | head -5 || true)
    if [[ -n "${port_dups}" ]]; then
        # 多 compose 文件之间允许重叠（不同环境用不同 file），仅当主 dev 文件内重复才告警
        local dev_dups
        dev_dups=$(grep -hE '^\s*-\s*"[0-9]+:[0-9]+"' infra/docker/docker-compose.dev.yml 2>/dev/null \
            | grep -oE '^\s*-\s*"[0-9]+' | grep -oE '[0-9]+' | sort | uniq -d | head -5 || true)
        if [[ -n "${dev_dups}" ]]; then
            issues+=("ports(dev: ${dev_dups})")
        fi
    fi

    # 7d: CORS — 简单 grep 是否有 allow_origins=["*"]
    local cors_wild
    cors_wild=$(grep -rE 'allow_origins\s*=\s*\[\s*"\*"' services/ 2>/dev/null | grep -v test | head -3 || true)
    if [[ -n "${cors_wild}" ]]; then
        issues+=("CORS-wildcard")
    fi

    if [[ "${#issues[@]}" -eq 0 ]]; then
        emit_pass 7 "RLS/凭证/端口/CORS/secrets 零告警" "全部通过"
    else
        emit_fail 7 "RLS/凭证/端口/CORS/secrets 零告警" "告警项: ${issues[*]}"
    fi
}

# ── 项 8：demo-reset.sh 回退验证 ─────────────────────────────────────────
check_8_demo_reset() {
    local script="${SCRIPT_DIR}/demo-reset.sh"
    if [[ ! -f "${script}" ]]; then
        emit_fail 8 "demo-reset.sh 回退验证" "脚本不存在"
        return
    fi
    # 8a: shell 语法
    if ! bash -n "${script}" 2>/tmp/.gate8.log; then
        emit_fail 8 "demo-reset.sh 回退验证" "shell 语法错误"
        return
    fi
    # 8b: --dry-run 必须存在且能跑通（不真改 DB）
    if grep -q '\-\-dry-run' "${script}"; then
        # dry-run 不依赖 psql 连通时也应该正常列出操作
        if bash "${script}" --dry-run --merchant czyz >/tmp/.gate8_run.log 2>&1; then
            emit_pass 8 "demo-reset.sh 回退验证" "--dry-run 通过"
        else
            emit_fail 8 "demo-reset.sh 回退验证" "--dry-run 退出码非 0"
        fi
    else
        emit_fail 8 "demo-reset.sh 回退验证" "缺少 --dry-run 参数"
    fi
}

# ── 项 9：A/B 实验 ≥ 1 个 running 未熔断 ─────────────────────────────────
check_9_experiment() {
    if ! command -v curl &>/dev/null; then
        emit_warn 9 "A/B 实验 running 未熔断" "缺少 curl，无法检查"
        return
    fi
    local resp
    resp=$(curl -fsS --max-time 5 "${EXPERIMENT_API}" 2>/dev/null || echo "")
    if [[ -z "${resp}" ]]; then
        emit_warn 9 "A/B 实验 running 未熔断" "实验 API 不可达: ${EXPERIMENT_API}"
        return
    fi
    # 期望 JSON 形如 {"running": N, "tripped": M}
    local running tripped
    running=$(python3 -c "import json,sys; d=json.loads(sys.argv[1]); print(d.get('running',0))" "${resp}" 2>/dev/null || echo 0)
    tripped=$(python3 -c "import json,sys; d=json.loads(sys.argv[1]); print(d.get('tripped',0))" "${resp}" 2>/dev/null || echo 0)
    if [[ "${running}" -ge 1 && "${tripped}" -eq 0 ]]; then
        emit_pass 9 "A/B 实验 running 未熔断" "running=${running} tripped=${tripped}"
    else
        emit_fail 9 "A/B 实验 running 未熔断" "running=${running} tripped=${tripped}"
    fi
}

# ── 项 10：三套演示话术 ──────────────────────────────────────────────────
check_10_demo_script() {
    if "${SCRIPT_DIR}/check_signoffs.sh" --check demo-script >/tmp/.gate10.log 2>&1; then
        emit_pass 10 "三套演示话术打印就位" "$(tr -d '\n' </tmp/.gate10.log)"
    else
        emit_fail 10 "三套演示话术打印就位" "$(tr -d '\n' </tmp/.gate10.log)"
    fi
}

# ── 主流程 ────────────────────────────────────────────────────────────────
echo "════════════════════════════════════════════════════════════════"
echo "  屯象OS Week 8 DEMO Gate Check"
echo "  时间: $(date '+%Y-%m-%d %H:%M:%S')"
echo "  仓库: ${REPO_ROOT}"
echo "  严格模式: ${STRICT}"
echo "════════════════════════════════════════════════════════════════"
echo ""

check_1_tier1
check_2_k6_p99
check_3_payment_rate
check_4_offline_e2e
check_5_cashier_signoff
check_6_scorecard
check_7_security_zero
check_8_demo_reset
check_9_experiment
check_10_demo_script

echo ""
for line in "${RESULTS[@]}"; do
    printf '%s\n' "${line}"
done
echo ""
echo "════════════════════════════════════════════════════════════════"
TOTAL=$((PASS_COUNT + FAIL_COUNT))
echo "  通过: ${PASS_COUNT}/${TOTAL}"
echo "  未达: ${FAIL_COUNT}/${TOTAL}"
if [[ "${FAIL_COUNT}" -eq 0 ]]; then
    echo "  ${GREEN}DEMO Go/No-Go: GO${RESET}"
    echo "════════════════════════════════════════════════════════════════"
    exit 0
else
    echo "  ${RED}DEMO Go/No-Go: NO-GO${RESET}"
    echo "════════════════════════════════════════════════════════════════"
    exit 1
fi
