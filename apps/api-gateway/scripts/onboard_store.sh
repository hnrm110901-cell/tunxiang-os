#!/usr/bin/env bash
# =============================================================================
# 屯象OS 门店边缘节点快速接入脚本
#
# 作用：
#   1. 从云端动态发放 Bootstrap Token
#   2. 输出完整安装命令（本地一键 or SSH 远程）
#   3. 可选：直接触发 SSH 远程安装
#
# 用法：
#   bash scripts/onboard_store.sh \
#     --api-url    https://api.zlsjos.cn \
#     --admin-jwt  <管理员JWT> \
#     --store-id   CZYZ-2461 \
#     --store-name "尝在一起文化园店" \
#     --pi-ip      192.168.10.101 \
#     [--execute]               # 加此参数则直接执行 SSH 安装
#
# =============================================================================
set -euo pipefail

API_URL=""
ADMIN_JWT=""
STORE_ID=""
STORE_NAME=""
PI_IP=""
PI_USER="${PI_USER:-pi}"
SSH_KEY="${SSH_KEY:-}"
EXECUTE=0
SHOKZ_SECRET=""

usage() {
  cat <<EOF
用法:
  bash $0 \\
    --api-url    https://api.zlsjos.cn \\
    --admin-jwt  <管理员JWT> \\
    --store-id   CZYZ-2461 \\
    --store-name "尝在一起文化园店" \\
    --pi-ip      <树莓派IP> \\
    [--pi-user   tunxiangos]        # 默认 pi，如系统用户不同请指定 \\
    [--ssh-key   ~/.ssh/id_ed25519] \\
    [--execute]
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --api-url)    API_URL="$2";    shift 2 ;;
    --admin-jwt)  ADMIN_JWT="$2";  shift 2 ;;
    --store-id)   STORE_ID="$2";   shift 2 ;;
    --store-name) STORE_NAME="$2"; shift 2 ;;
    --pi-ip)      PI_IP="$2";      shift 2 ;;
    --pi-user)    PI_USER="$2";    shift 2 ;;
    --ssh-key)    SSH_KEY="$2";    shift 2 ;;
    --execute)    EXECUTE=1;       shift ;;
    --help)       usage; exit 0 ;;
    *) echo "未知参数: $1" >&2; usage; exit 1 ;;
  esac
done

if [[ -z "${API_URL}" || -z "${ADMIN_JWT}" || -z "${STORE_ID}" ]]; then
  echo "错误: --api-url, --admin-jwt, --store-id 为必填参数" >&2
  usage; exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

echo
echo "========================================================"
echo "  屯象OS 门店边缘节点接入"
echo "  门店ID   : ${STORE_ID}"
echo "  门店名称 : ${STORE_NAME}"
echo "  API      : ${API_URL}"
echo "========================================================"
echo

# ── 步骤 1: 从云端发放 Bootstrap Token ──────────────────────────────────────
echo "步骤 1/4  发放 Bootstrap Token …"
TOKEN_RESP="$(curl -s -X POST "${API_URL}/api/v1/hardware/admin/bootstrap-token/issue" \
  -H "Authorization: Bearer ${ADMIN_JWT}" \
  -H "Content-Type: application/json" \
  -d "{\"note\": \"${STORE_NAME:-${STORE_ID}} $(date +%Y-%m-%d)\", \"store_id\": \"${STORE_ID}\", \"ttl_days\": 7}")"

BOOTSTRAP_TOKEN="$(echo "${TOKEN_RESP}" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('token',''))" 2>/dev/null || echo "")"

if [[ -z "${BOOTSTRAP_TOKEN}" ]]; then
  echo "错误: 获取 Bootstrap Token 失败，响应:" >&2
  echo "${TOKEN_RESP}" >&2
  exit 1
fi
echo "  ✅ Token 已发放（前16位）: ${BOOTSTRAP_TOKEN:0:16}…"

# ── 步骤 2: 生成 Shokz 回调密钥 ────────────────────────────────────────────
SHOKZ_SECRET="$(python3 -c "import secrets; print(secrets.token_hex(16))")"
DEVICE_NAME="$(echo "${STORE_ID}" | tr '[:upper:]' '[:lower:]' | tr '_' '-')-rpi5"

echo
echo "步骤 2/4  生成配置参数 …"
echo "  Device Name  : ${DEVICE_NAME}"
echo "  Shokz Secret : ${SHOKZ_SECRET}"

# ── 步骤 3: 输出安装命令 ────────────────────────────────────────────────────
echo
echo "步骤 3/4  安装命令"
echo
echo "  ┌─ 方式A: SSH 远程安装（在开发机执行）─────────────────────────────"
if [[ -n "${PI_IP}" ]]; then
  SSH_KEY_ARG=""
  [[ -n "${SSH_KEY}" ]] && SSH_KEY_ARG=" SSH_KEY=${SSH_KEY}"
  cat <<INSTALL_CMD

  cd ${APP_DIR}
  sudo EDGE_API_BASE_URL=${API_URL} \\
       EDGE_API_TOKEN=${BOOTSTRAP_TOKEN} \\
       EDGE_STORE_ID=${STORE_ID} \\
       EDGE_DEVICE_NAME=${DEVICE_NAME} \\
       EDGE_SHOKZ_CALLBACK_SECRET=${SHOKZ_SECRET} \\
       REMOTE_HOST=${PI_IP} \\
       REMOTE_USER=${PI_USER}${SSH_KEY_ARG} \\
       bash scripts/install_raspberry_pi_edge_remote.sh

INSTALL_CMD
else
  echo
  echo "  （未提供 --pi-ip，将输出本地安装命令）"
  cat <<INSTALL_CMD

  cd ${APP_DIR}
  sudo EDGE_API_BASE_URL=${API_URL} \\
       EDGE_API_TOKEN=${BOOTSTRAP_TOKEN} \\
       EDGE_STORE_ID=${STORE_ID} \\
       EDGE_DEVICE_NAME=${DEVICE_NAME} \\
       EDGE_SHOKZ_CALLBACK_SECRET=${SHOKZ_SECRET} \\
       bash scripts/install_raspberry_pi_edge.sh

INSTALL_CMD
fi
echo "  └────────────────────────────────────────────────────────────────"

# ── 步骤 4: 可选：直接执行 SSH 安装 ────────────────────────────────────────
if [[ "${EXECUTE}" -eq 1 && -n "${PI_IP}" ]]; then
  echo
  echo "步骤 4/4  执行 SSH 远程安装 …"
  SSH_KEY_ARGS=()
  [[ -n "${SSH_KEY}" ]] && SSH_KEY_ARGS=(-i "${SSH_KEY}")

  sudo \
    EDGE_API_BASE_URL="${API_URL}" \
    EDGE_API_TOKEN="${BOOTSTRAP_TOKEN}" \
    EDGE_STORE_ID="${STORE_ID}" \
    EDGE_DEVICE_NAME="${DEVICE_NAME}" \
    EDGE_SHOKZ_CALLBACK_SECRET="${SHOKZ_SECRET}" \
    REMOTE_HOST="${PI_IP}" \
    REMOTE_USER="${PI_USER}" \
    bash "${SCRIPT_DIR}/install_raspberry_pi_edge_remote.sh"

  echo
  echo "步骤 4/4  健康检查 …"
  SSH_OPTS=(-o StrictHostKeyChecking=no "${SSH_KEY_ARGS[@]}")
  ssh "${SSH_OPTS[@]}" "${PI_USER}@${PI_IP}" "zhilian-check" || true
else
  echo
  echo "步骤 4/4  ⬜ 跳过（未传 --execute 或未提供 --pi-ip）"
fi

echo
echo "========================================================"
echo "  ✅ 接入准备完成"
echo "  门店  : ${STORE_NAME} (${STORE_ID})"
echo "  Token : ${BOOTSTRAP_TOKEN:0:20}… (7天有效，用后请到管理后台吊销)"
echo "  设备名: ${DEVICE_NAME}"
echo
echo "  验证："
echo "    ssh ${PI_USER}@${PI_IP:-<PI_IP>} 'zhilian-check'"
echo "    zhilian-queue stats"
echo "    zhilian-models list"
echo "========================================================"
