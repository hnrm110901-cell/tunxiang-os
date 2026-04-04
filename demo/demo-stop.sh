#!/bin/bash
# ================================================================
# 屯象OS 演示环境 — 停止所有服务
# ================================================================
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_ROOT"

echo "停止屯象OS演示环境..."
docker compose -f demo/docker-compose.demo-full.yml down
echo "✓ 所有服务已停止"
echo ""
echo "如需清除数据卷（重置数据库），运行:"
echo "  docker compose -f demo/docker-compose.demo-full.yml down -v"
