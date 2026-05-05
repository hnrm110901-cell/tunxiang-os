#!/bin/sh
# PostgreSQL 定时备份脚本
# 运行环境：postgres:16-alpine 容器（pg_dump 内置）
# 环境变量：PGHOST PGPORT PGDATABASE PGUSER PGPASSWORD BACKUP_KEEP_DAYS
set -e

BACKUP_DIR="/backups"
KEEP_DAYS="${BACKUP_KEEP_DAYS:-7}"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
FILENAME="tunxiang_os_${TIMESTAMP}.sql.gz"
FILEPATH="${BACKUP_DIR}/${FILENAME}"

echo "[$(date '+%Y-%m-%d %H:%M:%S')] 开始备份 ${PGDATABASE}..."

# 执行备份并压缩
pg_dump \
  --no-password \
  --format=plain \
  --encoding=UTF8 \
  "${PGDATABASE}" | gzip > "${FILEPATH}"

SIZE=$(du -sh "${FILEPATH}" | cut -f1)
echo "[$(date '+%Y-%m-%d %H:%M:%S')] 备份完成: ${FILENAME} (${SIZE})"

# 删除超过保留天数的旧备份
find "${BACKUP_DIR}" -name "tunxiang_os_*.sql.gz" -mtime "+${KEEP_DAYS}" -delete
REMAINING=$(find "${BACKUP_DIR}" -name "tunxiang_os_*.sql.gz" | wc -l | tr -d ' ')
echo "[$(date '+%Y-%m-%d %H:%M:%S')] 当前保留备份数量: ${REMAINING} (保留策略: ${KEEP_DAYS} 天)"
