#!/bin/bash
# deploy_models.sh — 将 CoreML 模型部署到 Mac mini M4
#
# 功能：
#   1. 从构建服务器 scp .mlpackage 文件到 Mac mini
#   2. 注册 launchd plist 实现 coreml-bridge 自动启动/崩溃重启
#   3. 健康检查验证部署结果
#
# 用法：
#   # 在构建服务器上运行（将模型推送到 Mac mini）：
#   bash deploy_models.sh push --host 192.168.1.50 --user tunxiang
#
#   # 在 Mac mini 上本地运行（模型已在本地）：
#   bash deploy_models.sh install --model-dir ./models
#
#   # 仅执行健康检查：
#   bash deploy_models.sh health-check
#
#   # 回滚到上一个版本：
#   bash deploy_models.sh rollback
#
# 前置条件：
#   - Mac mini 上已安装 Xcode Command Line Tools
#   - Swift Package 已编译（edge/coreml-bridge）
#   - SSH 免密登录（构建服务器 → Mac mini）

set -euo pipefail

# ─── 配置 ────────────────────────────────────────────────────────────────────

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

# 模型文件列表（相对于 edge/coreml-bridge/models/）
MODEL_FILES=(
    "dish_time_v1.mlpackage"
    "discount_risk_v1.mlpackage"
    "traffic_v1.mlpackage"
    "dish_price_v1.mlpackage"
    "dish_classifier_v1.mlpackage"
)

# Mac mini 上的部署路径
MAC_MINI_USER="${MAC_MINI_USER:-tunxiang}"
MAC_MINI_HOST="${MAC_MINI_HOST:-}"
MAC_MINI_MODEL_DIR="${MAC_MINI_MODEL_DIR:-/Users/tunxiang/coreml-bridge/Models}"
MAC_MINI_BRIDGE_DIR="${MAC_MINI_BRIDGE_DIR:-/Users/tunxiang/coreml-bridge}"
MAC_MINI_LAUNCHD_NAME="com.tunxiang.coreml-bridge"
MAC_MINI_HEALTH_URL="${MAC_MINI_HEALTH_URL:-http://localhost:8100/health}"
MAC_MINI_BRIDGE_PORT="${MAC_MINI_BRIDGE_PORT:-8100}"

# 本地模型构建目录
LOCAL_MODEL_DIR="${LOCAL_MODEL_DIR:-${PROJECT_ROOT}/edge/coreml-bridge/models}"

# 回滚保留版本数
KEEP_VERSIONS="${KEEP_VERSIONS:-3}"

# 颜色输出
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log_info()  { echo -e "${GREEN}[deploy_models]${NC} $*"; }
log_warn()  { echo -e "${YELLOW}[deploy_models]${NC} $*"; }
log_error() { echo -e "${RED}[deploy_models]${NC} $*"; }

# ─── 参数解析 ────────────────────────────────────────────────────────────────

usage() {
    cat <<EOF
Usage: $0 <command> [options]

Commands:
  push        从构建服务器推送模型到 Mac mini（SCP + launchd 注册）
  install     在 Mac mini 本地安装模型（模型已在本地目录）
  health-check  验证部署（bridge 可达性 + 模型加载状态）
  rollback    回滚到上一个版本
  status      查看当前部署状态

Options:
  --host HOST         Mac mini IP/主机名（push 命令必需）
  --user USER         SSH 用户（默认: tunxiang）
  --model-dir DIR     本地模型目录（默认: edge/coreml-bridge/models/）
  --port PORT         Bridge 端口（默认: 8100）

Examples:
  $0 push --host 192.168.1.50
  $0 install --model-dir ./models
  $0 health-check
EOF
    exit 0
}

COMMAND="${1:-}"
shift || true

while [[ $# -gt 0 ]]; do
    case "$1" in
        --host)      MAC_MINI_HOST="$2"; shift 2 ;;
        --user)      MAC_MINI_USER="$2"; shift 2 ;;
        --model-dir) LOCAL_MODEL_DIR="$2"; shift 2 ;;
        --port)      MAC_MINI_BRIDGE_PORT="$2"; shift 2 ;;
        --help|-h)   usage ;;
        *)           log_error "unknown option: $1"; usage ;;
    esac
done

# ─── 工具函数 ────────────────────────────────────────────────────────────────

_ssh_cmd() {
    if [ -n "${MAC_MINI_HOST:-}" ]; then
        ssh "${MAC_MINI_USER}@${MAC_MINI_HOST}" "$@"
    else
        eval "$@"
    fi
}

_scp_to_host() {
    local src="$1"
    local dst="$2"
    if [ -n "${MAC_MINI_HOST:-}" ]; then
        scp -r "$src" "${MAC_MINI_USER}@${MAC_MINI_HOST}:${dst}"
    else
        cp -r "$src" "$dst"
    fi
}

_backup_existing_models() {
    # 在 Mac mini 上备份现有模型
    local backup_dir="${MAC_MINI_MODEL_DIR}/backups/$(date +%Y%m%d_%H%M%S)"
    log_info "backing up existing models to ${backup_dir}"

    _ssh_cmd "mkdir -p ${backup_dir}"
    for model in "${MODEL_FILES[@]}"; do
        _ssh_cmd "if [ -d ${MAC_MINI_MODEL_DIR}/${model} ]; then cp -r ${MAC_MINI_MODEL_DIR}/${model} ${backup_dir}/; fi" || true
    done

    # 清理旧备份（保留最近 KEEP_VERSIONS 个）
    _ssh_cmd "ls -dt ${MAC_MINI_MODEL_DIR}/backups/*/ 2>/dev/null | tail -n +$((KEEP_VERSIONS + 1)) | xargs rm -rf" || true
}

# ─── Commands ────────────────────────────────────────────────────────────────

cmd_push() {
    if [ -z "${MAC_MINI_HOST:-}" ]; then
        log_error "--host is required for push command"
        exit 1
    fi

    log_info "pushing models to ${MAC_MINI_USER}@${MAC_MINI_HOST}"

    # 1. 验证本地模型存在
    local missing=()
    for model in "${MODEL_FILES[@]}"; do
        if [ ! -d "${LOCAL_MODEL_DIR}/${model}" ] && [ ! -f "${LOCAL_MODEL_DIR}/${model}" ]; then
            missing+=("$model")
        fi
    done

    if [ ${#missing[@]} -gt 0 ]; then
        log_warn "missing model files (will skip): ${missing[*]}"
    fi

    # 2. 在 Mac mini 上创建目标目录
    _ssh_cmd "mkdir -p ${MAC_MINI_MODEL_DIR}"

    # 3. 备份现有模型
    _backup_existing_models

    # 4. SCP 推送模型
    log_info "transferring models..."
    for model in "${MODEL_FILES[@]}"; do
        local src="${LOCAL_MODEL_DIR}/${model}"
        if [ -d "$src" ] || [ -f "$src" ]; then
            local dst="${MAC_MINI_MODEL_DIR}/${model}"
            _scp_to_host "$src" "$dst"
            log_info "  transferred: ${model}"
        fi
    done

    # 5. 安装 launchd plist（如果尚未安装）
    _install_launchd

    # 6. 重启 bridge
    _restart_bridge

    # 7. 健康检查
    sleep 3
    cmd_health_check
}

cmd_install() {
    log_info "installing models locally on Mac mini"

    # 1. 验证本地模型存在
    local found=0
    _ssh_cmd "mkdir -p ${MAC_MINI_MODEL_DIR}"

    for model in "${MODEL_FILES[@]}"; do
        local src="${LOCAL_MODEL_DIR}/${model}"
        if [ -d "$src" ] || [ -f "$src" ]; then
            _backup_existing_models
            _scp_to_host "$src" "${MAC_MINI_MODEL_DIR}/${model}"
            log_info "  installed: ${model}"
            found=$((found + 1))
        fi
    done

    if [ "$found" -eq 0 ]; then
        log_warn "no model files found in ${LOCAL_MODEL_DIR}"
        log_info "expected models: ${MODEL_FILES[*]}"
    fi

    # 2. 安装 launchd
    _install_launchd

    # 3. 重启 bridge
    _restart_bridge

    # 4. 健康检查
    sleep 3
    cmd_health_check
}

_install_launchd() {
    local plist_name="${MAC_MINI_LAUNCHD_NAME}.plist"
    local plist_path="${HOME}/Library/LaunchAgents/${plist_name}"

    log_info "installing launchd plist: ${plist_path}"

    cat <<PLIST | _ssh_cmd "cat > ${plist_path}"
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>${MAC_MINI_LAUNCHD_NAME}</string>

    <key>ProgramArguments</key>
    <array>
        <string>${MAC_MINI_BRIDGE_DIR}/.build/release/CoreMLBridge</string>
        <string>--port</string>
        <string>${MAC_MINI_BRIDGE_PORT}</string>
        <string>--model-dir</string>
        <string>${MAC_MINI_MODEL_DIR}</string>
    </array>

    <key>RunAtLoad</key>
    <true/>

    <key>KeepAlive</key>
    <true/>

    <key>ThrottleInterval</key>
    <integer>5</integer>

    <key>WorkingDirectory</key>
    <string>${MAC_MINI_BRIDGE_DIR}</string>

    <key>StandardOutPath</key>
    <string>${MAC_MINI_BRIDGE_DIR}/logs/bridge-stdout.log</string>

    <key>StandardErrorPath</key>
    <string>${MAC_MINI_BRIDGE_DIR}/logs/bridge-stderr.log</string>

    <key>EnvironmentVariables</key>
    <dict>
        <key>COREML_MODEL_DIR</key>
        <string>${MAC_MINI_MODEL_DIR}</string>
        <key>BRIDGE_PORT</key>
        <string>${MAC_MINI_BRIDGE_PORT}</string>
    </dict>

    <key>ProcessType</key>
    <string>Interactive</string>
</dict>
</plist>
PLIST

    # 创建日志目录
    _ssh_cmd "mkdir -p ${MAC_MINI_BRIDGE_DIR}/logs"

    # 加载 launchd
    _ssh_cmd "launchctl bootout gui/\$(id -u)/${MAC_MINI_LAUNCHD_NAME} 2>/dev/null || true"
    _ssh_cmd "launchctl bootstrap gui/\$(id -u) ${plist_path}"
    log_info "launchd plist installed and loaded"
}

_restart_bridge() {
    log_info "restarting coreml-bridge..."

    _ssh_cmd "launchctl bootout gui/\$(id -u)/${MAC_MINI_LAUNCHD_NAME} 2>/dev/null || true"
    _ssh_cmd "launchctl bootstrap gui/\$(id -u) ${HOME}/Library/LaunchAgents/${MAC_MINI_LAUNCHD_NAME}.plist"

    log_info "bridge restarted, waiting for readiness..."
    sleep 2
}

cmd_health_check() {
    log_info "checking bridge health at ${MAC_MINI_HEALTH_URL}..."

    local max_retries=10
    local retry=0

    while [ $retry -lt $max_retries ]; do
        local response
        response=$(_ssh_cmd "curl -s -o /dev/null -w '%{http_code}' ${MAC_MINI_HEALTH_URL}" 2>/dev/null || echo "000")

        if [ "$response" = "200" ]; then
            log_info "bridge health: OK (HTTP 200)"
            break
        fi

        retry=$((retry + 1))
        if [ $retry -lt $max_retries ]; then
            log_warn "bridge not ready (attempt ${retry}/${max_retries}), retrying in 2s..."
            sleep 2
        else
            log_error "bridge health check FAILED after ${max_retries} attempts"
            return 1
        fi
    done

    # 获取详细健康信息
    local health_json
    health_json=$(_ssh_cmd "curl -s ${MAC_MINI_HEALTH_URL}" 2>/dev/null || echo "{}")
    log_info "bridge health detail: ${health_json}"

    # 检查模型加载状态
    local models_loaded
    models_loaded=$(echo "$health_json" | python3 -c "import json,sys; d=json.load(sys.stdin); print(len(d.get('models_loaded',[])))" 2>/dev/null || echo "0")

    if [ "$models_loaded" -gt 0 ]; then
        log_info "models loaded: ${models_loaded}"
    else
        log_warn "no CoreML models loaded (bridge running in fallback mode)"
        log_info "this is expected if .mlpackage files are not yet trained/present"
        log_info "run: python edge/coreml-bridge/scripts/train_dish_time.py --samples 5000"
    fi
}

cmd_rollback() {
    log_info "rolling back to previous model version..."

    local backups
    backups=$(_ssh_cmd "ls -dt ${MAC_MINI_MODEL_DIR}/backups/*/ 2>/dev/null | head -2" || echo "")

    if [ -z "$backups" ]; then
        log_error "no backup found to rollback to"
        exit 1
    fi

    # 取最新的备份（即回滚目标）—— 当前运行的是比最新备份更新的版本
    local rollback_target
    rollback_target=$(echo "$backups" | head -1)
    log_info "rolling back to: ${rollback_target}"

    _backup_existing_models  # 当前版本也备份

    for model in "${MODEL_FILES[@]}"; do
        local backup_model="${rollback_target%/}/${model}"
        _ssh_cmd "if [ -d ${backup_model} ]; then rm -rf ${MAC_MINI_MODEL_DIR}/${model} && cp -r ${backup_model} ${MAC_MINI_MODEL_DIR}/${model}; fi" || true
    done

    _restart_bridge
    sleep 3
    cmd_health_check
}

cmd_status() {
    log_info "deployment status:"

    # Bridge 进程状态
    log_info "--- bridge process ---"
    _ssh_cmd "pgrep -fl CoreMLBridge || echo '  (not running)'"

    # launchd 状态
    log_info "--- launchd ---"
    _ssh_cmd "launchctl print gui/\$(id -u)/${MAC_MINI_LAUNCHD_NAME} 2>/dev/null | head -5 || echo '  (not loaded)'"

    # 模型文件
    log_info "--- model files ---"
    _ssh_cmd "ls -la ${MAC_MINI_MODEL_DIR}/*.mlpackage 2>/dev/null || echo '  (no .mlpackage found)'"

    # 健康检查
    log_info "--- health ---"
    cmd_health_check
}

# ─── 主入口 ──────────────────────────────────────────────────────────────────

case "${COMMAND}" in
    push)
        cmd_push
        ;;
    install)
        cmd_install
        ;;
    health-check)
        cmd_health_check
        ;;
    rollback)
        cmd_rollback
        ;;
    status)
        cmd_status
        ;;
    *)
        usage
        ;;
esac
