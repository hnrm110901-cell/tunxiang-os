"""ESC/POS 网口打印机驱动 — 北洋 BTP-98NP / BTP-2002CP

支持所有兼容 ESC/POS 标准指令集的热敏打印机。
连接方式: TCP/IP Socket (端口9100)
纸宽: 80mm (48 ASCII字符 / 24 中文字符)
编码: GBK (北洋默认)
"""
import asyncio
from enum import Enum
from typing import Optional

import structlog

logger = structlog.get_logger()

# ─── ESC/POS 指令常量 ───

ESC_INIT = b'\x1b\x40'

ESC_ALIGN_LEFT = b'\x1b\x61\x00'
ESC_ALIGN_CENTER = b'\x1b\x61\x01'
ESC_ALIGN_RIGHT = b'\x1b\x61\x02'

ESC_BOLD_ON = b'\x1b\x45\x01'
ESC_BOLD_OFF = b'\x1b\x45\x00'

GS_SIZE_NORMAL = b'\x1d\x21\x00'
GS_SIZE_DOUBLE_WIDTH = b'\x1d\x21\x10'
GS_SIZE_DOUBLE_HEIGHT = b'\x1d\x21\x01'
GS_SIZE_DOUBLE_BOTH = b'\x1d\x21\x11'

GS_CUT_PARTIAL = b'\x1d\x56\x01'
GS_CUT_FULL = b'\x1d\x56\x00'

ESC_OPEN_DRAWER = b'\x1b\x70\x00\x19\xfa'
ESC_FEED = b'\x1b\x64'

ESC_CHINESE_ON = b'\x1c\x26'

LF = b'\x0a'

# 蜂鸣: ESC B n t (n=次数, t=持续时间)
ESC_BEEP = b'\x1b\x42'

# 80mm纸宽 = 48个ASCII字符
LINE_WIDTH = 48


class PrinterStatus(Enum):
    ONLINE = "online"
    OFFLINE = "offline"
    PAPER_OUT = "paper_out"
    COVER_OPEN = "cover_open"
    ERROR = "error"


class TextAlign(Enum):
    LEFT = "left"
    CENTER = "center"
    RIGHT = "right"


class TextSize(Enum):
    NORMAL = 1
    DOUBLE_WIDTH = 2
    DOUBLE_HEIGHT = 3
    DOUBLE_BOTH = 4


# 对齐映射
_ALIGN_MAP = {
    TextAlign.LEFT: ESC_ALIGN_LEFT,
    TextAlign.CENTER: ESC_ALIGN_CENTER,
    TextAlign.RIGHT: ESC_ALIGN_RIGHT,
    "left": ESC_ALIGN_LEFT,
    "center": ESC_ALIGN_CENTER,
    "right": ESC_ALIGN_RIGHT,
}

# 字号映射
_SIZE_MAP = {
    TextSize.NORMAL: GS_SIZE_NORMAL,
    TextSize.DOUBLE_WIDTH: GS_SIZE_DOUBLE_WIDTH,
    TextSize.DOUBLE_HEIGHT: GS_SIZE_DOUBLE_HEIGHT,
    TextSize.DOUBLE_BOTH: GS_SIZE_DOUBLE_BOTH,
    1: GS_SIZE_NORMAL,
    2: GS_SIZE_DOUBLE_WIDTH,
    3: GS_SIZE_DOUBLE_HEIGHT,
    4: GS_SIZE_DOUBLE_BOTH,
}


class ESCPOSPrinter:
    """ESC/POS 网口打印机驱动

    支持北洋 BTP-98NP / BTP-2002CP 及所有兼容 ESC/POS 的热敏打印机。
    连接方式: TCP/IP Socket (端口9100)

    用法::

        printer = ESCPOSPrinter("192.168.1.100")
        await printer.connect()
        await printer.reset()
        await printer.print_text("你好世界", align="center", bold=True, size=4)
        await printer.cut()
        await printer.disconnect()
    """

    def __init__(self, ip: str, port: int = 9100, timeout: int = 5):
        self.ip = ip
        self.port = port
        self.timeout = timeout
        self._reader: Optional[asyncio.StreamReader] = None
        self._writer: Optional[asyncio.StreamWriter] = None
        self._lock = asyncio.Lock()

    # ─── 连接管理 ───

    async def connect(self) -> None:
        """建立 TCP 连接到打印机。"""
        if self._writer is not None:
            return
        try:
            self._reader, self._writer = await asyncio.wait_for(
                asyncio.open_connection(self.ip, self.port),
                timeout=self.timeout,
            )
            logger.info("printer.connected", ip=self.ip, port=self.port)
        except asyncio.TimeoutError as exc:
            logger.error("printer.connect_timeout", ip=self.ip, port=self.port)
            raise ConnectionError(f"打印机连接超时: {self.ip}:{self.port}") from exc
        except OSError as exc:
            logger.error("printer.connect_failed", ip=self.ip, error=str(exc))
            raise ConnectionError(f"打印机连接失败: {self.ip}:{self.port} - {exc}") from exc

    async def disconnect(self) -> None:
        """断开 TCP 连接。"""
        if self._writer is not None:
            try:
                self._writer.close()
                await self._writer.wait_closed()
            except OSError:
                pass
            finally:
                self._writer = None
                self._reader = None
                logger.info("printer.disconnected", ip=self.ip)

    async def _send(self, data: bytes) -> None:
        """发送原始字节到打印机，线程安全。"""
        if self._writer is None:
            raise ConnectionError(f"打印机未连接: {self.ip}:{self.port}")
        async with self._lock:
            self._writer.write(data)
            await asyncio.wait_for(self._writer.drain(), timeout=30)

    async def send_raw(self, data: bytes) -> None:
        """发送预构建的 ESC/POS 字节流（模板渲染结果）。"""
        await self._send(data)
        logger.info("printer.raw_sent", ip=self.ip, size=len(data))

    @property
    def is_connected(self) -> bool:
        return self._writer is not None

    # ─── 基础指令 ───

    async def reset(self) -> None:
        """ESC @ — 初始化打印机（恢复默认设置）。"""
        await self._send(ESC_INIT)

    # ─── 文字打印 ───

    async def print_text(
        self,
        text: str,
        align: str = "left",
        bold: bool = False,
        size: int = 1,
    ) -> None:
        """打印文本行。

        Args:
            text: 待打印文本（支持中文，自动 GBK 编码）
            align: 对齐方式 left / center / right
            bold: 是否加粗
            size: 字号 1=正常, 2=倍宽, 3=倍高, 4=倍宽倍高
        """
        buf = bytearray()
        buf += _ALIGN_MAP.get(align, ESC_ALIGN_LEFT)
        buf += _SIZE_MAP.get(size, GS_SIZE_NORMAL)
        if bold:
            buf += ESC_BOLD_ON
        buf += text.encode("gbk", errors="replace") + LF
        if bold:
            buf += ESC_BOLD_OFF
        buf += GS_SIZE_NORMAL + ESC_ALIGN_LEFT
        await self._send(bytes(buf))

    async def print_chinese(self, text: str) -> None:
        """GBK 编码中文打印（启用中文模式）。"""
        buf = ESC_CHINESE_ON + text.encode("gbk", errors="replace") + LF
        await self._send(buf)

    # ─── 排版 ───

    async def print_line(self, char: str = "-") -> None:
        """打印分割线（80mm = 48 字符宽）。"""
        line = (char * LINE_WIDTH)[:LINE_WIDTH]
        await self._send(line.encode("ascii") + LF)

    async def print_two_columns(self, left: str, right: str) -> None:
        """打印左右两列对齐文本。"""
        line = _pad_two_columns(left, right, LINE_WIDTH)
        await self._send(line.encode("gbk", errors="replace") + LF)

    async def print_three_columns(
        self, left: str, center: str, right: str
    ) -> None:
        """打印三列文本（菜品 | 数量 | 金额）。"""
        line = _pad_three_columns(left, center, right, LINE_WIDTH)
        await self._send(line.encode("gbk", errors="replace") + LF)

    async def feed(self, lines: int = 1) -> None:
        """走纸 n 行。"""
        await self._send(ESC_FEED + bytes([lines]))

    async def cut(self, partial: bool = True) -> None:
        """切纸。

        Args:
            partial: True=半切, False=全切
        """
        await self.feed(3)
        await self._send(GS_CUT_PARTIAL if partial else GS_CUT_FULL)

    # ─── 特殊功能 ───

    async def print_qrcode(self, data: str, size: int = 6) -> None:
        """打印二维码 (GS ( k)。

        Args:
            data: 二维码内容（URL 等）
            size: 模块大小 1-16
        """
        if not data:
            return
        buf = bytearray()
        buf += ESC_ALIGN_CENTER

        encoded = data.encode("utf-8")
        data_len = len(encoded) + 3
        pL = data_len & 0xFF
        pH = (data_len >> 8) & 0xFF

        # QR Code Model 2
        buf += b'\x1d\x28\x6b\x04\x00\x31\x41\x32\x00'
        # 设置大小
        size = max(1, min(16, size))
        buf += b'\x1d\x28\x6b\x03\x00\x31\x43' + bytes([size])
        # 纠错等级 M
        buf += b'\x1d\x28\x6b\x03\x00\x31\x45\x31'
        # 存储数据
        buf += b'\x1d\x28\x6b' + bytes([pL, pH]) + b'\x31\x50\x30' + encoded
        # 打印
        buf += b'\x1d\x28\x6b\x03\x00\x31\x51\x30'

        buf += ESC_ALIGN_LEFT + LF
        await self._send(bytes(buf))

    async def print_barcode(
        self, data: str, barcode_type: str = "CODE128"
    ) -> None:
        """打印条形码。

        Args:
            data: 条形码数据
            barcode_type: 条形码类型 CODE128 / EAN13 / CODE39
        """
        type_map = {"CODE39": 4, "EAN13": 2, "CODE128": 73}
        code = type_map.get(barcode_type, 73)

        buf = bytearray()
        buf += ESC_ALIGN_CENTER
        # 设置条形码高度 80 点
        buf += b'\x1d\x68\x50'
        # 设置条形码宽度 2
        buf += b'\x1d\x77\x02'
        # HRI 字符在条形码下方
        buf += b'\x1d\x48\x02'

        encoded = data.encode("ascii", errors="replace")
        if code == 73:
            # CODE128 使用 GS k m n d1...dn
            buf += b'\x1d\x6b' + bytes([code, len(encoded)]) + encoded
        else:
            # 其他类型使用 GS k m d1...dn NUL
            buf += b'\x1d\x6b' + bytes([code]) + encoded + b'\x00'

        buf += ESC_ALIGN_LEFT + LF
        await self._send(bytes(buf))

    async def open_cash_drawer(self) -> None:
        """开钱箱 (ESC p 0)。"""
        await self._send(ESC_OPEN_DRAWER)
        logger.info("printer.cash_drawer_opened", ip=self.ip)

    async def beep(self, times: int = 1) -> None:
        """蜂鸣提示。

        Args:
            times: 蜂鸣次数 1-9
        """
        times = max(1, min(9, times))
        # ESC B n t: n=次数, t=持续时间(100ms单位)
        await self._send(ESC_BEEP + bytes([times, 3]))

    # ─── 状态查询 ───

    async def get_status(self) -> PrinterStatus:
        """查询打印机状态（在线/缺纸/开盖）。

        Returns:
            PrinterStatus 枚举值
        """
        if self._writer is None:
            return PrinterStatus.OFFLINE

        try:
            # DLE EOT 1 — 查询打印机状态
            async with self._lock:
                self._writer.write(b'\x10\x04\x01')
                await self._writer.drain()
                data = await asyncio.wait_for(
                    self._reader.read(1),  # type: ignore[union-attr]
                    timeout=self.timeout,
                )
            if not data:
                return PrinterStatus.OFFLINE

            status_byte = data[0]
            # bit 3: 开盖, bit 5: 走纸中, bit 6: 错误
            if status_byte & 0x04:
                return PrinterStatus.COVER_OPEN
            if status_byte & 0x20:
                return PrinterStatus.ERROR

            # DLE EOT 4 — 查询纸张状态
            async with self._lock:
                self._writer.write(b'\x10\x04\x04')
                await self._writer.drain()
                data = await asyncio.wait_for(
                    self._reader.read(1),
                    timeout=self.timeout,
                )
            if data and (data[0] & 0x60):
                return PrinterStatus.PAPER_OUT

            return PrinterStatus.ONLINE

        except (asyncio.TimeoutError, OSError) as exc:
            logger.warning("printer.status_query_failed", ip=self.ip, error=str(exc))
            return PrinterStatus.OFFLINE

    async def is_online(self) -> bool:
        """检查打印机是否在线。"""
        status = await self.get_status()
        return status == PrinterStatus.ONLINE

    # ─── 上下文管理器 ───

    async def __aenter__(self) -> "ESCPOSPrinter":
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self.disconnect()


# ─── 工具函数 ───


def _gbk_len(text: str) -> int:
    """计算文本的 GBK 编码字节宽度（中文2字节，ASCII 1字节）。"""
    return len(text.encode("gbk", errors="replace"))


def _pad_two_columns(left: str, right: str, width: int = LINE_WIDTH) -> str:
    """左右两列对齐。"""
    left_width = _gbk_len(left)
    right_width = _gbk_len(right)
    spaces = max(1, width - left_width - right_width)
    return left + " " * spaces + right


def _pad_three_columns(
    left: str, center: str, right: str, width: int = LINE_WIDTH
) -> str:
    """三列对齐（菜品 | 数量 | 金额）。"""
    col1_width = width // 2
    col3_width = 10
    col2_width = width - col1_width - col3_width

    left_padded = left
    left_len = _gbk_len(left)
    if left_len < col1_width:
        left_padded = left + " " * (col1_width - left_len)
    else:
        left_padded = left[:col1_width]

    center_len = _gbk_len(center)
    center_padded = center
    if center_len < col2_width:
        center_padded = center + " " * (col2_width - center_len)

    right_len = _gbk_len(right)
    right_padded = " " * max(0, col3_width - right_len) + right

    return left_padded + center_padded + right_padded


def build_escpos_commands() -> dict[str, bytes]:
    """返回所有 ESC/POS 指令常量字典，供外部引用。"""
    return {
        "init": ESC_INIT,
        "align_left": ESC_ALIGN_LEFT,
        "align_center": ESC_ALIGN_CENTER,
        "align_right": ESC_ALIGN_RIGHT,
        "bold_on": ESC_BOLD_ON,
        "bold_off": ESC_BOLD_OFF,
        "size_normal": GS_SIZE_NORMAL,
        "size_double_width": GS_SIZE_DOUBLE_WIDTH,
        "size_double_height": GS_SIZE_DOUBLE_HEIGHT,
        "size_double_both": GS_SIZE_DOUBLE_BOTH,
        "cut_partial": GS_CUT_PARTIAL,
        "cut_full": GS_CUT_FULL,
        "open_drawer": ESC_OPEN_DRAWER,
        "chinese_on": ESC_CHINESE_ON,
    }
