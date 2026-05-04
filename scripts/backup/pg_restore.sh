#!/bin/sh
# PostgreSQL 备份恢复脚本
# 用法: ./pg_restore.sh <备份文件名>
# 示例: ./pg_restore.sh tunxiang_os_20260503_020000.sql.gz
set -e

BACKUP_DIR="/backups"

if [ -z "$1" ]; then
  echo "用法: $0 <备份文件名>"
  echo ""
  echo "可用备份："
  ls -lh "${BACKUP_DIR}"/tunxiang_os_*.sql.gz 2>/dev/null || echo "  (无备份文件)"
  exit 1
fi

FILEPATH="${BACKUP_DIR}/$1"

if [ ! -f "${FILEPATH}" ]; then
  echo "错误: 文件不存在: ${FILEPATH}"
  exit 1
fi

echo "[$(date '+%Y-%m-%d %H:%M:%S')] 开始恢复: $1"
echo "目标数据库: ${PGDATABASE}@${PGHOST}"
echo "警告: 此操作将覆盖现有数据！确认继续请输入 YES:"
read -r CONFIRM
if [ "${CONFIRM}" != "YES" ]; then
  echo "已取消"
  exit 0
fi

# 解压并恢复
gunzip -c "${FILEPATH}" | psql \
  --no-password \
  --quiet \
  "${PGDATABASE}"

echo "[$(date '+%Y-%m-%d %H:%M:%S')] 恢复完成"
