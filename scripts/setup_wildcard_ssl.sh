#!/bin/bash
# =====================================================
# 屯象OS — 泛域名 SSL 证书申请脚本
# 使用 Let's Encrypt certbot DNS-01 验证
# 运行位置: 42.194.229.21 服务器
# =====================================================
set -e

DOMAIN="zlsjos.cn"
EMAIL="admin@${DOMAIN}"
CERT_DIR="/etc/letsencrypt/live/${DOMAIN}"
NGINX_SSL_DIR="/etc/nginx/ssl"

echo "=============================================="
echo "  屯象OS 泛域名 SSL 证书申请"
echo "  域名: *.${DOMAIN} + ${DOMAIN}"
echo "=============================================="

# Step 1: 安装 certbot（如未安装）
if ! command -v certbot &> /dev/null; then
    echo "[1/5] 安装 certbot..."
    apt-get update -qq
    apt-get install -y certbot
else
    echo "[1/5] certbot 已安装: $(certbot --version 2>&1)"
fi

# Step 2: 申请泛域名证书（DNS-01 手动验证）
echo ""
echo "[2/5] 申请泛域名证书..."
echo "⚠️  注意: DNS-01 验证需要你手动添加 TXT 记录"
echo "   certbot 会提示你添加 _acme-challenge.${DOMAIN} 的 TXT 值"
echo "   在域名服务商后台添加后，等待 DNS 生效（通常 1-2 分钟）再继续"
echo ""

certbot certonly \
    --manual \
    --preferred-challenges dns \
    -d "*.${DOMAIN}" \
    -d "${DOMAIN}" \
    --email "${EMAIL}" \
    --agree-tos \
    --no-eff-email

# Step 3: 创建 Nginx SSL 目录并链接证书
echo "[3/5] 链接证书到 Nginx SSL 目录..."
mkdir -p ${NGINX_SSL_DIR}

# 如果已有旧证书，备份
if [ -f "${NGINX_SSL_DIR}/fullchain.pem" ]; then
    cp "${NGINX_SSL_DIR}/fullchain.pem" "${NGINX_SSL_DIR}/fullchain.pem.bak.$(date +%Y%m%d)"
    cp "${NGINX_SSL_DIR}/privkey.pem" "${NGINX_SSL_DIR}/privkey.pem.bak.$(date +%Y%m%d)"
fi

# 复制证书（不用软链接，避免 Docker 挂载问题）
cp "${CERT_DIR}/fullchain.pem" "${NGINX_SSL_DIR}/fullchain.pem"
cp "${CERT_DIR}/privkey.pem" "${NGINX_SSL_DIR}/privkey.pem"
chmod 644 "${NGINX_SSL_DIR}/fullchain.pem"
chmod 600 "${NGINX_SSL_DIR}/privkey.pem"

# Step 4: 重载 Nginx
echo "[4/5] 重载 Nginx..."
if command -v docker &> /dev/null && docker ps --format '{{.Names}}' | grep -q nginx; then
    docker exec $(docker ps -q --filter name=nginx) nginx -t && \
    docker exec $(docker ps -q --filter name=nginx) nginx -s reload
    echo "Docker Nginx 已重载"
elif systemctl is-active --quiet nginx; then
    nginx -t && systemctl reload nginx
    echo "系统 Nginx 已重载"
else
    echo "⚠️  未检测到运行中的 Nginx，请手动重载"
fi

# Step 5: 配置自动续期
echo "[5/5] 配置自动续期..."
RENEW_SCRIPT="/etc/cron.d/certbot-renew-zlsjos"
cat > ${RENEW_SCRIPT} << 'CRON'
# 每天凌晨 2:30 检查证书续期
30 2 * * * root certbot renew --quiet --deploy-hook "cp /etc/letsencrypt/live/zlsjos.cn/fullchain.pem /etc/nginx/ssl/fullchain.pem && cp /etc/letsencrypt/live/zlsjos.cn/privkey.pem /etc/nginx/ssl/privkey.pem && nginx -s reload 2>/dev/null || docker exec $(docker ps -q --filter name=nginx) nginx -s reload 2>/dev/null || true"
CRON
chmod 644 ${RENEW_SCRIPT}
echo "自动续期 cron 已配置"

echo ""
echo "=============================================="
echo "  ✅ SSL 证书申请完成"
echo "  证书位置: ${NGINX_SSL_DIR}/"
echo "  覆盖域名: *.${DOMAIN} + ${DOMAIN}"
echo "  自动续期: 每天 02:30 检查"
echo ""
echo "  验证命令:"
echo "    curl -I https://admin.${DOMAIN}"
echo "    curl -I https://changzaiyiqi.${DOMAIN}"
echo "    curl -I https://zuiqianxian.${DOMAIN}"
echo "    curl -I https://shanggongchu.${DOMAIN}"
echo "=============================================="
