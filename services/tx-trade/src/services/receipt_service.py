"""小票打印服务 — ESC/POS 命令生成 + 厨房分单"""

import hashlib

import structlog

logger = structlog.get_logger()


# ─── ESC/POS 命令常量 ───
ESC = b"\x1b"
GS = b"\x1d"
LF = b"\x0a"
CUT = GS + b"\x56\x00"  # 切纸
ALIGN_CENTER = ESC + b"\x61\x01"
ALIGN_LEFT = ESC + b"\x61\x00"
ALIGN_RIGHT = ESC + b"\x61\x02"
BOLD_ON = ESC + b"\x45\x01"
BOLD_OFF = ESC + b"\x45\x00"
DOUBLE_HEIGHT = GS + b"\x21\x11"
NORMAL_SIZE = GS + b"\x21\x00"
OPEN_DRAWER = ESC + b"\x70\x00\x19\xfa"


class ReceiptService:
    """小票打印服务"""

    @staticmethod
    def format_receipt(order: dict, store_name: str = "", paper_width: int = 58) -> bytes:
        """生成客户小票 ESC/POS 命令

        Args:
            order: 订单数据（含 items）
            store_name: 门店名称
            paper_width: 纸宽 58mm 或 80mm

        Returns:
            ESC/POS 字节流，直接发送到打印机
        """
        cols = 32 if paper_width == 58 else 48
        sep = b"-" * cols + LF
        buf = bytearray()

        # 门店名（居中加粗大字）
        buf += ALIGN_CENTER + DOUBLE_HEIGHT + BOLD_ON
        buf += (store_name or "TunxiangOS").encode("gbk", errors="replace") + LF
        buf += NORMAL_SIZE + BOLD_OFF

        # 订单信息
        buf += ALIGN_LEFT + sep
        buf += f"单号: {order.get('order_no', '')}\n".encode("gbk", errors="replace")
        buf += f"桌号: {order.get('table_number', '-')}\n".encode("gbk", errors="replace")
        buf += f"时间: {order.get('order_time', '')[:19]}\n".encode("gbk", errors="replace")
        buf += sep

        # 菜品明细
        buf += BOLD_ON
        buf += _pad_line("品名", "数量", "金额", cols).encode("gbk", errors="replace")
        buf += BOLD_OFF + sep

        for item in order.get("items", []):
            name = item.get("item_name", "")[:12]
            qty = str(item.get("quantity", 0))
            amount = _fen_to_yuan(item.get("subtotal_fen", 0))
            buf += _pad_line(name, qty, amount, cols).encode("gbk", errors="replace")

        buf += sep

        # 合计
        total = _fen_to_yuan(order.get("total_amount_fen", 0))
        discount = _fen_to_yuan(order.get("discount_amount_fen", 0))
        final = _fen_to_yuan(order.get("final_amount_fen", 0))

        buf += f"合计: {total}\n".encode("gbk", errors="replace")
        if order.get("discount_amount_fen", 0) > 0:
            buf += f"优惠: -{discount}\n".encode("gbk", errors="replace")
        buf += BOLD_ON + DOUBLE_HEIGHT
        buf += f"应付: {final}\n".encode("gbk", errors="replace")
        buf += NORMAL_SIZE + BOLD_OFF

        # 尾部
        buf += sep
        buf += ALIGN_CENTER
        buf += "谢谢惠顾 欢迎再次光临\n".encode("gbk", errors="replace")
        buf += LF + LF + CUT

        return bytes(buf)

    @staticmethod
    def format_kitchen_order(order: dict, station: str, paper_width: int = 80) -> bytes:
        """生成厨房单 — 按档口过滤菜品

        Args:
            order: 订单数据
            station: 目标档口（如"热菜档"/"凉菜档"/"面点档"）
            paper_width: 纸宽

        Returns:
            ESC/POS 字节流
        """
        cols = 48 if paper_width == 80 else 32
        buf = bytearray()

        buf += ALIGN_CENTER + DOUBLE_HEIGHT + BOLD_ON
        buf += f"[{station}]\n".encode("gbk", errors="replace")
        buf += NORMAL_SIZE + BOLD_OFF

        buf += ALIGN_LEFT
        buf += f"桌号: {order.get('table_number', '-')}  单号: {order.get('order_no', '')[-6:]}\n".encode(
            "gbk", errors="replace"
        )
        buf += (b"-" * cols) + LF

        for item in order.get("items", []):
            buf += BOLD_ON + DOUBLE_HEIGHT
            buf += f"  {item['item_name']}  x{item['quantity']}\n".encode("gbk", errors="replace")
            buf += NORMAL_SIZE + BOLD_OFF
            if item.get("notes"):
                buf += f"    [{item['notes']}]\n".encode("gbk", errors="replace")

        buf += LF + CUT
        return bytes(buf)

    @staticmethod
    def split_by_station(order: dict) -> dict[str, list]:
        """按档口拆分订单明细

        Returns:
            {"热菜档": [item1, item2], "凉菜档": [item3], "default": [item4]}
        """
        stations: dict[str, list] = {}
        for item in order.get("items", []):
            station = item.get("kitchen_station") or "default"
            stations.setdefault(station, []).append(item)
        return stations

    @staticmethod
    def content_hash(content: bytes) -> str:
        """生成内容哈希，防止重复打印"""
        return hashlib.sha256(content).hexdigest()[:16]

    # ─── F6: 高级打印功能 ───

    @staticmethod
    def format_delivery_receipt(order: dict, store_name: str = "", paper_width: int = 58) -> bytes:
        """生成外卖配送单（含地址+电话）

        Args:
            order: 订单数据（含 items + delivery_address + delivery_phone + rider_name）
            store_name: 门店名称

        Returns:
            ESC/POS 字节流
        """
        cols = 32 if paper_width == 58 else 48
        sep = b"-" * cols + LF
        buf = bytearray()

        # 标题
        buf += ALIGN_CENTER + DOUBLE_HEIGHT + BOLD_ON
        buf += "[ 外 卖 单 ]\n".encode("gbk", errors="replace")
        buf += NORMAL_SIZE + BOLD_OFF

        buf += (store_name or "TunxiangOS").encode("gbk", errors="replace") + LF
        buf += sep

        # 订单信息
        buf += ALIGN_LEFT
        buf += f"单号: {order.get('order_no', '')}\n".encode("gbk", errors="replace")
        buf += f"时间: {order.get('order_time', '')[:19]}\n".encode("gbk", errors="replace")
        buf += sep

        # 配送信息（加粗突出）
        buf += BOLD_ON + DOUBLE_HEIGHT
        buf += f"地址: {order.get('delivery_address', '')}\n".encode("gbk", errors="replace")
        buf += NORMAL_SIZE
        buf += f"电话: {order.get('delivery_phone', '')}\n".encode("gbk", errors="replace")
        buf += BOLD_OFF

        rider = order.get("rider_name", "")
        if rider:
            buf += f"骑手: {rider}\n".encode("gbk", errors="replace")
        buf += sep

        # 菜品明细
        buf += BOLD_ON
        buf += _pad_line("品名", "数量", "金额", cols).encode("gbk", errors="replace")
        buf += BOLD_OFF + sep

        for item in order.get("items", []):
            name = item.get("item_name", "")[:12]
            qty = str(item.get("quantity", 0))
            amount = _fen_to_yuan(item.get("subtotal_fen", 0))
            buf += _pad_line(name, qty, amount, cols).encode("gbk", errors="replace")

        buf += sep

        # 合计
        total = _fen_to_yuan(order.get("total_amount_fen", 0))
        delivery_fee = _fen_to_yuan(order.get("delivery_fee_fen", 0))
        final = _fen_to_yuan(order.get("final_amount_fen", 0))

        buf += f"菜品合计: {total}\n".encode("gbk", errors="replace")
        if order.get("delivery_fee_fen", 0) > 0:
            buf += f"配送费:   {delivery_fee}\n".encode("gbk", errors="replace")
        buf += BOLD_ON + DOUBLE_HEIGHT
        buf += f"应付: {final}\n".encode("gbk", errors="replace")
        buf += NORMAL_SIZE + BOLD_OFF

        # 备注
        remark = order.get("remark", "")
        if remark:
            buf += sep
            buf += BOLD_ON
            buf += f"备注: {remark}\n".encode("gbk", errors="replace")
            buf += BOLD_OFF

        buf += sep + LF + CUT
        return bytes(buf)

    @staticmethod
    def format_shift_report(settlement: dict, store_name: str = "", paper_width: int = 80) -> bytes:
        """生成交接班报表打印

        Args:
            settlement: 交班汇总数据（含营收/支付方式/订单数等）
            store_name: 门店名称

        Returns:
            ESC/POS 字节流
        """
        cols = 48 if paper_width == 80 else 32
        sep = b"=" * cols + LF
        dash = b"-" * cols + LF
        buf = bytearray()

        # 标题
        buf += ALIGN_CENTER + DOUBLE_HEIGHT + BOLD_ON
        buf += "交 接 班 报 表\n".encode("gbk", errors="replace")
        buf += NORMAL_SIZE + BOLD_OFF
        buf += (store_name or "TunxiangOS").encode("gbk", errors="replace") + LF
        buf += sep

        # 基本信息
        buf += ALIGN_LEFT
        buf += f"日期: {settlement.get('settlement_date', '')}\n".encode("gbk", errors="replace")
        buf += f"班次: {settlement.get('settlement_type', 'shift')}\n".encode("gbk", errors="replace")
        buf += f"操作员: {settlement.get('operator_id', '')}\n".encode("gbk", errors="replace")
        buf += dash

        # 营收汇总
        buf += BOLD_ON
        buf += "营收汇总\n".encode("gbk", errors="replace")
        buf += BOLD_OFF
        buf += f"  总营收:   {_fen_to_yuan(settlement.get('total_revenue_fen', 0))}\n".encode("gbk", errors="replace")
        buf += f"  总折扣:  -{_fen_to_yuan(settlement.get('total_discount_fen', 0))}\n".encode("gbk", errors="replace")
        buf += f"  总退款:  -{_fen_to_yuan(settlement.get('total_refund_fen', 0))}\n".encode("gbk", errors="replace")
        buf += BOLD_ON
        buf += f"  净营收:   {_fen_to_yuan(settlement.get('net_revenue_fen', 0))}\n".encode("gbk", errors="replace")
        buf += BOLD_OFF
        buf += dash

        # 按支付方式
        buf += BOLD_ON
        buf += "支付方式明细\n".encode("gbk", errors="replace")
        buf += BOLD_OFF
        payment_methods = [
            ("现金", "cash_fen"),
            ("微信", "wechat_fen"),
            ("支付宝", "alipay_fen"),
            ("银联", "unionpay_fen"),
            ("挂账", "credit_fen"),
            ("会员余额", "member_balance_fen"),
        ]
        for label, key in payment_methods:
            val = settlement.get(key, 0)
            if val > 0:
                buf += f"  {label}: {_fen_to_yuan(val)}\n".encode("gbk", errors="replace")
        buf += dash

        # 订单统计
        buf += BOLD_ON
        buf += "订单统计\n".encode("gbk", errors="replace")
        buf += BOLD_OFF
        buf += f"  总单数: {settlement.get('total_orders', 0)}\n".encode("gbk", errors="replace")
        buf += f"  总客数: {settlement.get('total_guests', 0)}\n".encode("gbk", errors="replace")
        buf += f"  客单价: {_fen_to_yuan(settlement.get('avg_per_guest_fen', 0))}\n".encode("gbk", errors="replace")
        buf += dash

        # 现金盘点
        buf += BOLD_ON
        buf += "现金盘点\n".encode("gbk", errors="replace")
        buf += BOLD_OFF
        buf += f"  应有现金: {_fen_to_yuan(settlement.get('cash_expected_fen', 0))}\n".encode("gbk", errors="replace")
        actual = settlement.get("cash_actual_fen")
        if actual is not None:
            buf += f"  实际现金: {_fen_to_yuan(actual)}\n".encode("gbk", errors="replace")
            diff = settlement.get("cash_diff_fen", 0)
            buf += f"  差异:     {_fen_to_yuan(diff)}\n".encode("gbk", errors="replace")

        buf += sep
        buf += ALIGN_CENTER
        buf += "交班确认签字: __________\n".encode("gbk", errors="replace")
        buf += "接班确认签字: __________\n".encode("gbk", errors="replace")
        buf += LF + LF + CUT
        return bytes(buf)

    @staticmethod
    def format_prepay_receipt(order: dict, deposit_fen: int, store_name: str = "", paper_width: int = 58) -> bytes:
        """生成预结单（含定金信息）

        Args:
            order: 订单数据
            deposit_fen: 已收定金（分）
            store_name: 门店名称

        Returns:
            ESC/POS 字节流
        """
        cols = 32 if paper_width == 58 else 48
        sep = b"-" * cols + LF
        buf = bytearray()

        # 标题
        buf += ALIGN_CENTER + DOUBLE_HEIGHT + BOLD_ON
        buf += "[ 预 结 单 ]\n".encode("gbk", errors="replace")
        buf += NORMAL_SIZE + BOLD_OFF
        buf += (store_name or "TunxiangOS").encode("gbk", errors="replace") + LF
        buf += sep

        # 订单信息
        buf += ALIGN_LEFT
        buf += f"单号: {order.get('order_no', '')}\n".encode("gbk", errors="replace")
        buf += f"桌号: {order.get('table_number', '-')}\n".encode("gbk", errors="replace")
        buf += f"时间: {order.get('order_time', '')[:19]}\n".encode("gbk", errors="replace")
        buf += sep

        # 菜品明细
        buf += BOLD_ON
        buf += _pad_line("品名", "数量", "金额", cols).encode("gbk", errors="replace")
        buf += BOLD_OFF + sep

        for item in order.get("items", []):
            name = item.get("item_name", "")[:12]
            qty = str(item.get("quantity", 0))
            amount = _fen_to_yuan(item.get("subtotal_fen", 0))
            buf += _pad_line(name, qty, amount, cols).encode("gbk", errors="replace")

        buf += sep

        # 金额汇总
        total = _fen_to_yuan(order.get("total_amount_fen", 0))
        discount = _fen_to_yuan(order.get("discount_amount_fen", 0))
        final_fen = order.get("final_amount_fen", 0)
        remaining_fen = max(final_fen - deposit_fen, 0)

        buf += f"合计:     {total}\n".encode("gbk", errors="replace")
        if order.get("discount_amount_fen", 0) > 0:
            buf += f"优惠:    -{discount}\n".encode("gbk", errors="replace")
        buf += f"应付:     {_fen_to_yuan(final_fen)}\n".encode("gbk", errors="replace")
        buf += sep
        buf += BOLD_ON + DOUBLE_HEIGHT
        buf += f"已收定金: {_fen_to_yuan(deposit_fen)}\n".encode("gbk", errors="replace")
        buf += f"待付余款: {_fen_to_yuan(remaining_fen)}\n".encode("gbk", errors="replace")
        buf += NORMAL_SIZE + BOLD_OFF

        # 提示
        buf += sep
        buf += ALIGN_CENTER
        buf += "此单为预结单 非最终结算凭证\n".encode("gbk", errors="replace")
        buf += "最终金额以结账单为准\n".encode("gbk", errors="replace")
        buf += LF + LF + CUT
        return bytes(buf)


def generate_qr_code_escpos(url: str, size: int = 4) -> bytes:
    """生成二维码 ESC/POS 命令（支付码/评价码）

    支持 QR Code Model 2，大小可调。
    适用于微信/支付宝付款码、好评二维码等场景。

    Args:
        url: 二维码内容（URL 或支付码字符串）
        size: 二维码模块大小 1-16，默认 4

    Returns:
        ESC/POS 字节流（包含居中对齐）
    """
    if not url:
        return b""

    data = url.encode("utf-8")
    data_len = len(data) + 3
    pL = data_len & 0xFF
    pH = (data_len >> 8) & 0xFF

    buf = bytearray()

    # 居中
    buf += ALIGN_CENTER

    # QR Code Model 2
    buf += GS + b"(k\x04\x001A2\x00"

    # 设置大小 (1-16)
    size = max(1, min(16, size))
    buf += GS + b"(k\x03\x001C" + bytes([size])

    # 纠错等级 M (49)
    buf += GS + b"(k\x03\x001E1"

    # 存储数据
    buf += GS + b"(k" + bytes([pL, pH]) + b"1P0" + data

    # 打印二维码
    buf += GS + b"(k\x03\x001Q0"

    # 恢复左对齐
    buf += ALIGN_LEFT + LF

    return bytes(buf)


def format_kitchen_label(
    dish_name: str,
    table_no: str,
    notes: str = "",
    seq: int = 1,
    paper_width: int = 40,
) -> bytes:
    """生成厨房贴标签（小标签纸）

    适用于 40mm 小标签打印机，用于菜品出品标识。

    Args:
        dish_name: 菜品名称
        table_no: 桌号
        notes: 备注（如"不辣""多葱"）
        seq: 出品序号
        paper_width: 标签纸宽度 mm

    Returns:
        ESC/POS 字节流
    """
    cols = 20 if paper_width <= 40 else 32
    buf = bytearray()

    # 菜品名（大字加粗居中）
    buf += ALIGN_CENTER + BOLD_ON + DOUBLE_HEIGHT
    buf += dish_name.encode("gbk", errors="replace") + LF
    buf += NORMAL_SIZE + BOLD_OFF

    # 桌号 + 序号
    buf += BOLD_ON
    buf += f"{table_no} #{seq}".encode("gbk", errors="replace") + LF
    buf += BOLD_OFF

    # 备注
    if notes:
        buf += b"-" * cols + LF
        buf += BOLD_ON
        buf += f"[{notes}]".encode("gbk", errors="replace") + LF
        buf += BOLD_OFF

    buf += LF + CUT
    return bytes(buf)


def _fen_to_yuan(fen: int) -> str:
    """分转元，保留2位小数"""
    return f"¥{fen / 100:.2f}"


def _pad_line(left: str, mid: str, right: str, cols: int) -> str:
    """三栏对齐"""
    mid_pos = cols // 2
    right_pos = cols - len(right.encode("gbk", errors="replace"))
    line = left.ljust(mid_pos - len(mid)) + mid + right.rjust(cols - mid_pos)
    return line[:cols] + "\n"
