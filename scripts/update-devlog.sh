#!/usr/bin/env bash
# update-devlog.sh — 按 CLAUDE.md §16 规范追加 DEVLOG.md 条目
#
# 用法 1（交互式 / EDITOR）：
#   scripts/update-devlog.sh
#   会用 $EDITOR 打开模板，编辑后保存自动 prepend 到 DEVLOG.md
#
# 用法 2（stdin 管道）：
#   cat <<'EOF' | scripts/update-devlog.sh --stdin "标题简述"
#   ### 今日完成
#   - 修了 #244
#   ...
#   EOF
#
# 用法 3（参数文件）：
#   scripts/update-devlog.sh --file /tmp/today.md "标题简述"

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DEVLOG="${ROOT}/DEVLOG.md"
DATE=$(date +%Y-%m-%d)

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

# 读 content
case "$mode" in
  stdin) content=$(cat) ;;
  file)  content=$(cat "$content_file") ;;
  interactive)
    tmp=$(mktemp /tmp/devlog-XXXXXX.md)
    cat > "$tmp" <<EOF
### 今日完成
-

### 数据变化
-

### 遗留问题
-

### 明日计划
-
EOF
    "${EDITOR:-vi}" "$tmp"
    content=$(cat "$tmp")
    rm "$tmp"
    ;;
esac

if [[ -z "$title" ]]; then
  echo "✗ 错误：必须提供标题简述（如 'Sprint 1 #251 落地'）"
  exit 1
fi

# 构造新条目
header="## ${DATE} ${title}"

# Prepend 到 DEVLOG.md
tmp_devlog=$(mktemp)
{
  echo "$header"
  echo ""
  echo "$content"
  echo ""
  echo "---"
  echo ""
  cat "$DEVLOG"
} > "$tmp_devlog"
mv "$tmp_devlog" "$DEVLOG"

echo "✓ DEVLOG.md 已追加：$header"
