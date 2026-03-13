#!/bin/bash
# =====================================================
# 屯象OS — 按租户 Schema 独立备份脚本
# 运行位置: 42.194.229.21 服务器
# cron: 0 3 * * * /opt/zhilian-os/scripts/backup_tenant.sh
# =====================================================
set -e

DB_NAME="zhilian_os"
DB_USER="zhilian"
BACKUP_DIR="/var/backups/zhilian-os"
DATE=$(date +%Y%m%d_%H%M%S)
RETAIN_DAYS=7

# 租户 Schema 列表
SCHEMAS=("czq" "zqx" "sgc" "public")

mkdir -p "${BACKUP_DIR}"

echo "[$(date)] 开始备份..."

for schema in "${SCHEMAS[@]}"; do
    BACKUP_FILE="${BACKUP_DIR}/${schema}_${DATE}.sql.gz"
    echo "  备份 ${schema} → ${BACKUP_FILE}"
    pg_dump -U "${DB_USER}" -n "${schema}" "${DB_NAME}" | gzip > "${BACKUP_FILE}"
    SIZE=$(du -h "${BACKUP_FILE}" | cut -f1)
    echo "  ✅ ${schema} 完成 (${SIZE})"
done

# 清理过期备份
echo "  清理 ${RETAIN_DAYS} 天前的备份..."
find "${BACKUP_DIR}" -name "*.sql.gz" -mtime +${RETAIN_DAYS} -delete
REMAINING=$(ls -1 "${BACKUP_DIR}"/*.sql.gz 2>/dev/null | wc -l)
echo "  当前备份数: ${REMAINING}"

echo "[$(date)] 备份完成！"
