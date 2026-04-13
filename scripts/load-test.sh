#!/usr/bin/env bash
# 屯象OS 压测脚本 — 上线前压力测试
# 用法: ./scripts/load-test.sh [--merchant czyz|zqx|sgc] [--concurrency 5] [--requests 50] [--gateway http://localhost:8000]
set -uo pipefail

# ── 默认参数 ──────────────────────────────────────────────────────────────────────
MERCHANT="czyz"
CONCURRENCY=5
REQUESTS=50
GATEWAY="http://localhost:8000"

# ── 参数解析 ──────────────────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
    case "$1" in
        --merchant)    MERCHANT="$2";    shift 2 ;;
        --concurrency) CONCURRENCY="$2"; shift 2 ;;
        --requests)    REQUESTS="$2";    shift 2 ;;
        --gateway)     GATEWAY="$2";     shift 2 ;;
        *) echo "未知参数: $1"; exit 1 ;;
    esac
done

# ── 算术工具（优先 bc，降级到 awk） ───────────────────────────────────────────────
_calc() {
    # _calc "表达式"  → 输出结果（保留1位小数）
    local expr="$1"
    if command -v bc >/dev/null 2>&1; then
        printf "%.1f" "$(echo "scale=4; $expr" | bc -l 2>/dev/null || echo 0)"
    else
        awk "BEGIN { printf \"%.1f\", $expr }"
    fi
}

_calc_int() {
    # _calc_int "表达式"  → 输出整数结果
    local expr="$1"
    if command -v bc >/dev/null 2>&1; then
        echo "$(echo "scale=0; ($expr)/1" | bc -l 2>/dev/null || echo 0)"
    else
        awk "BEGIN { printf \"%d\", $expr }"
    fi
}

# ── curl 单次请求，返回 HTTP 状态码 ───────────────────────────────────────────────
_request() {
    local url="$1"
    local tenant_header="$2"
    local status
    status=$(curl -s -o /dev/null -w "%{http_code}" \
        -H "X-Tenant-ID: ${tenant_header}" \
        --connect-timeout 5 \
        --max-time 30 \
        "${url}" 2>/dev/null || echo "000")
    echo "$status"
}

# ── 并发执行 N 个请求，返回 "success_count fail_count elapsed_ms" ─────────────────
_run_scenario() {
    local url="$1"
    local tenant_header="$2"
    local total="$3"
    local concurrency="$4"

    local success=0
    local fail=0
    local start_ms
    start_ms=$(date +%s%3N 2>/dev/null || python3 -c "import time; print(int(time.time()*1000))")

    local dispatched=0
    local pids=()
    local tmpdir
    tmpdir=$(mktemp -d)

    while [[ $dispatched -lt $total ]]; do
        # 发射一批并发请求
        local batch=0
        pids=()
        while [[ $batch -lt $concurrency && $dispatched -lt $total ]]; do
            local result_file="${tmpdir}/r_${dispatched}"
            (
                code=$(_request "$url" "$tenant_header")
                echo "$code" > "$result_file"
            ) &
            pids+=($!)
            (( dispatched++ )) || true
            (( batch++ ))     || true
        done
        # 等待本批完成
        for pid in "${pids[@]}"; do
            wait "$pid" 2>/dev/null || true
        done
    done

    # 统计结果
    for f in "${tmpdir}"/r_*; do
        [[ -f "$f" ]] || continue
        code=$(cat "$f" 2>/dev/null || echo "000")
        if [[ "$code" =~ ^2[0-9][0-9]$ ]]; then
            (( success++ )) || true
        else
            (( fail++ )) || true
        fi
    done
    rm -rf "$tmpdir"

    local end_ms
    end_ms=$(date +%s%3N 2>/dev/null || python3 -c "import time; print(int(time.time()*1000))")
    local elapsed_ms=$(( end_ms - start_ms ))

    echo "${success} ${fail} ${elapsed_ms}"
}

# ── 格式化输出行 ──────────────────────────────────────────────────────────────────
_print_row() {
    local label="$1"
    local total="$2"
    local success="$3"
    local fail="$4"
    local elapsed_ms="$5"

    local elapsed_s rps
    elapsed_s=$(_calc "$elapsed_ms / 1000")
    if [[ "$elapsed_ms" -gt 0 ]]; then
        rps=$(_calc "$total * 1000 / $elapsed_ms")
    else
        rps="0.0"
    fi

    printf "%-14s  %4d  %4d  %4d    %6s   %5s\n" \
        "$label" "$total" "$success" "$fail" "$elapsed_s" "$rps"
}

# ── 主体 ──────────────────────────────────────────────────────────────────────────
TENANT_HEADER="${MERCHANT}-demo-tenant"

# 计算各场景请求数
N_HEALTH=10
N_MENU=$REQUESTS
N_QUALITY=$(( REQUESTS / 5 < 1 ? 1 : REQUESTS / 5 ))
N_KPI=$(( REQUESTS / 5 < 1 ? 1 : REQUESTS / 5 ))
N_MONITOR=$(( REQUESTS / 10 < 1 ? 1 : REQUESTS / 10 ))

echo ""
echo "[LOAD TEST] 屯象OS 压测报告"
echo "商户: ${MERCHANT} | 并发: ${CONCURRENCY} | 总请求: ${REQUESTS}"
echo "网关: ${GATEWAY}"
echo "─────────────────────────────────────────────────────"
printf "%-14s  %4s  %4s  %4s    %6s   %5s\n" "场景" "总数" "成功" "失败" "耗时(s)" "RPS"
echo "─────────────────────────────────────────────────────"

# 各场景累计
TOTAL_SENT=0
TOTAL_SUCCESS=0
TOTAL_FAIL=0

# 1. 健康检查（warmup）
read -r s1 f1 e1 <<< "$(_run_scenario "${GATEWAY}/health" "" "$N_HEALTH" "$CONCURRENCY")"
_print_row "健康检查" "$N_HEALTH" "$s1" "$f1" "$e1"
(( TOTAL_SENT    += N_HEALTH )) || true
(( TOTAL_SUCCESS += s1       )) || true
(( TOTAL_FAIL    += f1       )) || true

# 2. 菜单查询（read-heavy）
read -r s2 f2 e2 <<< "$(_run_scenario "${GATEWAY}/api/v1/menu/dishes" "$TENANT_HEADER" "$N_MENU" "$CONCURRENCY")"
_print_row "菜单查询" "$N_MENU" "$s2" "$f2" "$e2"
(( TOTAL_SENT    += N_MENU )) || true
(( TOTAL_SUCCESS += s2     )) || true
(( TOTAL_FAIL    += f2     )) || true

# 3. 数据质量（analytics）
read -r s3 f3 e3 <<< "$(_run_scenario "${GATEWAY}/api/v1/analytics/data-quality/${MERCHANT}" "$TENANT_HEADER" "$N_QUALITY" "$CONCURRENCY")"
_print_row "数据质量" "$N_QUALITY" "$s3" "$f3" "$e3"
(( TOTAL_SENT    += N_QUALITY )) || true
(( TOTAL_SUCCESS += s3        )) || true
(( TOTAL_FAIL    += f3        )) || true

# 4. KPI目标（analytics）
read -r s4 f4 e4 <<< "$(_run_scenario "${GATEWAY}/api/v1/analytics/merchant-targets/${MERCHANT}" "$TENANT_HEADER" "$N_KPI" "$CONCURRENCY")"
_print_row "KPI目标" "$N_KPI" "$s4" "$f4" "$e4"
(( TOTAL_SENT    += N_KPI )) || true
(( TOTAL_SUCCESS += s4    )) || true
(( TOTAL_FAIL    += f4    )) || true

# 5. 演示监控（dashboard）
read -r s5 f5 e5 <<< "$(_run_scenario "${GATEWAY}/api/v1/demo/monitor" "$TENANT_HEADER" "$N_MONITOR" "$CONCURRENCY")"
_print_row "演示监控" "$N_MONITOR" "$s5" "$f5" "$e5"
(( TOTAL_SENT    += N_MONITOR )) || true
(( TOTAL_SUCCESS += s5        )) || true
(( TOTAL_FAIL    += f5        )) || true

echo "─────────────────────────────────────────────────────"

# 成功率计算
if [[ "$TOTAL_SENT" -gt 0 ]]; then
    SUCCESS_RATE_PCT=$(_calc_int "$TOTAL_SUCCESS * 100 / $TOTAL_SENT")
else
    SUCCESS_RATE_PCT=0
fi

echo ""
if [[ "$SUCCESS_RATE_PCT" -ge 90 ]]; then
    echo "[PASS] 总体成功率: ${SUCCESS_RATE_PCT}% (≥90% 阈值通过)"
    echo "       总请求: ${TOTAL_SENT} | 成功: ${TOTAL_SUCCESS} | 失败: ${TOTAL_FAIL}"
    exit 0
else
    echo "[FAIL] 总体成功率: ${SUCCESS_RATE_PCT}% (<90% 阈值未通过)"
    echo "       总请求: ${TOTAL_SENT} | 成功: ${TOTAL_SUCCESS} | 失败: ${TOTAL_FAIL}"
    exit 1
fi
