#!/usr/bin/env bash
# 用法: ./scripts/collect-offline-results.sh [PLAYWRIGHT_REPORT_DIR]
#
# 功能：
#   1. 读取 Playwright JSON report（默认 e2e/playwright-report/results.json）
#   2. 计算通过/失败数
#   3. 追加一条记录到 infra/nightly/offline-e2e-results.json
#   4. 保留最近30条记录（滚动窗口）
#
# 依赖: jq（CI runner 默认已安装）

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

REPORT_DIR="${1:-e2e/playwright-report}"
RESULTS_JSON="${REPORT_DIR}/results.json"
OUTPUT_FILE="${REPO_ROOT}/infra/nightly/offline-e2e-results.json"

# ── 检查依赖 ─────────────────────────────────────────────────────────────
if ! command -v jq &>/dev/null; then
  echo "ERROR: jq is required but not installed." >&2
  exit 1
fi

# ── 检查 Playwright JSON report 是否存在 ─────────────────────────────────
if [ ! -f "$RESULTS_JSON" ]; then
  echo "ERROR: Playwright JSON report not found at $RESULTS_JSON" >&2
  echo "Hint: ensure playwright.config.ts includes ['json', { outputFile: 'playwright-report/results.json' }]" >&2
  exit 1
fi

# ── 解析 Playwright JSON report ──────────────────────────────────────────
# Playwright JSON report 结构: { suites: [...], stats: { expected, unexpected, ... } }
TESTS_TOTAL=$(jq '[.. | objects | select(.status != null and .title != null)] | length' "$RESULTS_JSON" 2>/dev/null || echo "0")
TESTS_PASSED=$(jq '[.. | objects | select(.status == "passed" or .status == "expected")] | length' "$RESULTS_JSON" 2>/dev/null || echo "0")

# 备用解析：如果上面的 jq 查询返回 0，尝试 stats 字段
if [ "$TESTS_TOTAL" -eq 0 ]; then
  TESTS_TOTAL=$(jq '.stats.expected + .stats.unexpected + .stats.flaky + .stats.skipped' "$RESULTS_JSON" 2>/dev/null || echo "0")
  TESTS_PASSED=$(jq '.stats.expected' "$RESULTS_JSON" 2>/dev/null || echo "0")
fi

# ── 判定状态 ──────────────────────────────────────────────────────────────
if [ "$TESTS_TOTAL" -gt 0 ] && [ "$TESTS_PASSED" -eq "$TESTS_TOTAL" ]; then
  STATUS="green"
else
  STATUS="red"
fi

# ── 获取 duration（从环境变量 OFFLINE_HOURS，默认 0） ─────────────────────
DURATION_HOURS="${OFFLINE_HOURS:-0}"

# ── 获取 workflow run ID（CI 环境下可用） ─────────────────────────────────
WORKFLOW_RUN_ID="${GITHUB_RUN_ID:-local-$(date +%s)}"

# ── 构建新记录 ────────────────────────────────────────────────────────────
TODAY=$(date -u +"%Y-%m-%d")
NEW_RECORD=$(jq -n \
  --arg date "$TODAY" \
  --arg status "$STATUS" \
  --argjson duration "$DURATION_HOURS" \
  --argjson passed "$TESTS_PASSED" \
  --argjson total "$TESTS_TOTAL" \
  --arg run_id "$WORKFLOW_RUN_ID" \
  '{
    date: $date,
    status: $status,
    duration_hours: $duration,
    tests_passed: $passed,
    tests_total: $total,
    workflow_run_id: $run_id
  }')

# ── 初始化或更新结果文件 ──────────────────────────────────────────────────
mkdir -p "$(dirname "$OUTPUT_FILE")"

if [ ! -f "$OUTPUT_FILE" ]; then
  echo '{"description":"Offline E2E nightly test results — auto-updated by CI","recent_runs":[]}' > "$OUTPUT_FILE"
fi

# 追加记录并保留最近30条
jq --argjson record "$NEW_RECORD" '
  .recent_runs += [$record] |
  .recent_runs = .recent_runs[-30:]
' "$OUTPUT_FILE" > "${OUTPUT_FILE}.tmp" && mv "${OUTPUT_FILE}.tmp" "$OUTPUT_FILE"

# ── 输出摘要 ──────────────────────────────────────────────────────────────
echo "=== Offline E2E Result Collected ==="
echo "Date:         $TODAY"
echo "Status:       $STATUS"
echo "Tests:        $TESTS_PASSED / $TESTS_TOTAL passed"
echo "Duration:     ${DURATION_HOURS}h"
echo "Run ID:       $WORKFLOW_RUN_ID"
echo "Output:       $OUTPUT_FILE"
echo "Total runs:   $(jq '.recent_runs | length' "$OUTPUT_FILE")"
