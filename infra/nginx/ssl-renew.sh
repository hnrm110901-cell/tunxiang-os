#!/usr/bin/env bash
# ─── TunxiangOS V3 Let's Encrypt SSL 证书自动续期脚本 ───
#
# 用途：
#   1. 申请通配符证书 *.tunxiangos.com + tunxiangos.com
#   2. 使用 DNS-01 验证（腾讯云 DNSPod）
#   3. 配置自动续期 cron
#
# 前置条件：
#   - 安装 certbot + certbot-dns-dnspod 插件
#   - 配置 DNSPod API 凭证文件
#
# 域名：通配符覆盖所有子域名
#   *.tunxiangos.com  (hub/os/pos/kds/m/forge/api/ws/docs/www)
#   tunxiangos.com    (裸域名)

DOMAIN="tunxiangos.com"
WILDCARD="*.tunxiangos.com"
EMAIL="${SSL_EMAIL:-devops@tunxiang.tech}"
NGINX_CONTAINER="tunxiang-nginx"
CERT_DIR="/etc/letsencrypt/live/${DOMAIN}"
NGINX_SSL_DIR="/etc/nginx/ssl"
DNSPOD_CREDENTIALS="/etc/letsencrypt/dnspod.ini"

set -euo pipefail

# ─── 颜色输出 ───
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log_info()  { echo -e "${GREEN}[INFO]${NC} $*"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC} $*"; }
log_error() { echo -e "${RED}[ERROR]${NC} $*"; }

# ─── 1. 安装 certbot + DNS 插件 ───
install_certbot() {
    log_info "检查 certbot 安装状态..."
    if command -v certbot &>/dev/null; then
        log_info "certbot 已安装: $(certbot --version 2>&1)"
    else
        log_info "安装 certbot..."
        if [ -f /etc/debian_version ]; then
            apt-get update -qq
            apt-get install -y -qq certbot
        elif [ -f /etc/redhat-release ]; then
            yum install -y epel-release
            yum install -y certbot
        elif command -v brew &>/dev/null; then
            brew install certbot
        else
            log_error "不支持的操作系统，请手动安装 certbot"
            exit 1
        fi
        log_info "certbot 安装完成: $(certbot --version 2>&1)"
    fi

    # 安装 DNSPod DNS 插件
    log_info "安装 certbot DNS 插件..."
    if pip3 show certbot-dns-dnspod &>/dev/null 2>&1; then
        log_info "certbot-dns-dnspod 插件已安装"
    else
        pip3 install certbot-dns-dnspod
        log_info "certbot-dns-dnspod 插件安装完成"
    fi
}

# ─── 2. 配置 DNSPod API 凭证 ───
setup_dnspod_credentials() {
    if [ -f "$DNSPOD_CREDENTIALS" ]; then
        log_info "DNSPod 凭证文件已存在: $DNSPOD_CREDENTIALS"
        return 0
    fi

    if [ -z "${DNSPOD_API_ID:-}" ] || [ -z "${DNSPOD_API_TOKEN:-}" ]; then
        log_error "请设置环境变量 DNSPOD_API_ID 和 DNSPOD_API_TOKEN"
        log_error "或手动创建凭证文件: $DNSPOD_CREDENTIALS"
        echo ""
        echo "文件格式："
        echo "  dns_dnspod_api_id = YOUR_API_ID"
        echo "  dns_dnspod_api_token = YOUR_API_TOKEN"
        exit 1
    fi

    log_info "创建 DNSPod 凭证文件..."
    mkdir -p "$(dirname "$DNSPOD_CREDENTIALS")"
    cat > "$DNSPOD_CREDENTIALS" <<EOF
dns_dnspod_api_id = ${DNSPOD_API_ID}
dns_dnspod_api_token = ${DNSPOD_API_TOKEN}
EOF
    chmod 600 "$DNSPOD_CREDENTIALS"
    log_info "凭证文件创建完成: $DNSPOD_CREDENTIALS"
}

# ─── 3. 申请通配符证书（DNS-01 验证） ───
request_cert() {
    log_info "申请通配符 SSL 证书..."
    log_info "  域名: $DOMAIN + $WILDCARD"
    log_info "  验证方式: DNS-01 (DNSPod)"

    setup_dnspod_credentials

    certbot certonly \
        --authenticator dns-dnspod \
        --dns-dnspod-credentials "$DNSPOD_CREDENTIALS" \
        --dns-dnspod-propagation-seconds 60 \
        --non-interactive \
        --agree-tos \
        --email "$EMAIL" \
        -d "$DOMAIN" \
        -d "$WILDCARD" \
        --preferred-challenges dns-01

    if [ $? -eq 0 ]; then
        log_info "通配符证书申请成功"
        copy_certs
    else
        log_error "证书申请失败"
        exit 1
    fi
}

# ─── 4. 复制证书到 Nginx 目录 ───
copy_certs() {
    log_info "复制证书到 Nginx SSL 目录..."
    mkdir -p "$NGINX_SSL_DIR"
    cp "$CERT_DIR/fullchain.pem" "$NGINX_SSL_DIR/fullchain.pem"
    cp "$CERT_DIR/privkey.pem"   "$NGINX_SSL_DIR/privkey.pem"
    chmod 600 "$NGINX_SSL_DIR/privkey.pem"
    chmod 644 "$NGINX_SSL_DIR/fullchain.pem"
    log_info "证书复制完成"
}

# ─── 5. 续期证书 ───
renew_cert() {
    log_info "执行证书续期..."

    certbot renew \
        --quiet \
        --deploy-hook "$(realpath "$0") reload-nginx"

    if [ $? -eq 0 ]; then
        log_info "证书续期检查完成"
    else
        log_error "证书续期失败"
        exit 1
    fi
}

# ─── 6. 重载 Nginx ───
reload_nginx() {
    log_info "重载 Nginx 配置..."

    # 先复制新证书
    copy_certs

    # Docker 环境
    if command -v docker &>/dev/null && docker ps --format '{{.Names}}' | grep -q "$NGINX_CONTAINER"; then
        docker exec "$NGINX_CONTAINER" nginx -t && \
        docker exec "$NGINX_CONTAINER" nginx -s reload
        log_info "Docker Nginx 重载完成"
        return 0
    fi

    # 原生 Nginx
    if command -v nginx &>/dev/null; then
        nginx -t && nginx -s reload
        log_info "Nginx 重载完成"
        return 0
    fi

    # systemctl
    if command -v systemctl &>/dev/null; then
        systemctl reload nginx
        log_info "Nginx (systemctl) 重载完成"
        return 0
    fi

    log_warn "未找到 Nginx 进程，请手动重载"
}

# ─── 7. 配置 cron 定时续期 ───
setup_cron() {
    log_info "配置自动续期 cron..."
    SCRIPT_PATH="$(realpath "$0")"
    CRON_JOB="0 3 1,15 * * $SCRIPT_PATH renew >> /var/log/ssl-renew.log 2>&1"

    if crontab -l 2>/dev/null | grep -qF "ssl-renew"; then
        log_warn "cron 任务已存在，跳过"
        crontab -l | grep "ssl-renew"
        return 0
    fi

    (crontab -l 2>/dev/null; echo "$CRON_JOB") | crontab -
    log_info "cron 已配置：每月 1 号和 15 号凌晨 3 点自动续期"
}

# ─── 8. 检查证书状态 ───
check_status() {
    log_info "证书状态："

    if [ -f "$CERT_DIR/fullchain.pem" ]; then
        EXPIRY=$(openssl x509 -enddate -noout -in "$CERT_DIR/fullchain.pem" 2>/dev/null | cut -d= -f2)
        SANS=$(openssl x509 -text -noout -in "$CERT_DIR/fullchain.pem" 2>/dev/null | grep "DNS:" | tr ',' '\n' | sed 's/^ */  /')
        log_info "  证书到期: $EXPIRY"
        log_info "  覆盖域名:"
        echo "$SANS"
    else
        log_warn "  未找到证书: $CERT_DIR/fullchain.pem"
    fi

    # 检查 Nginx SSL 目录
    if [ -f "$NGINX_SSL_DIR/fullchain.pem" ]; then
        NGINX_EXPIRY=$(openssl x509 -enddate -noout -in "$NGINX_SSL_DIR/fullchain.pem" 2>/dev/null | cut -d= -f2)
        log_info "  Nginx SSL 证书到期: $NGINX_EXPIRY"
    else
        log_warn "  Nginx SSL 目录未找到证书"
    fi

    # 测试 Nginx 配置
    if command -v nginx &>/dev/null; then
        nginx -t 2>&1 && log_info "Nginx 配置测试通过" || log_error "Nginx 配置测试失败"
    fi
}

# ─── 主入口 ───
usage() {
    echo "用法: $0 {install|request|renew|reload-nginx|setup-cron|status|all}"
    echo ""
    echo "  install       安装 certbot + DNSPod 插件"
    echo "  request       申请通配符证书（DNS-01 验证）"
    echo "  renew         续期证书"
    echo "  reload-nginx  重载 Nginx（deploy-hook 回调）"
    echo "  setup-cron    配置自动续期定时任务"
    echo "  status        检查证书状态"
    echo "  all           首次全量执行（安装+申请+cron）"
    echo ""
    echo "环境变量（申请证书时需要）："
    echo "  DNSPOD_API_ID     DNSPod API ID"
    echo "  DNSPOD_API_TOKEN  DNSPod API Token"
    echo "  SSL_EMAIL         证书通知邮箱（默认 devops@tunxiang.tech）"
}

case "${1:-}" in
    install)
        install_certbot
        ;;
    request)
        request_cert
        ;;
    renew)
        renew_cert
        ;;
    reload-nginx)
        reload_nginx
        ;;
    setup-cron)
        setup_cron
        ;;
    status)
        check_status
        ;;
    all)
        install_certbot
        request_cert
        setup_cron
        check_status
        log_info "全量配置完成"
        ;;
    *)
        usage
        exit 1
        ;;
esac
