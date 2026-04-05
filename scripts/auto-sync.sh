#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────
# 屯象OS 自动同步部署脚本（服务器 cron 每5分钟执行）
# crontab: */5 * * * * /opt/tunxiang-os/scripts/auto-sync.sh
#
# 同步逻辑：
#   - 有新 commit  → 拉取
#   - db-migrations 变更 → alembic upgrade head
#   - services/shared/infra/docker 变更 → rebuild + docker compose up -d
# ─────────────────────────────────────────────────────────────
set -euo pipefail

LOG=/opt/tunxiang-os/logs/auto-sync.log
REPO=/opt/tunxiang-os
COMPOSE_DIR="$REPO/infra/docker"
COMPOSE_FILE="docker-compose.prod.yml"
DB_URL="postgresql://tunxiang:Lichun849299@localhost:5432/tunxiang_os"

mkdir -p "$REPO/logs"
cd "$REPO"

# ── 拉取最新代码 ─────────────────────────────────────────────
BEFORE=$(git rev-parse HEAD)
git remote set-url origin https://github.com/hnrm110901-cell/tunxiang-os.git
git pull origin main --ff-only >> "$LOG" 2>&1 || {
  echo "$(date '+%F %T') PULL_FAILED" >> "$LOG"
  exit 1
}
AFTER=$(git rev-parse HEAD)

# 无新提交，直接退出
[ "$BEFORE" = "$AFTER" ] && exit 0

echo "$(date '+%F %T') UPDATED $BEFORE -> $AFTER" >> "$LOG"
CHANGED=$(git diff --name-only "$BEFORE" "$AFTER")

# ── 数据库迁移 ───────────────────────────────────────────────
if echo "$CHANGED" | grep -q "db-migrations/versions"; then
  echo "$(date '+%F %T') RUNNING MIGRATIONS" >> "$LOG"
  source "$REPO/.venv/bin/activate"
  cd "$REPO/shared/db-migrations"
  PYTHONPATH="$REPO" DATABASE_URL="$DB_URL" \
    alembic upgrade head >> "$LOG" 2>&1
  deactivate
  cd "$REPO"
fi

# ── 重建镜像并滚动重启所有微服务 ─────────────────────────────
if echo "$CHANGED" | grep -qE "^(services|shared|infra/docker)/"; then
  echo "$(date '+%F %T') REBUILDING DOCKER IMAGES" >> "$LOG"
  cd "$COMPOSE_DIR"
  docker compose -f "$COMPOSE_FILE" build >> "$LOG" 2>&1
  echo "$(date '+%F %T') RESTARTING SERVICES" >> "$LOG"
  docker compose -f "$COMPOSE_FILE" up -d >> "$LOG" 2>&1
  cd "$REPO"
  echo "$(date '+%F %T') DEPLOY DONE" >> "$LOG"
fi
