#!/usr/bin/env bash
# update-progress.sh — 按 CLAUDE.md §18 规范追加 progress.md 条目（防漂移）
#
# 时间戳精确到分钟（与 DEVLOG.md 日级别区分）。
#
# 用法 1（交互式）：
#   scripts/update-progress.sh "S2-04 焦点环落地"
#
# 用法 2（stdin）：
#   cat <<'EOF' | scripts/update-progress.sh --stdin "S2-04 焦点环落地"
#   ### 完成状态
#   - [x] ...
#   EOF
#
# 用法 3（文件）：
#   scripts/update-progress.sh --file /tmp/p.md "S2-04 焦点环落地"

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PROGRESS="${ROOT}/docs/progress.md"
TS=$(date +"%Y-%m-%d %H:%M")

mode="interactive"
content=""
title=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --stdin)
      mode="stdin"
      title="${2:-}"
      shift 2
      ;;
    --file)
      mode="file"
      content_file="$2"
      title="${3:-}"
      shift 3
      ;;
    -h|--help)
      sed -n '2,15p' "$0"
      exit 0
      ;;
    *)
      title="$1"
      shift
      ;;
  esac
done

case "$mode" in
  stdin) content=$(cat) ;;
  file)  content=$(cat "$content_file") ;;
  interactive)
    tmp=$(mktemp /tmp/progress-XXXXXX.md)
    cat > "$tmp" <<EOF
### 完成状态
- [x]
- [ ]

### 关键决策
- **决策 N**：[决策]
  - 理由：[为什么这样而非其他]

### 下一步
-

### 已知风险
-
EOF
    "${EDITOR:-vi}" "$tmp"
    content=$(cat "$tmp")
    rm "$tmp"
    ;;
esac

if [[ -z "$title" ]]; then
  echo "✗ 错误：必须提供标题简述"
  exit 1
fi

header="## ${TS} · ${title}"

tmp_progress=$(mktemp)
{
  echo "$header"
  echo ""
  echo "$content"
  echo ""
  echo "---"
  echo ""
  cat "$PROGRESS"
} > "$tmp_progress"
mv "$tmp_progress" "$PROGRESS"

echo "✓ progress.md 已追加：$header"
