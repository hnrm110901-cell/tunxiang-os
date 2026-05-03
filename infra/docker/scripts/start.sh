#!/usr/bin/env bash
# ============================================================
# 屯象OS Docker 启动脚本
# 用法: ./start.sh [dev|staging|prod] [--init-db] [--build]
# ============================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DOCKER_DIR="$(dirname "$SCRIPT_DIR")"
PROJECT_ROOT="$(cd "$DOCKER_DIR/../.." && pwd)"

# 颜色输出
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info()  { echo -e "${GREEN}[INFO]${NC} $*"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC} $*"; }
log_error() { echo -e "${RED}[ERROR]${NC} $*"; }
log_step()  { echo -e "${BLUE}[STEP]${NC} $*"; }

# ── 参数解析 ─────────────────────────────────────────────────
ENV="${1:-dev}"
INIT_DB=false
BUILD=false

for arg in "$@"; do
    case $arg in
        --init-db) INIT_DB=true ;;
        --build)   BUILD=true ;;
        dev|staging|prod) ENV="$arg" ;;
    esac
done

COMPOSE_FILE="$DOCKER_DIR/docker-compose.${ENV}.yml"

# ── 前置检查 ─────────────────────────────────────────────────
log_step "检查运行环境..."

# 检查 Docker
if ! command -v docker &> /dev/null; then
    log_error "Docker 未安装。请先安装 Docker: https://docs.docker.com/get-docker/"
    exit 1
fi

DOCKER_VERSION=$(docker --version | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | head -1)
log_info "Docker 版本: $DOCKER_VERSION"

# 检查 Docker Compose (V2)
if docker compose version &> /dev/null; then
    COMPOSE_CMD="docker compose"
    COMPOSE_VERSION=$(docker compose version --short 2>/dev/null || echo "unknown")
    log_info "Docker Compose 版本: $COMPOSE_VERSION"
elif command -v docker-compose &> /dev/null; then
    COMPOSE_CMD="docker-compose"
    COMPOSE_VERSION=$(docker-compose --version | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | head -1)
    log_warn "使用旧版 docker-compose ($COMPOSE_VERSION)，建议升级到 Docker Compose V2"
else
    log_error "Docker Compose 未安装。请先安装: https://docs.docker.com/compose/install/"
    exit 1
fi

# 检查 compose 文件存在
if [ ! -f "$COMPOSE_FILE" ]; then
    log_error "Compose 文件不存在: $COMPOSE_FILE"
    exit 1
fi

# 检查 .env 文件
ENV_FILE="$DOCKER_DIR/.env"
if [ ! -f "$ENV_FILE" ]; then
    if [ "$ENV" = "dev" ]; then
        log_warn ".env 文件不存在，从模板创建开发环境配置（随机密码）..."
        cp "$DOCKER_DIR/.env.example" "$ENV_FILE"
        # 开发环境生成随机密码
        DB_PASS=$(openssl rand -hex 16)
        REDIS_PASS=$(openssl rand -hex 16)
        JWT_SECRET=$(openssl rand -hex 32)
        sed -i.bak "s/CHANGE_ME_USE_STRONG_PASSWORD/${DB_PASS}/g" "$ENV_FILE" 2>/dev/null || \
            sed -i '' "s/CHANGE_ME_USE_STRONG_PASSWORD/${DB_PASS}/g" "$ENV_FILE"
        sed -i.bak "s/CHANGE_ME_REDIS_PASSWORD/${REDIS_PASS}/g" "$ENV_FILE" 2>/dev/null || \
            sed -i '' "s/CHANGE_ME_REDIS_PASSWORD/${REDIS_PASS}/g" "$ENV_FILE"
        sed -i.bak "s/CHANGE_ME_USE_32_CHAR_RANDOM_STRING/${JWT_SECRET}/g" "$ENV_FILE" 2>/dev/null || \
            sed -i '' "s/CHANGE_ME_USE_32_CHAR_RANDOM_STRING/${JWT_SECRET}/g" "$ENV_FILE"
        rm -f "$ENV_FILE.bak"
        log_info "已创建 .env（开发环境随机密码），请按需修改"
    else
        log_error ".env 文件不存在。请从 .env.example 复制并填入真实配置:"
        log_error "  cp $DOCKER_DIR/.env.example $ENV_FILE"
        exit 1
    fi
fi

# 生产环境检查密钥是否为占位符
if [ "$ENV" = "prod" ]; then
    if grep -q "CHANGE_ME" "$ENV_FILE"; then
        log_error "生产环境 .env 中包含占位符 'CHANGE_ME'，请替换为真实密钥后重试"
        exit 1
    fi
fi

# ── 启动 ─────────────────────────────────────────────────────
log_step "启动屯象OS [$ENV] 环境..."
log_info "Compose 文件: $COMPOSE_FILE"
log_info "项目根目录: $PROJECT_ROOT"

cd "$DOCKER_DIR"

# 构建镜像（staging/prod 默认构建，dev 按需）
if [ "$BUILD" = true ] || [ "$ENV" != "dev" ]; then
    log_step "构建 Docker 镜像..."
    $COMPOSE_CMD -f "$COMPOSE_FILE" build
fi

# 启动服务
if [ "$ENV" = "dev" ]; then
    log_step "启动服务（前台模式）..."
    $COMPOSE_CMD -f "$COMPOSE_FILE" up --remove-orphans
else
    log_step "启动服务（后台模式）..."
    $COMPOSE_CMD -f "$COMPOSE_FILE" up -d --remove-orphans
fi

# ── 数据库初始化（可选）─────────────────────────────────────
if [ "$INIT_DB" = true ]; then
    log_step "等待数据库就绪..."
    sleep 5

    log_step "执行 Alembic 数据库迁移..."
    # 找到 gateway 容器执行迁移
    GATEWAY_CONTAINER=$($COMPOSE_CMD -f "$COMPOSE_FILE" ps -q gateway 2>/dev/null || true)
    if [ -n "$GATEWAY_CONTAINER" ]; then
        docker exec "$GATEWAY_CONTAINER" \
            alembic -c /app/shared/db-migrations/alembic.ini upgrade head \
            && log_info "数据库迁移完成" \
            || log_warn "数据库迁移失败，请手动执行: alembic upgrade head"
    else
        log_warn "gateway 容器未找到，跳过数据库迁移"
    fi
fi

# ── 完成 ─────────────────────────────────────────────────────
if [ "$ENV" != "dev" ]; then
    log_step "服务状态:"
    $COMPOSE_CMD -f "$COMPOSE_FILE" ps

    echo ""
    log_info "屯象OS [$ENV] 环境启动完成"
    if [ "$ENV" = "dev" ]; then
        echo ""
        log_info "访问地址:"
        log_info "  API Gateway:  http://localhost:8000"
        log_info "  Web Admin:    http://localhost:5173"
        log_info "  Web POS:      http://localhost:5174"
        log_info "  Web KDS:      http://localhost:5175"
        log_info "  PostgreSQL:   localhost:5432"
        log_info "  Redis:        localhost:6379"
    fi
fi
