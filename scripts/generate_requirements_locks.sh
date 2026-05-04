#!/bin/bash
# 为所有服务生成 requirements.lock（精确版本锁定）
# 依赖：pip install pip-tools
# 用法：./scripts/generate_requirements_locks.sh
set -e

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

if ! command -v pip-compile &>/dev/null; then
  echo "错误: 需要 pip-tools，请先执行: pip install pip-tools"
  exit 1
fi

SERVICES=(
  gateway tx-trade tx-member tx-ops tx-agent tx-menu
  tx-supply tx-finance tx-org tx-analytics tx-brain tx-intel
  tx-devforge tx-forge tx-growth tx-civic tx-expense tx-pay
)

SUCCESS=0
FAILED=0

for svc in "${SERVICES[@]}"; do
  req_file="${REPO_ROOT}/services/${svc}/requirements.txt"
  lock_file="${REPO_ROOT}/services/${svc}/requirements.lock"
  if [ ! -f "${req_file}" ]; then
    echo "  [跳过] ${svc}：requirements.txt 不存在"
    continue
  fi
  echo -n "  生成 ${svc} ..."
  if pip-compile "${req_file}" \
      --output-file="${lock_file}" \
      --quiet \
      --no-header \
      --resolver=backtracking \
      2>/dev/null; then
    echo " ✓"
    SUCCESS=$((SUCCESS + 1))
  else
    echo " ✗（依赖冲突或网络问题，跳过）"
    FAILED=$((FAILED + 1))
  fi
done

echo ""
echo "完成：${SUCCESS} 个成功，${FAILED} 个失败"
echo "提交：git add services/*/requirements.lock && git commit -m 'chore: pin requirements.lock'"
