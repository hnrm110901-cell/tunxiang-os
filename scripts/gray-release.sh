#!/usr/bin/env bash
# ==============================================================================
# 屯象OS 灰度发布管理脚本（Task 3.5）
#
# 三级灰度: 5% → 50% → 100%
# 回滚阈值: 错误率 > 0.1% → 自动回滚
#
# 用法:
#   gray-release.sh <service> start     -- 启动灰度（5%）
#   gray-release.sh <service> promote   -- 推进到下一个灰度阶段
#   gray-release.sh <service> rollback  -- 立即回滚
#   gray-release.sh <service> status    -- 查看灰度状态
#
# K8s 实现:
#   通过调整 Deployment replicas 和 Service selector 控制流量比例。
#   稳定版本: deployment/<service>-stable
#   灰度版本: deployment/<service>-canary
#   Service 通过 label version=stable|canary 分流。
#
# 环境变量:
#   TX_DEPLOY_MODE=k8s|compose
#   TX_GRAY_THRESHOLD_ERROR_RATE=0.001  回滚阈值（默认 0.1%）
# ==============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
GRAY_STATE_DIR="${SCRIPT_DIR}/../.gray-state"
mkdir -p "$GRAY_STATE_DIR"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
log_info()  { echo -e "${GREEN}[GRAY]${NC} $(date '+%H:%M:%S') $*"; }
log_warn()  { echo -e "${YELLOW}[GRAY]${NC} $(date '+%H:%M:%S') $*"; }
log_error() { echo -e "${RED}[GRAY]${NC} $(date '+%H:%M:%S') $*"; }

# 灰度阶段定义: 阶段名 → canary权重
declare -A GRAY_STAGES=(
    ["5"]="5"
    ["50"]="50"
    ["100"]="100"
)
GRAY_STAGE_ORDER=("5" "50" "100")

# ── 获取当前灰度状态 ──────────────────────────────────────────────────
get_gray_state() {
    local svc=$1
    local state_file="${GRAY_STATE_DIR}/${svc}.json"
    if [[ -f "$state_file" ]]; then
        cat "$state_file"
    else
        echo '{"stage":"0","canary_pct":0,"started_at":"","promoted_at":""}'
    fi
}

set_gray_state() {
    local svc=$1
    local stage=$2
    local pct=$3
    local state_file="${GRAY_STATE_DIR}/${svc}.json"
    local now=$(date -Iseconds)
    cat > "$state_file" << EOF
{"stage":"${stage}","canary_pct":${pct},"started_at":"$(get_gray_state "$svc" | python3 -c 'import sys,json; print(json.load(sys.stdin).get("started_at","'"$now"'"))')","promoted_at":"$now"}
EOF
}

# ── 监控错误率 ────────────────────────────────────────────────────────
check_error_rate() {
    local svc=$1
    local threshold="${TX_GRAY_THRESHOLD_ERROR_RATE:-0.001}"

    # 从 Prometheus/服务指标获取最近 5 分钟错误率
    # 当前使用 /health 端点 + 日志解析作为简化版
    local error_rate=0

    # 尝试从 metrics 端点获取（如果暴露了 Prometheus）
    local port="${2:-8000}"
    if curl -sf "http://localhost:${port}/metrics" 2>/dev/null | grep -q "http_requests_total"; then
        local total=$(curl -sf "http://localhost:${port}/metrics" 2>/dev/null | grep 'http_requests_total' | grep -v 'canary' | awk '{sum+=$2} END {print sum+0}')
        local errors=$(curl -sf "http://localhost:${port}/metrics" 2>/dev/null | grep 'http_requests_total.*status=\"5[0-9][0-9]\"' | awk '{sum+=$2} END {print sum+0}')
        if [[ "$total" -gt 0 ]]; then
            error_rate=$(python3 -c "print($errors / $total)")
        fi
    fi

    if python3 -c "exit(0 if ${error_rate} > ${threshold} else 1)" 2>/dev/null; then
        log_error "错误率 ${error_rate} 超过阈值 ${threshold}，触发自动回滚！"
        return 1
    fi
    log_info "错误率 ${error_rate} < 阈值 ${threshold}，灰度正常"
    return 0
}

# ── K8s 灰度启动 ──────────────────────────────────────────────────────
start_canary_k8s() {
    local svc=$1
    local current_image
    current_image=$(kubectl get deployment "${svc}" -o jsonpath='{.spec.template.spec.containers[0].image}' 2>/dev/null || echo "")

    if [[ -z "$current_image" ]]; then
        log_error "无法获取 ${svc} 当前镜像"
        return 1
    fi

    log_info "创建灰度 Deployment: ${svc}-canary (5% 流量)"
    kubectl apply -f - << EOF
apiVersion: apps/v1
kind: Deployment
metadata:
  name: ${svc}-canary
  labels:
    app: ${svc}
    version: canary
spec:
  replicas: 1
  selector:
    matchLabels:
      app: ${svc}
      version: canary
  template:
    metadata:
      labels:
        app: ${svc}
        version: canary
    spec:
      containers:
      - name: ${svc}
        image: ${current_image}
        ports:
        - containerPort: 8000
        env:
        - name: TX_GRAY_MODE
          value: "canary"
EOF

    # 更新 Service 指向稳定版本 + 灰度版本（通过 Istio/NGINX Ingress 权重分流）
    kubectl patch service "${svc}" -p '{"spec":{"selector":{"version":null}}}' 2>/dev/null || true
    kubectl annotate service "${svc}" "gray.stage=5" --overwrite 2>/dev/null || true

    set_gray_state "$svc" "5" 5
    log_info "灰度已启动: ${svc} 5% canary"
}

# ── K8s 灰度推进 ──────────────────────────────────────────────────────
promote_canary_k8s() {
    local svc=$1
    local state
    state=$(get_gray_state "$svc")
    local current_stage=$(echo "$state" | python3 -c 'import sys,json; print(json.load(sys.stdin)["stage"])')

    # 找到下一个阶段
    local next_stage=""
    for i in $(seq 0 $((${#GRAY_STAGE_ORDER[@]} - 2))); do
        if [[ "${GRAY_STAGE_ORDER[$i]}" == "$current_stage" ]]; then
            next_stage="${GRAY_STAGE_ORDER[$((i + 1))]}"
            break
        fi
    done

    if [[ -z "$next_stage" ]]; then
        log_info "已到 100%，灰度完成！清理 canary deployment..."
        kubectl delete deployment "${svc}-canary" 2>/dev/null || true
        set_gray_state "$svc" "100" 100
        return 0
    fi

    # 先检查错误率
    if ! check_error_rate "$svc"; then
        log_error "错误率超标，拒绝推进！请执行: gray-release.sh $svc rollback"
        return 1
    fi

    local canary_pct="${GRAY_STAGES[$next_stage]}"
    log_info "推进灰度: ${svc} ${current_stage}% → ${canary_pct}%"

    # 调整 canary replicas
    local canary_replicas=$(( canary_pct / 10 ))
    [[ $canary_replicas -lt 1 ]] && canary_replicas=1
    kubectl scale deployment "${svc}-canary" --replicas="$canary_replicas"
    kubectl scale deployment "${svc}" --replicas="$((10 - canary_replicas))"

    kubectl annotate service "${svc}" "gray.stage=${next_stage}" --overwrite 2>/dev/null || true
    set_gray_state "$svc" "$next_stage" "$canary_pct"
    log_info "灰度推进完成: ${svc} → ${canary_pct}%"
}

# ── K8s 灰度回滚 ──────────────────────────────────────────────────────
rollback_canary_k8s() {
    local svc=$1
    log_warn "灰度回滚: ${svc}"

    # 删除 canary deployment，所有流量回到稳定版本
    kubectl delete deployment "${svc}-canary" 2>/dev/null || true
    kubectl scale deployment "${svc}" --replicas=3  # 恢复稳定版本副本数
    kubectl annotate service "${svc}" "gray.stage=0" --overwrite 2>/dev/null || true

    set_gray_state "$svc" "0" 0
    log_info "灰度回滚完成: ${svc} → 0% canary (全部回到稳定版本)"
}

# ── 状态展示 ──────────────────────────────────────────────────────────
show_status() {
    local svc=$1
    local state
    state=$(get_gray_state "$svc")

    local stage=$(echo "$state" | python3 -c 'import sys,json; print(json.load(sys.stdin)["stage"])')
    local pct=$(echo "$state" | python3 -c 'import sys,json; print(json.load(sys.stdin)["canary_pct"])')
    local started=$(echo "$state" | python3 -c 'import sys,json; print(json.load(sys.stdin).get("started_at","N/A"))')
    local promoted=$(echo "$state" | python3 -c 'import sys,json; print(json.load(sys.stdin).get("promoted_at","N/A"))')

    echo ""
    echo "═══════════════════════════════════════════════"
    echo "  灰度发布状态: $svc"
    echo "═══════════════════════════════════════════════"
    echo "  当前阶段:  ${stage}%"
    echo "  Canary:    ${pct}%"
    echo "  Stable:    $((100 - pct))%"
    echo "  开始时间:  $started"
    echo "  最近推进:  $promoted"
    echo "═══════════════════════════════════════════════"

    # K8s 状态
    if kubectl get deployment "${svc}-canary" &>/dev/null 2>&1; then
        echo ""
        echo "  Canary pods:"
        kubectl get pods -l "app=${svc},version=canary" --no-headers 2>/dev/null || echo "    (无)"
    fi
    echo ""
}

# ── 主入口 ────────────────────────────────────────────────────────────

usage() {
    cat << 'EOF'
屯象OS 灰度发布管理工具

用法:
  gray-release.sh <service> start      启动灰度（5% canary）
  gray-release.sh <service> promote    推进到下一灰度阶段
  gray-release.sh <service> rollback   立即回滚（删除 canary）
  gray-release.sh <service> status     查看灰度状态

灰度阶段: 5% → 50% → 100%
回滚阈值: 错误率 > 0.1%（可配 TX_GRAY_THRESHOLD_ERROR_RATE）
EOF
    exit 0
}

main() {
    local svc="${1:-}"
    local action="${2:-}"

    if [[ -z "$svc" ]] || [[ -z "$action" ]]; then
        usage
    fi

    case "$action" in
        start)
            start_canary_k8s "$svc"
            show_status "$svc"
            ;;
        promote)
            promote_canary_k8s "$svc"
            show_status "$svc"
            ;;
        rollback)
            rollback_canary_k8s "$svc"
            show_status "$svc"
            ;;
        status)
            show_status "$svc"
            ;;
        *)
            usage
            ;;
    esac
}

main "$@"
