#!/usr/bin/env bash
# 演示环境快速重置脚本
# 用法: bash scripts/reset_demo.sh
#
# 流程:
# 1. 清空所有业务表(保留 alembic 迁移表)
# 2. 重新运行种子脚本
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

echo "============================================"
echo "  屯象OS 演示环境重置"
echo "============================================"
echo ""
echo "警告: 此操作将清空所有业务数据!"
echo ""

# 确认
read -r -p "确认重置? (输入 yes 继续): " confirm
if [[ "$confirm" != "yes" ]]; then
    echo "已取消"
    exit 0
fi

echo ""
echo "[1/2] 清空业务表 + 写入种子数据..."
cd "$PROJECT_ROOT"
python scripts/seed_demo_data.py --reset

echo ""
echo "[2/2] 验证数据..."
python -c "
import asyncio
import sys
sys.path.insert(0, '.')
from sqlalchemy import text

async def verify():
    from shared.ontology.src.database import async_session_factory
    async with async_session_factory() as session:
        tables = ['stores', 'dishes', 'employees', 'customers', 'ingredients', 'orders', 'order_items']
        print()
        print('  验证结果:')
        for t in tables:
            result = await session.execute(text(f'SELECT COUNT(*) FROM {t}'))
            count = result.scalar()
            print(f'    {t:<25} {count:>8,} rows')
        print()

asyncio.run(verify())
"

echo "============================================"
echo "  重置完成!"
echo "============================================"
