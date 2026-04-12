#!/bin/bash
# ============================================================
# 屯象OS 演示前端构建 & 部署脚本
# 构建 web-admin / web-kds / web-pos / h5-self-order
# 部署到 /var/www/tunxiang-demo/
#
# 使用方式:
#   ./scripts/demo_build_deploy.sh             # 本地构建后 rsync 到服务器
#   ./scripts/demo_build_deploy.sh --local     # 仅本地构建，不推送
#   SERVER=root@42.194.229.21 ./scripts/demo_build_deploy.sh
# ============================================================
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DEPLOY_TARGET="/var/www/tunxiang-demo"
SERVER="${SERVER:-root@42.194.229.21}"
LOCAL_ONLY="${1:-}"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] [BUILD] $*"; }
cd "$REPO_ROOT"

# ── 确认 pnpm 可用 ────────────────────────────────────────────
if ! command -v pnpm &>/dev/null; then
  log "ERROR: pnpm 未安装。运行: npm install -g pnpm"
  exit 1
fi

# ── 安装依赖 ──────────────────────────────────────────────────
log "安装依赖..."
pnpm install --frozen-lockfile

# ── 设置演示环境变量 ──────────────────────────────────────────
export VITE_API_BASE_URL="https://demo-os.tunxiangos.com/api"
export VITE_WS_BASE_URL="wss://demo-os.tunxiangos.com/ws"
export VITE_APP_ENV="demo"
export VITE_TENANT_ID="10000000-0000-0000-0000-000000000001"

# ── 构建各应用 ────────────────────────────────────────────────
APPS=("web-admin" "web-kds" "web-pos" "h5-self-order")

for app in "${APPS[@]}"; do
  log "构建 $app ..."
  pnpm --filter "$app" build
  log "✓ $app 构建完成 → apps/$app/dist"
done

# ── 本地模式：仅构建不推送 ───────────────────────────────────
if [ "$LOCAL_ONLY" = "--local" ]; then
  log "本地模式，跳过部署"
  log "构建产物位于:"
  for app in "${APPS[@]}"; do
    echo "  apps/$app/dist/"
  done
  exit 0
fi

# ── 推送到服务器 ──────────────────────────────────────────────
log "推送到服务器 $SERVER ..."

# 创建目标目录
ssh "$SERVER" "mkdir -p $DEPLOY_TARGET/{web-admin,web-kds,web-pos,h5-self-order}"

for app in "${APPS[@]}"; do
  log "部署 $app → $DEPLOY_TARGET/$app ..."
  rsync -az --delete \
    "$REPO_ROOT/apps/$app/dist/" \
    "$SERVER:$DEPLOY_TARGET/$app/"
done

# ── 重载 Nginx ────────────────────────────────────────────────
log "重载 Nginx..."
ssh "$SERVER" "nginx -t && nginx -s reload"

log "============================================"
log "前端部署完成！"
log ""
log "  管理后台:  https://demo-os.tunxiangos.com"
log "  KDS后厨:   https://demo-kds.tunxiangos.com"
log "  POS工作台: https://demo-pos.tunxiangos.com"
log "  顾客点餐:  https://demo-m.tunxiangos.com"
log "============================================"
