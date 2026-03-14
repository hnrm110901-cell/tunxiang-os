#!/usr/bin/env bash
# =============================================================================
# 屯象OS 树莓派5 边缘节点定制镜像构建脚本
#
# 目标
# ----
# 生成一个可直接烧录的 .img 文件，烧录后开机自动：
#   1. 首次联网完成边缘节点注册
#   2. 启动 edge-node / edge-shokz 服务
#   3. 无需手动 SSH 配置
#
# 前置依赖（运行在 Linux x86-64 构建机上）
# -----------------------------------------
#   apt: kpartx qemu-user-static binfmt-support wget xz-utils
#   可选: pv（显示进度条）
#
# 用法
# ----
#   sudo bash scripts/build_edge_image.sh \
#     --api-url    https://api.zlsjos.cn \
#     --token      your-bootstrap-token \
#     --wifi-ssid  MyWifi \
#     --wifi-pass  MyPassword \
#     --output     zhilian-edge-20260314.img
#
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
EDGE_DIR="${APP_DIR}/edge"
BUILD_DIR="${APP_DIR}/build/edge-image"

# ---------- 默认参数 ----------
API_URL=""
BOOTSTRAP_TOKEN=""
WIFI_SSID=""
WIFI_PASS=""
OUTPUT_IMG="${BUILD_DIR}/zhilian-edge-$(date +%Y%m%d).img"
HOSTNAME_PREFIX="zhilian-edge"

# Raspberry Pi OS Lite (ARM64) 下载地址（定期更新为最新版）
RPI_OS_URL="https://downloads.raspberrypi.com/raspios_lite_arm64/images/raspios_lite_arm64-2024-11-19/2024-11-19-raspios-bookworm-arm64-lite.img.xz"
RPI_OS_SHA256="sha256sum.txt"  # 与 img.xz 同目录

usage() {
  cat <<EOF
用法:
  sudo bash $0 \\
    --api-url    https://api.zlsjos.cn \\
    --token      <bootstrap-token> \\
    [--wifi-ssid  <SSID>] \\
    [--wifi-pass  <PASSWORD>] \\
    [--output     <output.img>]

选项:
  --api-url     API Gateway 地址（必填）
  --token       Bootstrap Token（必填）
  --wifi-ssid   WiFi SSID（可选，有线网络可不填）
  --wifi-pass   WiFi 密码（可选）
  --output      输出镜像路径（默认：build/edge-image/zhilian-edge-DATE.img）
  --help        显示此帮助
EOF
}

# ---------- 解析参数 ----------
while [[ $# -gt 0 ]]; do
  case "$1" in
    --api-url)    API_URL="$2";         shift 2 ;;
    --token)      BOOTSTRAP_TOKEN="$2"; shift 2 ;;
    --wifi-ssid)  WIFI_SSID="$2";       shift 2 ;;
    --wifi-pass)  WIFI_PASS="$2";       shift 2 ;;
    --output)     OUTPUT_IMG="$2";      shift 2 ;;
    --help)       usage; exit 0 ;;
    *) echo "未知参数: $1" >&2; usage; exit 1 ;;
  esac
done

# ---------- 校验 ----------
if [[ -z "${API_URL}" || -z "${BOOTSTRAP_TOKEN}" ]]; then
  echo "错误: --api-url 和 --token 为必填参数" >&2
  usage; exit 1
fi

if [[ "$(id -u)" -ne 0 ]]; then
  echo "错误: 此脚本需要 root 权限（sudo）" >&2
  exit 1
fi

# ---------- 检查依赖 ----------
for dep in kpartx qemu-aarch64-static wget xz; do
  if ! command -v "${dep}" &>/dev/null; then
    echo "错误: 缺少依赖 ${dep}，请先安装：apt install kpartx qemu-user-static binfmt-support wget xz-utils" >&2
    exit 1
  fi
done

# ---------- 准备工作目录 ----------
mkdir -p "${BUILD_DIR}"
WORK_DIR="$(mktemp -d "${BUILD_DIR}/work.XXXXXX")"
MOUNT_DIR="${WORK_DIR}/mnt"
mkdir -p "${MOUNT_DIR}/boot" "${MOUNT_DIR}/root"

cleanup() {
  set +e
  echo "清理挂载点 …"
  umount "${MOUNT_DIR}/root/proc" 2>/dev/null || true
  umount "${MOUNT_DIR}/root/sys" 2>/dev/null || true
  umount "${MOUNT_DIR}/root/dev/pts" 2>/dev/null || true
  umount "${MOUNT_DIR}/root/dev" 2>/dev/null || true
  umount "${MOUNT_DIR}/boot" 2>/dev/null || true
  umount "${MOUNT_DIR}/root" 2>/dev/null || true
  kpartx -d "${WORK_DIR}/base.img" 2>/dev/null || true
  rm -rf "${WORK_DIR}"
}
trap cleanup EXIT

# ---------- 下载基础镜像 ----------
XZ_FILE="${BUILD_DIR}/rpi-os-arm64.img.xz"
BASE_IMG="${WORK_DIR}/base.img"

if [[ ! -f "${XZ_FILE}" ]]; then
  echo "下载 Raspberry Pi OS Lite ARM64 …"
  wget -q --show-progress -O "${XZ_FILE}" "${RPI_OS_URL}"
else
  echo "使用已缓存的基础镜像：${XZ_FILE}"
fi

echo "解压镜像 …"
xz -dkc "${XZ_FILE}" > "${BASE_IMG}"

# 扩展镜像（为屯象边缘层预留 3GB）
echo "扩展镜像空间 …"
dd if=/dev/zero bs=1M count=3072 >> "${BASE_IMG}"
LOOP_DEV="$(losetup --find --show "${BASE_IMG}")"
# 在最后一个分区扩展
parted -s "${LOOP_DEV}" resizepart 2 100%
e2fsck -f "${LOOP_DEV}p2" || true
resize2fs "${LOOP_DEV}p2"
losetup -d "${LOOP_DEV}"

# ---------- 挂载分区 ----------
echo "挂载分区 …"
LOOP_MAPS="$(kpartx -av "${BASE_IMG}")"
BOOT_DEV="/dev/mapper/$(echo "${LOOP_MAPS}" | grep "p1 " | awk '{print $3}')"
ROOT_DEV="/dev/mapper/$(echo "${LOOP_MAPS}" | grep "p2 " | awk '{print $3}')"

mount "${BOOT_DEV}" "${MOUNT_DIR}/boot"
mount "${ROOT_DEV}" "${MOUNT_DIR}/root"

# ---------- 注入 qemu-aarch64-static ----------
cp "$(which qemu-aarch64-static)" "${MOUNT_DIR}/root/usr/bin/"
mount --bind /proc  "${MOUNT_DIR}/root/proc"
mount --bind /sys   "${MOUNT_DIR}/root/sys"
mount --bind /dev   "${MOUNT_DIR}/root/dev"
mount --bind /dev/pts "${MOUNT_DIR}/root/dev/pts"

# ---------- chroot 安装屯象边缘层 ----------
echo "chroot 安装边缘层依赖 …"
chroot "${MOUNT_DIR}/root" /bin/bash -c "
  export DEBIAN_FRONTEND=noninteractive
  apt-get update -q
  apt-get install -y -q python3 curl bluez pipewire-audio espeak-ng python3-dbus
  apt-get clean
"

# 拷贝边缘层文件
INSTALL_DIR="${MOUNT_DIR}/root/opt/zhilian-edge"
CONFIG_DIR="${MOUNT_DIR}/root/etc/zhilian-edge"
STATE_DIR="${MOUNT_DIR}/root/var/lib/zhilian-edge"
mkdir -p "${INSTALL_DIR}" "${CONFIG_DIR}" "${STATE_DIR}"

cp "${EDGE_DIR}/edge_node_agent.py"          "${INSTALL_DIR}/"
cp "${EDGE_DIR}/shokz_callback_daemon.py"    "${INSTALL_DIR}/"
cp "${EDGE_DIR}/shokz_bluetooth_manager.py"  "${INSTALL_DIR}/"
cp "${EDGE_DIR}/edge_model_manager.py"       "${INSTALL_DIR}/"
cp "${EDGE_DIR}/edge_business_queue.py"      "${INSTALL_DIR}/"
cp "${EDGE_DIR}/edge_health_check.py"        "${INSTALL_DIR}/"
cp "${EDGE_DIR}/bootstrap_edge_firstboot.sh" "${INSTALL_DIR}/"
cp "${SCRIPT_DIR}/install_raspberry_pi_edge.sh" "${INSTALL_DIR}/"
chmod 755 "${INSTALL_DIR}"/*.py "${INSTALL_DIR}"/*.sh

# 注入 systemd 服务
cp "${EDGE_DIR}/zhilian-edge-node.service"  "${MOUNT_DIR}/root/etc/systemd/system/"
cp "${EDGE_DIR}/zhilian-edge-shokz.service" "${MOUNT_DIR}/root/etc/systemd/system/"

# 写入初始配置（含 bootstrap token）
cat > "${CONFIG_DIR}/edge-node.env" <<ENVEOF
EDGE_API_BASE_URL=${API_URL}
EDGE_API_TOKEN=${BOOTSTRAP_TOKEN}
EDGE_STORE_ID=
EDGE_DEVICE_NAME=
EDGE_NETWORK_MODE=cloud
EDGE_STATUS_INTERVAL_SECONDS=30
EDGE_SHOKZ_CALLBACK_BIND=0.0.0.0
EDGE_SHOKZ_CALLBACK_PORT=9781
EDGE_SHOKZ_CALLBACK_SECRET=
EDGE_STATE_DIR=/var/lib/zhilian-edge
ENVEOF
chmod 640 "${CONFIG_DIR}/edge-node.env"

# WiFi 配置（可选）
if [[ -n "${WIFI_SSID}" ]]; then
  cat > "${MOUNT_DIR}/boot/wpa_supplicant.conf" <<WPAEOF
ctrl_interface=DIR=/var/run/wpa_supplicant GROUP=netdev
country=CN
update_config=1
network={
    ssid="${WIFI_SSID}"
    psk="${WIFI_PASS}"
    key_mgmt=WPA-PSK
}
WPAEOF
  # RPi OS Bookworm 使用 NetworkManager
  mkdir -p "${MOUNT_DIR}/root/etc/NetworkManager/system-connections"
  cat > "${MOUNT_DIR}/root/etc/NetworkManager/system-connections/zhilian-wifi.nmconnection" <<NMEOF
[connection]
id=zhilian-wifi
type=wifi
autoconnect=true

[wifi]
ssid=${WIFI_SSID}
mode=infrastructure

[wifi-security]
auth-alg=open
key-mgmt=wpa-psk
psk=${WIFI_PASS}

[ipv4]
method=auto
[ipv6]
method=auto
NMEOF
  chmod 600 "${MOUNT_DIR}/root/etc/NetworkManager/system-connections/zhilian-wifi.nmconnection"
  echo "已注入 WiFi 配置：${WIFI_SSID}"
fi

# 创建系统用户
chroot "${MOUNT_DIR}/root" /bin/bash -c "
  id -u zhilian-edge 2>/dev/null || useradd --system --no-create-home --shell /usr/sbin/nologin zhilian-edge
  chown -R zhilian-edge:zhilian-edge /opt/zhilian-edge /etc/zhilian-edge /var/lib/zhilian-edge
  systemctl enable zhilian-edge-node.service zhilian-edge-shokz.service
"

# 开启 SSH（方便初期运维）
touch "${MOUNT_DIR}/boot/ssh"

# 设置默认 hostname 模板（首启脚本会用 node_id 覆盖）
echo "${HOSTNAME_PREFIX}" > "${MOUNT_DIR}/root/etc/hostname"
sed -i "s/127\.0\.1\.1.*/127.0.1.1\t${HOSTNAME_PREFIX}/" "${MOUNT_DIR}/root/etc/hosts" || true

# ---------- 卸载 chroot 绑定 ----------
echo "卸载 chroot 绑定 …"
umount "${MOUNT_DIR}/root/proc"
umount "${MOUNT_DIR}/root/sys"
umount "${MOUNT_DIR}/root/dev/pts"
umount "${MOUNT_DIR}/root/dev"
rm "${MOUNT_DIR}/root/usr/bin/qemu-aarch64-static"

# ---------- 卸载分区并输出 ----------
umount "${MOUNT_DIR}/boot"
umount "${MOUNT_DIR}/root"
kpartx -d "${BASE_IMG}"

# 复制到输出路径
cp "${BASE_IMG}" "${OUTPUT_IMG}"
echo
echo "============================================================"
echo "  ✅ 镜像构建完成"
echo "  输出: ${OUTPUT_IMG}"
echo "  大小: $(du -sh "${OUTPUT_IMG}" | cut -f1)"
echo
echo "  烧录命令（替换 /dev/sdX 为实际设备）:"
echo "    sudo dd if=${OUTPUT_IMG} of=/dev/sdX bs=4M status=progress conv=fsync"
echo
echo "  首次上电后，树莓派将自动："
echo "    1. 连接网络（${WIFI_SSID:-有线}）"
echo "    2. 向 ${API_URL} 注册边缘节点"
echo "    3. 启动 edge-node 和 edge-shokz 服务"
echo "============================================================"

trap - EXIT
