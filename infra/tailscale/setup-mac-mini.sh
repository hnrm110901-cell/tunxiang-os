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

# 7. Core ML Bridge Swift 构建
echo ""
echo "=== Building Core ML Bridge (Swift) ==="
COREML_DIR="$TXOS_DIR/edge/coreml-bridge"
if [ -d "$COREML_DIR" ]; then
    echo "Building coreml-bridge with Swift..."
    cd "$COREML_DIR"

    # 确保 Xcode Command Line Tools 已安装
    if ! xcode-select -p &>/dev/null; then
        echo "Installing Xcode Command Line Tools..."
        xcode-select --install
        echo "Please complete Xcode CLI Tools installation and re-run this script."
        exit 1
    fi

    # 使用 Swift Package Manager 构建
    if [ -f "Package.swift" ]; then
        swift build -c release
        COREML_BIN=$(swift build -c release --show-bin-path)/coreml-bridge
        echo "Core ML Bridge built: $COREML_BIN"
    else
        echo "Warning: Package.swift not found in $COREML_DIR, skipping Swift build."
        echo "Please create the Swift package first."
    fi

    # coreml-bridge launchd 配置
    cat > ~/Library/LaunchAgents/com.tunxiang.coreml-bridge.plist << PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.tunxiang.coreml-bridge</string>
    <key>ProgramArguments</key>
    <array>
        <string>$TXOS_DIR/edge/coreml-bridge/.build/release/coreml-bridge</string>
        <string>--port</string>
        <string>8100</string>
    </array>
    <key>WorkingDirectory</key>
    <string>$TXOS_DIR/edge/coreml-bridge</string>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>$TXOS_DIR/logs/coreml-bridge.log</string>
    <key>StandardErrorPath</key>
    <string>$TXOS_DIR/logs/coreml-bridge.error.log</string>
</dict>
</plist>
PLIST
    echo "Core ML Bridge launchd service configured."
else
    echo "Warning: $COREML_DIR not found, skipping Core ML Bridge build."
fi
cd "$TXOS_DIR"

# 8. 本地 PG 数据库 schema 初始化（Alembic 迁移）
echo ""
echo "=== Initializing Local PostgreSQL Schema ==="
DB_MIGRATIONS_DIR="$TXOS_DIR/shared/db-migrations"
if [ -d "$DB_MIGRATIONS_DIR" ]; then
    echo "Running Alembic migrations on local database..."

    # 安装 Alembic 如果未安装
    pip3 install --user alembic psycopg2-binary 2>/dev/null || true

    # 设置本地数据库 URL
    export LOCAL_DATABASE_URL="${LOCAL_DATABASE_URL:-postgresql://$(whoami)@localhost/tunxiang_local}"

    # 确保数据库存在
    createdb tunxiang_local 2>/dev/null || echo "Database tunxiang_local already exists."

    # 运行 Alembic 迁移
    cd "$DB_MIGRATIONS_DIR"
    if [ -f "alembic.ini" ]; then
        DATABASE_URL="$LOCAL_DATABASE_URL" alembic upgrade head
        echo "Alembic migrations applied successfully."
    else
        echo "Warning: alembic.ini not found. Running migration scripts directly..."
        # 回退方案：直接用 psql 运行迁移 SQL
        for migration in versions/*.py; do
            echo "  Registered migration: $(basename "$migration")"
        done
        echo "Please run 'alembic upgrade head' manually after configuring alembic.ini"
    fi
    cd "$TXOS_DIR"
else
    echo "Warning: $DB_MIGRATIONS_DIR not found, skipping schema init."
fi

# 9. sync-engine 云端 DB URL 配置
echo ""
echo "=== Configuring sync-engine Cloud DB URL ==="
SYNC_ENGINE_DIR="$TXOS_DIR/edge/sync-engine"
SYNC_ENV_FILE="$SYNC_ENGINE_DIR/.env"

if [ -d "$SYNC_ENGINE_DIR" ]; then
    # 创建 .env 文件（如果不存在）
    if [ ! -f "$SYNC_ENV_FILE" ]; then
        cat > "$SYNC_ENV_FILE" << ENVFILE
# sync-engine 配置
# 本地数据库（Mac mini PostgreSQL）
LOCAL_DATABASE_URL=postgresql://$(whoami)@localhost/tunxiang_local

# 云端数据库（腾讯云 PostgreSQL）— 部署时填入实际值
CLOUD_DATABASE_URL=postgresql+asyncpg://tunxiang:CHANGE_ME@cloud-db.tunxiang.com:5432/tunxiang_os

# 同步间隔（秒）
SYNC_INTERVAL_SECONDS=300

# 冲突解决策略: cloud_wins / local_wins / latest_wins
CONFLICT_STRATEGY=cloud_wins

# 门店标识（用于 RLS 过滤）
STORE_ID=${STORE_ID:-}
TENANT_ID=${TENANT_ID:-}
ENVFILE
        echo "sync-engine .env created at $SYNC_ENV_FILE"
        echo "[ACTION REQUIRED] Please edit $SYNC_ENV_FILE with actual cloud DB credentials."
    else
        echo "sync-engine .env already exists at $SYNC_ENV_FILE"
    fi
else
    echo "Warning: $SYNC_ENGINE_DIR not found."
fi

# 10. UPS 关机脚本配置
echo ""
echo "=== Configuring UPS Shutdown Script ==="
UPS_SCRIPT="$TXOS_DIR/scripts/ups-shutdown.sh"
mkdir -p "$TXOS_DIR/scripts"

cat > "$UPS_SCRIPT" << 'UPSSCRIPT'
#!/bin/bash
# UPS 断电安全关机脚本
# 当 UPS 检测到市电中断后触发此脚本
#
# 配合 apcupsd 或 NUT (Network UPS Tools) 使用:
#   apcupsd: 将此脚本路径写入 /etc/apcupsd/apccontrol
#   NUT:     配置 upsmon SHUTDOWNCMD

set -euo pipefail

TXOS_DIR="$HOME/tunxiang-os"
LOG_FILE="$TXOS_DIR/logs/ups-shutdown.log"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG_FILE"
}

log "=== UPS Power Loss Detected — Starting Safe Shutdown ==="

# 1. 通知云端（尽力而为）
log "Notifying cloud about power loss..."
curl -s -m 5 -X POST "${CLOUD_API_URL:-http://localhost:8000}/api/v1/edge/power-loss" \
    -H "Content-Type: application/json" \
    -d "{\"store_id\": \"${STORE_ID:-unknown}\", \"event\": \"ups_power_loss\", \"timestamp\": \"$(date -u +%Y-%m-%dT%H:%M:%SZ)\"}" \
    2>/dev/null || log "Warning: Cloud notification failed (expected if offline)"

# 2. 停止应用服务（优雅关闭）
log "Stopping TunxiangOS services..."
launchctl unload ~/Library/LaunchAgents/com.tunxiang.mac-station.plist 2>/dev/null || true
launchctl unload ~/Library/LaunchAgents/com.tunxiang.sync-engine.plist 2>/dev/null || true
launchctl unload ~/Library/LaunchAgents/com.tunxiang.coreml-bridge.plist 2>/dev/null || true
log "Services stopped."

# 3. 确保 PostgreSQL 数据落盘
log "Flushing PostgreSQL data..."
pg_ctl stop -D /usr/local/var/postgresql@16 -m fast 2>/dev/null || \
    brew services stop postgresql@16 2>/dev/null || \
    log "Warning: Could not stop PostgreSQL gracefully"
log "PostgreSQL stopped."

# 4. 同步文件系统
log "Syncing filesystem..."
sync

# 5. 关机
log "Initiating system shutdown..."
sudo shutdown -h now
UPSSCRIPT

chmod +x "$UPS_SCRIPT"
echo "UPS shutdown script created at $UPS_SCRIPT"

# 配置 apcupsd（如果 UPS 是 APC 品牌）
if command -v apcupsd &>/dev/null; then
    echo "apcupsd detected. Configure /etc/apcupsd/apccontrol to call $UPS_SCRIPT"
else
    echo "Tip: Install apcupsd for APC UPS: brew install apcupsd"
    echo "  Or install NUT for other UPS brands: brew install nut"
fi

# 11. 启动服务
echo ""
echo "=== Starting Services ==="
launchctl load ~/Library/LaunchAgents/com.tunxiang.mac-station.plist
launchctl load ~/Library/LaunchAgents/com.tunxiang.sync-engine.plist
if [ -f ~/Library/LaunchAgents/com.tunxiang.coreml-bridge.plist ]; then
    launchctl load ~/Library/LaunchAgents/com.tunxiang.coreml-bridge.plist
fi

# 12. 服务健康检查验证
echo ""
echo "=== Running Health Checks ==="
sleep 3  # 等待服务启动

check_service() {
    local name="$1"
    local url="$2"
    local max_retries="${3:-5}"
    local retry=0

    while [ $retry -lt $max_retries ]; do
        if curl -s -o /dev/null -w "%{http_code}" "$url" 2>/dev/null | grep -q "200"; then
            echo "  [OK] $name — $url"
            return 0
        fi
        retry=$((retry + 1))
        sleep 2
    done
    echo "  [FAIL] $name — $url (not responding after ${max_retries} retries)"
    return 1
}

HEALTH_OK=true
check_service "Mac Station" "http://localhost:8000/health" || HEALTH_OK=false
check_service "Core ML Bridge" "http://localhost:8100/health" 3 || echo "  (Core ML Bridge is optional)"

# 检查 PostgreSQL
if pg_isready -q 2>/dev/null; then
    echo "  [OK] PostgreSQL — running"
else
    echo "  [FAIL] PostgreSQL — not running"
    HEALTH_OK=false
fi

# 检查 Tailscale
if tailscale status &>/dev/null; then
    TS_IP=$(tailscale ip -4 2>/dev/null || echo "unknown")
    echo "  [OK] Tailscale — connected (IP: ${TS_IP})"
else
    echo "  [WARN] Tailscale — not connected. Run: sudo tailscale up --authkey=YOUR_KEY"
fi

echo ""
echo "=== Setup Complete ==="
echo ""
echo "Services:"
echo "  Mac Station:    http://localhost:8000/health"
echo "  Core ML Bridge: http://localhost:8100/health"
echo "  PostgreSQL:     localhost:5432/tunxiang_local"
echo ""
if [ "$HEALTH_OK" = true ]; then
    echo "All critical services are running."
else
    echo "[WARNING] Some services failed health checks. Please investigate."
fi
echo ""
echo "Next steps:"
echo "  1. Configure Tailscale: STORE_ID=store-xxx TAILSCALE_AUTH_KEY=tskey-xxx bash infra/tailscale/tailscale-config.sh"
echo "  2. Edit sync-engine .env with cloud DB credentials: $SYNC_ENV_FILE"
echo "  3. Connect UPS and configure shutdown script: $UPS_SCRIPT"
