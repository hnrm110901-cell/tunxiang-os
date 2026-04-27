#!/usr/bin/env bash
# check_tier1_pass.sh — 检查 Tier 1 测试是否 100% 通过
#
# 来源依据：CLAUDE.md §22 第 1 项 "Tier 1 全绿"
# 数据源：pytest 生成的 JUnit XML（默认 build/junit-tier1.xml）
#
# 退出码：
#   0  全绿（且至少有 1 个用例）
#   1  有失败/错误用例
#   2  没找到 JUnit XML 或没用例
#
# 用法：
#   scripts/check_tier1_pass.sh [path-to-junit.xml]

set -euo pipefail

JUNIT_PATH="${1:-${TIER1_JUNIT_PATH:-build/junit-tier1.xml}}"

if [[ ! -f "${JUNIT_PATH}" ]]; then
    echo "[FAIL] Tier 1 JUnit XML not found: ${JUNIT_PATH}"
    echo "       提示：先运行 pytest -m tier1 --junitxml=${JUNIT_PATH}"
    exit 2
fi

# 从 testsuite 标签里抽 tests / failures / errors（不强依赖 xmllint）
read -r TOTAL FAILED ERRORED < <(
    python3 - "$JUNIT_PATH" <<'PY'
import sys, xml.etree.ElementTree as ET
try:
    root = ET.parse(sys.argv[1]).getroot()
except Exception as exc:  # noqa: BLE001 — 顶层兜底
    print("0 0 0")
    sys.stderr.write(f"parse error: {exc}\n")
    sys.exit(0)

# 兼容 testsuite 根 / testsuites 根
suites = [root] if root.tag == "testsuite" else list(root.iter("testsuite"))
total = sum(int(s.get("tests", "0")) for s in suites)
failed = sum(int(s.get("failures", "0")) for s in suites)
errored = sum(int(s.get("errors", "0")) for s in suites)
print(f"{total} {failed} {errored}")
PY
)

if [[ "${TOTAL}" == "0" ]]; then
    echo "[FAIL] Tier 1 用例数为 0（XML: ${JUNIT_PATH}）"
    exit 2
fi

PASSED=$((TOTAL - FAILED - ERRORED))

if [[ "${FAILED}" -eq 0 && "${ERRORED}" -eq 0 ]]; then
    echo "[PASS] Tier 1: ${PASSED}/${TOTAL} 全绿"
    exit 0
else
    echo "[FAIL] Tier 1: ${PASSED}/${TOTAL} 通过（失败 ${FAILED}, 错误 ${ERRORED}）"
    exit 1
fi
