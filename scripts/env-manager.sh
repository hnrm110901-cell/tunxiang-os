#!/bin/bash
# ============================================================
# 屯象OS 环境管理脚本
# 版本: 1.0.0  |  最后更新: 2026-04-06
# 维护人: 李淳（屯象OS创始人）
#
# 用于手动触发环境启停（在Harness CCM接入前的过渡方案）
# 接入Harness后，此脚本可作为 AutoStopping on_shutdown_hook 调用
#
# 使用方式:
#   ./env-manager.sh start dev
#   ./env-manager.sh stop test
#   ./env-manager.sh status all
#   ./env-manager.sh status dev
#   ./env-manager.sh demo create --brand="试点品牌" --expires=7d
#   ./env-manager.sh demo destroy demo_abc
# ============================================================

set -euo pipefail

# ──────────────────────────────────────────────
# 常量定义
# ──────────────────────────────────────────────
readonly SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
readonly TUNXIANG_SERVER="42.194.229.21"
readonly COMPOSE_BASE="${REPO_ROOT}/docker-compose.yml"

# 所有合法环境列表
readonly ENVS=(dev test uat pilot prod demo)
# 受保护环境（禁止 stop）
readonly PROTECTED_ENVS=(pilot prod)

# 成本估算单价（元/小时）
declare -A ENV_COST_PER_HOUR=(
  [dev]=0.8
  [test]=0.6
  [uat]=0.5
  [pilot]=2.0
  [prod]=5.0
  [demo]=0.3
)

# ──────────────────────────────────────────────
# 颜色输出
# ──────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
BOLD='\033[1m'
RESET='\033[0m'

info()    { echo -e "${BLUE}[INFO]${RESET} $*"; }
ok()      { echo -e "${GREEN}[OK]${RESET}  $*"; }
warn()    { echo -e "${YELLOW}[WARN]${RESET} $*"; }
error()   { echo -e "${RED}[ERROR]${RESET} $*" >&2; }
fatal()   { echo -e "${RED}[FATAL]${RESET} $*" >&2; exit 1; }
header()  { echo -e "\n${BOLD}${CYAN}=== $* ===${RESET}"; }

# ──────────────────────────────────────────────
# 工具函数
# ──────────────────────────────────────────────
is_valid_env() {
  local env="$1"
  for e in "${ENVS[@]}"; do
    [[ "$e" == "$env" ]] && return 0
  done
  return 1
}

is_protected_env() {
  local env="$1"
  for e in "${PROTECTED_ENVS[@]}"; do
    [[ "$e" == "$env" ]] && return 0
  done
  return 1
}

get_compose_file() {
  local env="$1"
  case "$env" in
    prod)    echo "${REPO_ROOT}/docker-compose.prod.yml" ;;
    pilot)   echo "${REPO_ROOT}/docker-compose.staging.yml" ;;
    dev)     echo "${REPO_ROOT}/docker-compose.yml" ;;
    test)    echo "${REPO_ROOT}/docker-compose.yml" ;;
    uat)     echo "${REPO_ROOT}/docker-compose.yml" ;;
    demo)    echo "${REPO_ROOT}/docker-compose.yml" ;;
    *)       echo "${REPO_ROOT}/docker-compose.yml" ;;
  esac
}

get_env_namespace() {
  local env="$1"
  echo "tunxiang-${env}"
}

# 获取环境运行时长（秒），通过 Docker 容器启动时间估算
get_uptime_seconds() {
  local env="$1"
  local namespace
  namespace=$(get_env_namespace "$env")

  # 尝试从 Docker label 获取启动时间
  local start_time
  start_time=$(docker ps --filter "label=tunxiang.env=${env}" \
    --format "{{.CreatedAt}}" 2>/dev/null | head -1) || true

  if [[ -z "$start_time" ]]; then
    echo "0"
    return
  fi

  local start_epoch
  start_epoch=$(date -d "$start_time" +%s 2>/dev/null || date -j -f "%Y-%m-%d %H:%M:%S" "${start_time:0:19}" +%s 2>/dev/null || echo "0")
  local now_epoch
  now_epoch=$(date +%s)
  echo $((now_epoch - start_epoch))
}

# 估算运行成本
estimate_cost() {
  local env="$1"
  local uptime_seconds
  uptime_seconds=$(get_uptime_seconds "$env")
  local uptime_hours
  uptime_hours=$(echo "scale=2; $uptime_seconds / 3600" | bc 2>/dev/null || echo "0")
  local rate="${ENV_COST_PER_HOUR[$env]:-0.5}"
  local cost
  cost=$(echo "scale=2; $uptime_hours * $rate" | bc 2>/dev/null || echo "0.00")
  echo "$cost"
}

# 格式化时长显示
format_duration() {
  local seconds="$1"
  if [[ "$seconds" -le 0 ]]; then
    echo "N/A"
    return
  fi
  local hours=$((seconds / 3600))
  local minutes=$(( (seconds % 3600) / 60 ))
  echo "${hours}h ${minutes}m"
}

# ──────────────────────────────────────────────
# 命令实现
# ──────────────────────────────────────────────

cmd_start() {
  local env="${1:-}"
  [[ -z "$env" ]] && fatal "用法: $0 start <env>\n  可用环境: ${ENVS[*]}"
  is_valid_env "$env" || fatal "无效环境: $env。可用环境: ${ENVS[*]}"

  header "启动 ${env} 环境"
  info "目标环境: ${env}"

  local compose_file
  compose_file=$(get_compose_file "$env")

  # 检查 compose 文件是否存在
  if [[ ! -f "$compose_file" ]]; then
    warn "compose文件不存在: ${compose_file}，使用默认文件"
    compose_file="${COMPOSE_BASE}"
  fi

  info "使用配置文件: ${compose_file}"
  info "正在启动服务..."

  # 设置环境变量后启动
  TUNXIANG_ENV="$env" \
  TUNXIANG_NAMESPACE="$(get_env_namespace "$env")" \
    docker compose -f "$compose_file" --profile "${env}" up -d 2>&1 || {
    # 如果 profile 不存在，降级不使用 profile
    warn "profile '${env}' 不存在，尝试默认启动"
    TUNXIANG_ENV="$env" docker compose -f "$compose_file" up -d
  }

  ok "环境 ${env} 已启动"
  info "成本估算: ¥${ENV_COST_PER_HOUR[$env]:-0.5}/小时"
}

cmd_stop() {
  local env="${1:-}"
  [[ -z "$env" ]] && fatal "用法: $0 stop <env>\n  可用环境: ${ENVS[*]}"
  is_valid_env "$env" || fatal "无效环境: $env。可用环境: ${ENVS[*]}"

  # 生产/Pilot保护
  if is_protected_env "$env"; then
    fatal "🛑 禁止操作: 环境 '${env}' 是受保护的生产环境，不允许通过此脚本停止！\n  如确需操作，请通过 Harness 流水线执行并获得审批。"
  fi

  header "停止 ${env} 环境"

  # 二次确认
  local uptime
  uptime=$(get_uptime_seconds "$env")
  local cost
  cost=$(estimate_cost "$env")

  warn "即将停止环境: ${env}"
  warn "当前已运行: $(format_duration $uptime)"
  warn "本次估算成本: ¥${cost}"

  read -r -p "$(echo -e "${YELLOW}确认停止? [y/N]${RESET} ")" confirm
  if [[ ! "$confirm" =~ ^[Yy]$ ]]; then
    info "已取消操作"
    exit 0
  fi

  local compose_file
  compose_file=$(get_compose_file "$env")
  [[ ! -f "$compose_file" ]] && compose_file="${COMPOSE_BASE}"

  info "正在停止服务..."
  TUNXIANG_ENV="$env" docker compose -f "$compose_file" --profile "${env}" stop 2>/dev/null || \
    TUNXIANG_ENV="$env" docker compose -f "$compose_file" stop

  ok "环境 ${env} 已停止"
  info "总运行时长: $(format_duration $uptime)，估算费用: ¥${cost}"
}

cmd_status() {
  local target="${1:-all}"

  header "屯象OS 环境状态总览"
  printf "\n${BOLD}%-10s %-12s %-15s %-10s %-12s${RESET}\n" \
    "环境" "状态" "运行时长" "估算成本" "备注"
  printf "%s\n" "$(printf '─%.0s' {1..60})"

  local envs_to_check=()
  if [[ "$target" == "all" ]]; then
    envs_to_check=("${ENVS[@]}")
  else
    is_valid_env "$target" || fatal "无效环境: $target"
    envs_to_check=("$target")
  fi

  local total_cost=0

  for env in "${envs_to_check[@]}"; do
    # 检查 Docker 容器是否运行
    local running_count
    running_count=$(docker ps --filter "label=tunxiang.env=${env}" --filter "status=running" -q 2>/dev/null | wc -l | tr -d ' ') || running_count=0

    local status_label status_color
    if [[ "$running_count" -gt 0 ]]; then
      status_label="运行中(${running_count})"
      status_color="${GREEN}"
    else
      # 检查是否有已停止的容器
      local stopped_count
      stopped_count=$(docker ps -a --filter "label=tunxiang.env=${env}" --filter "status=exited" -q 2>/dev/null | wc -l | tr -d ' ') || stopped_count=0
      if [[ "$stopped_count" -gt 0 ]]; then
        status_label="已停止"
        status_color="${RED}"
      else
        status_label="未部署"
        status_color="${YELLOW}"
      fi
    fi

    local uptime cost
    uptime=$(get_uptime_seconds "$env")
    cost=$(estimate_cost "$env")

    local note=""
    if is_protected_env "$env"; then
      note="7x24保护"
    elif [[ "$env" == "demo" ]]; then
      note="7天TTL"
    fi

    printf "${status_color}%-10s${RESET} %-12s %-15s %-10s %-12s\n" \
      "$env" \
      "$status_label" \
      "$(format_duration $uptime)" \
      "¥${cost}" \
      "$note"

    # 累加成本（bc可能不可用时保护）
    total_cost=$(echo "$total_cost + $cost" | bc 2>/dev/null || echo "$total_cost")
  done

  printf "%s\n" "$(printf '─%.0s' {1..60})"
  printf "${BOLD}%-10s %-12s %-15s ¥%-10s${RESET}\n" "合计" "" "" "${total_cost}"
  echo ""

  # 月度成本警告
  local monthly_budget=3000
  local daily_cost
  daily_cost=$(echo "scale=2; $total_cost / 1" | bc 2>/dev/null || echo "0")
  info "本次统计周期估算总成本: ¥${total_cost}"
  info "月度预算上限: ¥${monthly_budget}"
}

cmd_demo() {
  local action="${1:-}"
  shift || true

  case "$action" in
    create)
      local brand="" expires="7d" tenant=""
      for arg in "$@"; do
        case "$arg" in
          --brand=*)  brand="${arg#*=}" ;;
          --expires=*) expires="${arg#*=}" ;;
          --tenant=*) tenant="${arg#*=}" ;;
        esac
      done

      [[ -z "$brand" ]] && fatal "用法: $0 demo create --brand='品牌名' [--expires=7d] [--tenant=demo_xxx]"

      # 自动生成 tenant ID
      if [[ -z "$tenant" ]]; then
        local slug
        slug=$(echo "$brand" | tr '[:upper:]' '[:lower:]' | sed 's/[^a-z0-9]/_/g' | head -c 20)
        tenant="demo_${slug}_$(date +%Y%m%d)"
      fi

      header "创建演示环境: ${brand}"
      info "Tenant ID: ${tenant}"
      info "品牌名称: ${brand}"
      info "有效期: ${expires}"

      # 调用专用演示环境创建脚本
      if [[ -f "${SCRIPT_DIR}/create-demo-env.sh" ]]; then
        info "调用 create-demo-env.sh..."
        bash "${SCRIPT_DIR}/create-demo-env.sh" \
          --tenant="${tenant}" \
          --brand="${brand}" \
          --expires="${expires}"
      else
        warn "create-demo-env.sh 未找到，执行基础创建流程..."
        # 基础流程：打标签启动 demo 容器
        TUNXIANG_ENV=demo \
        DEMO_TENANT="${tenant}" \
        DEMO_BRAND="${brand}" \
        DEMO_EXPIRES="${expires}" \
          docker compose -f "${REPO_ROOT}/docker-compose.yml" up -d

        ok "演示环境基础容器已启动"
        info "访问地址: http://${tenant}.demo.tunxiang.com"
        warn "请手动完成: DB schema创建、种子数据导入"
      fi

      ok "演示环境创建完成"
      info "Tenant: ${tenant}"
      info "品牌: ${brand}"
      info "到期时间: $(date -d "+${expires//d/ days}" '+%Y-%m-%d' 2>/dev/null || echo "7天后")"
      ;;

    destroy)
      local tenant="${1:-}"
      [[ -z "$tenant" ]] && fatal "用法: $0 demo destroy <tenant_id>"

      warn "即将销毁演示环境: ${tenant}"
      warn "此操作将删除 DB schema 及所有数据，不可恢复！"

      read -r -p "$(echo -e "${RED}确认销毁? 请输入 tenant ID 确认: ${RESET}")" confirm
      if [[ "$confirm" != "$tenant" ]]; then
        info "输入不匹配，已取消"
        exit 0
      fi

      header "销毁演示环境: ${tenant}"

      # 停止相关容器
      docker ps -a --filter "label=tunxiang.tenant=${tenant}" -q | \
        xargs -r docker rm -f 2>/dev/null || true

      # 清理 DB schema（调用 Python 脚本）
      if [[ -f "${SCRIPT_DIR}/../reset_demo.sh" ]]; then
        info "清理DB schema..."
        DEMO_TENANT="${tenant}" bash "${REPO_ROOT}/reset_demo.sh" || warn "DB清理可能未完全执行"
      else
        warn "未找到 reset_demo.sh，请手动清理数据库 schema: ${tenant}"
      fi

      ok "演示环境 ${tenant} 已销毁"
      ;;

    list)
      header "演示环境列表"
      docker ps -a \
        --filter "label=tunxiang.env=demo" \
        --format "table {{.Names}}\t{{.Status}}\t{{.Labels}}" 2>/dev/null || \
        warn "未找到任何演示环境容器"
      ;;

    *)
      fatal "未知 demo 子命令: $action\n  可用: create / destroy / list"
      ;;
  esac
}

# ──────────────────────────────────────────────
# 帮助信息
# ──────────────────────────────────────────────
cmd_help() {
  cat << EOF
${BOLD}屯象OS 环境管理脚本${RESET} v1.0.0

${BOLD}用法:${RESET}
  $(basename "$0") <命令> [参数]

${BOLD}命令:${RESET}
  ${GREEN}start${RESET}  <env>              启动指定环境
  ${RED}stop${RESET}   <env>              停止指定环境（prod/pilot受保护，禁止停止）
  ${CYAN}status${RESET} [env|all]          查看环境状态（默认all）
  ${YELLOW}demo${RESET}   create --brand=名称  创建演示环境
  ${YELLOW}demo${RESET}   destroy <tenant_id>  销毁演示环境
  ${YELLOW}demo${RESET}   list               列出所有演示环境
  help                       显示此帮助信息

${BOLD}可用环境:${RESET}
  dev    开发环境（工作日夜间自动停机）
  test   测试环境（周末全停）
  uat    验收环境（4小时无活动自动停）
  pilot  灰度环境（7x24保护，禁止手动停止）
  prod   生产环境（7x24保护，禁止手动停止）
  demo   演示环境（7天TTL，售前使用）

${BOLD}示例:${RESET}
  $(basename "$0") start dev
  $(basename "$0") stop test
  $(basename "$0") status all
  $(basename "$0") demo create --brand="某餐饮品牌" --expires=3d
  $(basename "$0") demo destroy demo_xxx_20260406

${BOLD}成本估算单价:${RESET}
  dev=¥0.8/h  test=¥0.6/h  uat=¥0.5/h
  pilot=¥2.0/h  prod=¥5.0/h  demo=¥0.3/h
EOF
}

# ──────────────────────────────────────────────
# 入口
# ──────────────────────────────────────────────
main() {
  local cmd="${1:-help}"
  shift || true

  case "$cmd" in
    start)   cmd_start "$@" ;;
    stop)    cmd_stop "$@" ;;
    status)  cmd_status "$@" ;;
    demo)    cmd_demo "$@" ;;
    help|-h|--help) cmd_help ;;
    *)
      error "未知命令: $cmd"
      cmd_help
      exit 1
      ;;
  esac
}

main "$@"
