#!/usr/bin/env bash
# ======================================================================
# PR #199 (v500 RLS FORCE migration) merge 前置检查
# ======================================================================
#
# verifier 第三轮 review 指出：PR #199 的 down_revision="v399"。如果用户的
# v400/v401/v402 (WITH CHECK 系列) 在 #199 之前 merge，main 的 alembic head
# 变成 v402，#199 的 down_revision 指向历史中间节点 → alembic multi-heads
# 错误 → staging/生产 DB 迁移卡死。
#
# 本脚本一键检查 + 给出修复命令。
#
# 用法：
#   bash scripts/db/check_alembic_head_for_pr_199.sh
#
# 输出：
#   - 当前 main 的 alembic head
#   - PR #199 的 down_revision
#   - PASS / NEEDS REBASE 判定
#   - 如需 rebase，给出具体命令
# ======================================================================

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
VERSIONS="$REPO_ROOT/shared/db-migrations/versions"
PR_199_FILE="$VERSIONS/v500_rls_force_all_business_tables.py"

echo "=== PR #199 merge 前置检查 ==="
echo ""

# 1. 找当前 main 的 alembic head（最大 vNNN 不被任何文件作为 down_revision）
echo "【1】扫描所有 migration 文件..."
# 严格 regex：只匹配 revision = "vNNN" 或 revision: str = "vNNN"，
# 数字 only（不接 branch suffix 如 v22a / v22b — 这些是历史 multi-head debt 不算）
# 用 perl regex 带 lookahead 严格匹配
all_revisions=$(grep -hE '^(revision\s*(:\s*\S+\s*)?=\s*)"v[0-9]+"' "$VERSIONS"/*.py 2>/dev/null \
    | sed -E 's/.*"(v[0-9]+)".*/\1/' | sort -u)
all_down_refs=$(grep -hE '^down_revision.*=.*"v[0-9]+"' "$VERSIONS"/*.py 2>/dev/null \
    | sed -E 's/.*"(v[0-9]+)".*/\1/' | sort -u)

# head = 是 revision 但不被任何 down_revision 引用
heads=$(comm -23 <(echo "$all_revisions") <(echo "$all_down_refs"))
head_count=$(echo "$heads" | wc -l | tr -d ' ')

echo "   总 migration: $(echo "$all_revisions" | wc -l | tr -d ' ') 个"
echo "   alembic heads: $head_count"
echo "$heads" | sed 's/^/   - /'
echo ""

if [ "$head_count" -gt 1 ]; then
    # 已知 KNOWN_BROKEN 历史债（v048-v399 一堆 branch suffix） — 见
    # scripts/check_alembic_chain.py 顶部 KNOWN_BROKEN_PARENTS 注释。
    # 不影响 PR #199 merge（v500 down_revision 只需对齐主链最新 head）。
    echo "::notice::检测到多 head（含已知历史债，见 scripts/check_alembic_chain.py KNOWN_BROKEN）"
    echo "::notice::只关注最大数字 head 用于 PR #199 比较；其他参考 docs/migration-chain-debt.md"
    echo ""
    # 提取最大数字 head（vNNN 纯数字）
    main_head=$(echo "$heads" | grep -E '^v[0-9]+$' | sort -t v -k2 -n | tail -1)
    echo "   主链最新 head: $main_head"
    # 后续比较只用 main_head
    expected_down="$main_head"
fi

# 2. 看 PR #199 文件存在性
if [ ! -f "$PR_199_FILE" ]; then
    echo ""
    echo "::notice::$PR_199_FILE 不在当前 branch（PR #199 还没 merge / 分支不对）"
    echo "  脚本仅在含 v500 文件的分支跑（如 audit/p0-followup-rls-force-migration）"
    exit 0
fi

# 3. 读 PR #199 的 down_revision
pr_199_down=$(grep "^down_revision" "$PR_199_FILE" | sed -E 's/.*"(v[0-9]+)".*/\1/')

echo "【2】PR #199 信息..."
echo "   文件：$PR_199_FILE"
echo "   declared down_revision: $pr_199_down"
echo ""

# 4. 比较
echo "【3】判定..."
# 单 head 场景下取唯一值；multi-head 场景上方已设 expected_down=主链 head
if [ "$head_count" -eq 1 ]; then
    expected_down="$(echo "$heads" | head -1)"
fi

if [ "$pr_199_down" = "$expected_down" ]; then
    echo "   ✅ PASS — PR #199 down_revision ($pr_199_down) 与当前 main head 一致"
    echo ""
    echo "可以 merge。merge 后 alembic head 将变为 v500。"
    exit 0
fi

echo "   ❌ NEEDS REBASE — PR #199 down_revision ($pr_199_down) ≠ main head ($expected_down)"
echo ""
echo "如直接 merge，alembic upgrade head 会报 multi-heads 错。"
echo ""
echo "【修复步骤】"
echo "  1. checkout PR #199 分支："
echo "     gh pr checkout 199    # 或：git checkout audit/p0-followup-rls-force-migration"
echo ""
echo "  2. 编辑 v500_rls_force_all_business_tables.py，把 down_revision 从"
echo "     \"$pr_199_down\" 改为 \"$expected_down\""
echo ""
echo "  3. 跑本脚本再确认："
echo "     bash scripts/db/check_alembic_head_for_pr_199.sh"
echo "     期望：✅ PASS"
echo ""
echo "  4. force-push（合理：仅修 down_revision metadata，不改 SQL 行为）："
echo "     git add shared/db-migrations/versions/v500_rls_force_all_business_tables.py"
echo "     git commit --amend --no-edit"
echo "     git push --force-with-lease"
echo ""
echo "  5. 在 PR description 留言说明 rebase 原因"
echo ""
exit 1
