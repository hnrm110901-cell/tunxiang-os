#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────
# 屯象OS 安全部署脚本
# 用法:
#   ./scripts/deploy.sh staging          # 部署到 staging
#   ./scripts/deploy.sh prod             # 部署到生产（含确认）
#   ./scripts/deploy.sh prod --skip-test # 跳过 staging 验证（紧急修复）
# ─────────────────────────────────────────────────────────
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_ROOT"

# 颜色
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log()  { echo -e "${GREEN}[deploy]${NC} $*"; }
warn() { echo -e "${YELLOW}[warn]${NC} $*"; }
err()  { echo -e "${RED}[ERROR]${NC} $*" >&2; }
step() { echo -e "\n${BLUE}═══ $* ═══${NC}"; }

TARGET="${1:-help}"
SKIP_TEST="${2:-}"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)

# ─── 预检 ───
preflight() {
    step "预检"

    # 检查工作目录干净
    if [[ -n "$(git status --porcelain 2>/dev/null)" ]]; then
        warn "工作目录有未提交的修改:"
        git status --short
        read -p "继续部署？(y/N) " -n 1 -r
        echo
        [[ $REPLY =~ ^[Yy]$ ]] || exit 1
    fi

    # 检查在正确的分支上
    local branch
    branch=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "unknown")
    log "当前分支: $branch"
    log "当前提交: $(git rev-parse --short HEAD 2>/dev/null || echo 'unknown')"

    # 检查 Docker 可用
    if ! docker info &>/dev/null; then
        err "Docker 不可用"
        exit 1
    fi
    log "Docker: OK"

    # 检查 compose 文件存在
    if [[ "$TARGET" == "staging" ]]; then
        [[ -f docker-compose.staging.yml ]] || { err "docker-compose.staging.yml 不存在"; exit 1; }
        [[ -f .env.staging ]] || { err ".env.staging 不存在（从 .env.staging.example 复制）"; exit 1; }
    fi
}

# ─── 运行测试 ───
run_tests() {
    step "运行测试"
    if make test 2>&1; then
        log "测试全部通过"
    else
        err "测试失败，中止部署"
        exit 1
    fi
}

# ─── 数据库迁移 ───
run_migration() {
    step "数据库迁移"
    if [[ "$TARGET" == "staging" ]]; then
        log "Staging 环境迁移..."
        ./scripts/migrate.sh up --no-backup
    else
        log "生产环境迁移（含备份）..."
        ./scripts/migrate.sh up
    fi
}

# ─── 构建镜像 ───
build_images() {
    step "构建 Docker 镜像"
    local compose_file
    if [[ "$TARGET" == "staging" ]]; then
        compose_file="docker-compose.staging.yml"
        docker-compose -f "$compose_file" --env-file .env.staging build --parallel
    else
        compose_file="docker-compose.prod.yml"
        docker-compose -f "$compose_file" build --parallel
    fi
    log "镜像构建完成"
}

# ─── 部署服务 ───
deploy_services() {
    step "部署服务"
    local compose_file compose_args

    if [[ "$TARGET" == "staging" ]]; then
        compose_file="docker-compose.staging.yml"
        compose_args="--env-file .env.staging"
    else
        compose_file="docker-compose.prod.yml"
        compose_args=""
    fi

    # 滚动更新：先更新后端，再更新前端
    log "更新基础设施（postgres, redis）..."
    docker-compose -f "$compose_file" $compose_args up -d stg-postgres stg-redis 2>/dev/null \
        || docker-compose -f "$compose_file" $compose_args up -d postgres redis 2>/dev/null \
        || true

    log "等待数据库就绪..."
    sleep 5

    log "更新后端服务..."
    docker-compose -f "$compose_file" $compose_args up -d --no-deps \
        $(docker-compose -f "$compose_file" config --services 2>/dev/null \
            | grep -E '(gateway|tx-|celery)' | tr '\n' ' ')

    log "等待后端就绪..."
    sleep 10

    log "更新前端..."
    docker-compose -f "$compose_file" $compose_args up -d --no-deps \
        $(docker-compose -f "$compose_file" config --services 2>/dev/null \
            | grep -E '(web-|nginx|miniapp)' | tr '\n' ' ')
}

# ─── 健康检查 ───
health_check() {
    step "部署后健康检查"
    local base_url max_retries=12 retry=0

    if [[ "$TARGET" == "staging" ]]; then
        base_url="http://localhost:8080"
    else
        base_url="http://localhost"
    fi

    log "等待服务启动..."
    while [[ $retry -lt $max_retries ]]; do
        if curl -sf "${base_url}/health" &>/dev/null; then
            log "Gateway 健康检查: OK"
            return 0
        fi
        retry=$((retry + 1))
        log "  重试 ($retry/$max_retries)..."
        sleep 5
    done

    err "健康检查失败（${max_retries} 次重试后）"
    warn "查看日志: docker-compose -f docker-compose.${TARGET}.yml logs --tail=50"
    return 1
}

# ─── Staging 部署 ───
deploy_staging() {
    preflight
    run_tests
    run_migration
    build_images
    deploy_services
    health_check

    echo ""
    log "========================================="
    log "  Staging 部署完成"
    log "  访问: http://localhost:8080"
    log "  POS:  http://localhost:8080/pos/"
    log "  Admin: http://localhost:8080/admin/"
    log "  API:  http://localhost:8080/api/v1/"
    log "  日志: make logs-staging"
    log "========================================="
}

# ─── 生产部署 ───
deploy_prod() {
    # 安全确认
    echo -e "${RED}"
    echo "  ╔════════════════════════════════════╗"
    echo "  ║   即将部署到 生产环境              ║"
    echo "  ║   服务器: 42.194.229.21            ║"
    echo "  ╚════════════════════════════════════╝"
    echo -e "${NC}"

    if [[ "$SKIP_TEST" != "--skip-test" ]]; then
        # 检查 staging 是否已通过验证
        if ! curl -sf "http://localhost:8080/health" &>/dev/null; then
            err "Staging 环境未运行或健康检查失败"
            err "请先部署并验证 staging: ./scripts/deploy.sh staging"
            err "紧急修复可用: ./scripts/deploy.sh prod --skip-test"
            exit 1
        fi
        log "Staging 健康检查: OK（已验证）"
    else
        warn "跳过 staging 验证（紧急修复模式）"
    fi

    read -p "确认部署到生产环境？(输入 'DEPLOY' 确认) " confirm
    if [[ "$confirm" != "DEPLOY" ]]; then
        log "已取消"
        exit 0
    fi

    preflight
    run_migration
    build_images
    deploy_services

    if health_check; then
        echo ""
        log "========================================="
        log "  生产环境部署完成"
        log "  时间: $TIMESTAMP"
        log "  提交: $(git rev-parse --short HEAD 2>/dev/null || echo 'unknown')"
        log "========================================="

        # 记录部署历史
        mkdir -p "$PROJECT_ROOT/logs"
        echo "$TIMESTAMP | $(git rev-parse --short HEAD 2>/dev/null) | prod | success" \
            >> "$PROJECT_ROOT/logs/deploy-history.log"
    else
        err "生产部署健康检查失败！"
        warn "检查日志: docker-compose -f docker-compose.prod.yml logs --tail=100"
        warn "回滚: docker-compose -f docker-compose.prod.yml down && git checkout HEAD~1 && ./scripts/deploy.sh prod --skip-test"

        mkdir -p "$PROJECT_ROOT/logs"
        echo "$TIMESTAMP | $(git rev-parse --short HEAD 2>/dev/null) | prod | FAILED" \
            >> "$PROJECT_ROOT/logs/deploy-history.log"
        exit 1
    fi
}

# ─── 入口 ───
case "$TARGET" in
    staging) deploy_staging ;;
    prod)    deploy_prod ;;
    *)
        echo "用法: $0 {staging|prod} [--skip-test]"
        echo ""
        echo "  staging              部署到 staging 环境"
        echo "  prod                 部署到生产环境（需先通过 staging）"
        echo "  prod --skip-test     紧急修复：跳过 staging 验证"
        echo ""
        echo "正常发布流程："
        echo "  1. ./scripts/deploy.sh staging   # 先部署 staging"
        echo "  2. 手动验证 staging 功能正常"
        echo "  3. ./scripts/deploy.sh prod      # 再部署生产"
        ;;
esac
