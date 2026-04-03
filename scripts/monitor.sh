#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────
# 屯象OS 最低成本监控脚本
# 用法:
#   ./scripts/monitor.sh              # 一次性检查
#   ./scripts/monitor.sh install      # 安装到 crontab（每5分钟运行）
#   ./scripts/monitor.sh uninstall    # 从 crontab 移除
#
# 告警方式: 写入日志 + 可选企业微信/飞书 webhook
# ─────────────────────────────────────────────────────────
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
LOG_DIR="$PROJECT_ROOT/logs"
ALERT_LOG="$LOG_DIR/monitor-alerts.log"
CHECK_LOG="$LOG_DIR/monitor-checks.log"

mkdir -p "$LOG_DIR"

# ─── 配置 ───
# 健康检查端点
PROD_HEALTH_URL="${PROD_HEALTH_URL:-http://localhost/health}"
STG_HEALTH_URL="${STG_HEALTH_URL:-http://localhost:8080/health}"

# 数据库连接
DB_URL="${DATABASE_URL:-postgresql://tunxiang:changeme_dev@localhost/tunxiang_os}"
DB_URL="${DB_URL/postgresql+asyncpg:\/\//postgresql:\/\/}"

# 告警 webhook（企业微信/飞书，留空则只写日志）
ALERT_WEBHOOK="${ALERT_WEBHOOK:-}"

# 阈值
ORDER_MIN_5MIN="${ORDER_MIN_5MIN:-0}"       # 营业时段5分钟最低订单数（0=不检查）
ERROR_THRESHOLD="${ERROR_THRESHOLD:-10}"     # 5分钟内错误日志上限
DISK_THRESHOLD="${DISK_THRESHOLD:-85}"       # 磁盘使用率告警阈值（%）

NOW=$(date '+%Y-%m-%d %H:%M:%S')
HOUR=$(date '+%H')
ALERTS=()

# ─── 工具函数 ───
alert() {
    local level="$1" msg="$2"
    ALERTS+=("[$level] $msg")
    echo "$NOW | $level | $msg" >> "$ALERT_LOG"
}

send_webhook() {
    [[ -z "$ALERT_WEBHOOK" ]] && return
    local text="${ALERTS[*]}"
    curl -sf -X POST "$ALERT_WEBHOOK" \
        -H "Content-Type: application/json" \
        -d "{\"msgtype\":\"text\",\"text\":{\"content\":\"[屯象OS监控] $NOW\n$text\"}}" \
        &>/dev/null || true
}

# ─── 检查1: 服务健康 ───
check_health() {
    # 生产环境
    if curl -sf "$PROD_HEALTH_URL" --max-time 5 &>/dev/null; then
        echo "$NOW | OK | prod gateway healthy" >> "$CHECK_LOG"
    else
        alert "CRITICAL" "生产环境 Gateway 不可达: $PROD_HEALTH_URL"
    fi

    # Staging（如果在运行）
    if curl -sf "$STG_HEALTH_URL" --max-time 5 &>/dev/null; then
        echo "$NOW | OK | staging gateway healthy" >> "$CHECK_LOG"
    fi

    # 检查各容器状态
    local unhealthy
    unhealthy=$(docker ps --filter "health=unhealthy" --format "{{.Names}}" 2>/dev/null || true)
    if [[ -n "$unhealthy" ]]; then
        alert "WARNING" "容器健康检查失败: $unhealthy"
    fi

    # 检查是否有意外停止的容器
    local exited
    exited=$(docker ps -a --filter "status=exited" --filter "label=com.docker.compose.project" \
        --format "{{.Names}} (退出码:{{.Status}})" 2>/dev/null | head -5 || true)
    if [[ -n "$exited" ]]; then
        alert "WARNING" "容器已退出: $exited"
    fi
}

# ─── 检查2: 订单量异常检测（营业时段） ───
check_orders() {
    # 只在营业时段检查（09:00-23:00）
    if [[ "$HOUR" -lt 9 || "$HOUR" -ge 23 ]]; then
        return
    fi

    if ! command -v psql &>/dev/null; then
        return
    fi

    local count
    count=$(psql "$DB_URL" -t -A -c \
        "SELECT count(*) FROM orders WHERE created_at > now() - interval '5 minutes'" \
        2>/dev/null || echo "-1")

    if [[ "$count" == "-1" ]]; then
        alert "WARNING" "无法查询订单表（数据库连接问题）"
        return
    fi

    echo "$NOW | OK | 最近5分钟订单数: $count" >> "$CHECK_LOG"

    if [[ "$ORDER_MIN_5MIN" -gt 0 && "$count" -lt "$ORDER_MIN_5MIN" ]]; then
        alert "WARNING" "订单量异常低: 最近5分钟仅 $count 单（阈值: $ORDER_MIN_5MIN）"
    fi

    # 检查最近5分钟有没有大额退款
    local refund_count
    refund_count=$(psql "$DB_URL" -t -A -c \
        "SELECT count(*) FROM orders WHERE status = 'refunded' AND updated_at > now() - interval '5 minutes'" \
        2>/dev/null || echo "0")

    if [[ "$refund_count" -gt 5 ]]; then
        alert "WARNING" "异常退款: 最近5分钟 $refund_count 笔退款"
    fi
}

# ─── 检查3: 磁盘空间 ───
check_disk() {
    local usage
    usage=$(df -h / | awk 'NR==2 {gsub(/%/,""); print $5}')

    if [[ "$usage" -gt "$DISK_THRESHOLD" ]]; then
        alert "WARNING" "磁盘使用率: ${usage}%（阈值: ${DISK_THRESHOLD}%）"
    fi

    # PostgreSQL 数据目录
    local pg_size
    pg_size=$(docker exec "$(docker ps -q --filter 'name=postgres' | head -1)" \
        du -sh /var/lib/postgresql/data 2>/dev/null | cut -f1 || echo "unknown")
    echo "$NOW | OK | PG数据目录: $pg_size, 磁盘: ${usage}%" >> "$CHECK_LOG"
}

# ─── 检查4: Docker 日志错误 ───
check_errors() {
    local error_count=0
    local services
    services=$(docker ps --format "{{.Names}}" --filter "label=com.docker.compose.project" 2>/dev/null || true)

    for svc in $services; do
        local svc_errors
        svc_errors=$(docker logs --since 5m "$svc" 2>&1 | grep -ci "error\|exception\|traceback" || true)
        error_count=$((error_count + svc_errors))

        if [[ "$svc_errors" -gt "$ERROR_THRESHOLD" ]]; then
            alert "WARNING" "服务 $svc 最近5分钟 $svc_errors 个错误"
        fi
    done

    echo "$NOW | OK | 总错误数: $error_count" >> "$CHECK_LOG"
}

# ─── 检查5: 数据库连接池 ───
check_db_connections() {
    if ! command -v psql &>/dev/null; then
        return
    fi

    local conn_count max_conn
    conn_count=$(psql "$DB_URL" -t -A -c "SELECT count(*) FROM pg_stat_activity" 2>/dev/null || echo "-1")
    max_conn=$(psql "$DB_URL" -t -A -c "SHOW max_connections" 2>/dev/null || echo "100")

    if [[ "$conn_count" == "-1" ]]; then
        return
    fi

    local usage_pct=$((conn_count * 100 / max_conn))
    echo "$NOW | OK | DB连接: $conn_count/$max_conn (${usage_pct}%)" >> "$CHECK_LOG"

    if [[ "$usage_pct" -gt 80 ]]; then
        alert "WARNING" "数据库连接池使用率: ${usage_pct}% ($conn_count/$max_conn)"
    fi
}

# ─── 安装 crontab ───
install_cron() {
    local cron_line="*/5 * * * * $SCRIPT_DIR/monitor.sh >> $LOG_DIR/monitor-cron.log 2>&1"
    local marker="# tunxiang-os-monitor"

    # 先移除旧的
    crontab -l 2>/dev/null | grep -v "$marker" | crontab - 2>/dev/null || true

    # 添加新的
    (crontab -l 2>/dev/null; echo "$cron_line $marker") | crontab -
    echo "已安装 crontab（每5分钟运行）"
    echo "查看: crontab -l | grep tunxiang"
    echo "日志: tail -f $LOG_DIR/monitor-cron.log"
}

# ─── 卸载 crontab ───
uninstall_cron() {
    crontab -l 2>/dev/null | grep -v "tunxiang-os-monitor" | crontab - 2>/dev/null || true
    echo "已从 crontab 移除"
}

# ─── 日志轮转（保留7天） ───
rotate_logs() {
    find "$LOG_DIR" -name "monitor-*.log" -mtime +7 -delete 2>/dev/null || true
}

# ─── 主流程 ───
run_checks() {
    check_health
    check_orders
    check_disk
    check_errors
    check_db_connections
    rotate_logs

    if [[ ${#ALERTS[@]} -gt 0 ]]; then
        echo ""
        echo "====== 告警 (${#ALERTS[@]}) ======"
        printf '%s\n' "${ALERTS[@]}"
        send_webhook
    else
        echo "$NOW | ALL OK" >> "$CHECK_LOG"
    fi
}

# ─── 入口 ───
case "${1:-check}" in
    check)     run_checks ;;
    install)   install_cron ;;
    uninstall) uninstall_cron ;;
    *)
        echo "用法: $0 {check|install|uninstall}"
        echo ""
        echo "  check        运行一次检查"
        echo "  install      安装到 crontab（每5分钟）"
        echo "  uninstall    从 crontab 移除"
        echo ""
        echo "环境变量:"
        echo "  ALERT_WEBHOOK     企业微信/飞书 webhook URL"
        echo "  ORDER_MIN_5MIN    营业时段5分钟最低订单数"
        echo "  ERROR_THRESHOLD   5分钟错误日志上限（默认10）"
        echo "  DISK_THRESHOLD    磁盘告警阈值%（默认85）"
        ;;
esac
