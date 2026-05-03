#!/usr/bin/env bash
# 在服务器上生成生产环境 .env 文件
# 用法: bash /opt/tunxiang-os/scripts/create-prod-env.sh
#
# 安全说明：
#   - 数据库密码、Redis 密码、JWT 密钥通过 openssl rand 随机生成
#   - 每次运行生成不同的凭据
#   - 生成的 .env 文件权限为 600（仅所有者可读）
set -e

TARGET=/opt/tunxiang-os/infra/docker/.env

# 生成随机密码
POSTGRES_PASSWORD=$(openssl rand -hex 16)
REDIS_PASSWORD=$(openssl rand -hex 16)
TX_JWT_SECRET=$(openssl rand -hex 32)

cat > "$TARGET" <<ENVEOF
TX_ENV=prod
POSTGRES_USER=tunxiang
POSTGRES_PASSWORD=${POSTGRES_PASSWORD}
POSTGRES_DB=tunxiang_os
POSTGRES_PORT=5432
DATABASE_URL=postgresql+asyncpg://tunxiang:${POSTGRES_PASSWORD}@postgres-primary:5432/tunxiang_os
REDIS_PASSWORD=${REDIS_PASSWORD}
REDIS_URL=redis://:${REDIS_PASSWORD}@redis:6379/0
TX_JWT_SECRET=${TX_JWT_SECRET}
TX_JWT_ALGORITHM=HS256
TX_JWT_EXPIRE_MINUTES=1440
TX_AUTH_ENABLED=true
TX_RATE_LIMIT_ENABLED=true
LOG_LEVEL=INFO
TENCENT_SECRET_ID=CHANGE_ME
TENCENT_SECRET_KEY=CHANGE_ME
TENCENT_COS_BUCKET=CHANGE_ME
TENCENT_COS_REGION=ap-guangzhou
TENCENT_SMS_SDK_APP_ID=CHANGE_ME
TENCENT_SMS_SIGN_NAME=屯象科技
ANTHROPIC_API_KEY=CHANGE_ME
ANTHROPIC_MODEL=claude-sonnet-4-20250514
WECHAT_APP_ID=CHANGE_ME
WECHAT_APP_SECRET=CHANGE_ME
WECHAT_MCH_ID=CHANGE_ME
WECHAT_API_KEY=CHANGE_ME
DOUYIN_APP_ID=CHANGE_ME
DOUYIN_APP_SECRET=CHANGE_ME
TX_DOMAIN=tunxiangos.com
SSL_CERT_PATH=/etc/nginx/ssl/fullchain.pem
SSL_KEY_PATH=/etc/nginx/ssl/privkey.pem
CERTBOT_EMAIL=CHANGE_ME
TAILSCALE_AUTH_KEY=CHANGE_ME
ENVEOF

chmod 600 "$TARGET"
echo ".env created at $TARGET (permissions: 600)"
echo ""
echo "⚠️  请手动替换以下 CHANGE_ME 值："
grep -n "CHANGE_ME" "$TARGET"
