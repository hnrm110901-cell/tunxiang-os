#!/bin/bash
# ================================================================
# 屯象OS 演示环境 — 重置数据（保留容器，清空数据库重新导入）
# ================================================================
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_ROOT"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${YELLOW}重置演示数据...${NC}"
echo "这将清空所有数据并重新导入三商户演示数据"
echo ""

# 重新初始化数据库
echo "[1/2] 重建表结构..."
docker compose -f demo/docker-compose.demo-full.yml exec -T gateway \
    python -c "import asyncio; from shared.ontology.src.database import init_db; asyncio.run(init_db())" 2>/dev/null \
    || docker compose -f demo/docker-compose.demo-full.yml run --rm -T gateway \
    bash -c "pip install --no-cache-dir -q fastapi>=0.104.0 pydantic>=2.4.0 sqlalchemy>=2.0.0 asyncpg>=0.29.0 structlog>=23.1.0 passlib[bcrypt]>=1.7.4 PyJWT>=2.8.0 httpx>=0.25.0 redis>=5.0.0 python-multipart>=0.0.6 aiofiles>=23.0.0 && python -c 'import asyncio; from shared.ontology.src.database import init_db; asyncio.run(init_db())'"
echo -e "${GREEN}  ✓ 表结构就绪${NC}"

# 重新导入数据
echo "[2/2] 导入演示数据..."
docker compose -f demo/docker-compose.demo-full.yml exec -T gateway \
    python scripts/demo_seed.py 2>/dev/null \
    || docker compose -f demo/docker-compose.demo-full.yml run --rm -T gateway \
    bash -c "pip install --no-cache-dir -q fastapi>=0.104.0 pydantic>=2.4.0 sqlalchemy>=2.0.0 asyncpg>=0.29.0 structlog>=23.1.0 passlib[bcrypt]>=1.7.4 PyJWT>=2.8.0 httpx>=0.25.0 redis>=5.0.0 python-multipart>=0.0.6 aiofiles>=23.0.0 && python scripts/demo_seed.py"

echo ""
echo -e "${GREEN}✓ 演示数据重置完成！${NC}"
echo "  尝在一起: czq_admin / czq2024!"
echo "  最黔线:   zqx_admin / zqx2024!"
echo "  尚宫厨:   sgc_admin / sgc2024!"
