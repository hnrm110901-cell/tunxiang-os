#!/bin/bash
# ================================================================
# 屯象OS 演示环境 — Mac mini M4 一键部署脚本
# ================================================================
# 用法: bash demo/demo-mac-setup.sh
# 前置: Docker Desktop / OrbStack + Node.js 18+ + pnpm 8+
# ================================================================
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_ROOT"

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo ""
echo -e "${BLUE}╔══════════════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║           屯象OS 演示环境 一键部署                       ║${NC}"
echo -e "${BLUE}║           Mac mini M4 · 全服务本地运行                   ║${NC}"
echo -e "${BLUE}╚══════════════════════════════════════════════════════════╝${NC}"
echo ""

# ── Step 0: 环境检查 ─────────────────────────────────────────
echo -e "${YELLOW}[0/7] 环境检查...${NC}"

check_cmd() {
    if ! command -v "$1" &> /dev/null; then
        echo -e "${RED}  ✗ $1 未安装。$2${NC}"
        exit 1
    fi
    echo -e "${GREEN}  ✓ $1 已安装${NC}"
}

check_cmd "docker" "请安装 Docker Desktop: https://www.docker.com/products/docker-desktop/"
check_cmd "node" "请安装 Node.js 18+: brew install node"
check_cmd "pnpm" "请安装 pnpm: npm install -g pnpm"

# 检查 Docker 是否运行
if ! docker info &> /dev/null 2>&1; then
    echo -e "${RED}  ✗ Docker 未运行，请先启动 Docker Desktop / OrbStack${NC}"
    exit 1
fi
echo -e "${GREEN}  ✓ Docker 运行中${NC}"

# 检查 Node 版本
NODE_VER=$(node -v | sed 's/v//' | cut -d. -f1)
if [ "$NODE_VER" -lt 18 ]; then
    echo -e "${RED}  ✗ Node.js 版本需要 18+，当前: $(node -v)${NC}"
    exit 1
fi

echo ""

# ── Step 1: 构建前端 ─────────────────────────────────────────
echo -e "${YELLOW}[1/7] 构建前端应用...${NC}"

# 创建前端输出目录
DIST_DIR="$PROJECT_ROOT/demo/.dist"
mkdir -p "$DIST_DIR"/{web-pos,web-admin,web-kds,web-crew}

# 安装依赖
if [ ! -d "node_modules" ]; then
    echo "  安装根目录依赖..."
    pnpm install --frozen-lockfile 2>&1 | tail -3
fi

# 构建各前端应用
build_app() {
    local app_name=$1
    local app_dir="apps/$app_name"
    local base_path=$2

    if [ -d "$app_dir" ] && [ -f "$app_dir/package.json" ]; then
        echo "  构建 $app_name (base: $base_path)..."
        cd "$PROJECT_ROOT/$app_dir"
        [ ! -d "node_modules" ] && pnpm install --frozen-lockfile 2>&1 | tail -1
        # 设置 base path 用于子路径部署
        VITE_BASE_PATH="$base_path" pnpm run build 2>&1 | tail -2
        if [ -d "dist" ]; then
            cp -r dist/* "$DIST_DIR/$app_name/"
            echo -e "${GREEN}  ✓ $app_name 构建完成${NC}"
        else
            echo -e "${YELLOW}  ⚠ $app_name 无 dist 输出，使用占位页${NC}"
            echo "<html><head><meta charset='utf-8'><title>屯象OS - $app_name</title></head><body><h1>屯象OS $app_name</h1><p>前端构建中...</p></body></html>" > "$DIST_DIR/$app_name/index.html"
        fi
        cd "$PROJECT_ROOT"
    else
        echo -e "${YELLOW}  ⚠ $app_name 目录不存在，使用占位页${NC}"
        echo "<html><head><meta charset='utf-8'><title>屯象OS - $app_name</title></head><body><h1>屯象OS $app_name</h1></body></html>" > "$DIST_DIR/$app_name/index.html"
    fi
}

build_app "web-pos" "/pos/"
build_app "web-admin" "/admin/"
build_app "web-kds" "/kds/"
build_app "web-crew" "/crew/"

echo ""

# ── Step 2: 停止旧容器 ──────────────────────────────────────
echo -e "${YELLOW}[2/7] 清理旧容器...${NC}"
docker compose -f demo/docker-compose.demo-full.yml down 2>/dev/null || true
echo -e "${GREEN}  ✓ 清理完成${NC}"
echo ""

# ── Step 3: 启动基础设施 ─────────────────────────────────────
echo -e "${YELLOW}[3/7] 启动 PostgreSQL + Redis...${NC}"
docker compose -f demo/docker-compose.demo-full.yml up -d postgres redis
echo "  等待数据库就绪..."
for i in $(seq 1 30); do
    if docker compose -f demo/docker-compose.demo-full.yml exec -T postgres pg_isready -U tunxiang -d tunxiang_os > /dev/null 2>&1; then
        echo -e "${GREEN}  ✓ PostgreSQL 就绪 (${i}s)${NC}"
        break
    fi
    if [ "$i" -eq 30 ]; then
        echo -e "${RED}  ✗ PostgreSQL 启动超时${NC}"
        exit 1
    fi
    sleep 1
done
echo ""

# ── Step 4: 初始化数据库 ─────────────────────────────────────
echo -e "${YELLOW}[4/7] 初始化数据库表结构...${NC}"
docker compose -f demo/docker-compose.demo-full.yml run --rm -T gateway \
    bash -c "pip install --no-cache-dir -q fastapi>=0.104.0 pydantic>=2.4.0 sqlalchemy>=2.0.0 asyncpg>=0.29.0 structlog>=23.1.0 passlib[bcrypt]>=1.7.4 PyJWT>=2.8.0 httpx>=0.25.0 redis>=5.0.0 python-multipart>=0.0.6 aiofiles>=23.0.0 && python -c 'import asyncio; from shared.ontology.src.database import init_db; asyncio.run(init_db()); print(\"  ✓ 表结构初始化完成\")'"
echo ""

# ── Step 5: 导入演示数据 ─────────────────────────────────────
echo -e "${YELLOW}[5/7] 导入三商户演示数据...${NC}"
docker compose -f demo/docker-compose.demo-full.yml run --rm -T gateway \
    bash -c "pip install --no-cache-dir -q fastapi>=0.104.0 pydantic>=2.4.0 sqlalchemy>=2.0.0 asyncpg>=0.29.0 structlog>=23.1.0 passlib[bcrypt]>=1.7.4 PyJWT>=2.8.0 httpx>=0.25.0 redis>=5.0.0 python-multipart>=0.0.6 aiofiles>=23.0.0 && python scripts/demo_seed.py"
echo ""

# ── Step 6: 启动所有服务 ─────────────────────────────────────
echo -e "${YELLOW}[6/7] 启动全部14个微服务 + Nginx...${NC}"

# 复制前端构建产物到 Docker volume
docker compose -f demo/docker-compose.demo-full.yml up -d nginx
NGINX_CONTAINER=$(docker compose -f demo/docker-compose.demo-full.yml ps -q nginx)
if [ -n "$NGINX_CONTAINER" ]; then
    docker cp "$DIST_DIR/web-pos/." "$NGINX_CONTAINER:/usr/share/nginx/html/web-pos/"
    docker cp "$DIST_DIR/web-admin/." "$NGINX_CONTAINER:/usr/share/nginx/html/web-admin/"
    docker cp "$DIST_DIR/web-kds/." "$NGINX_CONTAINER:/usr/share/nginx/html/web-kds/"
    docker cp "$DIST_DIR/web-crew/." "$NGINX_CONTAINER:/usr/share/nginx/html/web-crew/"
    docker exec "$NGINX_CONTAINER" nginx -s reload 2>/dev/null || true
fi

# 启动所有服务
docker compose -f demo/docker-compose.demo-full.yml up -d
echo "  等待服务启动..."
sleep 10

# 检查服务状态
echo ""
echo -e "${YELLOW}[7/7] 服务状态检查...${NC}"
RUNNING=$(docker compose -f demo/docker-compose.demo-full.yml ps --status running -q | wc -l | tr -d ' ')
TOTAL=$(docker compose -f demo/docker-compose.demo-full.yml ps -q | wc -l | tr -d ' ')
echo -e "  运行中: ${GREEN}$RUNNING${NC} / $TOTAL"

# 尝试健康检查
sleep 5
if curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/health 2>/dev/null | grep -q "200"; then
    echo -e "${GREEN}  ✓ Gateway API 健康${NC}"
else
    echo -e "${YELLOW}  ⚠ Gateway 仍在启动中，请稍等30秒后重试${NC}"
fi

# 获取本机IP
LOCAL_IP=$(ifconfig en0 2>/dev/null | grep 'inet ' | awk '{print $2}' || echo "192.168.10.10")

echo ""
echo -e "${BLUE}╔══════════════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║                 演示环境部署完成！                       ║${NC}"
echo -e "${BLUE}╠══════════════════════════════════════════════════════════╣${NC}"
echo -e "${BLUE}║                                                        ║${NC}"
echo -e "${BLUE}║${NC}  Mac mini IP: ${GREEN}$LOCAL_IP${NC}                             ${BLUE}║${NC}"
echo -e "${BLUE}║                                                        ║${NC}"
echo -e "${BLUE}║${NC}  访问地址:                                              ${BLUE}║${NC}"
echo -e "${BLUE}║${NC}  POS收银:   ${GREEN}http://$LOCAL_IP/pos/${NC}               ${BLUE}║${NC}"
echo -e "${BLUE}║${NC}  KDS出餐:   ${GREEN}http://$LOCAL_IP/kds/${NC}               ${BLUE}║${NC}"
echo -e "${BLUE}║${NC}  总部后台:  ${GREEN}http://$LOCAL_IP/admin/${NC}             ${BLUE}║${NC}"
echo -e "${BLUE}║${NC}  服务员端:  ${GREEN}http://$LOCAL_IP/crew/${NC}              ${BLUE}║${NC}"
echo -e "${BLUE}║${NC}  API网关:   ${GREEN}http://$LOCAL_IP/api/health${NC}         ${BLUE}║${NC}"
echo -e "${BLUE}║                                                        ║${NC}"
echo -e "${BLUE}║${NC}  演示账号:                                              ${BLUE}║${NC}"
echo -e "${BLUE}║${NC}  尝在一起:  czq_admin / czq2024!                        ${BLUE}║${NC}"
echo -e "${BLUE}║${NC}  最黔线:    zqx_admin / zqx2024!                        ${BLUE}║${NC}"
echo -e "${BLUE}║${NC}  尚宫厨:    sgc_admin / sgc2024!                        ${BLUE}║${NC}"
echo -e "${BLUE}║${NC}  超管:      tx_superadmin / tunxiang2024!               ${BLUE}║${NC}"
echo -e "${BLUE}║                                                        ║${NC}"
echo -e "${BLUE}║${NC}  商米T2 POS: 打开浏览器访问 http://$LOCAL_IP/pos/  ${BLUE}║${NC}"
echo -e "${BLUE}║${NC}  商米V2:    打开浏览器访问 http://$LOCAL_IP/crew/   ${BLUE}║${NC}"
echo -e "${BLUE}║${NC}  KDS D2s:   打开浏览器访问 http://$LOCAL_IP/kds/   ${BLUE}║${NC}"
echo -e "${BLUE}║                                                        ║${NC}"
echo -e "${BLUE}╚══════════════════════════════════════════════════════════╝${NC}"
echo ""
echo "运行 'docker compose -f demo/docker-compose.demo-full.yml logs -f' 查看日志"
echo "运行 'docker compose -f demo/docker-compose.demo-full.yml down' 停止所有服务"
echo ""
