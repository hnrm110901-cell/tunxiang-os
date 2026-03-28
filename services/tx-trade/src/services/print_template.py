"""小票模板引擎 — 各类打印模板的 ESC/POS 字节流生成

支持模板类型：
- 收银小票（cashier_receipt）
- 厨打小票（kitchen_ticket）
- 结账单/客用（checkout_bill）
- 交班报表（shift_report）
- 菜品标签（label）
- 日结报表（daily_report）

输出: bytes — 可直接通过 ESCPOSPrinter.send_raw() 发送到打印机。
纸宽: 80mm = 48 ASCII 字符 = 24 中文字符。
编码: GBK。
"""
from datetime import datetime
from typing import Optional

import structlog

from .printer_driver import (
    ESC_INIT,
    ESC_ALIGN_LEFT,
    ESC_ALIGN_CENTER,
    ESC_ALIGN_RIGHT,
    ESC_BOLD_ON,
    ESC_BOLD_OFF,
    GS_SIZE_NORMAL,
    GS_SIZE_DOUBLE_WIDTH,
    GS_SIZE_DOUBLE_HEIGHT,
    GS_SIZE_DOUBLE_BOTH,
    GS_CUT_PARTIAL,
    GS_CUT_FULL,
    ESC_OPEN_DRAWER,
    ESC_FEED,
    ESC_CHINESE_ON,
    LF,
    LINE_WIDTH,
    _gbk_len,
    _pad_two_columns,
    _pad_three_columns,
)

logger = structlog.get_logger()


def _fen_to_yuan(fen: int) -> str:
    """分转元，保留2位小数。"""
    return f"\xa5{fen / 100:.2f}"  # \xa5 = GBK 中的 ¥


def _sep(char: str = "-") -> bytes:
    """生成分割线。"""
    return (char * LINE_WIDTH).encode("ascii") + LF


def _now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


class ReceiptTemplate:
    """小票模板生成器

    所有 render_* 方法返回完整的 ESC/POS 字节流（含初始化和切纸指令），
    可直接通过 ESCPOSPrinter.send_raw() 发送到打印机。
    """

    @staticmethod
    async def render_cashier_receipt(
        order: dict,
        store: dict,
        payment: dict,
    ) -> bytes:
        """渲染收银小票。

        内容: 店名 → 桌号 → 菜品列表 → 小计 → 折扣 → 实收 → 支付方式 → 二维码

        Args:
            order: 订单数据 {order_no, table_number, order_time, items, total_amount_fen, ...}
            store: 门店信息 {name, address, phone, qr_url}
            payment: 支付信息 {method, amount_fen, pay_time}

        Returns:
            ESC/POS 字节流
        """
        store_name = store.get("name", "屯象OS")
        buf = bytearray()
        buf += ESC_INIT

        # ── 店名（居中加粗大字）──
        buf += ESC_ALIGN_CENTER + GS_SIZE_DOUBLE_BOTH + ESC_BOLD_ON
        buf += store_name.encode("gbk", errors="replace") + LF
        buf += GS_SIZE_NORMAL + ESC_BOLD_OFF

        # 门店信息
        address = store.get("address", "")
        phone = store.get("phone", "")
        if address:
            buf += address.encode("gbk", errors="replace") + LF
        if phone:
            buf += f"电话: {phone}".encode("gbk", errors="replace") + LF

        buf += ESC_ALIGN_LEFT + _sep()

        # ── 订单信息 ──
        buf += f"单号: {order.get('order_no', '')}".encode("gbk", errors="replace") + LF
        table = order.get("table_number", "-")
        if table and table != "-":
            buf += f"桌号: {table}".encode("gbk", errors="replace") + LF
        order_time = order.get("order_time", "")
        if order_time:
            buf += f"时间: {str(order_time)[:19]}".encode("gbk", errors="replace") + LF
        buf += _sep()

        # ── 菜品明细 ──
        buf += ESC_BOLD_ON
        buf += _pad_three_columns("品名", "数量", "金额", LINE_WIDTH).encode("gbk", errors="replace") + LF
        buf += ESC_BOLD_OFF + _sep()

        for item in order.get("items", []):
            name = item.get("item_name", "")
            if _gbk_len(name) > 20:
                name = name[:10]
            qty = str(item.get("quantity", 0))
            amount = _fen_to_yuan(item.get("subtotal_fen", 0))
            buf += _pad_three_columns(name, qty, amount, LINE_WIDTH).encode("gbk", errors="replace") + LF

        buf += _sep()

        # ── 合计 ──
        total = _fen_to_yuan(order.get("total_amount_fen", 0))
        buf += _pad_two_columns("合计:", total).encode("gbk", errors="replace") + LF

        discount_fen = order.get("discount_amount_fen", 0)
        if discount_fen > 0:
            buf += _pad_two_columns("优惠:", f"-{_fen_to_yuan(discount_fen)}").encode("gbk", errors="replace") + LF

        # 实收（大字加粗）
        final = _fen_to_yuan(order.get("final_amount_fen", 0))
        buf += GS_SIZE_DOUBLE_BOTH + ESC_BOLD_ON
        buf += _pad_two_columns("实收:", final).encode("gbk", errors="replace") + LF
        buf += GS_SIZE_NORMAL + ESC_BOLD_OFF

        # ── 支付方式 ──
        buf += _sep()
        method_labels = {
            "wechat": "微信支付",
            "alipay": "支付宝",
            "cash": "现金",
            "unionpay": "银联",
            "member": "会员余额",
        }
        method = payment.get("method", "")
        label = method_labels.get(method, method)
        buf += f"支付方式: {label}".encode("gbk", errors="replace") + LF
        pay_time = payment.get("pay_time", "")
        if pay_time:
            buf += f"支付时间: {str(pay_time)[:19]}".encode("gbk", errors="replace") + LF

        # ── 二维码 ──
        qr_url = store.get("qr_url", "")
        if qr_url:
            buf += _sep()
            buf += ESC_ALIGN_CENTER
            buf += "扫码关注 享更多优惠".encode("gbk", errors="replace") + LF
            buf += _build_qrcode(qr_url)
            buf += ESC_ALIGN_LEFT

        # ── 尾部 ──
        buf += _sep()
        buf += ESC_ALIGN_CENTER
        buf += "谢谢惠顾 欢迎再次光临".encode("gbk", errors="replace") + LF
        buf += ESC_ALIGN_LEFT

        buf += ESC_FEED + b'\x03' + GS_CUT_PARTIAL
        return bytes(buf)

    @staticmethod
    async def render_kitchen_ticket(
        order_items: list[dict],
        table_no: str,
        dept_name: str,
        order_no: str = "",
        seq: int = 0,
    ) -> bytes:
        """渲染厨打小票。

        内容: 桌号(大字) → 菜品列表 → 做法 → 备注 → 下单时间

        Args:
            order_items: 菜品列表 [{item_name, quantity, notes, spec}]
            table_no: 桌号
            dept_name: 档口名称（如 "热菜档"）
            order_no: 订单号
            seq: 序号

        Returns:
            ESC/POS 字节流
        """
        buf = bytearray()
        buf += ESC_INIT

        # ── 档口名（居中大字）──
        buf += ESC_ALIGN_CENTER + GS_SIZE_DOUBLE_BOTH + ESC_BOLD_ON
        buf += f"[{dept_name}]".encode("gbk", errors="replace") + LF
        buf += GS_SIZE_NORMAL + ESC_BOLD_OFF

        # ── 桌号（大字加粗）──
        buf += GS_SIZE_DOUBLE_BOTH + ESC_BOLD_ON
        buf += f"桌号: {table_no}".encode("gbk", errors="replace") + LF
        buf += GS_SIZE_NORMAL + ESC_BOLD_OFF

        # ── 单号 + 序号 ──
        buf += ESC_ALIGN_LEFT
        short_no = order_no[-6:] if order_no else ""
        info = f"单号: {short_no}"
        if seq > 0:
            info += f"  #{seq}"
        buf += info.encode("gbk", errors="replace") + LF
        buf += (b'-' * LINE_WIDTH) + LF

        # ── 菜品列表 ──
        for item in order_items:
            name = item.get("item_name", "")
            qty = item.get("quantity", 1)

            buf += ESC_BOLD_ON + GS_SIZE_DOUBLE_HEIGHT
            buf += f"  {name}  x{qty}".encode("gbk", errors="replace") + LF
            buf += GS_SIZE_NORMAL + ESC_BOLD_OFF

            # 规格
            spec = item.get("spec", "")
            if spec:
                buf += f"    规格: {spec}".encode("gbk", errors="replace") + LF

            # 做法/备注
            notes = item.get("notes", "")
            if notes:
                buf += ESC_BOLD_ON
                buf += f"    [{notes}]".encode("gbk", errors="replace") + LF
                buf += ESC_BOLD_OFF

        # ── 下单时间 ──
        buf += (b'-' * LINE_WIDTH) + LF
        buf += f"下单: {_now_str()}".encode("gbk", errors="replace") + LF

        buf += LF + ESC_FEED + b'\x02' + GS_CUT_FULL
        return bytes(buf)

    @staticmethod
    async def render_checkout_bill(
        order: dict,
        store: dict,
    ) -> bytes:
        """渲染结账单（客用）。

        内容: 店名 → 菜品 → 金额 → 优惠 → 合计 → 发票二维码

        Args:
            order: 订单数据
            store: 门店信息 {name, invoice_qr_url}

        Returns:
            ESC/POS 字节流
        """
        store_name = store.get("name", "屯象OS")
        buf = bytearray()
        buf += ESC_INIT

        # ── 标题 ──
        buf += ESC_ALIGN_CENTER + GS_SIZE_DOUBLE_BOTH + ESC_BOLD_ON
        buf += "结 账 单".encode("gbk", errors="replace") + LF
        buf += GS_SIZE_NORMAL + ESC_BOLD_OFF
        buf += store_name.encode("gbk", errors="replace") + LF
        buf += ESC_ALIGN_LEFT
        buf += (b'=' * LINE_WIDTH) + LF

        # ── 订单信息 ──
        buf += f"单号: {order.get('order_no', '')}".encode("gbk", errors="replace") + LF
        table = order.get("table_number", "-")
        if table and table != "-":
            buf += f"桌号: {table}".encode("gbk", errors="replace") + LF
        guests = order.get("guest_count", 0)
        if guests > 0:
            buf += f"人数: {guests}".encode("gbk", errors="replace") + LF
        buf += f"时间: {str(order.get('order_time', ''))[:19]}".encode("gbk", errors="replace") + LF
        buf += _sep()

        # ── 菜品明细 ──
        buf += ESC_BOLD_ON
        buf += _pad_three_columns("品名", "数量", "金额", LINE_WIDTH).encode("gbk", errors="replace") + LF
        buf += ESC_BOLD_OFF + _sep()

        for item in order.get("items", []):
            name = item.get("item_name", "")
            if _gbk_len(name) > 20:
                name = name[:10]
            qty = str(item.get("quantity", 0))
            amount = _fen_to_yuan(item.get("subtotal_fen", 0))
            buf += _pad_three_columns(name, qty, amount, LINE_WIDTH).encode("gbk", errors="replace") + LF

        buf += (b'=' * LINE_WIDTH) + LF

        # ── 金额汇总 ──
        total = _fen_to_yuan(order.get("total_amount_fen", 0))
        buf += _pad_two_columns("菜品合计:", total).encode("gbk", errors="replace") + LF

        discount_fen = order.get("discount_amount_fen", 0)
        if discount_fen > 0:
            buf += _pad_two_columns("优惠:", f"-{_fen_to_yuan(discount_fen)}").encode("gbk", errors="replace") + LF

        service_fen = order.get("service_charge_fen", 0)
        if service_fen > 0:
            buf += _pad_two_columns("服务费:", _fen_to_yuan(service_fen)).encode("gbk", errors="replace") + LF

        buf += _sep()
        final = _fen_to_yuan(order.get("final_amount_fen", 0))
        buf += GS_SIZE_DOUBLE_BOTH + ESC_BOLD_ON
        buf += _pad_two_columns("合计:", final).encode("gbk", errors="replace") + LF
        buf += GS_SIZE_NORMAL + ESC_BOLD_OFF

        # ── 发票二维码 ──
        invoice_url = store.get("invoice_qr_url", "")
        if invoice_url:
            buf += _sep()
            buf += ESC_ALIGN_CENTER
            buf += "扫码开具电子发票".encode("gbk", errors="replace") + LF
            buf += _build_qrcode(invoice_url)
            buf += ESC_ALIGN_LEFT

        buf += _sep()
        buf += ESC_ALIGN_CENTER
        buf += "谢谢惠顾 欢迎再次光临".encode("gbk", errors="replace") + LF
        buf += ESC_ALIGN_LEFT

        buf += ESC_FEED + b'\x03' + GS_CUT_PARTIAL
        return bytes(buf)

    @staticmethod
    async def render_shift_report(shift_data: dict) -> bytes:
        """渲染交班报表。

        内容: 班次 → 订单数 → 各渠道金额 → 现金 → 差异

        Args:
            shift_data: 交班数据 {settlement_date, settlement_type, operator, total_orders,
                         total_revenue_fen, cash_fen, wechat_fen, alipay_fen, ...}

        Returns:
            ESC/POS 字节流
        """
        buf = bytearray()
        buf += ESC_INIT

        # ── 标题 ──
        buf += ESC_ALIGN_CENTER + GS_SIZE_DOUBLE_BOTH + ESC_BOLD_ON
        buf += "交 接 班 报 表".encode("gbk", errors="replace") + LF
        buf += GS_SIZE_NORMAL + ESC_BOLD_OFF
        buf += ESC_ALIGN_LEFT
        buf += (b'=' * LINE_WIDTH) + LF

        # ── 基本信息 ──
        buf += f"日期: {shift_data.get('settlement_date', '')}".encode("gbk", errors="replace") + LF
        buf += f"班次: {shift_data.get('settlement_type', 'shift')}".encode("gbk", errors="replace") + LF
        buf += f"操作员: {shift_data.get('operator', '')}".encode("gbk", errors="replace") + LF
        buf += _sep()

        # ── 营收汇总 ──
        buf += ESC_BOLD_ON
        buf += "营收汇总".encode("gbk", errors="replace") + LF
        buf += ESC_BOLD_OFF

        total_rev = _fen_to_yuan(shift_data.get("total_revenue_fen", 0))
        buf += _pad_two_columns("  总营收:", total_rev).encode("gbk", errors="replace") + LF

        total_disc = _fen_to_yuan(shift_data.get("total_discount_fen", 0))
        buf += _pad_two_columns("  总折扣:", f"-{total_disc}").encode("gbk", errors="replace") + LF

        total_refund = _fen_to_yuan(shift_data.get("total_refund_fen", 0))
        buf += _pad_two_columns("  总退款:", f"-{total_refund}").encode("gbk", errors="replace") + LF

        net_rev = _fen_to_yuan(shift_data.get("net_revenue_fen", 0))
        buf += ESC_BOLD_ON
        buf += _pad_two_columns("  净营收:", net_rev).encode("gbk", errors="replace") + LF
        buf += ESC_BOLD_OFF
        buf += _sep()

        # ── 支付方式明细 ──
        buf += ESC_BOLD_ON
        buf += "支付方式明细".encode("gbk", errors="replace") + LF
        buf += ESC_BOLD_OFF

        channels = [
            ("现金", "cash_fen"),
            ("微信", "wechat_fen"),
            ("支付宝", "alipay_fen"),
            ("银联", "unionpay_fen"),
            ("挂账", "credit_fen"),
            ("会员余额", "member_balance_fen"),
        ]
        for label, key in channels:
            val = shift_data.get(key, 0)
            if val > 0:
                buf += _pad_two_columns(f"  {label}:", _fen_to_yuan(val)).encode("gbk", errors="replace") + LF
        buf += _sep()

        # ── 订单统计 ──
        buf += ESC_BOLD_ON
        buf += "订单统计".encode("gbk", errors="replace") + LF
        buf += ESC_BOLD_OFF
        buf += f"  总单数: {shift_data.get('total_orders', 0)}".encode("gbk", errors="replace") + LF
        buf += f"  总客数: {shift_data.get('total_guests', 0)}".encode("gbk", errors="replace") + LF
        avg_fen = shift_data.get("avg_per_guest_fen", 0)
        buf += f"  客单价: {_fen_to_yuan(avg_fen)}".encode("gbk", errors="replace") + LF
        buf += _sep()

        # ── 现金盘点 ──
        buf += ESC_BOLD_ON
        buf += "现金盘点".encode("gbk", errors="replace") + LF
        buf += ESC_BOLD_OFF
        cash_expected = _fen_to_yuan(shift_data.get("cash_expected_fen", 0))
        buf += f"  应有现金: {cash_expected}".encode("gbk", errors="replace") + LF

        cash_actual = shift_data.get("cash_actual_fen")
        if cash_actual is not None:
            buf += f"  实际现金: {_fen_to_yuan(cash_actual)}".encode("gbk", errors="replace") + LF
            diff = shift_data.get("cash_diff_fen", 0)
            buf += f"  差异:     {_fen_to_yuan(diff)}".encode("gbk", errors="replace") + LF

        buf += (b'=' * LINE_WIDTH) + LF
        buf += ESC_ALIGN_CENTER
        buf += "交班确认签字: __________".encode("gbk", errors="replace") + LF
        buf += "接班确认签字: __________".encode("gbk", errors="replace") + LF
        buf += ESC_ALIGN_LEFT

        buf += ESC_FEED + b'\x03' + GS_CUT_PARTIAL
        return bytes(buf)

    @staticmethod
    async def render_label(
        dish_name: str,
        table_no: str,
        seq: int = 1,
        notes: str = "",
    ) -> bytes:
        """渲染菜品标签（一菜一签）。

        内容: 菜名 → 桌号 → 序号 → 时间

        Args:
            dish_name: 菜品名称
            table_no: 桌号
            seq: 出品序号
            notes: 备注

        Returns:
            ESC/POS 字节流
        """
        buf = bytearray()
        buf += ESC_INIT

        # ── 菜品名（居中大字加粗）──
        buf += ESC_ALIGN_CENTER + GS_SIZE_DOUBLE_BOTH + ESC_BOLD_ON
        buf += dish_name.encode("gbk", errors="replace") + LF
        buf += GS_SIZE_NORMAL + ESC_BOLD_OFF

        # ── 桌号 + 序号 ──
        buf += ESC_BOLD_ON
        buf += f"{table_no} #{seq}".encode("gbk", errors="replace") + LF
        buf += ESC_BOLD_OFF

        # ── 备注 ──
        if notes:
            buf += _sep()
            buf += ESC_BOLD_ON
            buf += f"[{notes}]".encode("gbk", errors="replace") + LF
            buf += ESC_BOLD_OFF

        # ── 时间 ──
        buf += _sep()
        buf += _now_str().encode("gbk", errors="replace") + LF
        buf += ESC_ALIGN_LEFT

        buf += LF + GS_CUT_FULL
        return bytes(buf)

    @staticmethod
    async def render_daily_report(daily_data: dict) -> bytes:
        """渲染日结报表。

        内容: 日期 → 营业额 → 订单数 → 各渠道 → 菜品排行

        Args:
            daily_data: 日结数据 {date, total_revenue_fen, total_orders, channel_summary,
                         top_dishes, total_guests, avg_per_order_fen}

        Returns:
            ESC/POS 字节流
        """
        buf = bytearray()
        buf += ESC_INIT

        # ── 标题 ──
        buf += ESC_ALIGN_CENTER + GS_SIZE_DOUBLE_BOTH + ESC_BOLD_ON
        buf += "日 结 报 表".encode("gbk", errors="replace") + LF
        buf += GS_SIZE_NORMAL + ESC_BOLD_OFF
        buf += ESC_ALIGN_LEFT
        buf += (b'=' * LINE_WIDTH) + LF

        # ── 日期 ──
        buf += f"日期: {daily_data.get('date', '')}".encode("gbk", errors="replace") + LF
        buf += _sep()

        # ── 营业概况 ──
        buf += ESC_BOLD_ON
        buf += "营业概况".encode("gbk", errors="replace") + LF
        buf += ESC_BOLD_OFF

        revenue = _fen_to_yuan(daily_data.get("total_revenue_fen", 0))
        buf += _pad_two_columns("  营业额:", revenue).encode("gbk", errors="replace") + LF
        buf += f"  订单数: {daily_data.get('total_orders', 0)}".encode("gbk", errors="replace") + LF
        buf += f"  客流量: {daily_data.get('total_guests', 0)}".encode("gbk", errors="replace") + LF

        avg = _fen_to_yuan(daily_data.get("avg_per_order_fen", 0))
        buf += _pad_two_columns("  桌均:", avg).encode("gbk", errors="replace") + LF
        buf += _sep()

        # ── 渠道汇总 ──
        channels = daily_data.get("channel_summary", {})
        if channels:
            buf += ESC_BOLD_ON
            buf += "渠道汇总".encode("gbk", errors="replace") + LF
            buf += ESC_BOLD_OFF
            for ch_name, ch_data in channels.items():
                ch_amount = _fen_to_yuan(ch_data.get("amount_fen", 0))
                ch_count = ch_data.get("count", 0)
                buf += _pad_two_columns(f"  {ch_name}({ch_count}单):", ch_amount).encode("gbk", errors="replace") + LF
            buf += _sep()

        # ── 菜品排行 TOP10 ──
        top_dishes = daily_data.get("top_dishes", [])
        if top_dishes:
            buf += ESC_BOLD_ON
            buf += "菜品排行 TOP10".encode("gbk", errors="replace") + LF
            buf += ESC_BOLD_OFF
            buf += _pad_three_columns("排名 菜名", "销量", "金额", LINE_WIDTH).encode("gbk", errors="replace") + LF
            buf += _sep()
            for i, dish in enumerate(top_dishes[:10], 1):
                name = f"{i:>2}. {dish.get('name', '')}"
                qty = str(dish.get("sold", 0))
                amount = _fen_to_yuan(dish.get("amount_fen", 0))
                buf += _pad_three_columns(name, qty, amount, LINE_WIDTH).encode("gbk", errors="replace") + LF

        buf += (b'=' * LINE_WIDTH) + LF
        buf += ESC_ALIGN_CENTER
        buf += f"打印时间: {_now_str()}".encode("gbk", errors="replace") + LF
        buf += ESC_ALIGN_LEFT

        buf += ESC_FEED + b'\x03' + GS_CUT_PARTIAL
        return bytes(buf)


# ─── 内部工具 ───


def _build_qrcode(data: str, size: int = 6) -> bytes:
    """生成二维码 ESC/POS 指令。"""
    if not data:
        return b""

    encoded = data.encode("utf-8")
    data_len = len(encoded) + 3
    pL = data_len & 0xFF
    pH = (data_len >> 8) & 0xFF

    buf = bytearray()
    # QR Code Model 2
    buf += b'\x1d\x28\x6b\x04\x00\x31\x41\x32\x00'
    # 大小
    size = max(1, min(16, size))
    buf += b'\x1d\x28\x6b\x03\x00\x31\x43' + bytes([size])
    # 纠错等级 M
    buf += b'\x1d\x28\x6b\x03\x00\x31\x45\x31'
    # 存储数据
    buf += b'\x1d\x28\x6b' + bytes([pL, pH]) + b'\x31\x50\x30' + encoded
    # 打印
    buf += b'\x1d\x28\x6b\x03\x00\x31\x51\x30'
    buf += LF
    return bytes(buf)
