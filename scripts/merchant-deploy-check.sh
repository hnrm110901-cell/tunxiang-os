#!/usr/bin/env bash
# ============================================================
# 屯象OS — 商户部署就绪检查脚本
# 用法: ./scripts/merchant-deploy-check.sh <merchant_code>
#       merchant_code: czyz | zqx | sgc  (默认: czyz)
#
# 检查项:
#   1. 环境变量完整性
#   2. 14个服务 UP/DOWN 状态
#   3. Demo 健康检查接口
#   4. 交付评分卡 (total_score + go_no_go)
#   5. 商户 KPI 配置是否已植入
#
# 退出码: 0=GO, 1=NO-GO
# ============================================================

# 不使用 set -euo pipefail，改用手动错误捕获，避免单项检查失败中断整体
set -uo pipefail

# ── 颜色 ──────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
BOLD='\033[1m'
NC='\033[0m' # No Color

# ── 参数 ──────────────────────────────────────────────────
MERCHANT_CODE="${1:-czyz}"

# 验证商户编码
case "$MERCHANT_CODE" in
  czyz|zqx|sgc)
    ;;
  *)
    echo -e "${RED}❌ 无效的商户编码: '$MERCHANT_CODE'. 有效值: czyz | zqx | sgc${NC}"
    exit 1
    ;;
esac

# ── 根据商户确定端口偏移 ────────────────────────────────────
case "$MERCHANT_CODE" in
  czyz) PORT_OFFSET=0   ; TENANT_ID="czyz-demo-tenant"   ; MERCHANT_NAME="尝在一起" ;;
  zqx)  PORT_OFFSET=100 ; TENANT_ID="zqx-demo-tenant"    ; MERCHANT_NAME="最黔线"   ;;
  sgc)  PORT_OFFSET=200 ; TENANT_ID="sgc-demo-tenant"    ; MERCHANT_NAME="尚宫厨"   ;;
esac

GATEWAY_PORT=$((8000 + PORT_OFFSET))
GATEWAY_URL="${GATEWAY_URL:-http://localhost:${GATEWAY_PORT}}"

# ── JSON 解析工具 ────────────────────────────────────────────
if command -v jq &>/dev/null; then
  parse_json() { jq -r "$1" 2>/dev/null; }
else
  # 回退到 python3
  parse_json() {
    local expr="$1"
    python3 -c "
import sys, json
try:
    data = json.load(sys.stdin)
    # 简单键路径解析: .key.subkey 或 .key
    path = '${expr}'.lstrip('.')
    for k in path.split('.'):
        if k:
            data = data[k] if isinstance(data, dict) else data
    print(data if data is not None else 'null')
except Exception as e:
    print('null')
" 2>/dev/null
  }
fi

# ── 结果追踪 ─────────────────────────────────────────────────
CHECKS_PASS=0
CHECKS_WARN=0
CHECKS_FAIL=0
GO_NO_GO="PENDING"

print_header() {
  echo ""
  echo -e "${BOLD}${BLUE}══════════════════════════════════════════════════════${NC}"
  echo -e "${BOLD}${BLUE}  屯象OS 部署就绪检查 — ${MERCHANT_NAME} (${MERCHANT_CODE})${NC}"
  echo -e "${BOLD}${BLUE}  时间: $(date '+%Y-%m-%d %H:%M:%S')${NC}"
  echo -e "${BOLD}${BLUE}══════════════════════════════════════════════════════${NC}"
  echo ""
}

print_section() {
  echo -e "\n${BOLD}── $1 ──────────────────────────────────────────────────${NC}"
}

pass() {
  echo -e "  ${GREEN}✅ $1${NC}"
  CHECKS_PASS=$((CHECKS_PASS + 1))
}

warn() {
  echo -e "  ${YELLOW}⚠️  $1${NC}"
  CHECKS_WARN=$((CHECKS_WARN + 1))
}

fail() {
  echo -e "  ${RED}❌ $1${NC}"
  CHECKS_FAIL=$((CHECKS_FAIL + 1))
}

# ── 检查 1: 环境变量 ──────────────────────────────────────────
check_env_vars() {
  print_section "检查 1/5: 环境变量"

  local required_vars=("DATABASE_URL" "REDIS_URL" "GATEWAY_URL")
  local all_ok=true

  for var in "${required_vars[@]}"; do
    if [[ -n "${!var:-}" ]]; then
      pass "$var 已设置"
    else
      warn "$var 未设置（将使用默认值）"
      all_ok=false
    fi
  done

  # 检查可选但重要的变量
  local optional_vars=("TX_ENV" "TX_AUTH_ENABLED" "LOG_LEVEL")
  for var in "${optional_vars[@]}"; do
    if [[ -z "${!var:-}" ]]; then
      warn "$var 未设置（可选）"
    fi
  done

  $all_ok && pass "所有必需环境变量已就绪" || true
}

# ── 检查 2: 服务健康状态（14个端口）─────────────────────────
check_services() {
  print_section "检查 2/5: 服务可用性 (14 个微服务)"

  declare -A SERVICE_PORTS=(
    ["gateway"]=$((8000 + PORT_OFFSET))
    ["tx-trade"]=$((8001 + PORT_OFFSET))
    ["tx-menu"]=$((8002 + PORT_OFFSET))
    ["tx-member"]=$((8003 + PORT_OFFSET))
    ["tx-growth"]=$((8004 + PORT_OFFSET))
    ["tx-ops"]=$((8005 + PORT_OFFSET))
    ["tx-supply"]=$((8006 + PORT_OFFSET))
    ["tx-finance"]=$((8007 + PORT_OFFSET))
    ["tx-agent"]=$((8008 + PORT_OFFSET))
    ["tx-analytics"]=$((8009 + PORT_OFFSET))
    ["tx-brain"]=$((8010 + PORT_OFFSET))
    ["tx-intel"]=$((8011 + PORT_OFFSET))
    ["tx-org"]=$((8012 + PORT_OFFSET))
    ["tx-civic"]=$((8014 + PORT_OFFSET))
  )

  local up_count=0
  local down_count=0

  for svc in gateway tx-trade tx-menu tx-member tx-growth tx-ops tx-supply tx-finance tx-agent tx-analytics tx-brain tx-intel tx-org tx-civic; do
    local port="${SERVICE_PORTS[$svc]}"
    # 先尝试 /health，再尝试 /api/v1/health，失败则标 DOWN
    local status
    if curl -sf --max-time 3 "http://localhost:${port}/health" -o /dev/null 2>/dev/null; then
      status="UP"
    elif curl -sf --max-time 3 "http://localhost:${port}/api/v1/health" -o /dev/null 2>/dev/null; then
      status="UP"
    else
      status="DOWN"
    fi

    if [[ "$status" == "UP" ]]; then
      pass "${svc} [:${port}] UP"
      up_count=$((up_count + 1))
    else
      fail "${svc} [:${port}] DOWN"
      down_count=$((down_count + 1))
    fi
  done

  echo ""
  echo -e "  服务统计: ${GREEN}${up_count} UP${NC} / ${RED}${down_count} DOWN${NC}"

  if [[ $down_count -gt 3 ]]; then
    fail "超过 3 个服务不可用，阻断上线"
  elif [[ $down_count -gt 0 ]]; then
    warn "$down_count 个服务不可用，需人工确认是否关键服务"
  fi
}

# ── 检查 3: Demo 健康检查接口 ────────────────────────────────
check_demo_health() {
  print_section "检查 3/5: Demo 健康检查接口"

  local url="${GATEWAY_URL}/api/v1/demo/health-check"
  local response
  response=$(curl -sf --max-time 10 \
    -H "X-Tenant-ID: ${TENANT_ID}" \
    "$url" 2>/dev/null) || response=""

  if [[ -z "$response" ]]; then
    warn "Demo 健康检查接口不可达: $url（可能尚未部署 demo_monitor_routes.py）"
    return
  fi

  local ok
  ok=$(echo "$response" | parse_json ".ok")

  if [[ "$ok" == "true" ]]; then
    # 尝试解析更多字段
    local services_healthy
    services_healthy=$(echo "$response" | parse_json ".data.services_healthy" 2>/dev/null || echo "unknown")
    pass "Demo 健康检查通过 (services_healthy: ${services_healthy})"
  else
    local error_msg
    error_msg=$(echo "$response" | parse_json ".error.message" 2>/dev/null || echo "unknown error")
    warn "Demo 健康检查返回非 ok: $error_msg"
  fi
}

# ── 检查 4: 交付评分卡 ───────────────────────────────────────
check_delivery_scorecard() {
  print_section "检查 4/5: 交付评分卡 (Delivery Scorecard)"

  local url="${GATEWAY_URL}/api/v1/analytics/delivery-scorecard/${MERCHANT_CODE}"
  local response
  response=$(curl -sf --max-time 10 \
    -H "X-Tenant-ID: ${TENANT_ID}" \
    "$url" 2>/dev/null) || response=""

  if [[ -z "$response" ]]; then
    fail "评分卡接口不可达: $url"
    return
  fi

  local ok
  ok=$(echo "$response" | parse_json ".ok")

  if [[ "$ok" != "true" ]]; then
    fail "评分卡接口返回错误: $(echo "$response" | parse_json ".error.message")"
    return
  fi

  # 提取关键字段
  local total_score grade go_no_go demo_readiness
  total_score=$(echo "$response" | parse_json ".data.total_score" 2>/dev/null || echo "0")
  grade=$(echo "$response" | parse_json ".data.grade" 2>/dev/null || echo "N/A")
  go_no_go=$(echo "$response" | parse_json ".data.go_no_go" 2>/dev/null || echo "NO-GO")
  demo_readiness=$(echo "$response" | parse_json ".data.demo_readiness_score" 2>/dev/null || echo "0")

  echo -e "  ${BOLD}评分详情:${NC}"
  echo -e "    总分: ${BOLD}${total_score}${NC} / 100"
  echo -e "    等级: ${BOLD}${grade}${NC}"
  echo -e "    GO/NO-GO: ${BOLD}${go_no_go}${NC}"
  echo -e "    演示就绪度: ${BOLD}${demo_readiness}${NC}"

  # 设置全局 GO_NO_GO
  GO_NO_GO="$go_no_go"

  # 判断评分是否达标
  local target_score
  case "$MERCHANT_CODE" in
    czyz|zqx) target_score=90 ;;
    sgc)      target_score=85 ;;
  esac

  # 使用 python3 比较浮点数
  local score_ok
  score_ok=$(python3 -c "print('yes' if float('${total_score:-0}') >= ${target_score} else 'no')" 2>/dev/null || echo "no")

  if [[ "$score_ok" == "yes" ]]; then
    pass "总分 ${total_score} ≥ ${target_score}（目标达成）"
  else
    fail "总分 ${total_score} < ${target_score}（目标: ≥ ${target_score}）"
  fi

  if [[ "$go_no_go" == "GO" ]]; then
    pass "GO/NO-GO 判定: ${GREEN}GO${NC}"
  else
    fail "GO/NO-GO 判定: ${RED}NO-GO${NC}"
  fi
}

# ── 检查 5: 商户 KPI 配置 ────────────────────────────────────
check_merchant_kpi_config() {
  print_section "检查 5/5: 商户 KPI 配置"

  local url="${GATEWAY_URL}/api/v1/analytics/merchant-kpi/configs"
  local response
  response=$(curl -sf --max-time 10 \
    -H "X-Tenant-ID: ${TENANT_ID}" \
    "$url" 2>/dev/null) || response=""

  if [[ -z "$response" ]]; then
    warn "KPI 配置接口不可达: $url（可能尚未部署 merchant_kpi_config_routes.py）"
    return
  fi

  local ok
  ok=$(echo "$response" | parse_json ".ok")

  if [[ "$ok" != "true" ]]; then
    warn "KPI 配置接口返回错误: $(echo "$response" | parse_json ".error.message")"
    return
  fi

  # 检查是否有对应商户的配置
  local has_config
  has_config=$(echo "$response" | parse_json ".data.merchant_code" 2>/dev/null || echo "null")

  if [[ "$has_config" == "$MERCHANT_CODE" ]]; then
    pass "商户 ${MERCHANT_CODE} KPI 配置已存在"

    # 显示 KPI 摘要
    case "$MERCHANT_CODE" in
      czyz)
        local turnover
        turnover=$(echo "$response" | parse_json ".data.table_turnover_daily" 2>/dev/null || echo "N/A")
        echo -e "    翻台率目标: ${turnover}/天"
        ;;
      zqx)
        local avg_ticket
        avg_ticket=$(echo "$response" | parse_json ".data.avg_ticket_rmb" 2>/dev/null || echo "N/A")
        echo -e "    客单价目标: ¥${avg_ticket}"
        ;;
      sgc)
        local banquet_rate
        banquet_rate=$(echo "$response" | parse_json ".data.banquet_deposit_rate_pct" 2>/dev/null || echo "N/A")
        echo -e "    宴会订金率目标: ${banquet_rate}%"
        ;;
    esac
  else
    warn "未找到商户 ${MERCHANT_CODE} 的 KPI 配置（请运行 scripts/seed_${MERCHANT_CODE}.py）"
  fi
}

# ── 打印汇总 ─────────────────────────────────────────────────
print_summary() {
  echo ""
  echo -e "${BOLD}${BLUE}══════════════════════════════════════════════════════${NC}"
  echo -e "${BOLD}  检查汇总 — ${MERCHANT_NAME} (${MERCHANT_CODE})${NC}"
  echo -e "${BLUE}══════════════════════════════════════════════════════${NC}"
  echo -e "  ${GREEN}✅ 通过: ${CHECKS_PASS}${NC}"
  echo -e "  ${YELLOW}⚠️  警告: ${CHECKS_WARN}${NC}"
  echo -e "  ${RED}❌ 失败: ${CHECKS_FAIL}${NC}"
  echo ""

  if [[ $CHECKS_FAIL -eq 0 && "$GO_NO_GO" == "GO" ]]; then
    echo -e "  ${BOLD}${GREEN}🚀 最终判定: GO — ${MERCHANT_NAME} 已就绪，可部署上线${NC}"
    echo -e "${BLUE}══════════════════════════════════════════════════════${NC}"
    echo ""
    exit 0
  else
    local reasons=""
    [[ $CHECKS_FAIL -gt 0 ]] && reasons="${CHECKS_FAIL} 项检查失败"
    [[ "$GO_NO_GO" != "GO" ]] && reasons="${reasons:+$reasons, }评分卡 NO-GO"
    echo -e "  ${BOLD}${RED}🚫 最终判定: NO-GO — ${MERCHANT_NAME} 尚未就绪 (${reasons})${NC}"
    echo -e "${BLUE}══════════════════════════════════════════════════════${NC}"
    echo ""
    exit 1
  fi
}

# ── 主流程 ───────────────────────────────────────────────────
main() {
  print_header
  check_env_vars
  check_services
  check_demo_health
  check_delivery_scorecard
  check_merchant_kpi_config
  print_summary
}

main
