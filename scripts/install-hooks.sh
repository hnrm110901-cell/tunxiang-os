#!/usr/bin/env bash
# install-hooks.sh — 安装本仓的 git hooks（DEVLOG / progress 提示等）
#
# 用法：scripts/install-hooks.sh

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
HOOK_SRC="${ROOT}/scripts/hooks"
HOOK_DST="${ROOT}/.git/hooks"

if [[ ! -d "$ROOT/.git" ]]; then
  echo "✗ 不在 git 仓库根目录"
  exit 1
fi

mkdir -p "$HOOK_SRC"

# pre-commit：检查 DEVLOG / progress 是否随 [type]([service]) 提交一起更新
cat > "$HOOK_SRC/pre-commit" <<'EOF'
#!/usr/bin/env bash
# 检查：commit 含业务类型前缀（feat/fix/refactor）但 DEVLOG.md / progress.md 未变 → warn（不阻塞）
# 跳过：仅 docs / chore / merge / 初始化等

cached_files=$(git diff --cached --name-only)
msg_file="$1"  # commit-msg path（pre-commit 不传，但兼容）

# 没改任何文件就退出
[[ -z "$cached_files" ]] && exit 0

# 取 cached 修改类型范围
biz_types=$(git diff --cached --name-only | grep -E "^(apps|packages|services|edge|shared/(?!design-system|api-types))/" | head -1)
[[ -z "$biz_types" ]] && exit 0

# 已包含 DEVLOG / progress 改动则放行
if echo "$cached_files" | grep -qE "^(DEVLOG\.md|docs/progress\.md)$"; then
  exit 0
fi

# 否则 warn（不阻塞）
cat <<'WARN'
⚠ 业务代码 commit 未同步更新 DEVLOG.md / docs/progress.md
   按 CLAUDE.md §16 / §18，建议会话结束后追加一段：
     scripts/update-devlog.sh "本次会话标题"
     scripts/update-progress.sh "本次会话标题"
   （此为提示，不阻塞 commit）

WARN
exit 0
EOF
chmod +x "$HOOK_SRC/pre-commit"

# 安装：软链到 .git/hooks/
ln -sf "../../scripts/hooks/pre-commit" "$HOOK_DST/pre-commit"

echo "✓ pre-commit hook 安装完成（提示模式，不阻塞）"
echo "  位置：$HOOK_DST/pre-commit -> ../../scripts/hooks/pre-commit"
echo "  如需关闭，删除该 symlink 即可"
