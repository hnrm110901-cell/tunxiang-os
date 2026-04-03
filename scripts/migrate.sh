#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────
# 屯象OS 数据库迁移安全脚本
# 用法:
#   ./scripts/migrate.sh check          # 预检：显示待执行迁移
#   ./scripts/migrate.sh up             # 执行迁移（含预检+备份）
#   ./scripts/migrate.sh up --no-backup # 跳过备份（仅dev环境）
#   ./scripts/migrate.sh rollback       # 回滚最近一次迁移
#   ./scripts/migrate.sh history        # 查看迁移历史
# ─────────────────────────────────────────────────────────
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
MIGRATIONS_DIR="$PROJECT_ROOT/shared/db-migrations"

# 颜色
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

# 从环境变量或 alembic.ini 获取数据库 URL
DB_URL="${DATABASE_URL:-postgresql://tunxiang:changeme_dev@localhost/tunxiang_os}"
# 迁移用同步驱动
DB_URL="${DB_URL/postgresql+asyncpg:\/\//postgresql:\/\/}"

log()  { echo -e "${GREEN}[migrate]${NC} $*"; }
warn() { echo -e "${YELLOW}[warn]${NC} $*"; }
err()  { echo -e "${RED}[ERROR]${NC} $*" >&2; }

# ─── 预检 ───
cmd_check() {
    log "当前数据库: $(echo "$DB_URL" | sed 's/:[^@]*@/:***@/')"

    # 检查数据库连通性
    if ! psql "$DB_URL" -c "SELECT 1" &>/dev/null; then
        err "无法连接数据库"
        exit 1
    fi
    log "数据库连接: OK"

    # 当前版本
    local current
    current=$(cd "$MIGRATIONS_DIR" && PYTHONPATH="$PROJECT_ROOT" alembic current 2>/dev/null | awk '{print $1}' || true)
    if [[ -z "$current" ]]; then
        log "当前迁移版本: (未初始化)"
    else
        log "当前迁移版本: $current"
    fi

    # 待执行迁移
    local pending
    pending=$(cd "$MIGRATIONS_DIR" && PYTHONPATH="$PROJECT_ROOT" alembic history --indicate-current 2>/dev/null || true)
    log "迁移历史:"
    if [[ -n "$pending" ]]; then
        echo "$pending" | while IFS= read -r line; do
            if echo "$line" | grep -q "(current)"; then
                echo -e "  ${GREEN}$line${NC}"
            elif echo "$line" | grep -q "(head)"; then
                echo -e "  ${YELLOW}$line${NC}"
            else
                echo "  $line"
            fi
        done
    else
        echo "  (无历史记录)"
    fi

    # 检查是否有重复 revision ID
    log "检查 revision ID 唯一性..."
    local dupes
    dupes=$(grep -rh "^revision" "$MIGRATIONS_DIR/versions/"*.py 2>/dev/null \
        | sort | uniq -d || true)
    if [[ -n "$dupes" ]]; then
        err "发现重复 revision ID（必须修复）:"
        echo "$dupes"
        return 1
    fi
    log "Revision ID 唯一性: OK"

    # 检查 down_revision 链完整性
    log "检查迁移链完整性..."
    if cd "$MIGRATIONS_DIR" && PYTHONPATH="$PROJECT_ROOT" alembic heads 2>/dev/null | grep -q ","; then
        err "发现多个 head（迁移链分叉），需要合并"
        cd "$MIGRATIONS_DIR" && PYTHONPATH="$PROJECT_ROOT" alembic heads
        return 1
    fi
    log "迁移链完整性: OK"
}

# ─── 备份 ───
backup_db() {
    local backup_dir="$PROJECT_ROOT/backups"
    mkdir -p "$backup_dir"

    local timestamp
    timestamp=$(date +%Y%m%d_%H%M%S)
    local db_name
    db_name=$(echo "$DB_URL" | sed 's|.*/||')
    local backup_file="$backup_dir/${db_name}_${timestamp}.sql.gz"

    log "备份数据库到 $backup_file ..."
    if pg_dump "$DB_URL" | gzip > "$backup_file"; then
        local size
        size=$(du -h "$backup_file" | cut -f1)
        log "备份完成 ($size)"
        echo "$backup_file"
    else
        err "备份失败"
        exit 1
    fi
}

# ─── 执行迁移 ───
cmd_up() {
    local skip_backup=false
    [[ "${1:-}" == "--no-backup" ]] && skip_backup=true

    # 预检
    cmd_check || exit 1

    # 检查是否有待执行的迁移
    local current head
    current=$(cd "$MIGRATIONS_DIR" && PYTHONPATH="$PROJECT_ROOT" alembic current 2>/dev/null | awk '{print $1}' || echo "")
    head=$(cd "$MIGRATIONS_DIR" && PYTHONPATH="$PROJECT_ROOT" alembic heads 2>/dev/null | awk '{print $1}' || echo "")

    if [[ "$current" == "$head" ]]; then
        log "已在最新版本，无需迁移"
        return 0
    fi

    # 生产环境强制备份
    if [[ "$skip_backup" == false ]]; then
        local backup_file
        backup_file=$(backup_db)
        log "回滚时使用: gunzip -c $backup_file | psql \$DATABASE_URL"
    else
        warn "跳过备份（仅限开发环境使用）"
    fi

    # 执行迁移
    log "开始执行迁移..."
    if cd "$MIGRATIONS_DIR" && PYTHONPATH="$PROJECT_ROOT" alembic upgrade head; then
        log "迁移执行成功"
    else
        err "迁移执行失败！"
        if [[ "$skip_backup" == false ]]; then
            err "回滚命令: gunzip -c $backup_file | psql \$DATABASE_URL"
        fi
        exit 1
    fi

    # 验证
    log "验证迁移结果..."
    local new_current
    new_current=$(cd "$MIGRATIONS_DIR" && PYTHONPATH="$PROJECT_ROOT" alembic current 2>/dev/null | head -1)
    log "当前版本: $new_current"

    # 验证核心表存在且 RLS 启用
    log "验证 RLS 状态..."
    local tables_without_rls
    tables_without_rls=$(psql "$DB_URL" -t -A -c "
        SELECT tablename FROM pg_tables
        WHERE schemaname = 'public'
          AND tablename NOT IN ('alembic_version', 'spatial_ref_sys')
          AND tablename NOT IN (
              SELECT tablename FROM pg_tables t
              JOIN pg_class c ON c.relname = t.tablename
              WHERE t.schemaname = 'public' AND c.relrowsecurity = true
          )
    " 2>/dev/null | grep -v '^$' || true)

    if [[ -n "$tables_without_rls" ]]; then
        warn "以下表未启用 RLS（请检查）:"
        echo "$tables_without_rls" | while read -r t; do
            echo "  - $t"
        done
    else
        log "所有业务表 RLS: OK"
    fi
}

# ─── 回滚 ───
cmd_rollback() {
    local current
    current=$(cd "$MIGRATIONS_DIR" && PYTHONPATH="$PROJECT_ROOT" alembic current 2>/dev/null | awk '{print $1}' || echo "")
    log "当前版本: $current"

    if [[ -z "$current" ]]; then
        err "无法获取当前版本"
        exit 1
    fi

    # 先备份
    local backup_file
    backup_file=$(backup_db)

    log "回滚一个版本..."
    if cd "$MIGRATIONS_DIR" && PYTHONPATH="$PROJECT_ROOT" alembic downgrade -1; then
        local new_current
        new_current=$(cd "$MIGRATIONS_DIR" && PYTHONPATH="$PROJECT_ROOT" alembic current 2>/dev/null | head -1)
        log "回滚成功，当前版本: $new_current"
    else
        err "回滚失败"
        exit 1
    fi
}

# ─── 历史 ───
cmd_history() {
    cd "$MIGRATIONS_DIR" && PYTHONPATH="$PROJECT_ROOT" alembic history --verbose
}

# ─── 入口 ───
case "${1:-help}" in
    check)    cmd_check ;;
    up)       cmd_up "${2:-}" ;;
    rollback) cmd_rollback ;;
    history)  cmd_history ;;
    *)
        echo "用法: $0 {check|up|rollback|history}"
        echo ""
        echo "  check              预检：连通性、版本、重复ID、链完整性"
        echo "  up [--no-backup]   执行迁移（默认先备份）"
        echo "  rollback           回滚最近一次迁移"
        echo "  history            查看完整迁移历史"
        ;;
esac
