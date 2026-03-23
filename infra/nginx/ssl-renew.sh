#!/usr/bin/env bash
# ─── TunxiangOS Let's Encrypt SSL 证书自动续期脚本 ───
#
# 用途：
#   1. 首次安装 certbot 并申请证书
#   2. 配置自动续期 cron
#   3. 手动续期
#
# 域名列表（按需修改）：
DOMAINS=("api.zlsjos.cn" "admin.zlsjos.cn" "miniapp.zlsjos.cn")
EMAIL="devops@tunxiang.tech"
NGINX_CONTAINER="tunxiang-nginx"
CERT_DIR="/etc/letsencrypt/live/api.zlsjos.cn"
NGINX_SSL_DIR="/etc/nginx/ssl"

set -euo pipefail

# ─── 颜色输出 ───
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log_info()  { echo -e "${GREEN}[INFO]${NC} $*"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC} $*"; }
log_error() { echo -e "${RED}[ERROR]${NC} $*"; }

# ─── 1. 安装 certbot ───
install_certbot() {
    log_info "检查 certbot 安装状态..."
    if command -v certbot &>/dev/null; then
        log_info "certbot 已安装: $(certbot --version 2>&1)"
        return 0
    fi

    log_info "安装 certbot..."
    if [ -f /etc/debian_version ]; then
        # Debian / Ubuntu
        apt-get update -qq
        apt-get install -y -qq certbot python3-certbot-nginx
    elif [ -f /etc/redhat-release ]; then
        # CentOS / RHEL
        yum install -y epel-release
        yum install -y certbot python3-certbot-nginx
    elif command -v brew &>/dev/null; then
        # macOS (开发环境)
        brew install certbot
    else
        log_error "不支持的操作系统，请手动安装 certbot"
        exit 1
    fi

    log_info "certbot 安装完成: $(certbot --version 2>&1)"
}

# ─── 2. 申请证书（首次） ───
request_cert() {
    log_info "申请 SSL 证书..."

    # 构建 -d 参数
    DOMAIN_ARGS=""
    for d in "${DOMAINS[@]}"; do
        DOMAIN_ARGS="$DOMAIN_ARGS -d $d"
    done

    certbot certonly \
        --nginx \
        --non-interactive \
        --agree-tos \
        --email "$EMAIL" \
        $DOMAIN_ARGS \
        --preferred-challenges http

    if [ $? -eq 0 ]; then
        log_info "证书申请成功"
        copy_certs
    else
        log_error "证书申请失败"
        exit 1
    fi
}

# ─── 3. 复制证书到 Nginx 目录 ───
copy_certs() {
    log_info "复制证书到 Nginx SSL 目录..."
    mkdir -p "$NGINX_SSL_DIR"
    cp "$CERT_DIR/fullchain.pem" "$NGINX_SSL_DIR/fullchain.pem"
    cp "$CERT_DIR/privkey.pem"   "$NGINX_SSL_DIR/privkey.pem"
    chmod 600 "$NGINX_SSL_DIR/privkey.pem"
    chmod 644 "$NGINX_SSL_DIR/fullchain.pem"
    log_info "证书复制完成"
}

# ─── 4. 续期证书 ───
renew_cert() {
    log_info "执行证书续期..."

    certbot renew --quiet --deploy-hook "$(realpath "$0") reload-nginx"

    if [ $? -eq 0 ]; then
        log_info "证书续期检查完成"
    else
        log_error "证书续期失败"
        exit 1
    fi
}

# ─── 5. 重载 Nginx ───
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

# ─── 6. 配置 cron 定时续期 ───
setup_cron() {
    log_info "配置自动续期 cron..."
    SCRIPT_PATH="$(realpath "$0")"
    CRON_JOB="0 3 1,15 * * $SCRIPT_PATH renew >> /var/log/ssl-renew.log 2>&1"

    # 检查是否已存在
    if crontab -l 2>/dev/null | grep -qF "ssl-renew"; then
        log_warn "cron 任务已存在，跳过"
        crontab -l | grep "ssl-renew"
        return 0
    fi

    # 添加 cron
    (crontab -l 2>/dev/null; echo "$CRON_JOB") | crontab -
    log_info "cron 已配置：每月 1 号和 15 号凌晨 3 点自动续期"
}

# ─── 7. 检查证书状态 ───
check_status() {
    log_info "证书状态："
    for d in "${DOMAINS[@]}"; do
        if [ -f "/etc/letsencrypt/live/$d/fullchain.pem" ]; then
            EXPIRY=$(openssl x509 -enddate -noout -in "/etc/letsencrypt/live/$d/fullchain.pem" 2>/dev/null | cut -d= -f2)
            log_info "  $d -> 到期: $EXPIRY"
        else
            log_warn "  $d -> 未找到证书"
        fi
    done

    # 测试 Nginx 配置
    if command -v nginx &>/dev/null; then
        nginx -t 2>&1 && log_info "Nginx 配置测试通过" || log_error "Nginx 配置测试失败"
    fi
}

# ─── 主入口 ───
usage() {
    echo "用法: $0 {install|request|renew|reload-nginx|setup-cron|status|all}"
    echo ""
    echo "  install       安装 certbot"
    echo "  request       首次申请证书"
    echo "  renew         续期证书"
    echo "  reload-nginx  重载 Nginx（deploy-hook 回调）"
    echo "  setup-cron    配置自动续期定时任务"
    echo "  status        检查证书状态"
    echo "  all           首次全量执行（安装+申请+cron）"
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
