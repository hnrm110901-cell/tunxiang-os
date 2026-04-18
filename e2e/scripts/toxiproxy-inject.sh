#!/usr/bin/env bash
# ============================================================
# toxiproxy 故障注入脚本
#
# 用法：
#   ./toxiproxy-inject.sh down tx-trade           # 将 tx-trade 代理下线（模拟完全断网）
#   ./toxiproxy-inject.sh up tx-trade             # 恢复
#   ./toxiproxy-inject.sh latency tx-trade 2000   # 注入 2s 延迟
#   ./toxiproxy-inject.sh slow_close tx-trade     # 慢关闭（模拟 TCP RST）
#   ./toxiproxy-inject.sh reset tx-trade          # 清除所有 toxic
#
# 依赖：
#   - docker-compose.toxiproxy.yml 已 up
#   - curl
# ============================================================
set -euo pipefail

TOXI_HOST="${TOXIPROXY_HOST:-localhost}"
TOXI_PORT="${TOXIPROXY_PORT:-8474}"
BASE="http://${TOXI_HOST}:${TOXI_PORT}"

ACTION="${1:-}"
PROXY="${2:-}"
ARG3="${3:-}"

if [[ -z "${ACTION}" || -z "${PROXY}" ]]; then
    echo "usage: $0 <action> <proxy> [arg]" >&2
    echo "  actions: down | up | latency <ms> | slow_close | reset" >&2
    exit 2
fi

case "${ACTION}" in
    down)
        curl -sS -X POST "${BASE}/proxies/${PROXY}" \
            -H 'Content-Type: application/json' \
            -d '{"enabled":false}' >/dev/null
        echo "[toxiproxy] ${PROXY} DISABLED"
        ;;
    up)
        curl -sS -X POST "${BASE}/proxies/${PROXY}" \
            -H 'Content-Type: application/json' \
            -d '{"enabled":true}' >/dev/null
        echo "[toxiproxy] ${PROXY} ENABLED"
        ;;
    latency)
        LATENCY_MS="${ARG3:-1000}"
        curl -sS -X POST "${BASE}/proxies/${PROXY}/toxics" \
            -H 'Content-Type: application/json' \
            -d "{\"type\":\"latency\",\"name\":\"lag\",\"stream\":\"downstream\",\"attributes\":{\"latency\":${LATENCY_MS}}}" >/dev/null
        echo "[toxiproxy] ${PROXY} latency=${LATENCY_MS}ms"
        ;;
    slow_close)
        curl -sS -X POST "${BASE}/proxies/${PROXY}/toxics" \
            -H 'Content-Type: application/json' \
            -d '{"type":"slow_close","name":"rst","stream":"upstream","attributes":{"delay":100}}' >/dev/null
        echo "[toxiproxy] ${PROXY} slow_close injected"
        ;;
    reset)
        # 列出并删除所有 toxic
        TOXICS=$(curl -sS "${BASE}/proxies/${PROXY}/toxics" | python3 -c 'import json,sys;print("\n".join(t["name"] for t in json.load(sys.stdin)))' 2>/dev/null || true)
        for t in ${TOXICS}; do
            curl -sS -X DELETE "${BASE}/proxies/${PROXY}/toxics/${t}" >/dev/null
        done
        curl -sS -X POST "${BASE}/proxies/${PROXY}" \
            -H 'Content-Type: application/json' \
            -d '{"enabled":true}' >/dev/null
        echo "[toxiproxy] ${PROXY} reset (all toxics cleared, enabled=true)"
        ;;
    *)
        echo "unknown action: ${ACTION}" >&2
        exit 2
        ;;
esac
