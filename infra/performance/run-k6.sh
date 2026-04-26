#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# run-k6.sh — 运行 k6 性能测试并输出结果到 k6-latest-results.json
#
# 用法:
#   ./run-k6.sh [BASE_URL]
#
# 示例:
#   ./run-k6.sh                          # 默认 http://localhost:8000
#   ./run-k6.sh http://staging:8000      # 指定目标
#
# 输出:
#   infra/performance/k6-latest-results.json  (--summary-export 格式)
#   infra/performance/raw-results.json        (逐条原始数据)
# ---------------------------------------------------------------------------
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
K6_SCRIPT="${SCRIPT_DIR}/k6-load-test.js"
RESULTS_FILE="${SCRIPT_DIR}/k6-latest-results.json"
RAW_FILE="${SCRIPT_DIR}/raw-results.json"

# 可选参数: BASE_URL
export K6_BASE_URL="${1:-${K6_BASE_URL:-http://localhost:8000}}"

# ---------------------------------------------------------------------------
# 1. 检查 k6 是否安装
# ---------------------------------------------------------------------------
if ! command -v k6 &>/dev/null; then
  echo "ERROR: k6 未安装。"
  echo ""
  echo "安装方式:"
  echo "  macOS:   brew install k6"
  echo "  Linux:   sudo gpg -k && sudo gpg --no-default-keyring --keyring /usr/share/keyrings/k6-archive-keyring.gpg --keyserver hkp://keyserver.ubuntu.com:80 --recv-keys C5AD17C747E3415A3642D57D77C6C491D6AC1D68 && echo 'deb [signed-by=/usr/share/keyrings/k6-archive-keyring.gpg] https://dl.k6.io/deb stable main' | sudo tee /etc/apt/sources.list.d/k6.list && sudo apt-get update && sudo apt-get install k6"
  echo "  Docker:  docker run --rm -i grafana/k6 run - <k6-load-test.js"
  exit 1
fi

# ---------------------------------------------------------------------------
# 2. 检查测试脚本是否存在
# ---------------------------------------------------------------------------
if [[ ! -f "${K6_SCRIPT}" ]]; then
  echo "ERROR: 找不到 k6 测试脚本: ${K6_SCRIPT}"
  exit 1
fi

# ---------------------------------------------------------------------------
# 3. 清理旧结果
# ---------------------------------------------------------------------------
rm -f "${RESULTS_FILE}" "${RAW_FILE}"

# ---------------------------------------------------------------------------
# 4. 运行 k6
# ---------------------------------------------------------------------------
echo "========================================"
echo "  屯象OS k6 性能测试"
echo "  目标: ${K6_BASE_URL}"
echo "  VUs:  200 (120 堂食 + 50 菜单 + 30 会员)"
echo "  时长: 2 分钟"
echo "========================================"
echo ""

k6 run \
  --out "json=${RAW_FILE}" \
  --summary-export="${RESULTS_FILE}" \
  "${K6_SCRIPT}"

K6_EXIT=$?

# ---------------------------------------------------------------------------
# 5. 验证结果文件
# ---------------------------------------------------------------------------
if [[ -f "${RESULTS_FILE}" ]]; then
  echo ""
  echo "========================================"
  echo "  结果已写入: ${RESULTS_FILE}"
  echo "========================================"

  # 提取 P99 供快速查看
  if command -v python3 &>/dev/null; then
    P99=$(python3 -c "
import json, sys
try:
    d = json.load(open('${RESULTS_FILE}'))
    p99 = d.get('metrics', {}).get('http_req_duration', {}).get('p(99)', 'N/A')
    print(f'P99 = {p99}ms')
except Exception as e:
    print(f'解析失败: {e}', file=sys.stderr)
" 2>&1)
    echo "  ${P99}"
    echo "  门槛: < 200ms"
    echo "========================================"
  fi
else
  echo "WARNING: k6 运行完成但未生成结果文件"
fi

exit ${K6_EXIT}
