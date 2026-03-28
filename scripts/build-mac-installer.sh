#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────
# 屯象OS Mac mini 安装包构建脚本
# 输出: dist/TunxiangOS-Mac-v{version}.dmg
# 用法: ./scripts/build-mac-installer.sh
# ─────────────────────────────────────────────────────────
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
VERSION="3.0.0"
APP_NAME="TunxiangOS-Mac"
BUILD_DIR="$PROJECT_ROOT/dist/mac-installer"
DMG_NAME="${APP_NAME}-v${VERSION}.dmg"

RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m'

log()  { echo -e "${GREEN}[build]${NC} $*"; }
step() { echo -e "\n${BLUE}═══ $* ═══${NC}"; }

# ─── 清理旧构建 ───
step "清理旧构建"
rm -rf "$BUILD_DIR"
mkdir -p "$BUILD_DIR/TunxiangOS"

APP_DIR="$BUILD_DIR/TunxiangOS"

# ─── 打包目录结构 ───
step "打包文件"

# 核心服务
log "复制 mac-station..."
mkdir -p "$APP_DIR/services/mac-station"
cp -r "$PROJECT_ROOT/edge/mac-station/src/"*.py "$APP_DIR/services/mac-station/"
cp "$PROJECT_ROOT/edge/mac-station/requirements.txt" "$APP_DIR/services/mac-station/"

log "复制 sync-engine..."
mkdir -p "$APP_DIR/services/sync-engine"
cp "$PROJECT_ROOT/edge/sync-engine/src/main.py" "$APP_DIR/services/sync-engine/"

log "复制 coreml-bridge..."
mkdir -p "$APP_DIR/services/coreml-bridge"
cp -r "$PROJECT_ROOT/edge/coreml-bridge/Package.swift" "$APP_DIR/services/coreml-bridge/"
cp -r "$PROJECT_ROOT/edge/coreml-bridge/Sources" "$APP_DIR/services/coreml-bridge/"

# 数据库迁移
log "复制数据库迁移..."
mkdir -p "$APP_DIR/db-migrations"
cp "$PROJECT_ROOT/shared/db-migrations/alembic.ini" "$APP_DIR/db-migrations/"
cp "$PROJECT_ROOT/shared/db-migrations/env.py" "$APP_DIR/db-migrations/"
cp "$PROJECT_ROOT/shared/db-migrations/script.py.mako" "$APP_DIR/db-migrations/"
cp -r "$PROJECT_ROOT/shared/db-migrations/versions" "$APP_DIR/db-migrations/"

# Ontology（迁移脚本依赖）
log "复制 Ontology..."
mkdir -p "$APP_DIR/shared/ontology/src"
cp -r "$PROJECT_ROOT/shared/ontology/src/"*.py "$APP_DIR/shared/ontology/src/"

# 安装脚本
log "复制安装脚本..."
mkdir -p "$APP_DIR/scripts"
cp "$PROJECT_ROOT/infra/tailscale/setup-mac-mini.sh" "$APP_DIR/scripts/"
cp "$PROJECT_ROOT/infra/tailscale/tailscale-config.sh" "$APP_DIR/scripts/"

# ─── 创建一键安装脚本 ───
log "生成安装脚本..."
cat > "$APP_DIR/安装屯象OS.command" << 'INSTALL_SCRIPT'
#!/usr/bin/env bash
# ─────────────────────────────────────────────
# 屯象OS Mac mini 一键安装
# 双击此文件即可开始安装
# ─────────────────────────────────────────────
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

echo ""
echo -e "${GREEN}╔═══════════════════════════════════════╗${NC}"
echo -e "${GREEN}║     屯象OS Mac mini 安装程序 v3.0     ║${NC}"
echo -e "${GREEN}║     AI-Native 连锁餐饮操作系统        ║${NC}"
echo -e "${GREEN}╚═══════════════════════════════════════╝${NC}"
echo ""

INSTALL_DIR="/opt/tunxiang-os"

# 检查是否有 sudo 权限
if [[ $EUID -ne 0 ]]; then
    echo -e "${YELLOW}需要管理员权限安装，请输入密码：${NC}"
    sudo -v || { echo -e "${RED}需要管理员权限${NC}"; exit 1; }
fi

echo ""
echo "安装路径: $INSTALL_DIR"
echo ""

# ─── Step 1: 安装 Homebrew（如果没有） ───
echo -e "${GREEN}[1/7] 检查 Homebrew...${NC}"
if ! command -v brew &>/dev/null; then
    echo "安装 Homebrew..."
    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
    eval "$(/opt/homebrew/bin/brew shellenv)"
else
    echo "Homebrew 已安装 ✓"
fi

# ─── Step 2: 安装依赖 ───
echo -e "${GREEN}[2/7] 安装系统依赖...${NC}"
brew install python@3.12 postgresql@16 2>/dev/null || true
echo "Python + PostgreSQL ✓"

# ─── Step 3: 复制文件 ───
echo -e "${GREEN}[3/7] 复制屯象OS文件...${NC}"
sudo mkdir -p "$INSTALL_DIR"
sudo cp -r "$SCRIPT_DIR/services" "$INSTALL_DIR/"
sudo cp -r "$SCRIPT_DIR/db-migrations" "$INSTALL_DIR/"
sudo cp -r "$SCRIPT_DIR/shared" "$INSTALL_DIR/"
sudo cp -r "$SCRIPT_DIR/scripts" "$INSTALL_DIR/"
sudo chown -R "$(whoami)" "$INSTALL_DIR"
echo "文件已复制到 $INSTALL_DIR ✓"

# ─── Step 4: Python 虚拟环境 ───
echo -e "${GREEN}[4/7] 创建 Python 环境...${NC}"
cd "$INSTALL_DIR"
python3 -m venv .venv
source .venv/bin/activate
pip install -q -r services/mac-station/requirements.txt
pip install -q alembic psycopg2-binary
echo "Python 依赖已安装 ✓"

# ─── Step 5: 初始化 PostgreSQL ───
echo -e "${GREEN}[5/7] 初始化数据库...${NC}"
brew services start postgresql@16 2>/dev/null || true
sleep 3

# 创建数据库和用户
createdb tunxiang_os 2>/dev/null || true
psql tunxiang_os -c "SELECT 1" &>/dev/null && echo "数据库 tunxiang_os ✓" || {
    echo -e "${RED}数据库初始化失败，请手动检查 PostgreSQL${NC}"
}

# 运行迁移
cd "$INSTALL_DIR/db-migrations"
PYTHONPATH="$INSTALL_DIR" alembic upgrade head 2>/dev/null && echo "数据库迁移完成 ✓" || {
    echo -e "${YELLOW}迁移跳过（可能已是最新）${NC}"
}

# ─── Step 6: 创建 launchd 服务（开机自启） ───
echo -e "${GREEN}[6/7] 配置开机自启...${NC}"
LAUNCH_DIR="$HOME/Library/LaunchAgents"
mkdir -p "$LAUNCH_DIR"

# mac-station 服务
cat > "$LAUNCH_DIR/com.tunxiang.mac-station.plist" << PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.tunxiang.mac-station</string>
    <key>ProgramArguments</key>
    <array>
        <string>$INSTALL_DIR/.venv/bin/uvicorn</string>
        <string>main:app</string>
        <string>--host</string>
        <string>0.0.0.0</string>
        <string>--port</string>
        <string>8000</string>
    </array>
    <key>WorkingDirectory</key>
    <string>$INSTALL_DIR/services/mac-station</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>$INSTALL_DIR/.venv/bin:/opt/homebrew/bin:/usr/bin:/bin</string>
        <key>PYTHONPATH</key>
        <string>$INSTALL_DIR</string>
    </dict>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>$INSTALL_DIR/logs/mac-station.log</string>
    <key>StandardErrorPath</key>
    <string>$INSTALL_DIR/logs/mac-station-error.log</string>
</dict>
</plist>
PLIST

# sync-engine 服务
cat > "$LAUNCH_DIR/com.tunxiang.sync-engine.plist" << PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.tunxiang.sync-engine</string>
    <key>ProgramArguments</key>
    <array>
        <string>$INSTALL_DIR/.venv/bin/python</string>
        <string>$INSTALL_DIR/services/sync-engine/main.py</string>
    </array>
    <key>WorkingDirectory</key>
    <string>$INSTALL_DIR/services/sync-engine</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>$INSTALL_DIR/.venv/bin:/opt/homebrew/bin:/usr/bin:/bin</string>
        <key>PYTHONPATH</key>
        <string>$INSTALL_DIR</string>
    </dict>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>$INSTALL_DIR/logs/sync-engine.log</string>
    <key>StandardErrorPath</key>
    <string>$INSTALL_DIR/logs/sync-engine-error.log</string>
</dict>
</plist>
PLIST

mkdir -p "$INSTALL_DIR/logs"

# 加载服务
launchctl load "$LAUNCH_DIR/com.tunxiang.mac-station.plist" 2>/dev/null || true
launchctl load "$LAUNCH_DIR/com.tunxiang.sync-engine.plist" 2>/dev/null || true
echo "开机自启已配置 ✓"

# ─── Step 7: 验证 ───
echo -e "${GREEN}[7/7] 验证安装...${NC}"
sleep 3

if curl -sf http://localhost:8000/health &>/dev/null; then
    echo -e "${GREEN}Mac Station: 运行中 ✓${NC}"
else
    echo -e "${YELLOW}Mac Station: 启动中...（稍后检查 http://localhost:8000/health）${NC}"
fi

echo ""
echo -e "${GREEN}╔═══════════════════════════════════════╗${NC}"
echo -e "${GREEN}║       屯象OS 安装完成！               ║${NC}"
echo -e "${GREEN}╠═══════════════════════════════════════╣${NC}"
echo -e "${GREEN}║  Mac Station: http://localhost:8000   ║${NC}"
echo -e "${GREEN}║  日志目录:    $INSTALL_DIR/logs/      ║${NC}"
echo -e "${GREEN}║                                       ║${NC}"
echo -e "${GREEN}║  下一步：                              ║${NC}"
echo -e "${GREEN}║  1. iPad 打开 pos.tunxiangos.com     ║${NC}"
echo -e "${GREEN}║  2. 设置 → Mac mini 地址 → 本机IP    ║${NC}"
echo -e "${GREEN}║  3. 连接蓝牙/网络打印机               ║${NC}"
echo -e "${GREEN}╚═══════════════════════════════════════╝${NC}"
echo ""

INSTALL_SCRIPT
chmod +x "$APP_DIR/安装屯象OS.command"

# ─── 创建卸载脚本 ───
cat > "$APP_DIR/卸载屯象OS.command" << 'UNINSTALL_SCRIPT'
#!/usr/bin/env bash
set -euo pipefail

echo "确定要卸载屯象OS吗？(y/N)"
read -r confirm
[[ "$confirm" =~ ^[Yy]$ ]] || exit 0

launchctl unload ~/Library/LaunchAgents/com.tunxiang.mac-station.plist 2>/dev/null || true
launchctl unload ~/Library/LaunchAgents/com.tunxiang.sync-engine.plist 2>/dev/null || true
rm -f ~/Library/LaunchAgents/com.tunxiang.mac-station.plist
rm -f ~/Library/LaunchAgents/com.tunxiang.sync-engine.plist
sudo rm -rf /opt/tunxiang-os
echo "屯象OS 已卸载"
UNINSTALL_SCRIPT
chmod +x "$APP_DIR/卸载屯象OS.command"

# ─── 创建 README ───
cat > "$APP_DIR/README.txt" << 'README'
╔═══════════════════════════════════════╗
║     屯象OS Mac mini 安装包 v3.0      ║
║     AI-Native 连锁餐饮操作系统        ║
╚═══════════════════════════════════════╝

安装：双击「安装屯象OS.command」

卸载：双击「卸载屯象OS.command」

系统要求：
  - macOS 14.0+ (Sonoma)
  - Mac mini M1/M2/M4 (Apple Silicon)
  - 8GB+ 内存
  - 网络连接（首次安装需下载依赖）

包含组件：
  - Mac Station (门店本地 API 服务)
  - Sync Engine (云端数据同步)
  - Core ML Bridge (边缘 AI 推理)
  - PostgreSQL 16 (本地数据库)

技术支持：
  - 文档：https://docs.tunxiangos.com
  - 邮箱：support@tunxiangos.com
README

# ─── 生成 DMG ───
step "生成 DMG 安装包"

DMG_PATH="$PROJECT_ROOT/dist/$DMG_NAME"
rm -f "$DMG_PATH"

# 计算大小（MB + 20MB 余量）
SIZE_MB=$(du -sm "$APP_DIR" | cut -f1)
SIZE_MB=$((SIZE_MB + 20))

# 创建 DMG
hdiutil create \
    -volname "TunxiangOS" \
    -srcfolder "$APP_DIR" \
    -ov \
    -format UDZO \
    -imagekey zlib-level=9 \
    "$DMG_PATH"

# 清理临时目录
rm -rf "$BUILD_DIR"

# 结果
DMG_SIZE=$(du -sh "$DMG_PATH" | cut -f1)
log ""
log "========================================="
log "  DMG 安装包生成成功"
log "  文件: $DMG_PATH"
log "  大小: $DMG_SIZE"
log "========================================="
