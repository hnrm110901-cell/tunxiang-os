#!/usr/bin/env bash
# =============================================================================
# check_migrations.sh
# 目的：比较当前 alembic 迁移版本与上次部署版本（HEAD~1），
#       如有新迁移文件则输出清单并以退出码 1 通知 Harness 门禁检测。
#
# 用法：
#   ./scripts/check_migrations.sh [VERSIONS_DIR] [COMPARE_REF]
#
#   VERSIONS_DIR   alembic versions 目录路径（默认：s/alembic/versions）
#   COMPARE_REF    对比的 git 引用（默认：HEAD~1）
#
# 环境变量（优先级高于参数）：
#   VERSIONS_DIR               覆盖 versions 目录路径
#   COMPARE_REF                覆盖对比引用（如 origin/main）
#   MIGRATION_APPROVAL_REQUIRED  "true" 时有新迁移则以退出码1阻断
#                                "false"（默认）仅告警
#   REPO_ROOT                  仓库根目录（默认：脚本所在目录的上一级）
#
# 返回值：
#   0  无新迁移文件，或 MIGRATION_APPROVAL_REQUIRED=false
#   1  检测到新迁移文件，且 MIGRATION_APPROVAL_REQUIRED=true
# =============================================================================
set -uo pipefail

# ── 参数处理 ─────────────────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="${REPO_ROOT:-$(dirname "${SCRIPT_DIR}")}"

VERSIONS_DIR="${VERSIONS_DIR:-${1:-${REPO_ROOT}/s/alembic/versions}}"
COMPARE_REF="${COMPARE_REF:-${2:-HEAD~1}}"
MIGRATION_APPROVAL_REQUIRED="${MIGRATION_APPROVAL_REQUIRED:-false}"

# ── 颜色输出 ─────────────────────────────────────────────────────────────────
RED='\033[0;31m'
YELLOW='\033[1;33m'
GREEN='\033[0;32m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

print_header() {
  echo ""
  echo -e "${CYAN}=========================================${NC}"
  echo -e "${CYAN}  DB 迁移门禁检测脚本${NC}"
  echo -e "${CYAN}=========================================${NC}"
  echo "  仓库根目录:   ${REPO_ROOT}"
  echo "  Versions目录: ${VERSIONS_DIR}"
  echo "  对比引用:     ${COMPARE_REF}"
  echo "  阻断模式:     MIGRATION_APPROVAL_REQUIRED=${MIGRATION_APPROVAL_REQUIRED}"
  echo -e "${CYAN}-----------------------------------------${NC}"
}

# ── 前置检查 ─────────────────────────────────────────────────────────────────
check_prerequisites() {
  # 检查是否在 git 仓库中
  if ! git -C "${REPO_ROOT}" rev-parse --git-dir >/dev/null 2>&1; then
    echo -e "${RED}ERROR: ${REPO_ROOT} 不是 git 仓库${NC}"
    exit 1
  fi

  # 检查 COMPARE_REF 是否存在
  if ! git -C "${REPO_ROOT}" rev-parse --verify "${COMPARE_REF}" >/dev/null 2>&1; then
    echo -e "${YELLOW}WARNING: git 引用 '${COMPARE_REF}' 不存在（可能是首次提交）${NC}"
    echo "INFO: 跳过迁移检测，假定无历史版本可对比"
    exit 0
  fi

  # 检查 versions 目录是否存在
  if [ ! -d "${VERSIONS_DIR}" ]; then
    echo -e "${YELLOW}WARNING: alembic versions 目录不存在: ${VERSIONS_DIR}${NC}"
    echo "INFO: 跳过迁移检测"
    exit 0
  fi
}

# ── 获取相对路径（用于 git diff）────────────────────────────────────────────
get_relative_versions_path() {
  # 将绝对路径转换为相对于 REPO_ROOT 的路径
  python3 -c "
import os
abs_versions = os.path.abspath('${VERSIONS_DIR}')
abs_repo = os.path.abspath('${REPO_ROOT}')
try:
    rel = os.path.relpath(abs_versions, abs_repo)
    print(rel)
except ValueError:
    print('${VERSIONS_DIR}')
" 2>/dev/null || echo "s/alembic/versions"
}

# ── 主检测逻辑 ────────────────────────────────────────────────────────────────
detect_new_migrations() {
  local REL_VERSIONS_PATH
  REL_VERSIONS_PATH=$(get_relative_versions_path)

  echo "INFO: 扫描路径: ${REL_VERSIONS_PATH}"
  echo ""

  # 获取新增的 migration 文件（仅 .py，排除 __init__.py 和 env.py）
  NEW_MIGRATIONS=$(
    git -C "${REPO_ROOT}" diff --name-only "${COMPARE_REF}" HEAD \
      -- "${REL_VERSIONS_PATH}/*.py" 2>/dev/null \
    | grep -E '\.py$' \
    | grep -v '__init__\.py' \
    | grep -v '^env\.py$' \
    || true
  )

  # 同时查找 untracked 的新 migration 文件（针对未 commit 的场景）
  UNTRACKED_MIGRATIONS=$(
    git -C "${REPO_ROOT}" ls-files --others --exclude-standard \
      "${REL_VERSIONS_PATH}/" 2>/dev/null \
    | grep -E '\.py$' \
    | grep -v '__init__\.py' \
    || true
  )

  echo "${NEW_MIGRATIONS}"
}

# ── 输出新 migration 文件详情 ─────────────────────────────────────────────────
print_migration_details() {
  local MIGRATIONS="$1"
  echo -e "${YELLOW}!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!${NC}"
  echo -e "${YELLOW}WARNING: 检测到以下新增 alembic migration 文件${NC}"
  echo -e "${YELLOW}-----------------------------------------${NC}"

  local COUNT=0
  while IFS= read -r FILE; do
    [ -z "${FILE}" ] && continue
    COUNT=$((COUNT + 1))
    echo -e "  ${COUNT}. ${CYAN}${FILE}${NC}"

    # 尝试提取 revision 和 down_revision 信息
    FULL_PATH="${REPO_ROOT}/${FILE}"
    if [ -f "${FULL_PATH}" ]; then
      REVISION=$(grep -E "^revision\s*=" "${FULL_PATH}" 2>/dev/null | head -1 || echo "  (无法读取)")
      DOWN_REV=$(grep -E "^down_revision\s*=" "${FULL_PATH}" 2>/dev/null | head -1 || echo "  (无法读取)")
      echo "     revision:      ${REVISION}"
      echo "     down_revision: ${DOWN_REV}"
    fi
  done <<< "${MIGRATIONS}"

  echo -e "${YELLOW}-----------------------------------------${NC}"
  echo "  共计: ${COUNT} 个新增迁移文件"
  echo ""
  echo -e "${YELLOW}部署前必须确认以下事项：${NC}"
  echo "  [1] migration 已在 dev / test 环境执行并验证无误"
  echo "  [2] 已准备好回滚 SQL（alembic downgrade 或手动 SQL）"
  echo "  [3] 生产数据库已完成备份（RDS 快照 / pg_dump）"
  echo "  [4] 已通知 DBA 并获得上线窗口批准"
  echo "  [5] 确认 migration 幂等，支持多副本并发执行"
  echo -e "${YELLOW}!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!${NC}"
}

# ── 主流程 ────────────────────────────────────────────────────────────────────
main() {
  print_header
  check_prerequisites

  echo "INFO: 开始扫描新增 alembic migration 文件..."
  NEW_MIGRATIONS=$(detect_new_migrations)

  if [ -z "${NEW_MIGRATIONS}" ]; then
    echo -e "${GREEN}OK: 未检测到新的 alembic migration 文件${NC}"
    echo "INFO: 当前版本与 ${COMPARE_REF} 相比无 schema 变更，可安全部署"
    echo ""
    exit 0
  fi

  # 有新的迁移文件
  print_migration_details "${NEW_MIGRATIONS}"

  # 输出机器可读的变量（供 Harness 引用）
  echo ""
  echo "HAS_NEW_MIGRATIONS=true"
  echo "MIGRATION_COUNT=$(echo "${NEW_MIGRATIONS}" | grep -c '\.py' || echo 0)"

  if [ "${MIGRATION_APPROVAL_REQUIRED}" = "true" ]; then
    echo ""
    echo -e "${RED}ERROR: MIGRATION_APPROVAL_REQUIRED=true${NC}"
    echo -e "${RED}检测到新迁移文件，根据发布策略阻断流水线。${NC}"
    echo "请人工审核上述迁移文件，确认安全后重新触发部署。"
    exit 1
  else
    echo ""
    echo -e "${YELLOW}INFO: MIGRATION_APPROVAL_REQUIRED=false（仅告警模式）${NC}"
    echo "流水线将继续执行，但请务必在下一步人工确认迁移安全性。"
    exit 0
  fi
}

main "$@"
