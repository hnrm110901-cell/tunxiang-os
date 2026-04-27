#!/usr/bin/env bash
set -euo pipefail
echo "=== AB实验验证 ==="
DB_URL="${DATABASE_URL:-postgresql://localhost:5432/tunxiang}"
# 检查是否有活跃AB实验
ACTIVE=$(psql "$DB_URL" -t -c "SELECT COUNT(*) FROM campaign_optimization_logs WHERE status = 'running'" 2>/dev/null || echo "0")
echo "活跃AB实验数: $(echo $ACTIVE | tr -d ' ')"
if [ "$(echo $ACTIVE | tr -d ' ')" -ge 1 ]; then
  echo "✅ 至少1个AB实验running"
  # 检查是否熔断
  FUSED=$(psql "$DB_URL" -t -c "SELECT COUNT(*) FROM campaign_optimization_logs WHERE status = 'fused' AND created_at > NOW() - INTERVAL '24 hours'" 2>/dev/null || echo "0")
  if [ "$(echo $FUSED | tr -d ' ')" -gt 0 ]; then
    echo "❌ 发现24h内熔断的实验"
    exit 1
  fi
  echo "✅ 无熔断"
else
  echo "⚠️ 无活跃AB实验，需先创建"
fi
