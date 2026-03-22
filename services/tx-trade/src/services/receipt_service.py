"""小票打印服务 — ESC/POS 命令生成 + 厨房分单"""
import hashlib
import uuid
from datetime import datetime, timezone
from typing import Optional

import structlog

logger = structlog.get_logger()


# ─── ESC/POS 命令常量 ───
ESC = b'\x1b'
GS = b'\x1d'
LF = b'\x0a'
CUT = GS + b'\x56\x00'       # 切纸
ALIGN_CENTER = ESC + b'\x61\x01'
ALIGN_LEFT = ESC + b'\x61\x00'
ALIGN_RIGHT = ESC + b'\x61\x02'
BOLD_ON = ESC + b'\x45\x01'
BOLD_OFF = ESC + b'\x45\x00'
DOUBLE_HEIGHT = GS + b'\x21\x11'
NORMAL_SIZE = GS + b'\x21\x00'
OPEN_DRAWER = ESC + b'\x70\x00\x19\xfa'


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
        sep = b'-' * cols + LF
        buf = bytearray()

        # 门店名（居中加粗大字）
        buf += ALIGN_CENTER + DOUBLE_HEIGHT + BOLD_ON
        buf += (store_name or "TunxiangOS").encode('gbk', errors='replace') + LF
        buf += NORMAL_SIZE + BOLD_OFF

        # 订单信息
        buf += ALIGN_LEFT + sep
        buf += f"单号: {order.get('order_no', '')}\n".encode('gbk', errors='replace')
        buf += f"桌号: {order.get('table_number', '-')}\n".encode('gbk', errors='replace')
        buf += f"时间: {order.get('order_time', '')[:19]}\n".encode('gbk', errors='replace')
        buf += sep

        # 菜品明细
        buf += BOLD_ON
        buf += _pad_line("品名", "数量", "金额", cols).encode('gbk', errors='replace')
        buf += BOLD_OFF + sep

        for item in order.get("items", []):
            name = item.get("item_name", "")[:12]
            qty = str(item.get("quantity", 0))
            amount = _fen_to_yuan(item.get("subtotal_fen", 0))
            buf += _pad_line(name, qty, amount, cols).encode('gbk', errors='replace')

        buf += sep

        # 合计
        total = _fen_to_yuan(order.get("total_amount_fen", 0))
        discount = _fen_to_yuan(order.get("discount_amount_fen", 0))
        final = _fen_to_yuan(order.get("final_amount_fen", 0))

        buf += f"合计: {total}\n".encode('gbk', errors='replace')
        if order.get("discount_amount_fen", 0) > 0:
            buf += f"优惠: -{discount}\n".encode('gbk', errors='replace')
        buf += BOLD_ON + DOUBLE_HEIGHT
        buf += f"应付: {final}\n".encode('gbk', errors='replace')
        buf += NORMAL_SIZE + BOLD_OFF

        # 尾部
        buf += sep
        buf += ALIGN_CENTER
        buf += "谢谢惠顾 欢迎再次光临\n".encode('gbk', errors='replace')
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
        buf += f"[{station}]\n".encode('gbk', errors='replace')
        buf += NORMAL_SIZE + BOLD_OFF

        buf += ALIGN_LEFT
        buf += f"桌号: {order.get('table_number', '-')}  单号: {order.get('order_no', '')[-6:]}\n".encode('gbk', errors='replace')
        buf += (b'-' * cols) + LF

        for item in order.get("items", []):
            buf += BOLD_ON + DOUBLE_HEIGHT
            buf += f"  {item['item_name']}  x{item['quantity']}\n".encode('gbk', errors='replace')
            buf += NORMAL_SIZE + BOLD_OFF
            if item.get("notes"):
                buf += f"    [{item['notes']}]\n".encode('gbk', errors='replace')

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


def _fen_to_yuan(fen: int) -> str:
    """分转元，保留2位小数"""
    return f"¥{fen / 100:.2f}"


def _pad_line(left: str, mid: str, right: str, cols: int) -> str:
    """三栏对齐"""
    mid_pos = cols // 2
    right_pos = cols - len(right.encode('gbk', errors='replace'))
    line = left.ljust(mid_pos - len(mid)) + mid + right.rjust(cols - mid_pos)
    return line[:cols] + "\n"
