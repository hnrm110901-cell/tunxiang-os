#!/usr/bin/env bash
# demo-reset.sh — 演示环境数据重置脚本 (Gap C-03)
#
# 用法：
#   ./scripts/demo-reset.sh [--merchant czyz|zqx|sgc|all] [--keep-members] [--dry-run]
#
# 功能：
#   1. 删除目标商户近 7 天（保留最近 1 小时）的订单、KDS 工单、支付记录
#   2. 重新运行种子脚本
#   3. 调用数据质量 API 验证并输出分数

set -uo pipefail

# ── 默认参数 ──────────────────────────────────────────────────────────────────────
MERCHANT="all"
KEEP_MEMBERS=true
DRY_RUN=false
DATABASE_URL="${DATABASE_URL:-postgresql://tunxiang:tunxiang_demo_2024@localhost:5432/tunxiang_os}"
ANALYTICS_BASE_URL="${ANALYTICS_BASE_URL:-http://localhost:8009}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

# ── 参数解析 ──────────────────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
    case "$1" in
        --merchant)
            MERCHANT="$2"
            shift 2
            ;;
        --keep-members)
            KEEP_MEMBERS=true
            shift
            ;;
        --no-keep-members)
            KEEP_MEMBERS=false
            shift
            ;;
        --dry-run)
            DRY_RUN=true
            shift
            ;;
        -h|--help)
            echo "用法: $0 [--merchant czyz|zqx|sgc|all] [--keep-members] [--dry-run]"
            echo ""
            echo "选项:"
            echo "  --merchant CODE   指定要重置的商户（默认: all）"
            echo "  --keep-members    保留会员数据（默认）"
            echo "  --no-keep-members 删除会员数据"
            echo "  --dry-run         只显示将要执行的操作，不实际执行"
            exit 0
            ;;
        *)
            echo "未知参数: $1" >&2
            echo "运行 $0 --help 查看用法" >&2
            exit 1
            ;;
    esac
done

# ── 验证商户代码 ───────────────────────────────────────────────────────────────────
case "$MERCHANT" in
    czyz|zqx|sgc|all)
        ;;
    *)
        echo "错误：商户代码必须是 czyz、zqx、sgc 或 all，当前值: ${MERCHANT}" >&2
        exit 1
        ;;
esac

# ── 工具检查 ───────────────────────────────────────────────────────────────────────
if ! command -v psql &>/dev/null; then
    echo "错误：未找到 psql 命令，请先安装 PostgreSQL 客户端工具" >&2
    exit 1
fi

if ! command -v curl &>/dev/null; then
    echo "警告：未找到 curl 命令，将跳过数据质量验证步骤"
    SKIP_VERIFY=true
else
    SKIP_VERIFY=false
fi

# ── 辅助函数 ───────────────────────────────────────────────────────────────────────
log_info()  { echo "[INFO]  $*"; }
log_ok()    { echo "[OK]    $*"; }
log_warn()  { echo "[WARN]  $*"; }
log_error() { echo "[ERROR] $*" >&2; }

run_sql() {
    local sql="$1"
    local description="$2"
    if [[ "$DRY_RUN" == "true" ]]; then
        log_info "[DRY-RUN] 将执行 SQL: ${description}"
        log_info "SQL: ${sql}"
        return 0
    fi
    if psql "${DATABASE_URL}" -c "${sql}" 2>&1; then
        log_ok "${description}"
    else
        log_warn "${description} — 执行失败（可能表不存在，已跳过）"
    fi
}

reset_merchant() {
    local code="$1"
    local tenant_id="${code}-demo-tenant"

    log_info "开始重置商户: ${code}（租户: ${tenant_id}）"
    echo "──────────────────────────────────────────"

    # 1. 删除近 7 天（保留最近 1 小时）的订单
    run_sql \
        "DELETE FROM orders WHERE tenant_id = '${tenant_id}' AND created_at > NOW() - INTERVAL '7 days' AND created_at < NOW() - INTERVAL '1 hour';" \
        "${code}: 清理近7天订单（保留最近1小时）"

    # 2. 删除 KDS 工单
    run_sql \
        "DELETE FROM kds_tickets WHERE tenant_id = '${tenant_id}' AND created_at > NOW() - INTERVAL '7 days';" \
        "${code}: 清理近7天KDS工单"

    # 3. 删除支付记录
    run_sql \
        "DELETE FROM payment_records WHERE tenant_id = '${tenant_id}' AND created_at > NOW() - INTERVAL '7 days' AND created_at < NOW() - INTERVAL '1 hour';" \
        "${code}: 清理近7天支付记录"

    # 4. 删除会员数据（仅当 --no-keep-members 时）
    if [[ "$KEEP_MEMBERS" == "false" ]]; then
        run_sql \
            "DELETE FROM members WHERE tenant_id = '${tenant_id}';" \
            "${code}: 清理会员数据"
    else
        log_info "${code}: 保留会员数据（--keep-members）"
    fi

    # 5. 重新运行种子脚本
    local seed_script="${PROJECT_ROOT}/scripts/seed_${code}.py"
    if [[ -f "$seed_script" ]]; then
        if [[ "$DRY_RUN" == "true" ]]; then
            log_info "[DRY-RUN] 将运行种子脚本: ${seed_script}"
        else
            log_info "${code}: 运行种子脚本 ${seed_script}"
            if python3 "${seed_script}" 2>&1; then
                log_ok "${code}: 种子脚本执行完成"
            else
                log_warn "${code}: 种子脚本执行失败（已跳过）"
            fi
        fi
    else
        log_warn "${code}: 种子脚本不存在（${seed_script}），已跳过"
    fi

    # 6. 验证数据质量
    if [[ "$SKIP_VERIFY" == "true" || "$DRY_RUN" == "true" ]]; then
        if [[ "$DRY_RUN" == "true" ]]; then
            log_info "[DRY-RUN] 将调用: GET ${ANALYTICS_BASE_URL}/api/v1/analytics/data-quality/${code}"
        fi
    else
        log_info "${code}: 验证数据质量..."
        local quality_response
        quality_response=$(curl -s --max-time 10 \
            "${ANALYTICS_BASE_URL}/api/v1/analytics/data-quality/${code}" 2>/dev/null || echo "")

        if [[ -n "$quality_response" ]]; then
            # 尝试解析 total_score（依赖 python3 json 模块）
            local score
            score=$(python3 -c "
import json, sys
try:
    data = json.loads(sys.stdin.read())
    print(data.get('data', {}).get('total_score', 'N/A'))
except Exception:
    print('N/A')
" <<< "$quality_response" 2>/dev/null || echo "N/A")
            echo "✅ ${code} 演示环境重置完成 — 数据质量分: ${score}"
        else
            log_warn "${code}: 无法连接到 Analytics 服务（${ANALYTICS_BASE_URL}），跳过质量验证"
            echo "✅ ${code} 演示环境重置完成 — 数据质量分: (验证服务不可用)"
        fi
    fi

    echo ""
}

# ── 主逻辑 ────────────────────────────────────────────────────────────────────────
echo "════════════════════════════════════════════"
echo "  屯象OS 演示环境重置"
echo "  商户: ${MERCHANT} | 保留会员: ${KEEP_MEMBERS} | 演练模式: ${DRY_RUN}"
echo "  数据库: ${DATABASE_URL}"
echo "════════════════════════════════════════════"
echo ""

if [[ "$MERCHANT" == "all" ]]; then
    for code in czyz zqx sgc; do
        reset_merchant "$code"
    done
else
    reset_merchant "$MERCHANT"
fi

echo "════════════════════════════════════════════"
if [[ "$DRY_RUN" == "true" ]]; then
    echo "  [DRY-RUN] 演练完成，未执行任何实际操作"
else
    echo "  演示环境重置完成"
fi
echo "════════════════════════════════════════════"
