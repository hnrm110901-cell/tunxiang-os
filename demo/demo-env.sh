#!/bin/bash
# ================================================================
# 屯象OS 演示环境 环境变量配置
# ================================================================
# 用法: source demo/demo-env.sh
# ================================================================

# ── 网络配置 ──
export MAC_MINI_IP="192.168.10.10"
export PRINTER_IP="192.168.10.20"
export PRINTER_PORT="9100"
export SUNMI_T2_IP="192.168.10.30"
export SUNMI_V2_IP="192.168.10.31"
export KDS_D2S_IP="192.168.10.40"

# ── 数据库 ──
export DATABASE_URL="postgresql+asyncpg://tunxiang:tunxiang_demo_2024@localhost:5432/tunxiang_os"
export POSTGRES_USER="tunxiang"
export POSTGRES_PASSWORD="tunxiang_demo_2024"
export POSTGRES_DB="tunxiang_os"

# ── Redis ──
export REDIS_URL="redis://localhost:6379/0"

# ── JWT ──
export TX_JWT_SECRET_KEY="tunxiang-demo-jwt-secret-2024-mac-mini"

# ── 环境标识 ──
export ENV_NAME="demo"
export TZ="Asia/Shanghai"
export PYTHONPATH="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# ── AI（可选，填入后Agent功能可用）──
export ANTHROPIC_API_KEY="${ANTHROPIC_API_KEY:-}"

# ── 演示商户 ──
export TENANT_1_ID="10000000-0000-0000-0000-000000000001"
export TENANT_1_NAME="尝在一起"
export TENANT_2_ID="10000000-0000-0000-0000-000000000002"
export TENANT_2_NAME="最黔线"
export TENANT_3_ID="10000000-0000-0000-0000-000000000003"
export TENANT_3_NAME="尚宫厨"

echo "屯象OS 演示环境变量已加载"
echo "  Mac mini: $MAC_MINI_IP"
echo "  打印机:   $PRINTER_IP:$PRINTER_PORT"
echo "  数据库:   localhost:5432/tunxiang_os"
