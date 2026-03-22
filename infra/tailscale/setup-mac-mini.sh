#!/bin/bash
# Mac mini 首次部署脚本
# 运行方式：ssh admin@mac-mini "bash -s" < setup-mac-mini.sh

set -euo pipefail
echo "=== TunxiangOS Mac mini Setup ==="

# 1. Homebrew
if ! command -v brew &>/dev/null; then
    echo "Installing Homebrew..."
    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
fi

# 2. PostgreSQL 16
echo "Installing PostgreSQL 16..."
brew install postgresql@16
brew services start postgresql@16
createdb tunxiang_local 2>/dev/null || true

# 3. Python 3.11+
echo "Installing Python..."
brew install python@3.11
pip3 install --user fastapi uvicorn sqlalchemy asyncpg httpx structlog websockets

# 4. Tailscale
echo "Installing Tailscale..."
brew install tailscale
# 需要手动登录：sudo tailscale up --authkey=tskey-xxx

# 5. 创建服务目录
TXOS_DIR="$HOME/tunxiang-os"
mkdir -p "$TXOS_DIR"
echo "Service directory: $TXOS_DIR"

# 6. launchd 服务配置
echo "Installing launchd services..."
mkdir -p ~/Library/LaunchAgents

# mac-station
cat > ~/Library/LaunchAgents/com.tunxiang.mac-station.plist << 'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.tunxiang.mac-station</string>
    <key>ProgramArguments</key>
    <array>
        <string>/usr/local/bin/python3</string>
        <string>-m</string>
        <string>uvicorn</string>
        <string>src.main:app</string>
        <string>--host</string>
        <string>0.0.0.0</string>
        <string>--port</string>
        <string>8000</string>
    </array>
    <key>WorkingDirectory</key>
    <string>~/tunxiang-os/edge/mac-station</string>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>~/tunxiang-os/logs/mac-station.log</string>
    <key>StandardErrorPath</key>
    <string>~/tunxiang-os/logs/mac-station.error.log</string>
</dict>
</plist>
PLIST

# sync-engine
cat > ~/Library/LaunchAgents/com.tunxiang.sync-engine.plist << 'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.tunxiang.sync-engine</string>
    <key>ProgramArguments</key>
    <array>
        <string>/usr/local/bin/python3</string>
        <string>src/main.py</string>
    </array>
    <key>WorkingDirectory</key>
    <string>~/tunxiang-os/edge/sync-engine</string>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>~/tunxiang-os/logs/sync-engine.log</string>
    <key>StandardErrorPath</key>
    <string>~/tunxiang-os/logs/sync-engine.error.log</string>
</dict>
</plist>
PLIST

mkdir -p ~/tunxiang-os/logs

# 7. 启动服务
launchctl load ~/Library/LaunchAgents/com.tunxiang.mac-station.plist
launchctl load ~/Library/LaunchAgents/com.tunxiang.sync-engine.plist

echo ""
echo "=== Setup Complete ==="
echo "Mac Station: http://localhost:8000/health"
echo "Core ML Bridge: http://localhost:8100/health (需要单独构建 Swift)"
echo "Tailscale: sudo tailscale up --authkey=YOUR_KEY"
echo ""
echo "下一步："
echo "  1. 配置 Tailscale 连接云端"
echo "  2. 配置本地 PG 数据库 schema"
echo "  3. 构建并部署 coreml-bridge"
