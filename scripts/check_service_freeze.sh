#!/usr/bin/env bash
# 服务冻结令检查 — 12 周升级战略 W1-T4
# =========================================================
# 配置 SoT：.omc/policy/service-freeze.yml
# pre-commit 集成：.pre-commit-config.yaml local hook
#
# 用法（pre-commit 自动调用）：
#   bash scripts/check_service_freeze.sh
#
# 手动测试：
#   git add services/tx-newthing/src/main.py
#   bash scripts/check_service_freeze.sh   # 应该拦截
#
# 例外绕过（架构守门会评审用）：
#   TX_ALLOW_NEW_SERVICE=1 git commit -m "..."
# =========================================================

set -eu

POLICY_FILE=".omc/policy/service-freeze.yml"
BYPASS_LOG=".omc/state/freeze-bypass-log.txt"

# ── 1. 期限检查 — 过期自动失效 ─────────────────────────────
if [ -f "$POLICY_FILE" ]; then
    UNTIL=$(grep -E "^  effective_until:" "$POLICY_FILE" | head -1 | sed -E 's/.*"([^"]+)".*/\1/')
    TODAY=$(date +%Y-%m-%d)
    if [ -n "${UNTIL:-}" ] && [ "$TODAY" \> "$UNTIL" ]; then
        echo "ℹ️  服务冻结令已过期 ($UNTIL)，不再生效。"
        echo "   建议通过 docs/governance/ 决议刷新或显式解除。"
        exit 0
    fi
else
    echo "⚠️  $POLICY_FILE 不存在，跳过服务冻结检查。"
    exit 0
fi

# ── 2. 找出 staged 新增的 services/tx-*/src/main.py ──────
NEW_SERVICES=$(git diff --cached --name-only --diff-filter=A 2>/dev/null | \
               grep -E "^services/tx-[^/]+/src/main\.py$" || true)

if [ -z "$NEW_SERVICES" ]; then
    exit 0
fi

# ── 3. 例外绕过（记入 bypass log）─────────────────────────
if [ "${TX_ALLOW_NEW_SERVICE:-}" = "1" ]; then
    mkdir -p "$(dirname "$BYPASS_LOG")"
    {
        echo "$(date -Iseconds) bypass by $(git config user.email 2>/dev/null || echo unknown)"
        echo "  policy_until: $UNTIL"
        echo "  files:"
        echo "$NEW_SERVICES" | sed 's/^/    - /'
        echo ""
    } >> "$BYPASS_LOG"
    echo "⚠️  TX_ALLOW_NEW_SERVICE=1 已记入 $BYPASS_LOG"
    echo "    架构守门会下次评审请说明理由。"
    exit 0
fi

# ── 4. 拦截 ─────────────────────────────────────────────
# 注意：所有变量引用必须 ${VAR} 形式 — 防止 set -u + UTF-8 中文标点
# （如全角逗号 `，` `、`）被解析为变量名一部分
cat >&2 <<EOF

❌ 服务冻结令生效中：禁止新建 services/tx-*/
   配置：${POLICY_FILE} (until ${UNTIL})

被拦截的新增文件：
$(echo "${NEW_SERVICES}" | sed 's/^/  - /')

当前现状（W20 baseline）:
  - 23 个微服务
  - 11 个红色健康度服务
  - W12 战略目标 17 个服务

例外申请:
  1. 走架构守门会（每两周一次）— 推荐
  2. 一次性绕过 TX_ALLOW_NEW_SERVICE=1 git commit ...
     绕过会被记入 ${BYPASS_LOG}，下次守门会评审

详情:
  - 战略 docs/service-health/2026-W20.md
  - 治理 .omc/policy/service-freeze.yml

EOF
exit 1
