#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────────────
# 屯象OS — Phase 4a-5 路线 a per-service alembic orchestrator
#
# 顺序：
#   1. shared/db-migrations-core/    (cross-service: tenants / RLS infra / ENUMs)
#   2. 17 services × alembic upgrade  (services 各持独立 version_table 互不冲突)
#   3. (optional) shared/db-migrations/ (legacy mono-repo，--include-legacy 启用)
#
# 用法：
#   ./scripts/migrate-all.sh                 # core + 17 services 并发 upgrade
#   ./scripts/migrate-all.sh --sequential    # 串行（默认并发，--sequential 调试用）
#   ./scripts/migrate-all.sh --include-legacy # 同时跑 shared/db-migrations/ 老 chain
#   ./scripts/migrate-all.sh --check          # 仅打印计划，不执行
#
# 环境变量：
#   DATABASE_URL   PG 连接（默认 dev fallback）
#   PARALLEL_JOBS  并发数（默认 4，串行模式忽略）
#   ALEMBIC        alembic 可执行（默认 alembic on PATH）
#
# 退出码：
#   0  全部成功
#   1  任一 alembic upgrade 失败
#   2  参数错误 / 前置环境缺失
# ──────────────────────────────────────────────────────────────────────────────
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

# ── 颜色 ────────────────────────────────────────────────────────────────────
RED=$'\033[0;31m'; GREEN=$'\033[0;32m'; YELLOW=$'\033[1;33m'; CYAN=$'\033[0;36m'; NC=$'\033[0m'
log()  { echo "${GREEN}[migrate-all]${NC} $*"; }
warn() { echo "${YELLOW}[warn]${NC} $*"; }
err()  { echo "${RED}[ERROR]${NC} $*" >&2; }

# ── 参数 ────────────────────────────────────────────────────────────────────
MODE="parallel"        # parallel | sequential
INCLUDE_LEGACY="false"
DRY_RUN="false"
PARALLEL_JOBS="${PARALLEL_JOBS:-4}"
if ! [[ "$PARALLEL_JOBS" =~ ^[0-9]+$ ]] || (( PARALLEL_JOBS < 1 )); then
    echo "[ERROR] PARALLEL_JOBS 必须正整数 >= 1 [current: $PARALLEL_JOBS]" >&2
    exit 2
fi
ALEMBIC="${ALEMBIC:-alembic}"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --sequential)    MODE="sequential" ;;
        --include-legacy) INCLUDE_LEGACY="true" ;;
        --check|--dry-run) DRY_RUN="true" ;;
        -h|--help)
            grep -E "^#" "$0" | sed -E 's/^# ?//;s/^!.*//'; exit 0 ;;
        *) err "未知参数: $1"; exit 2 ;;
    esac
    shift
done

# ── 前置检查 ────────────────────────────────────────────────────────────────
if ! command -v "$ALEMBIC" >/dev/null 2>&1; then
    err "alembic 未安装或不在 PATH（设 ALEMBIC env 指向其路径）"
    exit 2
fi

DB_URL="${DATABASE_URL:-postgresql://tunxiang:CHANGE_ME@localhost/tunxiang_os}"
DB_URL="${DB_URL/postgresql+asyncpg:\/\//postgresql:\/\/}"
export DATABASE_URL="$DB_URL"

# ── alembic 列表（核心 + 17 services） ──────────────────────────────────────
# 注：未列入的 6 services（tx-civic / tx-devforge / tx-forge / tx-indonesia /
#     tx-vietnam / mcp-server）按 Phase 4a-1 audit 无 owner 表，暂无 shell。
CORE_DIR="$PROJECT_ROOT/shared/db-migrations-core"
SERVICE_NAMES=(
    gateway
    tx-agent
    tx-analytics
    tx-brain
    tx-expense
    tx-finance
    tx-growth
    tx-intel
    tx-malaysia
    tx-member
    tx-menu
    tx-ops
    tx-org
    tx-pay
    tx-predict
    tx-supply
    tx-trade
)
LEGACY_DIR="$PROJECT_ROOT/shared/db-migrations"

# ── 单个 alembic upgrade（命名 + 错误捕获） ─────────────────────────────────
run_alembic() {
    local name="$1"
    local dir="$2"
    if [[ ! -d "$dir" ]]; then
        warn "[$name] 目录不存在，跳过：$dir"
        return 0
    fi
    if [[ ! -f "$dir/alembic.ini" ]]; then
        warn "[$name] alembic.ini 缺失，跳过：$dir"
        return 0
    fi
    if [[ "$DRY_RUN" == "true" ]]; then
        echo "[$name] DRY-RUN: cd $dir && $ALEMBIC upgrade head"
        return 0
    fi
    echo "${CYAN}[$name]${NC} upgrade head 开始"
    # 进入 alembic dir 因 alembic.ini 用 `script_location = .`（相对路径）
    if (cd "$dir" && "$ALEMBIC" upgrade head); then
        echo "${GREEN}[$name]${NC} ✓ 完成"
    else
        err "[$name] upgrade 失败"
        return 1
    fi
}

# ── 并发执行（用 xargs -P） ──────────────────────────────────────────────────
run_parallel() {
    local entries=("$@")  # name|dir 形式
    if (( ${#entries[@]} == 0 )); then
        return 0
    fi
    log "并发执行 ${#entries[@]} 个 alembic [PARALLEL_JOBS=${PARALLEL_JOBS}]"
    # 临时目录收集每个 job 的退出码
    local tmp; tmp=$(mktemp -d)
    trap "rm -rf $tmp" RETURN
    local i=0
    for entry in "${entries[@]}"; do
        local name="${entry%%|*}"
        local dir="${entry#*|}"
        i=$((i+1))
        (
            if run_alembic "$name" "$dir"; then
                echo 0 > "$tmp/$i.rc"
            else
                echo 1 > "$tmp/$i.rc"
            fi
        ) &
        # 限并发：每达 PARALLEL_JOBS 等一次
        if (( i % PARALLEL_JOBS == 0 )); then
            wait
        fi
    done
    wait
    # 汇总
    local failed=0
    for f in "$tmp"/*.rc; do
        if [[ "$(cat "$f")" != "0" ]]; then
            failed=$((failed+1))
        fi
    done
    if (( failed > 0 )); then
        err "并发执行 $failed 个失败"
        return 1
    fi
    return 0
}

# ── 主流程 ──────────────────────────────────────────────────────────────────
log "PG: $(echo "$DB_URL" | sed 's/:[^@]*@/:***@/')"
log "模式：$MODE / dry-run=$DRY_RUN / include-legacy=$INCLUDE_LEGACY"

# Step 1: core 总在最前（其他 service 依赖 core 的 tenants / ENUMs / RLS infra）
log "── Step 1/2: shared/db-migrations-core ──"
run_alembic "core" "$CORE_DIR" || exit 1

# Step 2: 17 services
log "── Step 2/2: 17 services alembic upgrade ──"
service_entries=()
for svc in "${SERVICE_NAMES[@]}"; do
    service_entries+=("$svc|$PROJECT_ROOT/services/$svc/db-migrations")
done

if [[ "$MODE" == "parallel" ]]; then
    run_parallel "${service_entries[@]}" || exit 1
else
    for entry in "${service_entries[@]}"; do
        name="${entry%%|*}"
        dir="${entry#*|}"
        run_alembic "$name" "$dir" || exit 1
    done
fi

# Step 3 (optional): 老 mono-repo legacy
if [[ "$INCLUDE_LEGACY" == "true" ]]; then
    log "── Step 3: shared/db-migrations (legacy mono-repo) ──"
    run_alembic "legacy" "$LEGACY_DIR" || exit 1
fi

log "${GREEN}✓ 全部完成${NC}"
