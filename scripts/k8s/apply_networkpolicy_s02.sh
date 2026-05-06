#!/usr/bin/env bash
# ======================================================================
# 应用 S-02 cutover NetworkPolicy 到 21 tx-* charts + api-gateway
# ======================================================================
#
# 用法：
#   bash scripts/k8s/apply_networkpolicy_s02.sh <env> [--dry-run]
#
# 参数：
#   env       — staging / production / gray
#   --dry-run — 仅 helm template 不真应用（推荐先跑）
#
# 前置：
#   1. kubectl context 已切到目标集群
#   2. namespace 已 label：
#      kubectl label ns tunxiang-gateway kubernetes.io/metadata.name=tunxiang-gateway
#      kubectl label ns tunxiang-services kubernetes.io/metadata.name=tunxiang-services
#      kubectl label ns tunxiang-data kubernetes.io/metadata.name=tunxiang-data
#      kubectl label ns monitoring kubernetes.io/metadata.name=monitoring
#   3. 服务依赖见 docs/infra/service-dependency-graph.md
#   4. cutover playbook 阶段 A 准备完成（docs/runbooks/audit-2026-05-cutover.md）
#
# 回滚：
#   kubectl delete networkpolicy --all -n tunxiang-services
#   kubectl delete networkpolicy --all -n tunxiang-gateway
#   或 helm rollback <chart>
# ======================================================================

set -euo pipefail

ENV="${1:-}"
DRY_RUN="${2:-}"

if [ -z "$ENV" ]; then
    echo "用法: $0 <env> [--dry-run]"
    echo "env: staging / production / gray"
    exit 1
fi

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
HELM_DIR="$REPO_ROOT/infra/helm"
OVERRIDE_TX="$HELM_DIR/_overrides/networkpolicy-s02-cutover.yaml"
OVERRIDE_GW="$HELM_DIR/_overrides/networkpolicy-s02-gateway.yaml"

if [ ! -f "$OVERRIDE_TX" ] || [ ! -f "$OVERRIDE_GW" ]; then
    echo "::error::override values 文件不存在"
    exit 2
fi

# tx-* 服务（按 helm chart 名）
TX_SERVICES=(
    tx-trade tx-pay tx-menu tx-member tx-growth tx-ops
    tx-supply tx-finance tx-agent tx-analytics tx-brain
    tx-intel tx-org tx-civic tx-forge tx-devforge
    tx-expense tx-predict
)

# 单独处理的特殊 chart（如 mcp-server / tx-indonesia 等没有 helm chart 的）
SPECIAL_CHARTS=(
    api-gateway
)

echo "=== 应用 NetworkPolicy 到环境: $ENV (dry-run=$DRY_RUN) ==="

apply_one() {
    local chart=$1
    local override=$2
    local chart_dir="$HELM_DIR/$chart"

    if [ ! -d "$chart_dir" ]; then
        echo "::warning::$chart helm chart 不存在 ($chart_dir)"
        return
    fi

    if [ "$DRY_RUN" = "--dry-run" ]; then
        echo "--- $chart (dry-run) ---"
        helm template "$chart" "$chart_dir" \
            -f "$chart_dir/values.yaml" \
            -f "$override" \
            --show-only templates/networkpolicy.yaml \
            2>&1 | head -80
        echo ""
    else
        echo "--- $chart upgrade ---"
        helm upgrade --install "$chart" "$chart_dir" \
            -f "$chart_dir/values.yaml" \
            -f "$override" \
            --namespace tunxiang-services \
            --wait --timeout 5m
    fi
}

# api-gateway 特殊
echo ""
echo "=== api-gateway ==="
if [ "$DRY_RUN" = "--dry-run" ]; then
    helm template api-gateway "$HELM_DIR/api-gateway" \
        -f "$HELM_DIR/api-gateway/values.yaml" \
        -f "$OVERRIDE_GW" \
        --show-only templates/networkpolicy.yaml \
        2>&1 | head -80
else
    helm upgrade --install api-gateway "$HELM_DIR/api-gateway" \
        -f "$HELM_DIR/api-gateway/values.yaml" \
        -f "$OVERRIDE_GW" \
        --namespace tunxiang-gateway \
        --wait --timeout 5m
fi

# 21 个 tx-* services
for chart in "${TX_SERVICES[@]}"; do
    apply_one "$chart" "$OVERRIDE_TX"
done

echo ""
echo "=== 完成。下一步 ==="
echo "1. kubectl get networkpolicies -A"
echo "2. 监控 24h：tx-trade /metrics + 5xx 告警"
echo "3. 任何业务回归立刻：kubectl delete networkpolicy --all -n tunxiang-services"
