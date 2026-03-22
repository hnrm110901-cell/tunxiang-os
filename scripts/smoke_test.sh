#!/bin/bash
# TunxiangOS V3.0 — E2E 烟雾测试
cd "$(dirname "$0")/.."

G='\033[0;32m'; R='\033[0;31m'; N='\033[0m'
pass=0; fail=0

check() {
  if eval "$2" > /dev/null 2>&1; then
    echo -e "  ${G}✓${N} $1"; ((pass++))
  else
    echo -e "  ${R}✗${N} $1"; ((fail++))
  fi
}

echo "═══════════════════════════════════════════"
echo " TunxiangOS V3.0 Smoke Test"
echo "═══════════════════════════════════════════"

echo -e "\n▶ Unit Tests (213)"
check "all tests" "make test"

echo -e "\n▶ Agent (73/73)"
check "all agents callable" "make verify-agents"

echo -e "\n▶ Seed Data"
check "seed_demo_data" "python3 scripts/seed_demo_data.py"

echo ""
echo "═══════════════════════════════════════════"
total=$((pass + fail))
[ $fail -eq 0 ] && echo -e " ${G}✓ All $total checks passed${N}" || echo -e " ${R}✗ $fail/$total failed${N}"
echo "═══════════════════════════════════════════"
exit $fail
