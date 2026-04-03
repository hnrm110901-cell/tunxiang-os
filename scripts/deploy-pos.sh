#!/bin/bash
# ═══════════════════════════════════════════════════════════
#  屯象OS — 品智POS接入部署脚本
#  在服务器 42.194.229.21 上执行
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

# ── Step 2: 写入商户凭证到 .env ──
echo ""
echo "=== Step 2: 写入商户凭证 ==="

# 检查是否已配置
if grep -q "CZYZ_PINZHI_API_TOKEN" $PROJECT_DIR/.env 2>/dev/null; then
    echo "⚠️  .env 中已有品智配置，跳过写入"
else
    cat >> $PROJECT_DIR/.env << 'MERCHANT_EOF'

# ══════════════════════════════════════════════════════════
#  三家商户 POS/CRM 凭证 (2026-03-28 配置)
# ══════════════════════════════════════════════════════════

# ── 尝在一起 (CZYZ) — 品智收银 ──
CZYZ_PINZHI_BASE_URL=https://czyq.pinzhikeji.net/api/v1
CZYZ_PINZHI_API_TOKEN=3bbc9bed2b42c1e1b3cca26389fbb81c
CZYZ_PINZHI_STORE_2461_TOKEN=752b4b16a863ce47def11cf33b1b521f
CZYZ_PINZHI_STORE_7269_TOKEN=f5cc1a27db6e215ae7bb5512b6b57981
CZYZ_PINZHI_STORE_19189_TOKEN=56cd51b69211297104a0608f6a696b80

# ── 尝在一起 — 奥琦玮CRM ──
CZYZ_AOQIWEI_BASE_URL=https://api.acewill.net
CZYZ_AOQIWEI_APP_ID=dp25MLoc2gnXE7A223ZiVv
CZYZ_AOQIWEI_APP_KEY=3d2eaa5f9b9a6a6746a18d28e770b501
CZYZ_AOQIWEI_MERCHANT_ID=1275413383

# ── 最黔线 (ZQX) — 品智收银 ──
ZQX_PINZHI_BASE_URL=https://ljcg.pinzhikeji.net/api/v1
ZQX_PINZHI_API_TOKEN=47a428538d350fac1640a51b6bbda68c
ZQX_PINZHI_STORE_20529_TOKEN=29cdb6acac3615070bb853afcbb32f60
ZQX_PINZHI_STORE_32109_TOKEN=ed2c948284d09cf9e096e9d965936aa3
ZQX_PINZHI_STORE_32304_TOKEN=43f0b54db12b0618ea612b2a0a4d2675
ZQX_PINZHI_STORE_32305_TOKEN=a8a4e4daf86875d4a4e0254b6eb7191e
ZQX_PINZHI_STORE_32306_TOKEN=d656668d285a100c851bbe149d4364f3
ZQX_PINZHI_STORE_32309_TOKEN=36bf0644e5703adc8a4d1ddd7b8f0e95

# ── 最黔线 — 奥琦玮CRM ──
ZQX_AOQIWEI_BASE_URL=https://api.acewill.net
ZQX_AOQIWEI_APP_ID=dp2C8kqBMmGrHUVpBjqAw8q3
ZQX_AOQIWEI_APP_KEY=56573c798c8ab0dc565e704190207f12
ZQX_AOQIWEI_MERCHANT_ID=1827518239

# ── 尚宫厨 (SGC) — 品智收银 ──
SGC_PINZHI_BASE_URL=https://xcsgc.pinzhikeji.net/api/v1
SGC_PINZHI_API_TOKEN=8275cf74d1943d7a32531d2d4f889870
SGC_PINZHI_STORE_2463_TOKEN=852f1d34c75af0b8eb740ef47f133130
SGC_PINZHI_STORE_7896_TOKEN=27a36f2feea6d3a914438f6cb32108c3
SGC_PINZHI_STORE_24777_TOKEN=5cbfb449112f698218e0b1be1a3bc7c6
SGC_PINZHI_STORE_36199_TOKEN=08f3791e15f48338405728a3a92fcd7f
SGC_PINZHI_STORE_41405_TOKEN=bb7e89dcd0ac339b51631eca99e51c9b

# ── 尚宫厨 — 奥琦玮CRM ──
SGC_AOQIWEI_BASE_URL=https://api.acewill.net
SGC_AOQIWEI_APP_ID=dp0X0jl45wauwdGgkRETITz
SGC_AOQIWEI_APP_KEY=649738234c7426bfa0dbfa431c92a750
SGC_AOQIWEI_MERCHANT_ID=1549254243

# ── 尚宫厨 — 卡券中心 ──
SGC_COUPON_BASE_URL=https://apigateway.acewill.net
SGC_COUPON_APP_ID=1549254243_6
SGC_COUPON_APP_KEY=d650652396b1bab5434d51c44c4d1436
SGC_COUPON_PLATFORMS=DOUYIN,ALIPAY,KUAISHOU,XHS,VIDEONUMBER,BANK,QITIAN,JD,TAOBAO,SHANGOU,AMAP

MERCHANT_EOF
    echo "✓ 三家商户凭证已写入 .env"
fi

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
# 用尝在一起文化城店测试
RESPONSE=$(curl -sf -X POST "https://czyq.pinzhikeji.net/api/v1/pinzhi/organizations.do" \
    -d "token=3bbc9bed2b42c1e1b3cca26389fbb81c" 2>&1) && echo "✓ 品智API可达" || echo "⚠️  品智API不可达: $RESPONSE"

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
