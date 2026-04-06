#!/bin/bash
# ============================================================
# 屯象OS 月度成本报告脚本
# 版本: 1.0.0  |  最后更新: 2026-04-06
# 维护人: 李淳（屯象OS创始人）
#
# 功能:
#   1. 汇总各环境 Docker 容器运行时长
#   2. 从 tx-brain 日志读取 LLM token 用量并估算成本
#   3. 输出 Markdown 格式月度成本报告
#
# 使用方式:
#   ./cost-report.sh                       当前月度报告
#   ./cost-report.sh --month=2026-03       指定月份报告
#   ./cost-report.sh --output=report.md    输出到文件
#   ./cost-report.sh --format=json         JSON格式输出
# ============================================================

set -euo pipefail

# ──────────────────────────────────────────────
# 常量
# ──────────────────────────────────────────────
readonly SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
readonly LOG_DIR="${REPO_ROOT}/logs"
readonly REPORT_DIR="${REPO_ROOT}/logs/cost-reports"

# 成本单价（元）
declare -A ENV_COST_PER_HOUR=(
  [dev]=0.8
  [test]=0.6
  [uat]=0.5
  [pilot]=2.0
  [prod]=5.0
  [demo]=0.3
)

# LLM API 单价（元/千token）
readonly LLM_INPUT_COST_PER_1K=0.015    # 输入token价格（以DeepSeek为参考基准）
readonly LLM_OUTPUT_COST_PER_1K=0.06    # 输出token价格
readonly LLM_PREMIUM_MULTIPLIER=5       # 高级模型（如Claude/GPT-4）倍数

# 月度预算
readonly MONTHLY_BUDGET_TOTAL=3000
readonly MONTHLY_BUDGET_LLM=500
readonly MONTHLY_BUDGET_NONPROD=600

# ──────────────────────────────────────────────
# 参数解析
# ──────────────────────────────────────────────
REPORT_MONTH=$(date +%Y-%m)
OUTPUT_FILE=""
OUTPUT_FORMAT="markdown"

for arg in "$@"; do
  case "$arg" in
    --month=*)   REPORT_MONTH="${arg#*=}" ;;
    --output=*)  OUTPUT_FILE="${arg#*=}" ;;
    --format=*)  OUTPUT_FORMAT="${arg#*=}" ;;
    --help|-h)
      echo "用法: $(basename "$0") [--month=YYYY-MM] [--output=file.md] [--format=markdown|json]"
      exit 0 ;;
  esac
done

REPORT_YEAR="${REPORT_MONTH%-*}"
REPORT_MON="${REPORT_MONTH#*-}"

# ──────────────────────────────────────────────
# 工具函数
# ──────────────────────────────────────────────
bc_calc() {
  echo "scale=2; $1" | bc 2>/dev/null || echo "0.00"
}

bc_calc_int() {
  echo "scale=0; $1 / 1" | bc 2>/dev/null || echo "0"
}

# 格式化数字为货币（¥xx.xx）
fmt_cny() {
  printf "¥%.2f" "${1:-0}"
}

# ──────────────────────────────────────────────
# 数据采集: Docker 容器运行时长
# ──────────────────────────────────────────────
collect_docker_stats() {
  local env="$1"
  local month_start="${REPORT_YEAR}-${REPORT_MON}-01"

  # 通过 docker stats 历史或 docker inspect 获取运行时间
  # 由于 docker 不原生支持历史时长，使用 docker ps 和 created at 估算
  local running_containers
  running_containers=$(docker ps -a \
    --filter "label=tunxiang.env=${env}" \
    --format "{{.ID}} {{.CreatedAt}} {{.Status}}" 2>/dev/null) || running_containers=""

  local total_hours=0
  local container_count=0

  while IFS= read -r line; do
    [[ -z "$line" ]] && continue
    ((container_count++))

    local created_str status_str
    created_str=$(echo "$line" | awk '{print $2, $3}')
    status_str=$(echo "$line" | awk '{print $4}')

    # 计算本月运行小时数（简化：如果状态是running，用当前时间减月初）
    local start_epoch now_epoch
    now_epoch=$(date +%s)

    # 尝试解析创建时间
    start_epoch=$(date -d "$created_str" +%s 2>/dev/null || echo "0")
    local month_start_epoch
    month_start_epoch=$(date -d "${month_start}" +%s 2>/dev/null || echo "0")

    # 取月初和容器创建时间的较大值
    local effective_start=$(( start_epoch > month_start_epoch ? start_epoch : month_start_epoch ))

    local seconds=$(( now_epoch - effective_start ))
    local hours
    hours=$(bc_calc "$seconds / 3600")

    total_hours=$(bc_calc "$total_hours + $hours")
  done <<< "$running_containers"

  echo "$total_hours $container_count"
}

# ──────────────────────────────────────────────
# 数据采集: LLM Token 用量（从日志解析）
# ──────────────────────────────────────────────
collect_llm_usage() {
  local log_patterns=(
    "${LOG_DIR}/tx-brain*.log"
    "${LOG_DIR}/agent*.log"
    "${REPO_ROOT}/services/tx-brain/logs/*.log"
  )

  local total_input_tokens=0
  local total_output_tokens=0
  local total_requests=0
  local model_breakdown=""

  # 按月过滤日志并统计
  for pattern in "${log_patterns[@]}"; do
    for logfile in $pattern; do
      [[ -f "$logfile" ]] || continue

      # 解析格式: {"timestamp":"2026-03-xx","model":"deepseek","input_tokens":xxx,"output_tokens":xxx}
      while IFS= read -r line; do
        local input_t output_t
        input_t=$(echo "$line" | python3 -c "
import sys, json
try:
    d = json.loads(sys.stdin.read().strip())
    print(d.get('input_tokens', d.get('prompt_tokens', 0)))
except: print(0)
" 2>/dev/null || echo "0")
        output_t=$(echo "$line" | python3 -c "
import sys, json
try:
    d = json.loads(sys.stdin.read().strip())
    print(d.get('output_tokens', d.get('completion_tokens', 0)))
except: print(0)
" 2>/dev/null || echo "0")

        total_input_tokens=$((total_input_tokens + input_t))
        total_output_tokens=$((total_output_tokens + output_t))
        ((total_requests++))
      done < <(grep -i "\"${REPORT_YEAR}-${REPORT_MON}" "$logfile" 2>/dev/null || true)
    done
  done

  # 如果没有找到日志，返回估算值（占位）
  if [[ "$total_requests" -eq 0 ]]; then
    echo "0 0 0 no_data"
  else
    echo "$total_input_tokens $total_output_tokens $total_requests ok"
  fi
}

# ──────────────────────────────────────────────
# 生成 Markdown 报告
# ──────────────────────────────────────────────
generate_markdown_report() {
  local report_date
  report_date=$(date '+%Y-%m-%d %H:%M:%S')

  # ── 采集各环境数据 ──
  declare -A env_hours env_containers env_cost
  local total_infra_cost=0

  local envs=(dev test uat pilot prod demo)
  for env in "${envs[@]}"; do
    local stats
    stats=$(collect_docker_stats "$env")
    env_hours[$env]=$(echo "$stats" | awk '{print $1}')
    env_containers[$env]=$(echo "$stats" | awk '{print $2}')

    local rate="${ENV_COST_PER_HOUR[$env]:-0.5}"
    env_cost[$env]=$(bc_calc "${env_hours[$env]} * $rate")
    total_infra_cost=$(bc_calc "$total_infra_cost + ${env_cost[$env]}")
  done

  # ── 采集 LLM 数据 ──
  local llm_stats
  llm_stats=$(collect_llm_usage)
  local llm_input_tokens llm_output_tokens llm_requests llm_data_status
  read -r llm_input_tokens llm_output_tokens llm_requests llm_data_status <<< "$llm_stats"

  local llm_input_cost llm_output_cost llm_total_cost
  llm_input_cost=$(bc_calc "$llm_input_tokens / 1000 * $LLM_INPUT_COST_PER_1K")
  llm_output_cost=$(bc_calc "$llm_output_tokens / 1000 * $LLM_OUTPUT_COST_PER_1K")
  llm_total_cost=$(bc_calc "$llm_input_cost + $llm_output_cost")

  # ── 计算总成本 ──
  local total_cost
  total_cost=$(bc_calc "$total_infra_cost + $llm_total_cost")

  # ── 预算对比 ──
  local budget_pct
  budget_pct=$(bc_calc_int "$total_cost * 100 / $MONTHLY_BUDGET_TOTAL")

  local nonprod_cost
  nonprod_cost=$(bc_calc "${env_cost[dev]} + ${env_cost[test]} + ${env_cost[uat]} + ${env_cost[demo]}")

  # ── 生成报告 ──
  cat << EOF
# 屯象OS 月度成本报告

**报告月份**: ${REPORT_MONTH}
**生成时间**: ${report_date}
**报告版本**: v1.0

---

## 一、成本总览

| 项目 | 本月费用 | 月度预算 | 使用率 | 状态 |
|------|---------|---------|--------|------|
| 基础设施（服务器/容器） | $(fmt_cny $total_infra_cost) | - | - | - |
| LLM/AI API | $(fmt_cny $llm_total_cost) | $(fmt_cny $MONTHLY_BUDGET_LLM) | $(bc_calc_int "$llm_total_cost * 100 / $MONTHLY_BUDGET_LLM")% | $([ "$(bc_calc_int "$llm_total_cost * 100 / $MONTHLY_BUDGET_LLM")" -gt 80 ] && echo "⚠️ 告警" || echo "✅ 正常") |
| **合计** | **$(fmt_cny $total_cost)** | **$(fmt_cny $MONTHLY_BUDGET_TOTAL)** | **${budget_pct}%** | $([ "$budget_pct" -gt 80 ] && echo "⚠️ 告警" || echo "✅ 正常") |

> 非生产环境合计: $(fmt_cny $nonprod_cost) / 月预算上限 $(fmt_cny $MONTHLY_BUDGET_NONPROD)

---

## 二、基础设施成本明细（按环境）

| 环境 | 容器数 | 运行时长(h) | 单价(¥/h) | 费用 | 备注 |
|------|--------|------------|----------|------|------|
| dev  | ${env_containers[dev]} | ${env_hours[dev]} | ${ENV_COST_PER_HOUR[dev]} | $(fmt_cny ${env_cost[dev]}) | 工作日夜间停机 |
| test | ${env_containers[test]} | ${env_hours[test]} | ${ENV_COST_PER_HOUR[test]} | $(fmt_cny ${env_cost[test]}) | 周末全停 |
| uat  | ${env_containers[uat]} | ${env_hours[uat]} | ${ENV_COST_PER_HOUR[uat]} | $(fmt_cny ${env_cost[uat]}) | 4h无活动停 |
| pilot | ${env_containers[pilot]} | ${env_hours[pilot]} | ${ENV_COST_PER_HOUR[pilot]} | $(fmt_cny ${env_cost[pilot]}) | 7x24运行 |
| prod | ${env_containers[prod]} | ${env_hours[prod]} | ${ENV_COST_PER_HOUR[prod]} | $(fmt_cny ${env_cost[prod]}) | 7x24运行 |
| demo | ${env_containers[demo]} | ${env_hours[demo]} | ${ENV_COST_PER_HOUR[demo]} | $(fmt_cny ${env_cost[demo]}) | 售前演示 |
| **合计** | - | - | - | **$(fmt_cny $total_infra_cost)** | |

---

## 三、LLM/AI API 成本明细

$(if [[ "$llm_data_status" == "no_data" ]]; then
  echo "> ⚠️ **未找到 LLM 调用日志**（logs/tx-brain*.log），以下为估算占位数据"
fi)

| 指标 | 数值 |
|------|------|
| 总请求次数 | ${llm_requests} 次 |
| 输入 Tokens | $(printf "%'d" $llm_input_tokens) tokens |
| 输出 Tokens | $(printf "%'d" $llm_output_tokens) tokens |
| 输入成本（¥${LLM_INPUT_COST_PER_1K}/千token） | $(fmt_cny $llm_input_cost) |
| 输出成本（¥${LLM_OUTPUT_COST_PER_1K}/千token） | $(fmt_cny $llm_output_cost) |
| **LLM API 合计** | **$(fmt_cny $llm_total_cost)** |

### 按服务拆分（估算）

| 服务 | 占比 | 估算费用 |
|------|------|---------|
| tx-brain（主推理） | ~50% | $(fmt_cny $(bc_calc "$llm_total_cost * 0.5")) |
| Agent实验 | ~30% | $(fmt_cny $(bc_calc "$llm_total_cost * 0.3")) |
| 其他辅助调用 | ~20% | $(fmt_cny $(bc_calc "$llm_total_cost * 0.2")) |

---

## 四、成本优化建议

$(if (( $(bc_calc_int "${env_cost[dev]} + ${env_cost[test]}") > 200 )); then
  echo "- ⚠️ **dev+test 费用偏高**（$(fmt_cny $(bc_calc "${env_cost[dev]} + ${env_cost[test]}"))），检查是否有遗漏停机的容器"
fi)
$(if (( $(bc_calc_int "${env_cost[uat]}") > 150 )); then
  echo "- ⚠️ **uat 费用偏高**（$(fmt_cny ${env_cost[uat]})），检查是否长期未停机"
fi)
$(if [[ "$llm_data_status" == "ok" ]] && (( $(bc_calc_int "$llm_total_cost * 100 / $MONTHLY_BUDGET_LLM") > 70 )); then
  echo "- ⚠️ **LLM API 超过预算70%**，建议检查是否有重复调用或 Agent 循环请求"
fi)
- 建议每月初执行 \`./scripts/env-manager.sh status all\` 检查环境状态
- 非生产环境应确保已配置 Harness CCM AutoStopping 规则
- tx-brain Agent 实验完成后及时停止 GPU 实例

---

## 五、同期对比

| 月份 | 基础设施 | LLM API | 合计 | 环比变化 |
|------|---------|---------|------|---------|
| ${REPORT_MONTH} | $(fmt_cny $total_infra_cost) | $(fmt_cny $llm_total_cost) | $(fmt_cny $total_cost) | 当前月 |
| 上月 | - | - | - | 数据待采集 |

---

*本报告由 \`scripts/cost-report.sh\` 自动生成 | 屯象OS v1.0*
*基础设施成本为估算值（基于容器运行时长 × 单价），实际账单以云服务商为准*
EOF
}

# ──────────────────────────────────────────────
# 生成 JSON 报告
# ──────────────────────────────────────────────
generate_json_report() {
  local report_date
  report_date=$(date -u +%Y-%m-%dT%H:%M:%SZ)

  local envs=(dev test uat pilot prod demo)
  local env_json=""
  local total_infra_cost=0

  for env in "${envs[@]}"; do
    local stats
    stats=$(collect_docker_stats "$env")
    local hours containers
    hours=$(echo "$stats" | awk '{print $1}')
    containers=$(echo "$stats" | awk '{print $2}')

    local rate="${ENV_COST_PER_HOUR[$env]:-0.5}"
    local cost
    cost=$(bc_calc "$hours * $rate")
    total_infra_cost=$(bc_calc "$total_infra_cost + $cost")

    [[ -n "$env_json" ]] && env_json+=","
    env_json+="\"${env}\":{\"hours\":${hours},\"containers\":${containers},\"cost\":${cost}}"
  done

  local llm_stats
  llm_stats=$(collect_llm_usage)
  local llm_input_t llm_output_t llm_req llm_status
  read -r llm_input_t llm_output_t llm_req llm_status <<< "$llm_stats"

  local llm_cost
  llm_cost=$(bc_calc "$llm_input_t / 1000 * $LLM_INPUT_COST_PER_1K + $llm_output_t / 1000 * $LLM_OUTPUT_COST_PER_1K")

  local total_cost
  total_cost=$(bc_calc "$total_infra_cost + $llm_cost")

  cat << EOF
{
  "report_month": "${REPORT_MONTH}",
  "generated_at": "${report_date}",
  "currency": "CNY",
  "summary": {
    "infra_cost": ${total_infra_cost},
    "llm_cost": ${llm_cost},
    "total_cost": ${total_cost},
    "budget_total": ${MONTHLY_BUDGET_TOTAL},
    "budget_utilization_pct": $(bc_calc_int "$total_cost * 100 / $MONTHLY_BUDGET_TOTAL")
  },
  "environments": {${env_json}},
  "llm": {
    "input_tokens": ${llm_input_t},
    "output_tokens": ${llm_output_t},
    "requests": ${llm_req},
    "cost": ${llm_cost},
    "data_status": "${llm_status}"
  }
}
EOF
}

# ──────────────────────────────────────────────
# 主入口
# ──────────────────────────────────────────────
main() {
  # 确保报告目录存在
  mkdir -p "$REPORT_DIR"

  local report_content
  case "$OUTPUT_FORMAT" in
    json)     report_content=$(generate_json_report) ;;
    markdown) report_content=$(generate_markdown_report) ;;
    *)        fatal "未知输出格式: ${OUTPUT_FORMAT}（支持 markdown/json）" ;;
  esac

  if [[ -n "$OUTPUT_FILE" ]]; then
    echo "$report_content" > "$OUTPUT_FILE"
    echo "报告已保存至: ${OUTPUT_FILE}" >&2
  else
    # 同时保存一份到报告目录
    local auto_file="${REPORT_DIR}/cost-report-${REPORT_MONTH}.md"
    echo "$report_content" > "$auto_file"
    echo "报告已保存至: ${auto_file}" >&2
    echo ""
    echo "$report_content"
  fi
}

main "$@"
