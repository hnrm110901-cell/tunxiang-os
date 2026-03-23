#!/usr/bin/env bash
# ─── TunxiangOS V3 DNS 配置清单 ───
#
# 用途：
#   1. 输出所有 DNS 记录配置表格，方便在 DNSPod 控制台手动配置
#   2. （可选）通过 DNSPod API 自动创建记录
#
# 使用方式：
#   ./dns-records.sh list          # 输出配置清单表格
#   ./dns-records.sh create        # 通过 API 自动创建（需要 DNSPOD_API_ID + DNSPOD_API_TOKEN）
#
# 域名：tunxiangos.com
# 服务器 IP：通过 SERVER_IP 环境变量传入

set -euo pipefail

DOMAIN="tunxiangos.com"
SERVER_IP="${SERVER_IP:-YOUR_SERVER_IP}"
DNSPOD_API_ID="${DNSPOD_API_ID:-}"
DNSPOD_API_TOKEN="${DNSPOD_API_TOKEN:-}"

# ─── 颜色输出 ───
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'
BOLD='\033[1m'

log_info()  { echo -e "${GREEN}[INFO]${NC} $*"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC} $*"; }
log_error() { echo -e "${RED}[ERROR]${NC} $*"; }

# ─── DNS 记录定义 ───
# 格式: "子域名|记录类型|记录值|用途说明"
DNS_RECORDS=(
    "@|A|${SERVER_IP}|官网 tunxiangos.com"
    "www|CNAME|${DOMAIN}.|www 重定向到裸域名"
    "hub|A|${SERVER_IP}|总部 Hub 管理后台"
    "os|A|${SERVER_IP}|总部管理后台（web-admin）"
    "pos|A|${SERVER_IP}|POS 前端"
    "kds|A|${SERVER_IP}|KDS 出餐屏"
    "m|A|${SERVER_IP}|小程序 H5 / miniapp"
    "forge|A|${SERVER_IP}|Forge 开发者平台"
    "api|A|${SERVER_IP}|API Gateway"
    "ws|A|${SERVER_IP}|WebSocket 入口"
    "docs|A|${SERVER_IP}|文档站"
    "*|A|${SERVER_IP}|通配符兜底（可选）"
)

# ─── 1. 输出 DNS 配置清单表格 ───
list_records() {
    echo ""
    echo -e "${BOLD}============================================================${NC}"
    echo -e "${BOLD}  TunxiangOS V3 DNS 配置清单${NC}"
    echo -e "${BOLD}  域名: ${CYAN}${DOMAIN}${NC}"
    echo -e "${BOLD}  服务器: ${CYAN}${SERVER_IP}${NC}"
    echo -e "${BOLD}============================================================${NC}"
    echo ""

    # 表头
    printf "${BOLD}%-4s  %-10s  %-8s  %-30s  %-30s${NC}\n" \
        "#" "主机记录" "类型" "记录值" "用途"
    printf "%-4s  %-10s  %-8s  %-30s  %-30s\n" \
        "----" "----------" "--------" "------------------------------" "------------------------------"

    # 表体
    local i=1
    for record in "${DNS_RECORDS[@]}"; do
        IFS='|' read -r subdomain type value desc <<< "$record"
        printf "%-4s  %-10s  %-8s  %-30s  %-30s\n" \
            "$i" "$subdomain" "$type" "$value" "$desc"
        ((i++))
    done

    echo ""
    echo -e "${BOLD}── 完整域名列表 ──${NC}"
    echo ""
    echo "  https://tunxiangos.com          -> 官网"
    echo "  https://www.tunxiangos.com      -> 301 重定向到 tunxiangos.com"
    echo "  https://hub.tunxiangos.com      -> 总部 Hub（IP 白名单限制）"
    echo "  https://os.tunxiangos.com       -> 总部管理后台"
    echo "  https://pos.tunxiangos.com      -> POS 收银前端"
    echo "  https://kds.tunxiangos.com      -> KDS 出餐屏"
    echo "  https://m.tunxiangos.com        -> 小程序 H5"
    echo "  https://forge.tunxiangos.com    -> Forge 开发者平台"
    echo "  https://api.tunxiangos.com      -> API Gateway（纯 API）"
    echo "  wss://ws.tunxiangos.com         -> WebSocket（mac-station）"
    echo "  https://docs.tunxiangos.com     -> 文档站"
    echo ""
    echo -e "${BOLD}── SSL 证书 ──${NC}"
    echo ""
    echo "  通配符证书: *.tunxiangos.com + tunxiangos.com"
    echo "  验证方式: DNS-01 (DNSPod)"
    echo "  续期脚本: infra/nginx/ssl-renew.sh"
    echo ""
    echo -e "${BOLD}── DNSPod 控制台操作步骤 ──${NC}"
    echo ""
    echo "  1. 登录 https://console.dnspod.cn/"
    echo "  2. 进入域名 ${DOMAIN} 的解析设置"
    echo "  3. 按上表逐条添加记录"
    echo "  4. 将 SERVER_IP 替换为实际服务器公网 IP"
    echo "  5. TTL 建议设为 600（10分钟）"
    echo ""
}

# ─── 2. 通过 DNSPod API 自动创建记录 ───
create_records() {
    if [ -z "$DNSPOD_API_ID" ] || [ -z "$DNSPOD_API_TOKEN" ]; then
        log_error "需要设置环境变量 DNSPOD_API_ID 和 DNSPOD_API_TOKEN"
        echo "  export DNSPOD_API_ID=your_id"
        echo "  export DNSPOD_API_TOKEN=your_token"
        exit 1
    fi

    if [ "$SERVER_IP" = "YOUR_SERVER_IP" ]; then
        log_error "需要设置环境变量 SERVER_IP"
        echo "  export SERVER_IP=1.2.3.4"
        exit 1
    fi

    LOGIN_TOKEN="${DNSPOD_API_ID},${DNSPOD_API_TOKEN}"
    API_URL="https://dnsapi.cn/Record.Create"

    log_info "开始通过 DNSPod API 创建 DNS 记录..."
    echo ""

    local success=0
    local fail=0

    for record in "${DNS_RECORDS[@]}"; do
        IFS='|' read -r subdomain type value desc <<< "$record"

        log_info "创建记录: ${subdomain}.${DOMAIN} -> ${type} ${value}"

        RESPONSE=$(curl -s -X POST "$API_URL" \
            -d "login_token=${LOGIN_TOKEN}" \
            -d "format=json" \
            -d "domain=${DOMAIN}" \
            -d "sub_domain=${subdomain}" \
            -d "record_type=${type}" \
            -d "record_line=默认" \
            -d "value=${value}" \
            -d "ttl=600")

        STATUS_CODE=$(echo "$RESPONSE" | grep -o '"code":"[^"]*"' | head -1 | cut -d'"' -f4)

        if [ "$STATUS_CODE" = "1" ]; then
            log_info "  -> 成功"
            ((success++))
        else
            STATUS_MSG=$(echo "$RESPONSE" | grep -o '"message":"[^"]*"' | head -1 | cut -d'"' -f4)
            log_warn "  -> 失败: ${STATUS_MSG:-未知错误} (code: ${STATUS_CODE:-N/A})"
            ((fail++))
        fi

        # 避免 API 限速
        sleep 1
    done

    echo ""
    log_info "创建完成: ${success} 成功, ${fail} 失败"
}

# ─── 主入口 ───
usage() {
    echo "用法: $0 {list|create}"
    echo ""
    echo "  list    输出 DNS 配置清单表格（手动配置参考）"
    echo "  create  通过 DNSPod API 自动创建记录"
    echo ""
    echo "环境变量："
    echo "  SERVER_IP         服务器公网 IP（必须）"
    echo "  DNSPOD_API_ID     DNSPod API ID（create 模式必须）"
    echo "  DNSPOD_API_TOKEN  DNSPod API Token（create 模式必须）"
}

case "${1:-list}" in
    list)
        list_records
        ;;
    create)
        create_records
        ;;
    *)
        usage
        exit 1
        ;;
esac
