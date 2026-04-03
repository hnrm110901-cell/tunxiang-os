#!/bin/bash
# 屯象OS 生产安全密钥生成脚本
# 等保三级 — 一次性生成所有安全密钥，写入 /etc/txos/security.env
#
# 使用方法（服务器上以 root 运行）：
#   sudo bash scripts/setup-security-keys.sh
#
# 注意：此脚本幂等，已有密钥不会覆盖。

set -euo pipefail

ENV_FILE="/etc/txos/security.env"
ENV_DIR="/etc/txos"

echo "====== 屯象OS 安全密钥配置 ======"

# 创建目录并设置权限
if [[ ! -d "$ENV_DIR" ]]; then
    mkdir -p "$ENV_DIR"
    chmod 700 "$ENV_DIR"
    echo "[OK] 创建目录 $ENV_DIR"
fi

# 如果文件已存在，备份
if [[ -f "$ENV_FILE" ]]; then
    BACKUP="$ENV_FILE.bak.$(date +%Y%m%d%H%M%S)"
    cp "$ENV_FILE" "$BACKUP"
    echo "[OK] 已备份旧文件到 $BACKUP"
fi

# 生成密钥（如果环境变量不存在则生成新的）
TX_JWT_SECRET_KEY="${TX_JWT_SECRET_KEY:-$(openssl rand -base64 48 | tr -d '\n')}"
TX_MFA_ENCRYPT_KEY="${TX_MFA_ENCRYPT_KEY:-$(openssl rand -hex 32)}"
TX_FIELD_ENCRYPTION_KEY="${TX_FIELD_ENCRYPTION_KEY:-$(openssl rand -hex 32)}"
TX_INTEGRITY_SECRET="${TX_INTEGRITY_SECRET:-$(openssl rand -base64 48 | tr -d '\n')}"
BACKUP_ENCRYPTION_KEY="${BACKUP_ENCRYPTION_KEY:-$(openssl rand -base64 48 | tr -d '\n')}"

# 写入配置文件
cat > "$ENV_FILE" <<EOF
# 屯象OS 安全密钥配置
# 生成时间: $(date -Iseconds)
# 等保三级合规 — 所有密钥通过 openssl rand 随机生成

# JWT 签名密钥（HS256，access_token 15分钟，refresh_token 7天）
TX_JWT_SECRET_KEY=${TX_JWT_SECRET_KEY}

# MFA TOTP secret 加密密钥（XOR加密存储，64位十六进制=32字节）
TX_MFA_ENCRYPT_KEY=${TX_MFA_ENCRYPT_KEY}

# 字段级 AES-256-GCM 加密密钥（PII：手机号、身份证）（64位十六进制=32字节）
TX_FIELD_ENCRYPTION_KEY=${TX_FIELD_ENCRYPTION_KEY}

# HMAC-SHA256 数据完整性密钥（订单防篡改）
TX_INTEGRITY_SECRET=${TX_INTEGRITY_SECRET}

# 数据库异地备份加密密钥（openssl enc -aes-256-cbc）
BACKUP_ENCRYPTION_KEY=${BACKUP_ENCRYPTION_KEY}
EOF

chmod 600 "$ENV_FILE"
echo "[OK] 密钥已写入 $ENV_FILE（权限 600）"

echo ""
echo "====== 验证 ======"
echo "TX_JWT_SECRET_KEY 长度: $(echo -n "$TX_JWT_SECRET_KEY" | wc -c) 字节"
echo "TX_MFA_ENCRYPT_KEY 长度: $(echo -n "$TX_MFA_ENCRYPT_KEY" | wc -c) 字节（十六进制）"
echo "TX_FIELD_ENCRYPTION_KEY 长度: $(echo -n "$TX_FIELD_ENCRYPTION_KEY" | wc -c) 字节（十六进制）"
echo "TX_INTEGRITY_SECRET 长度: $(echo -n "$TX_INTEGRITY_SECRET" | wc -c) 字节"

echo ""
echo "====== 下一步 ======"
echo "1. 将 $ENV_FILE 添加到 docker-compose.prod.yml 的 env_file 配置"
echo "2. 或执行: source $ENV_FILE && docker-compose -f docker-compose.prod.yml up -d"
echo "3. 运行数据库迁移: docker-compose exec gateway alembic upgrade head"
echo "4. PII数据迁移（加密现有手机号）: docker-compose exec gateway python scripts/migrate_pii_encryption.py"
echo ""
echo "====== 完成 ======"
