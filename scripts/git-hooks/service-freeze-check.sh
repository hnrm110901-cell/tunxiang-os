#!/usr/bin/env bash
# service-freeze-check.sh — 服务冻结令 hook (本地 pre-commit + CI 共用)
# 战略 plan §3 W1 治理 + §5 取舍清单第 1 项 + §6 自动化 hook
# issue #755
set -e
set -o pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"
POLICY_FILE="$REPO_ROOT/.omc/policy/service-freeze.yml"

if [ ! -f "$POLICY_FILE" ]; then
    echo "::warning::service-freeze.yml 不存在, 跳过检查"
    exit 0
fi

# 读取 frozen_until 日期 (P1-1 fix: tr -d \r 防 windows checkout \r 漂移 silent skip)
FROZEN_UNTIL=$(grep -E "^frozen_until:" "$POLICY_FILE" | awk '{print $2}' | tr -d '[:space:]\r')
TODAY=$(date +%Y-%m-%d)

if [[ "$TODAY" > "$FROZEN_UNTIL" ]]; then
    echo "::warning::service freeze 已过期 ($FROZEN_UNTIL), 跳过检查"
    exit 0
fi

# 解析 allowed_existing 和 planned_additions
# P0-1 fix: sub(/#.*$/,"") 先去掉行尾注释, gsub trim 空白和 leading "- "
# 否则 "  - tx-ontology      # W10 issue #766" 整行被当成服务名, planned_additions 实际被拦截
ALLOWED=$(awk '/^allowed_existing:/{flag=1; next} /^[a-z]/{flag=0} flag && /^  - /{sub(/#.*$/,""); gsub(/^[ \t-]+|[ \t]+$/,""); if (length($0)) print}' "$POLICY_FILE")
PLANNED=$(awk '/^planned_additions:/{flag=1; next} /^[a-z]/{flag=0} flag && /^  - /{sub(/#.*$/,""); gsub(/^[ \t-]+|[ \t]+$/,""); if (length($0)) print}' "$POLICY_FILE")
ALL_ALLOWED=$(printf "%s\n%s" "$ALLOWED" "$PLANNED" | sort -u)

# 检测 staged 的新增文件 (pre-commit 模式)
# P1-2 fix: awk -F/ 严格分段提取 services/<dir>, 不依赖 grep regex (unicode 安全)
STAGED_NEW=$(git diff --cached --name-only --diff-filter=A 2>/dev/null \
    | awk -F/ '$1=="services" && NF>=2 {print "services/"$2}' | sort -u || true)

# 如果没有 staged 改动，检测 HEAD 对比 BASE (CI 模式)
# P0-2 fix: BASE 解析失败必须 fail-closed (exit 1), 否则 fork PR / fetch 失败时静默通过, 治理失效
if [ -z "$STAGED_NEW" ] && [ -n "${GITHUB_BASE_REF:-}" ]; then
    git fetch origin "${GITHUB_BASE_REF}" --quiet 2>/dev/null || true
    BASE=$(git rev-parse "origin/${GITHUB_BASE_REF}" 2>/dev/null || echo "")
    if [ -z "$BASE" ]; then
        echo "::error title=service-freeze fail-closed::无法解析 base ref origin/${GITHUB_BASE_REF} (fork PR or fetch failed); 治理 hook 强制 exit 1 防绕过"
        exit 1
    fi
    STAGED_NEW=$(git diff --name-only --diff-filter=A "$BASE"...HEAD 2>/dev/null \
        | awk -F/ '$1=="services" && NF>=2 {print "services/"$2}' | sort -u || true)
fi

if [ -z "$STAGED_NEW" ]; then
    echo "✅ service-freeze check passed (no new services/)"
    exit 0
fi

VIOLATIONS=""
for svc_path in $STAGED_NEW; do
    svc_name="${svc_path#services/}"
    if ! echo "$ALL_ALLOWED" | grep -qx "$svc_name"; then
        # 确认是真正的新目录（不存在于 HEAD）
        if ! git ls-tree --name-only HEAD -- "$svc_path" 2>/dev/null | grep -q .; then
            VIOLATIONS="$VIOLATIONS\n  - $svc_path"
        fi
    fi
done

if [ -n "$VIOLATIONS" ]; then
    echo "::error title=服务冻结令::禁止新建 services/ 目录 (冻结至 $FROZEN_UNTIL):"
    printf "%b\n" "$VIOLATIONS"
    echo ""
    echo "例外申请流程:"
    echo "  1. 创始人 explicit approval (飞书 / GitHub issue comment)"
    echo "  2. 架构守门会决议记录至 docs/governance/decisions/"
    echo "  3. 将新服务加入 .omc/policy/service-freeze.yml planned_additions"
    echo "  4. 实施"
    echo ""
    echo "详见: .omc/policy/README.md"
    exit 1
fi

echo "✅ service-freeze check passed"
