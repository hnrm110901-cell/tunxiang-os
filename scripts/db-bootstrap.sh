#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────────────
# 屯象OS — Phase 4a-5 fresh PG 一键 bootstrap
#
# 在空 PG 上从零拉起完整 schema：
#   1. 等 PG ready (pg_isready 重试 30 次)
#   2. CREATE DATABASE if not exists
#   3. 应用 init-rls.sql（infra/docker/）
#   4. 应用 init-pgvector.sql（infra/docker/）
#   5. 跑 scripts/migrate-all.sh（core + 17 services）
#
# 用途：
#   - 新机房 / 新 dev 环境一键初始化
#   - CI fresh-pg-upgrade-test 的核心驱动
#   - docker-compose-pg fixture（A 任务依赖）
#
# 用法：
#   DATABASE_URL=postgresql://... ./scripts/db-bootstrap.sh
#   ./scripts/db-bootstrap.sh --skip-create   # DB 已存在跳过 CREATE DATABASE
#
# 退出码：
#   0 全部成功
#   1 任一步骤失败
#   2 参数错误 / 前置环境
# ──────────────────────────────────────────────────────────────────────────────
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

GREEN=$'\033[0;32m'; YELLOW=$'\033[1;33m'; RED=$'\033[0;31m'; CYAN=$'\033[0;36m'; NC=$'\033[0m'
log()  { echo "${GREEN}[bootstrap]${NC} $*"; }
warn() { echo "${YELLOW}[warn]${NC} $*"; }
err()  { echo "${RED}[ERROR]${NC} $*" >&2; }

SKIP_CREATE="false"
while [[ $# -gt 0 ]]; do
    case "$1" in
        --skip-create) SKIP_CREATE="true" ;;
        -h|--help)
            grep -E "^#" "$0" | sed -E 's/^# ?//;s/^!.*//'; exit 0 ;;
        *) err "未知参数: $1"; exit 2 ;;
    esac
    shift
done

DB_URL="${DATABASE_URL:-postgresql://tunxiang:CHANGE_ME@localhost/tunxiang_os}"
DB_URL="${DB_URL/postgresql+asyncpg:\/\//postgresql:\/\/}"
export DATABASE_URL="$DB_URL"

# 解析 PG 连接组件（host / port / user / dbname）— 用于 pg_isready / 管理 SQL
parse_url() {
    python3 -c "
import os, sys
from urllib.parse import urlparse
u = urlparse(os.environ['DATABASE_URL'])
print(u.hostname or 'localhost')
print(u.port or 5432)
print(u.username or 'postgres')
print((u.path or '/postgres').lstrip('/'))
"
}

PG_INFO=$(parse_url)
PG_HOST=$(echo "$PG_INFO" | sed -n '1p')
PG_PORT=$(echo "$PG_INFO" | sed -n '2p')
PG_USER=$(echo "$PG_INFO" | sed -n '3p')
PG_DB=$(echo "$PG_INFO" | sed -n '4p')

log "PG: $PG_USER@$PG_HOST:$PG_PORT/$PG_DB"

# ── 1. 等 PG ready ──────────────────────────────────────────────────────────
log "── 1/4: 等 PG ready ──"
# 用 pg_isready (CI/Linux) 或 psycopg2 fallback (macOS 无 PG client tools)
check_pg_ready() {
    if command -v pg_isready >/dev/null 2>&1; then
        pg_isready -h "$PG_HOST" -p "$PG_PORT" -U "$PG_USER" >/dev/null 2>&1
    else
        python3 -c "
import psycopg2, sys, os
try:
    psycopg2.connect(os.environ['DATABASE_URL']).close()
    sys.exit(0)
except Exception:
    sys.exit(1)
" 2>/dev/null
    fi
}
i=0; until check_pg_ready; do
    i=$((i+1))
    if (( i > 30 )); then
        err "PG 30 次重试仍不 ready，bail"
        exit 1
    fi
    sleep 1
done
log "✓ PG ready"

# ── psql 或 psycopg2 fallback（macOS 无 PG client tools 时） ────────────────
exec_sql() {
    local conn_url="$1"
    local sql_or_file="$2"
    local from_file="${3:-false}"
    if command -v psql >/dev/null 2>&1; then
        if [[ "$from_file" == "true" ]]; then
            psql "$conn_url" -v ON_ERROR_STOP=1 -f "$sql_or_file" >/dev/null
        else
            psql "$conn_url" -tAc "$sql_or_file" 2>/dev/null
        fi
    else
        # 用 env var + heredoc 避免 bash 单引号展开污染 Python 字符串（review fix）
        FROM_FILE="$from_file" CONN_URL="$conn_url" SQL_OR_FILE="$sql_or_file" \
        python3 - <<'PYEOF'
import psycopg2, sys, os
conn = psycopg2.connect(os.environ['CONN_URL'])
conn.set_session(autocommit=True)
cur = conn.cursor()
if os.environ.get('FROM_FILE') == 'true':
    sql = open(os.environ['SQL_OR_FILE']).read()
else:
    sql = os.environ['SQL_OR_FILE']
try:
    cur.execute(sql)
    if cur.description:
        for row in cur.fetchall():
            print('\t'.join(str(c) for c in row))
except Exception as e:
    print(f'SQL ERROR: {e}', file=sys.stderr)
    sys.exit(1)
PYEOF
    fi
}

# ── 2. CREATE DATABASE if needed ────────────────────────────────────────────
if [[ "$SKIP_CREATE" == "false" ]]; then
    log "── 2/4: CREATE DATABASE $PG_DB if not exists ──"
    ADMIN_URL="${DATABASE_URL%/*}/postgres"
    if exec_sql "$ADMIN_URL" "SELECT 1 FROM pg_database WHERE datname='$PG_DB'" | grep -q 1; then
        log "DB $PG_DB 已存在，跳过 CREATE"
    else
        exec_sql "$ADMIN_URL" "CREATE DATABASE \"$PG_DB\""
        log "✓ DB $PG_DB 已创建"
    fi
else
    log "── 2/4: SKIP CREATE DATABASE (--skip-create) ──"
fi

# ── 3. 应用基础 SQL（init-rls / init-pgvector） ────────────────────────────
log "── 3/4: 应用基础 SQL ──"
for sql in infra/docker/init-pgvector.sql infra/docker/init-rls.sql; do
    if [[ -f "$PROJECT_ROOT/$sql" ]]; then
        echo "${CYAN}[$sql]${NC} apply"
        exec_sql "$DB_URL" "$PROJECT_ROOT/$sql" "true"
        echo "${GREEN}[$sql]${NC} ✓"
    else
        warn "$sql 不存在，跳过"
    fi
done

# ── 4. 跑 scripts/migrate-all.sh ────────────────────────────────────────────
log "── 4/4: scripts/migrate-all.sh (core + 17 services) ──"
"$SCRIPT_DIR/migrate-all.sh"

log "${GREEN}✓ Bootstrap 全部完成${NC}"
