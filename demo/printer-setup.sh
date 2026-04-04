#!/bin/bash
# ================================================================
# 佳博网络80打印机 配置与测试脚本
# ================================================================
# 用法: bash demo/printer-setup.sh [test|status|config]
# ================================================================

PRINTER_IP="${PRINTER_IP:-192.168.10.20}"
PRINTER_PORT="${PRINTER_PORT:-9100}"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo "╔══════════════════════════════════════╗"
echo "║  佳博网络80打印机 配置工具            ║"
echo "╚══════════════════════════════════════╝"
echo ""

# ── 功能：检查打印机连通性 ──
check_printer() {
    echo -e "${YELLOW}检查打印机连通性...${NC}"
    echo "  目标: $PRINTER_IP:$PRINTER_PORT"

    if ping -c 1 -W 2 "$PRINTER_IP" > /dev/null 2>&1; then
        echo -e "${GREEN}  ✓ Ping 通${NC}"
    else
        echo -e "${RED}  ✗ Ping 不通。请检查:${NC}"
        echo "    1. 打印机是否开机"
        echo "    2. 网线是否连接到路由器"
        echo "    3. 打印机IP是否已改为 $PRINTER_IP"
        echo ""
        echo "  修改打印机IP步骤:"
        echo "  ① 长按FEED键开机，打印自检页，查看当前IP"
        echo "  ② 电脑浏览器访问打印机当前IP（默认 192.168.123.100）"
        echo "  ③ 进入网络设置，修改IP为 $PRINTER_IP"
        echo "  ④ 子网: 255.255.255.0，网关: 192.168.10.1"
        echo "  ⑤ 保存重启"
        return 1
    fi

    # 检查TCP 9100端口
    if nc -z -w 3 "$PRINTER_IP" "$PRINTER_PORT" 2>/dev/null; then
        echo -e "${GREEN}  ✓ TCP $PRINTER_PORT 端口连通${NC}"
    else
        echo -e "${RED}  ✗ TCP $PRINTER_PORT 端口不通${NC}"
        echo "    打印机可能需要重启或检查网络端口设置"
        return 1
    fi

    echo -e "${GREEN}  ✓ 打印机就绪${NC}"
    return 0
}

# ── 功能：发送测试打印 ──
test_print() {
    echo -e "${YELLOW}发送测试打印...${NC}"

    if ! check_printer; then
        return 1
    fi

    # ESC/POS 测试打印内容
    # ESC @ = 初始化打印机
    # ESC a 1 = 居中对齐
    # ESC E 1 = 加粗开
    # ESC E 0 = 加粗关
    # GS V 1 = 切纸
    {
        printf '\x1b\x40'           # 初始化
        printf '\x1b\x61\x01'       # 居中
        printf '\x1b\x45\x01'       # 加粗
        printf '屯象OS 打印测试\n'
        printf '\x1b\x45\x00'       # 取消加粗
        printf '================================\n'
        printf '\x1b\x61\x00'       # 左对齐
        printf '打印机: 佳博网络80\n'
        printf 'IP地址: %s\n' "$PRINTER_IP"
        printf '端  口: %s\n' "$PRINTER_PORT"
        printf '时  间: %s\n' "$(date '+%Y-%m-%d %H:%M:%S')"
        printf '================================\n'
        printf '\x1b\x61\x01'       # 居中
        printf '演示环境打印测试成功!\n'
        printf '\n\n\n'
        printf '\x1d\x56\x01'       # 切纸
    } | nc -w 3 "$PRINTER_IP" "$PRINTER_PORT"

    if [ $? -eq 0 ]; then
        echo -e "${GREEN}  ✓ 测试打印已发送，请检查打印机出纸${NC}"
    else
        echo -e "${RED}  ✗ 发送失败${NC}"
        return 1
    fi
}

# ── 功能：打印模拟小票 ──
test_receipt() {
    echo -e "${YELLOW}发送模拟小票...${NC}"

    if ! check_printer; then
        return 1
    fi

    {
        printf '\x1b\x40'           # 初始化
        printf '\x1b\x61\x01'       # 居中
        printf '\x1b\x45\x01'       # 加粗
        printf '\x1d\x21\x11'       # 2倍宽高
        printf '尝在一起\n'
        printf '\x1d\x21\x00'       # 恢复正常
        printf '\x1b\x45\x00'
        printf '芙蓉路店\n'
        printf '================================\n'
        printf '\x1b\x61\x00'       # 左对齐
        printf '订单号: TX202604041200001A\n'
        printf '桌  号: A06\n'
        printf '人  数: 4\n'
        printf '时  间: 2026-04-04 12:35:22\n'
        printf '收银员: 张经理\n'
        printf '--------------------------------\n'
        printf '\x1b\x45\x01'
        printf '品名           数量  小计\n'
        printf '\x1b\x45\x00'
        printf '--------------------------------\n'
        printf '剁椒鱼头        x1  88.00\n'
        printf '口味虾          x1 128.00\n'
        printf '农家小炒肉      x1  42.00\n'
        printf '干锅花菜        x1  32.00\n'
        printf '米饭            x4  12.00\n'
        printf '鲜榨橙汁        x2  30.00\n'
        printf '--------------------------------\n'
        printf '小  计:            332.00\n'
        printf '优  惠:            -33.20\n'
        printf '\x1b\x45\x01'
        printf '\x1d\x21\x01'       # 2倍高
        printf '实  收:            298.80\n'
        printf '\x1d\x21\x00'
        printf '\x1b\x45\x00'
        printf '支付方式: 微信支付\n'
        printf '================================\n'
        printf '\x1b\x61\x01'       # 居中
        printf '屯象OS · AI-Native餐饮操作系统\n'
        printf '感谢光临，欢迎下次再来！\n'
        printf '\n\n\n'
        printf '\x1d\x56\x01'       # 切纸
    } | nc -w 3 "$PRINTER_IP" "$PRINTER_PORT"

    if [ $? -eq 0 ]; then
        echo -e "${GREEN}  ✓ 模拟小票已发送${NC}"
    else
        echo -e "${RED}  ✗ 发送失败${NC}"
    fi
}

# ── 主流程 ──
case "${1:-test}" in
    test)
        test_print
        ;;
    receipt)
        test_receipt
        ;;
    status|check)
        check_printer
        ;;
    *)
        echo "用法: $0 [test|receipt|status]"
        echo "  test    - 发送测试打印"
        echo "  receipt - 打印模拟小票"
        echo "  status  - 检查打印机连通性"
        ;;
esac
