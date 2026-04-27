#!/usr/bin/env bash
set -euo pipefail

echo "=== 屯象OS 安全扫描 ==="
ERRORS=0

# 1. RLS检查：所有新表必须有RLS
echo "[1/5] RLS策略检查..."
for migration in shared/db-migrations/versions/v3[5-9]*.py shared/db-migrations/versions/v37*.py; do
  if [ -f "$migration" ]; then
    tables=$(grep -oP "CREATE TABLE.*?(\w+)" "$migration" | awk '{print $NF}' || true)
    for table in $tables; do
      if ! grep -q "ENABLE ROW LEVEL SECURITY" "$migration" 2>/dev/null; then
        echo "  ❌ $migration: 表 $table 缺少RLS"
        ERRORS=$((ERRORS+1))
      fi
    done
  fi
done
[ $ERRORS -eq 0 ] && echo "  ✅ RLS检查通过"

# 2. 硬编码密钥检查
echo "[2/5] 硬编码密钥检查..."
SECRETS=$(grep -rn "sk-\|api_key\s*=\s*['\"]" services/ apps/ --include="*.py" --include="*.ts" --include="*.tsx" | grep -v "\.env\|config\|example\|test\|mock\|TODO\|environ\|getenv\|process.env" || true)
if [ -n "$SECRETS" ]; then
  echo "  ❌ 疑似硬编码密钥:"
  echo "$SECRETS" | head -5
  ERRORS=$((ERRORS+1))
else
  echo "  ✅ 未发现硬编码密钥"
fi

# 3. broad except检查
echo "[3/5] Broad except检查..."
BROAD=$(grep -rn "except Exception:" services/ --include="*.py" | grep -v "test_\|# 最外层" || true)
if [ -n "$BROAD" ]; then
  echo "  ⚠️ 发现broad except ($(echo "$BROAD" | wc -l | tr -d ' ')处):"
  echo "$BROAD" | head -5
else
  echo "  ✅ 未发现broad except"
fi

# 4. CORS通配符检查
echo "[4/5] CORS配置检查..."
CORS=$(grep -rn 'allow_origins=\["\*"\]' services/ --include="*.py" || true)
if [ -n "$CORS" ]; then
  echo "  ⚠️ CORS通配符 (生产环境应限制):"
  echo "$CORS" | head -3
else
  echo "  ✅ CORS配置安全"
fi

# 5. 端口暴露检查
echo "[5/5] 非标端口检查..."
PORTS=$(grep -rn "0.0.0.0" services/ --include="*.py" | grep -v "test_\|# " || true)
if [ -n "$PORTS" ]; then
  echo "  ⚠️ 绑定0.0.0.0 (生产应限制):"
  echo "$PORTS" | head -3
fi

echo ""
echo "=== 扫描完成: ${ERRORS}个错误 ==="
exit $ERRORS
