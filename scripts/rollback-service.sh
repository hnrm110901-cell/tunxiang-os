#!/usr/bin/env bash
# ==============================================================================
# 屯象OS 服务版本回滚脚本（Task 3.5）
#
# 用法：
#   ./scripts/rollback-service.sh <service_name> [target_version]
#
# 示例：
#   ./scripts/rollback-service.sh tx-trade            # 回滚到上一个部署版本
#   ./scripts/rollback-service.sh tx-finance v4.0.0   # 回滚到指定版本
#   ./scripts/rollback-service.sh --list              # 列出所有服务的可回滚版本
#   ./scripts/rollback-service.sh --dry-run tx-pay    # 预览将执行的回滚操作
#
# 依赖：
#   - kubectl（K8s 部署）或 docker-compose（本地部署）
#   - git（获取版本历史）
#
# 安全机制：
#   - 回滚前备份当前版本信息
#   - 回滚后执行健康检查
#   - 生产环境需人工二次确认
# ==============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
ROLLBACK_LOG_DIR="${PROJECT_ROOT}/logs/rollbacks"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)

# 服务列表（名称 → 端口）
declare -A SERVICE_PORTS=(
    ["gateway"]="8000"
    ["tx-trade"]="8001"
    ["tx-menu"]="8002"
    ["tx-member"]="8003"
    ["tx-growth"]="8004"
    ["tx-ops"]="8005"
    ["tx-supply"]="8006"
    ["tx-finance"]="8007"
    ["tx-agent"]="8008"
    ["tx-analytics"]="8009"
    ["tx-brain"]="8010"
    ["tx-intel"]="8011"
    ["tx-org"]="8012"
    ["tx-pay"]="8016"
    ["tx-civic"]="8014"
    ["tx-devforge"]="8017"
)

# ── 颜色 ──────────────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log_info()  { echo -e "${GREEN}[INFO]${NC}  $(date '+%H:%M:%S') $*"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC}  $(date '+%H:%M:%S') $*"; }
log_error() { echo -e "${RED}[ERROR]${NC} $(date '+%H:%M:%S') $*"; }

# ── 帮助 ──────────────────────────────────────────────────────────────
usage() {
    cat << 'EOF'
屯象OS 服务版本回滚工具

用法:
  rollback-service.sh <service> [version]    回滚服务到指定版本
  rollback-service.sh --list                 列出所有服务的可回滚版本
  rollback-service.sh --dry-run <service>    预览回滚操作
  rollback-service.sh --health <service>     仅执行健康检查

环境变量:
  TX_DEPLOY_MODE=k8s|compose   部署模式（默认: auto 自动检测）
  TX_AUTO_CONFIRM=true         跳过人工确认（仅限预发/测试环境）
EOF
    exit 0
}

# ── 检测部署模式 ──────────────────────────────────────────────────────
detect_mode() {
    if kubectl get ns &>/dev/null 2>&1; then
        echo "k8s"
    elif docker compose version &>/dev/null 2>&1; then
        echo "compose"
    else
        echo "unknown"
    fi
}

# ── 备份当前状态 ──────────────────────────────────────────────────────
backup_current_state() {
    local svc=$1
    mkdir -p "$ROLLBACK_LOG_DIR"
    local backup_file="${ROLLBACK_LOG_DIR}/${svc}_${TIMESTAMP}.json"

    case "${TX_DEPLOY_MODE:-$(detect_mode)}" in
        k8s)
            kubectl get deployment "${svc}" -o json > "$backup_file" 2>/dev/null || true
            kubectl get svc "${svc}" -o json >> "$backup_file" 2>/dev/null || true
            ;;
        compose)
            docker compose -f "${PROJECT_ROOT}/infra/docker/docker-compose.yml" ps "${svc}" > "$backup_file" 2>/dev/null || true
            ;;
    esac
    log_info "当前状态已备份到 $backup_file"
}

# ── K8s 回滚 ──────────────────────────────────────────────────────────
rollback_k8s() {
    local svc=$1
    local target=${2:-}

    if [[ -n "$target" ]]; then
        log_info "K8s 回滚 $svc → 版本 $target"
        kubectl set image "deployment/${svc}" "${svc}=${target}"
    else
        log_info "K8s 回滚 $svc → 上一个版本"
        kubectl rollout undo "deployment/${svc}"
    fi

    # 等待回滚完成
    kubectl rollout status "deployment/${svc}" --timeout=120s
}

# ── Docker Compose 回滚 ───────────────────────────────────────────────
rollback_compose() {
    local svc=$1
    local target=${2:-}

    local compose_file="${PROJECT_ROOT}/infra/docker/docker-compose.yml"
    local image_tag="${target:-latest}"

    log_info "Compose 回滚 $svc → 镜像标签 $image_tag"

    # 检查是否有带版本标签的镜像
    if docker images "tunxiang/${svc}:${image_tag}" --format '{{.Repository}}:{{.Tag}}' | grep -q .; then
        TAG="${image_tag}" docker compose -f "$compose_file" up -d --no-deps "${svc}"
    else
        log_error "镜像 tunxiang/${svc}:${image_tag} 不存在"
        log_info "可用镜像："
        docker images "tunxiang/${svc}" --format '  {{.Tag}}' || echo "  (无)"
        return 1
    fi
}

# ── 健康检查 ──────────────────────────────────────────────────────────
health_check() {
    local svc=$1
    local port="${SERVICE_PORTS[$svc]:-}"
    local max_retries=12
    local retry=0

    if [[ -z "$port" ]]; then
        log_warn "$svc 未配置端口，跳过 HTTP 健康检查"
        return 0
    fi

    local health_url="http://localhost:${port}/health"

    while [[ $retry -lt $max_retries ]]; do
        if curl -sf "$health_url" >/dev/null 2>&1; then
            local resp=$(curl -s "$health_url" 2>/dev/null)
            log_info "$svc 健康检查通过 (${retry}s): $resp"
            return 0
        fi
        sleep 2
        ((retry+=2))
    done

    log_error "$svc 健康检查失败: $health_url 在 ${max_retries}s 内未响应"
    return 1
}

# ── 迁移回滚 ──────────────────────────────────────────────────────────
rollback_migration() {
    local svc=$1
    local target_version=${2:-}

    log_info "检查数据库迁移..."

    # Alembic 迁移回滚（需指定版本号）
    if [[ -n "$target_version" ]]; then
        log_warn "迁移回滚需手动执行: alembic downgrade $target_version"
        log_info "当前迁移版本:"
        alembic current 2>/dev/null || echo "  (alembic 不可用，请在服务容器内执行)"
    fi
}

# ── 列出可回滚版本 ────────────────────────────────────────────────────
list_versions() {
    local mode="${TX_DEPLOY_MODE:-$(detect_mode)}"

    echo "部署模式: $mode"
    echo ""
    echo "服务              端口    可回滚版本"
    echo "────────────────────────────────────────────"

    for svc in $(echo "${!SERVICE_PORTS[@]}" | tr ' ' '\n' | sort); do
        local port="${SERVICE_PORTS[$svc]}"

        case "$mode" in
            k8s)
                local current=$(kubectl get deployment "$svc" -o jsonpath='{.spec.template.spec.containers[0].image}' 2>/dev/null || echo "N/A")
                local history=$(kubectl rollout history "deployment/${svc}" 2>/dev/null | wc -l || echo "0")
                printf "%-18s %-7s %s (history: %s revisions)\n" "$svc" "$port" "$current" "$((history - 1))"
                ;;
            compose)
                local images=$(docker images "tunxiang/${svc}" --format '{{.Tag}}' 2>/dev/null | head -3 | tr '\n' ' ')
                printf "%-18s %-7s %s\n" "$svc" "$port" "${images:-无本地镜像}"
                ;;
        esac
    done
}

# ── 主流程 ────────────────────────────────────────────────────────────
main() {
    local dry_run=false
    local health_only=false

    # 解析参数
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --help|-h) usage ;;
            --list) list_versions; exit 0 ;;
            --dry-run) dry_run=true; shift ;;
            --health) health_only=true; shift ;;
            *)
                local service_name="$1"
                local target_version="${2:-}"
                break
                ;;
        esac
    done

    if [[ -z "${service_name:-}" ]]; then
        usage
    fi

    # 验证服务名
    if [[ -z "${SERVICE_PORTS[$service_name]:-}" ]]; then
        log_error "未知服务: $service_name"
        echo "可用服务: ${!SERVICE_PORTS[*]}"
        exit 1
    fi

    # 仅健康检查模式
    if $health_only; then
        health_check "$service_name"
        exit $?
    fi

    # 生产环境二次确认
    local env="${TX_ENV:-development}"
    if [[ "$env" == "production" ]] && [[ "${TX_AUTO_CONFIRM:-}" != "true" ]]; then
        echo ""
        log_warn "══════════════════════════════════════════════════════"
        log_warn "  生产环境回滚确认"
        log_warn "  服务: $service_name"
        log_warn "  目标版本: ${target_version:-上一个版本}"
        log_warn "══════════════════════════════════════════════════════"
        read -r -p "输入 'ROLLBACK' 确认: " confirm
        if [[ "$confirm" != "ROLLBACK" ]]; then
            log_info "回滚已取消"
            exit 0
        fi
    fi

    # 备份当前状态
    backup_current_state "$service_name"

    if $dry_run; then
        log_info "[DRY RUN] 将回滚 $service_name → ${target_version:-上一个版本}"
        log_info "[DRY RUN] 部署模式: ${TX_DEPLOY_MODE:-$(detect_mode)}"
        exit 0
    fi

    # 执行回滚
    local mode="${TX_DEPLOY_MODE:-$(detect_mode)}"
    case "$mode" in
        k8s)
            rollback_k8s "$service_name" "$target_version"
            ;;
        compose)
            rollback_compose "$service_name" "$target_version"
            ;;
        *)
            log_error "无法检测部署模式 (k8s/compose)。设置 TX_DEPLOY_MODE 环境变量。"
            exit 1
            ;;
    esac

    # 健康检查
    sleep 3
    if ! health_check "$service_name"; then
        log_error "回滚后健康检查失败！请检查服务状态。"
        log_info "恢复建议: kubectl describe deployment/${service_name}"
        exit 1
    fi

    log_info "回滚完成: $service_name → ${target_version:-上一个版本}"
    log_info "回滚日志: ${ROLLBACK_LOG_DIR}/${service_name}_${TIMESTAMP}.json"
}

main "$@"
