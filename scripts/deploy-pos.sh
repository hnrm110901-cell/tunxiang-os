#!/bin/bash
# ═══════════════════════════════════════════════════════════
#  屯象OS — 品智POS接入部署脚本
#  在服务器 42.194.229.21 上执行
#
#  安全要求：所有商户凭证必须通过环境变量注入，禁止硬编码。
#  凭证来源：运维通过 Vault / 密钥管理服务注入 .env 文件。
# ═══════════════════════════════════════════════════════════
set -e

PROJECT_DIR="/opt/tunxiang-os"

echo "╔═══════════════════════════════════════╗"
echo "║  品智POS接入部署 — 三家商户14门店      ║"
echo "╚═══════════════════════════════════════╝"

# ── Step 1: 拉取最新代码 ──
echo ""
echo "=== Step 1: 拉取最新代码 ==="
cd $PROJECT_DIR
git pull origin main
echo "✓ 代码已更新"

# ── Step 2: 检查商户凭证 ──
echo ""
echo "=== Step 2: 检查商户凭证 ==="

# 必须的环境变量列表
REQUIRED_VARS=(
    "CZYZ_PINZHI_API_TOKEN"
    "CZYZ_AOQIWEI_APP_KEY"
    "ZQX_PINZHI_API_TOKEN"
    "ZQX_AOQIWEI_APP_KEY"
    "SGC_PINZHI_API_TOKEN"
    "SGC_AOQIWEI_APP_KEY"
    "SGC_COUPON_APP_KEY"
)

# 检查 .env 是否存在
if [ ! -f "$PROJECT_DIR/.env" ]; then
    echo "❌ .env 文件不存在！"
    echo ""
    echo "请先从密钥管理服务获取凭证并写入 .env："
    echo "  参考模板: $PROJECT_DIR/.env.example"
    echo "  必须包含: ${REQUIRED_VARS[*]}"
    echo ""
    echo "  方式1: 从 Vault 拉取"
    echo "    vault kv get -format=json secret/tunxiang/merchants > /tmp/creds.json"
    echo "    python3 scripts/inject-merchant-env.py /tmp/creds.json $PROJECT_DIR/.env"
    echo ""
    echo "  方式2: 手动创建"
    echo "    cp $PROJECT_DIR/.env.example $PROJECT_DIR/.env"
    echo "    # 然后填入真实凭证值"
    exit 1
fi

# 逐个检查必要环境变量
MISSING=0
for VAR in "${REQUIRED_VARS[@]}"; do
    if ! grep -q "^${VAR}=" "$PROJECT_DIR/.env" 2>/dev/null; then
        echo "❌ 缺少: $VAR"
        MISSING=1
    fi
done

if [ "$MISSING" -eq 1 ]; then
    echo ""
    echo "请补充缺失的凭证到 .env 文件后重新运行部署。"
    exit 1
fi

echo "✓ 所有商户凭证已配置"

# ── Step 3: 重启服务加载新环境变量 ──
echo ""
echo "=== Step 3: 重启服务 ==="
# 检测服务运行方式
if docker ps --format '{{.Names}}' | grep -q "tunxiang-gateway"; then
    echo "检测到 Docker 容器，重启中..."
    docker restart tunxiang-gateway
    sleep 5
elif systemctl is-active tunxiang-api &>/dev/null; then
    echo "检测到 systemd 服务，重启中..."
    systemctl restart tunxiang-api
    sleep 5
else
    echo "⚠️  未检测到服务管理器，请手动重启 Python 进程"
    echo "    kill $(pgrep -f 'uvicorn.*main') 2>/dev/null"
    echo "    cd $PROJECT_DIR/services/tunxiang-api && nohup python -m uvicorn src.main:app --host 0.0.0.0 --port 8000 &"
fi

# ── Step 4: 验证API可用 ──
echo ""
echo "=== Step 4: 验证API ==="
sleep 3
if curl -sf http://127.0.0.1:8000/docs > /dev/null 2>&1; then
    echo "✓ API 服务正常"
else
    echo "⚠️  API 未响应，请检查日志"
    echo "    docker logs tunxiang-gateway --tail 30"
    exit 1
fi

# ── Step 5: 验证品智API连通性 ──
echo ""
echo "=== Step 5: 验证品智API连通性 ==="
# 从 .env 读取 token（不硬编码）
CZYZ_TOKEN=$(grep '^CZYZ_PINZHI_API_TOKEN=' "$PROJECT_DIR/.env" | cut -d'=' -f2)
RESPONSE=$(curl -sf -X POST "https://czyq.pinzhikeji.net/api/v1/pinzhi/organizations.do" \
    -d "token=${CZYZ_TOKEN}" 2>&1) && echo "✓ 品智API可达" || echo "⚠️  品智API不可达: $RESPONSE"

# ── Step 6: 拉取尝在一起昨日数据 ──
echo ""
echo "=== Step 6: 拉取尝在一起数据 ==="
YESTERDAY=$(date -d "yesterday" +%Y-%m-%d 2>/dev/null || date -v-1d +%Y-%m-%d)
echo "拉取日期: $YESTERDAY"

curl -sf -X POST "http://127.0.0.1:8000/api/v1/integrations/pos-sync/backfill" \
    -H "Content-Type: application/json" \
    -d "{
        \"merchant_code\": \"czyz\",
        \"start_date\": \"$YESTERDAY\",
        \"end_date\": \"$YESTERDAY\",
        \"store_ids\": [\"2461\", \"7269\", \"19189\"]
    }" | python3 -m json.tool 2>/dev/null || echo "⚠️  数据拉取失败，请检查日志"

echo ""
echo "╔═══════════════════════════════════════════════════╗"
echo "║  部署完成！                                       ║"
echo "╠═══════════════════════════════════════════════════╣"
echo "║  品智API文档: https://czyq.pinzhikeji.net         ║"
echo "║  同步接口:    /api/v1/integrations/pos-sync/*     ║"
echo "║  Swagger:    http://127.0.0.1:8000/docs          ║"
echo "╠═══════════════════════════════════════════════════╣"
echo "║  后续操作:                                        ║"
echo "║  • 拉取最黔线: merchant_code='zqx'                ║"
echo "║  • 拉取尚宫厨: merchant_code='sgc'                ║"
echo "║  • 回填历史:   修改 start_date 往前推              ║"
echo "╚═══════════════════════════════════════════════════╝"
