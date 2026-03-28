#!/bin/bash
# ================================================================
# 屯象OS 演示环境一键部署
# ================================================================
# 用法: bash scripts/demo_deploy.sh
#
# 前置条件: Docker & Docker Compose, Node.js 18+
# 部署完成后访问: http://localhost:8000
# ================================================================
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_ROOT"

echo ""
echo "╔══════════════════════════════════════════════╗"
echo "║       屯象OS 演示环境 一键部署               ║"
echo "╚══════════════════════════════════════════════╝"
echo ""

# Step 1: Build frontend
echo "[1/5] 构建前端 (apps/web-admin)..."
if [ -d "apps/web-admin" ]; then
    cd apps/web-admin
    [ ! -d "node_modules" ] && npm install --silent
    npm run build 2>&1 | tail -3
    cd "$PROJECT_ROOT"
    echo "  ✓ 前端构建完成"
else
    mkdir -p apps/web-admin/dist
    echo "<h1>屯象OS</h1>" > apps/web-admin/dist/index.html
fi

# Step 2: Start containers
echo "[2/5] 启动 Docker 容器..."
docker compose -f infra/docker/docker-compose.demo.yml up -d --build 2>&1 | tail -5
echo "  ✓ 容器已启动"

# Step 3: Wait for DB
echo "[3/5] 等待 PostgreSQL 就绪..."
for i in $(seq 1 30); do
    if docker compose -f infra/docker/docker-compose.demo.yml exec -T postgres pg_isready -U tunxiang -d tunxiang_os > /dev/null 2>&1; then
        echo "  ✓ 数据库已就绪 (${i}s)"; break
    fi
    [ "$i" -eq 30 ] && echo "  ✗ 超时" && exit 1
    sleep 1
done

# Step 4: Init DB
echo "[4/5] 初始化数据库..."
docker compose -f infra/docker/docker-compose.demo.yml exec -T gateway \
    python -c "import asyncio; from shared.ontology.src.database import init_db; asyncio.run(init_db()); print('  ✓ 完成')"

# Step 5: Seed data
echo "[5/5] 导入三商户演示数据..."
docker compose -f infra/docker/docker-compose.demo.yml exec -T gateway python scripts/demo_seed.py

echo ""
echo "╔══════════════════════════════════════════════╗"
echo "║              部署完成！                       ║"
echo "╠══════════════════════════════════════════════╣"
echo "║  访问: http://localhost:8000                  ║"
echo "║                                              ║"
echo "║  尝在一起: czq_admin / czq2024!              ║"
echo "║  最黔线:   zqx_admin / zqx2024!              ║"
echo "║  尚宫厨:   sgc_admin / sgc2024!              ║"
echo "║  屯象超管: tx_superadmin / tunxiang2024!     ║"
echo "╚══════════════════════════════════════════════╝"
