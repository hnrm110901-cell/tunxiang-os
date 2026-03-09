#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TEMPLATE_DIR="$ROOT_DIR/scripts/ops/templates/systemd"

log() { printf '[ops-systemd] %s\n' "$1"; }
err() { printf '[ops-systemd][ERROR] %s\n' "$1" >&2; }

if [[ "$EUID" -ne 0 ]]; then
  err "please run as root: sudo bash scripts/ops/install_systemd_timer.sh"
  exit 1
fi

install -m 0644 "$TEMPLATE_DIR/zhilian-ops-patrol.service" /etc/systemd/system/zhilian-ops-patrol.service
install -m 0644 "$TEMPLATE_DIR/zhilian-ops-patrol.timer" /etc/systemd/system/zhilian-ops-patrol.timer

systemctl daemon-reload
systemctl enable --now zhilian-ops-patrol.timer

log "installed and enabled zhilian-ops-patrol.timer"
log "check: systemctl status zhilian-ops-patrol.timer"
log "next run: systemctl list-timers | grep zhilian-ops-patrol"
