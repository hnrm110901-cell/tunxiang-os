#!/bin/bash
# 屯象OS 每周代码健康度检查脚本
# 使用：bash scripts/weekly-health-check.sh
# 输出：docs/code-health-$(date +%Y-W%V).md

set -e

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WEEK_TAG=$(date +%Y-W%V)
OUTPUT_FILE="$PROJECT_ROOT/docs/code-health-$WEEK_TAG.md"

echo "# 屯象OS 代码健康度报告 - $WEEK_TAG" > "$OUTPUT_FILE"
echo "生成时间：$(date '+%Y-%m-%d %H:%M')" >> "$OUTPUT_FILE"
echo "" >> "$OUTPUT_FILE"

# 1. 各服务代码量
echo "## 各服务代码量" >> "$OUTPUT_FILE"
echo "" >> "$OUTPUT_FILE"
echo "| 服务 | Python行数 |" >> "$OUTPUT_FILE"
echo "|------|-----------|" >> "$OUTPUT_FILE"
for dir in "$PROJECT_ROOT"/services/*/; do
    service=$(basename "$dir")
    lines=$(find "$dir" -name "*.py" -not -path "*/node_modules/*" | xargs wc -l 2>/dev/null | tail -1 | awk '{print $1}' || echo "0")
    echo "| $service | $lines |" >> "$OUTPUT_FILE"
done
echo "" >> "$OUTPUT_FILE"

# 2. 测试覆盖情况
echo "## Tier 1 测试文件" >> "$OUTPUT_FILE"
echo "" >> "$OUTPUT_FILE"
tier1_tests=$(find "$PROJECT_ROOT/services" -name "test_*_tier1.py" 2>/dev/null)
if [ -z "$tier1_tests" ]; then
    echo "⚠️  未发现 Tier 1 测试文件（test_*_tier1.py）" >> "$OUTPUT_FILE"
else
    echo "$tier1_tests" | while read f; do
        count=$(grep -c "def test_" "$f" || echo 0)
        echo "- $(basename $f): $count 个用例" >> "$OUTPUT_FILE"
    done
fi
echo "" >> "$OUTPUT_FILE"

# 3. 危险模式检查
echo "## 危险代码模式检查" >> "$OUTPUT_FILE"
echo "" >> "$OUTPUT_FILE"

echo "### broad except（应指定具体异常类型）" >> "$OUTPUT_FILE"
broad_except=$(grep -r "except Exception:" "$PROJECT_ROOT/services" --include="*.py" -l 2>/dev/null | grep -v "__pycache__" || echo "")
if [ -z "$broad_except" ]; then
    echo "✅ 未发现 broad except" >> "$OUTPUT_FILE"
else
    echo "⚠️  发现以下文件使用 broad except：" >> "$OUTPUT_FILE"
    echo "$broad_except" | while read f; do
        echo "- $f" >> "$OUTPUT_FILE"
    done
fi
echo "" >> "$OUTPUT_FILE"

echo "### 可能的先查后改模式（需人工确认）" >> "$OUTPUT_FILE"
# 查找在service层既有SELECT又有UPDATE的函数（粗略检测）
suspect=$(grep -r "\.get_balance\|\.get_points\|\.get_deposit" "$PROJECT_ROOT/services" --include="*.py" -l 2>/dev/null | grep -v "test_" | grep -v "__pycache__" || echo "")
if [ -z "$suspect" ]; then
    echo "✅ 未发现明显的余额查询代码（可能已使用原子SQL）" >> "$OUTPUT_FILE"
else
    echo "⚠️  以下文件包含余额查询，请人工确认是否为原子操作：" >> "$OUTPUT_FILE"
    echo "$suspect" | while read f; do
        echo "- $f" >> "$OUTPUT_FILE"
    done
fi
echo "" >> "$OUTPUT_FILE"

# 4. 本周 git 变更
echo "## 本周代码变更（最近7天）" >> "$OUTPUT_FILE"
echo "" >> "$OUTPUT_FILE"
echo '```' >> "$OUTPUT_FILE"
cd "$PROJECT_ROOT"
git log --oneline --since="7 days ago" 2>/dev/null | head -30 >> "$OUTPUT_FILE" || echo "（git log 失败，跳过）" >> "$OUTPUT_FILE"
echo '```' >> "$OUTPUT_FILE"

echo ""
echo "✅ 健康度报告已生成：$OUTPUT_FILE"
echo ""
echo "下一步："
echo "1. 查看报告：cat $OUTPUT_FILE"
echo "2. 运行 Tier 1 测试：python -m pytest services/tx-trade/tests/test_*_tier1.py -v"
echo "3. 在新 Claude 会话中执行 AI 自审（参考 docs/weekly-ai-review-template.md）"
