#!/bin/bash
# 屯象OS 快速启动（无 Docker，需本地 PostgreSQL + Python 3.12+）
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_ROOT"

echo "╔══════════════════════════════════════════════╗"
echo "║       屯象OS 快速启动（无 Docker）            ║"
echo "╚══════════════════════════════════════════════╝"

pip install -q "fastapi>=0.104.0" "uvicorn[standard]>=0.24.0" "pydantic>=2.4.0" \
    "sqlalchemy>=2.0.0" "asyncpg>=0.29.0" "structlog>=23.1.0" "apscheduler>=3.10.0" \
    "passlib[bcrypt]>=1.7.4" "PyJWT>=2.8.0" "httpx>=0.25.0"

export DATABASE_URL="${DATABASE_URL:-postgresql+asyncpg://tunxiang:changeme@localhost/tunxiang_os}"
export JWT_SECRET="${JWT_SECRET:-$(openssl rand -hex 32)}"
export PYTHONPATH="$PROJECT_ROOT"

python3 -c "import asyncio; from shared.ontology.src.database import init_db; asyncio.run(init_db()); print('✓ DB initialized')"
python3 scripts/demo_seed.py

pkill -f "uvicorn.*8007" 2>/dev/null || true
pkill -f "uvicorn.*8000" 2>/dev/null || true
sleep 1

python3 -m uvicorn services.tx_analytics.src.main:app --host 0.0.0.0 --port 8007 &
ANALYTICS_PID=$!

echo ""
echo "访问: http://localhost:8000"
echo "尝在一起: czq_admin / czq2024!"
echo "最黔线:   zqx_admin / zqx2024!"
echo "尚宫厨:   sgc_admin / sgc2024!"
echo "按 Ctrl+C 停止"

trap "kill $ANALYTICS_PID 2>/dev/null; exit 0" INT TERM
python3 -m uvicorn services.gateway.src.main:app --host 0.0.0.0 --port 8000
