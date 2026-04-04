#!/bin/bash
# ================================================================
# 屯象OS 演示环境 — 全链路验证脚本
# ================================================================
# 用法: bash demo/demo-verify.sh
# 在部署完成后运行，验证所有设备和服务是否正常
# ================================================================
set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

MAC_MINI_IP="${MAC_MINI_IP:-192.168.10.10}"
PRINTER_IP="${PRINTER_IP:-192.168.10.20}"
SUNMI_T2_IP="${SUNMI_T2_IP:-192.168.10.30}"
SUNMI_V2_IP="${SUNMI_V2_IP:-192.168.10.31}"
KDS_D2S_IP="${KDS_D2S_IP:-192.168.10.40}"

PASS=0
FAIL=0
WARN=0

check() {
    local name=$1
    local result=$2
    if [ "$result" -eq 0 ]; then
        echo -e "  ${GREEN}✓${NC} $name"
        PASS=$((PASS + 1))
    else
        echo -e "  ${RED}✗${NC} $name"
        FAIL=$((FAIL + 1))
    fi
}

warn() {
    local name=$1
    echo -e "  ${YELLOW}⚠${NC} $name（可选设备）"
    WARN=$((WARN + 1))
}

echo ""
echo -e "${BLUE}╔══════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║     屯象OS 演示环境 全链路验证               ║${NC}"
echo -e "${BLUE}╚══════════════════════════════════════════════╝${NC}"
echo ""

# ── 1. 网络连通性 ──
echo -e "${YELLOW}[1/5] 网络连通性${NC}"

ping -c 1 -W 2 "$MAC_MINI_IP" > /dev/null 2>&1
check "Mac mini ($MAC_MINI_IP)" $?

ping -c 1 -W 2 "$PRINTER_IP" > /dev/null 2>&1
check "佳博打印机 ($PRINTER_IP)" $?

ping -c 1 -W 2 "$SUNMI_T2_IP" > /dev/null 2>&1 && check "商米T2 ($SUNMI_T2_IP)" 0 || warn "商米T2 ($SUNMI_T2_IP) 未检测到"

ping -c 1 -W 2 "$SUNMI_V2_IP" > /dev/null 2>&1 && check "商米V2 ($SUNMI_V2_IP)" 0 || warn "商米V2 ($SUNMI_V2_IP) 未检测到"

ping -c 1 -W 2 "$KDS_D2S_IP" > /dev/null 2>&1 && check "商米KDS D2s ($KDS_D2S_IP)" 0 || warn "商米KDS D2s ($KDS_D2S_IP) 未检测到"

echo ""

# ── 2. Docker服务状态 ──
echo -e "${YELLOW}[2/5] Docker 服务状态${NC}"

SERVICES=(postgres redis gateway tx-trade tx-menu tx-member tx-growth tx-ops tx-supply tx-finance tx-agent tx-analytics tx-brain tx-intel tx-org nginx)
for svc in "${SERVICES[@]}"; do
    STATUS=$(docker compose -f demo/docker-compose.demo-full.yml ps "$svc" --format '{{.Status}}' 2>/dev/null | head -1)
    if echo "$STATUS" | grep -qi "up\|running"; then
        check "$svc: $STATUS" 0
    else
        check "$svc: ${STATUS:-not found}" 1
    fi
done

echo ""

# ── 3. API健康检查 ──
echo -e "${YELLOW}[3/5] API 健康检查${NC}"

HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" "http://$MAC_MINI_IP:8000/health" 2>/dev/null || echo "000")
[ "$HTTP_CODE" = "200" ] && check "Gateway /health (HTTP $HTTP_CODE)" 0 || check "Gateway /health (HTTP $HTTP_CODE)" 1

HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" "http://$MAC_MINI_IP/demo-status" 2>/dev/null || echo "000")
[ "$HTTP_CODE" = "200" ] && check "Nginx /demo-status (HTTP $HTTP_CODE)" 0 || check "Nginx /demo-status (HTTP $HTTP_CODE)" 1

echo ""

# ── 4. 前端页面 ──
echo -e "${YELLOW}[4/5] 前端页面可访问性${NC}"

for path in "/pos/" "/admin/" "/kds/" "/crew/"; do
    HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" "http://$MAC_MINI_IP$path" 2>/dev/null || echo "000")
    [ "$HTTP_CODE" = "200" ] && check "前端 $path (HTTP $HTTP_CODE)" 0 || check "前端 $path (HTTP $HTTP_CODE)" 1
done

echo ""

# ── 5. 打印机端口 ──
echo -e "${YELLOW}[5/5] 外设检查${NC}"

nc -z -w 3 "$PRINTER_IP" 9100 2>/dev/null && check "佳博打印机 TCP 9100" 0 || check "佳博打印机 TCP 9100" 1

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo -e "  结果: ${GREEN}通过 $PASS${NC} / ${RED}失败 $FAIL${NC} / ${YELLOW}可选 $WARN${NC}"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

if [ "$FAIL" -eq 0 ]; then
    echo -e "${GREEN}演示环境全部就绪！${NC}"
else
    echo -e "${RED}有 $FAIL 项需要修复，请检查上方标记 ✗ 的项目${NC}"
fi
echo ""
