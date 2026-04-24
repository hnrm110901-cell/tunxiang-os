"""硬件通信协议支持层

支持的协议：
- ESC/POS: 热敏打印机（TCP/USB/串口）— 已在 printer_driver.py 实现，此处做桥接
- SerialPort: 电子秤（RS232/USB虚拟串口）
- HID: 扫码枪（键盘模拟/HID协议）
- SUNMI/JS Bridge: 商米设备内置打印/扫码
- HTTP API: 智能设备（排队机/自助机）
- ZPL/TSPL: 标签打印机
- ESC p: 钱箱触发（通过打印机RJ11接口）
"""

import asyncio
import re
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Optional

import structlog

logger = structlog.get_logger()


# ─── 协议状态枚举 ───


class ConnectionState(str, Enum):
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    ERROR = "error"


# ─── 协议处理基类 ───


class ProtocolHandler(ABC):
    """协议处理基类。

    所有硬件通信协议的统一抽象层。
    子类必须实现 connect / disconnect / health_check 方法。
    """

    def __init__(self, tenant_id: str, device_key: str):
        self.tenant_id = tenant_id
        self.device_key = device_key
        self.state = ConnectionState.DISCONNECTED
        self.last_error: Optional[str] = None
        self.connected_at: Optional[datetime] = None
        self._lock = asyncio.Lock()

    @abstractmethod
    async def connect(self, **kwargs: Any) -> None:
        """建立连接。"""

    @abstractmethod
    async def disconnect(self) -> None:
        """断开连接。"""

    @abstractmethod
    async def health_check(self) -> bool:
        """健康检查。"""

    def get_status(self) -> dict:
        """获取连接状态。"""
        return {
            "device_key": self.device_key,
            "state": self.state.value,
            "last_error": self.last_error,
            "connected_at": self.connected_at.isoformat() if self.connected_at else None,
            "tenant_id": self.tenant_id,
        }


# ─── ESC/POS 打印协议桥接 ───


class ESCPOSProtocol(ProtocolHandler):
    """ESC/POS 打印协议 -- 桥接到 printer_driver.py 已有实现。

    支持品牌: 北洋 / 佳博 / 爱普生 / 芯烨 / 容大
    连接方式: TCP/IP Socket (端口 9100)
    编码: GBK
    """

    def __init__(self, tenant_id: str, device_key: str):
        super().__init__(tenant_id, device_key)
        self._ip: Optional[str] = None
        self._port: int = 9100
        self._reader: Optional[asyncio.StreamReader] = None
        self._writer: Optional[asyncio.StreamWriter] = None

    async def connect(self, ip: str = "", port: int = 9100, timeout: int = 5, **kwargs: Any) -> None:
        """建立 TCP 连接到打印机。

        Args:
            ip: 打印机 IP 地址
            port: 端口号，默认 9100
            timeout: 连接超时秒数
        """
        self._ip = ip
        self._port = port
        self.state = ConnectionState.CONNECTING

        try:
            self._reader, self._writer = await asyncio.wait_for(
                asyncio.open_connection(ip, port),
                timeout=timeout,
            )
            self.state = ConnectionState.CONNECTED
            self.connected_at = datetime.now(timezone.utc)
            self.last_error = None
            logger.info(
                "escpos.connected",
                ip=ip,
                port=port,
                device_key=self.device_key,
                tenant_id=self.tenant_id,
            )
        except asyncio.TimeoutError:
            self.state = ConnectionState.ERROR
            self.last_error = f"连接超时: {ip}:{port}"
            logger.error("escpos.connect_timeout", ip=ip, port=port, tenant_id=self.tenant_id)
            raise ConnectionError(self.last_error)
        except OSError as exc:
            self.state = ConnectionState.ERROR
            self.last_error = f"连接失败: {exc}"
            logger.error("escpos.connect_failed", ip=ip, error=str(exc), tenant_id=self.tenant_id)
            raise ConnectionError(self.last_error) from exc

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
                self.state = ConnectionState.DISCONNECTED
                logger.info("escpos.disconnected", ip=self._ip, tenant_id=self.tenant_id)

    async def send_raw(self, data: bytes) -> None:
        """发送原始 ESC/POS 字节流。

        Args:
            data: ESC/POS 指令字节流
        """
        if self._writer is None:
            raise ConnectionError(f"打印机未连接: {self._ip}:{self._port}")
        async with self._lock:
            self._writer.write(data)
            await asyncio.wait_for(self._writer.drain(), timeout=30)

    async def health_check(self) -> bool:
        """检查打印机是否在线（DLE EOT 1）。"""
        if self._writer is None:
            return False
        try:
            async with self._lock:
                self._writer.write(b"\x10\x04\x01")
                await self._writer.drain()
                data = await asyncio.wait_for(
                    self._reader.read(1),  # type: ignore[union-attr]
                    timeout=3,
                )
            return len(data) > 0
        except (asyncio.TimeoutError, OSError):
            return False


# ─── 电子秤串口协议 ───


class SerialScaleProtocol(ProtocolHandler):
    """电子秤串口协议。

    支持品牌: 顶尖(DIGI) / 大华(Dahua) / 凯士(CAS) / 梅特勒-托利多(MT)
    连接方式: RS232 串口 / USB虚拟串口
    数据格式: 重量(g) + 稳定标志 + 去皮标志

    典型串口参数: 9600bps, 8N1
    数据帧格式（以大华为例）: STX + 符号 + 重量(6位) + 单位 + 稳定标志 + ETX
    """

    # 各品牌数据帧解析正则
    FRAME_PATTERNS: dict[str, re.Pattern[str]] = {
        "DIGI_SERIAL": re.compile(r"(?P<sign>[+-])\s*(?P<weight>[\d.]+)\s*(?P<unit>[gk]g)\s*(?P<stable>[SM])"),
        "DAHUA_SERIAL": re.compile(r"(?P<sign>[+-])(?P<weight>[\d.]+)\s*(?P<unit>[gk]g)\s*(?P<stable>[SM])"),
        "CAS_SERIAL": re.compile(r"(?P<sign>[+-])\s*(?P<weight>[\d.]+)\s*(?P<unit>[gk]g)\s*(?P<stable>[SM])"),
        "MT_SICS": re.compile(r"S\s+(?P<stable>[SD])\s+(?P<weight>[\d.]+)\s+(?P<unit>[gk]g)"),
    }

    def __init__(self, tenant_id: str, device_key: str, protocol: str = "DAHUA_SERIAL"):
        super().__init__(tenant_id, device_key)
        self._port_path: Optional[str] = None
        self._baudrate: int = 9600
        self._protocol_type = protocol
        self._serial_connection: Any = None
        self._weight_callback: Optional[Callable] = None
        self._reading_task: Optional[asyncio.Task[None]] = None

    async def connect(
        self,
        port: str = "/dev/ttyUSB0",
        baudrate: int = 9600,
        **kwargs: Any,
    ) -> None:
        """连接电子秤串口。

        Args:
            port: 串口路径，如 /dev/ttyUSB0 (Linux) 或 COM3 (Windows)
            baudrate: 波特率，默认 9600
        """
        self._port_path = port
        self._baudrate = baudrate
        self.state = ConnectionState.CONNECTING

        # Mock: 实际生产环境使用 pyserial-asyncio
        # import serial_asyncio
        # self._reader, self._writer = await serial_asyncio.open_serial_connection(
        #     url=port, baudrate=baudrate
        # )
        self.state = ConnectionState.CONNECTED
        self.connected_at = datetime.now(timezone.utc)
        logger.info(
            "scale.connected",
            port=port,
            baudrate=baudrate,
            protocol=self._protocol_type,
            device_key=self.device_key,
            tenant_id=self.tenant_id,
        )

    async def disconnect(self) -> None:
        """断开串口连接。"""
        if self._reading_task is not None:
            self._reading_task.cancel()
            self._reading_task = None
        self.state = ConnectionState.DISCONNECTED
        logger.info("scale.disconnected", port=self._port_path, tenant_id=self.tenant_id)

    async def read_weight(self) -> dict:
        """读取当前重量。

        Returns:
            {
                "weight_g": float,      # 重量（克）
                "stable": bool,         # 是否稳定
                "tare": bool,           # 是否已去皮
                "unit": str,            # 单位 g/kg
                "raw_value": float,     # 原始读数
            }
        """
        if self.state != ConnectionState.CONNECTED:
            raise ConnectionError(f"电子秤未连接: {self._port_path}")

        # Mock: 实际使用时从串口读取数据帧并解析
        logger.info("scale.read_weight", port=self._port_path, tenant_id=self.tenant_id)
        return {
            "weight_g": 0.0,
            "stable": True,
            "tare": False,
            "unit": "g",
            "raw_value": 0.0,
        }

    def _parse_frame(self, raw_data: str) -> dict:
        """解析串口数据帧。

        Args:
            raw_data: 原始串口数据字符串

        Returns:
            解析后的重量数据
        """
        pattern = self.FRAME_PATTERNS.get(self._protocol_type)
        if pattern is None:
            raise ValueError(f"不支持的秤协议: {self._protocol_type}")

        match = pattern.search(raw_data)
        if match is None:
            raise ValueError(f"数据帧解析失败: {raw_data!r}")

        groups = match.groupdict()
        weight = float(groups["weight"])
        unit = groups.get("unit", "g")
        if unit == "kg":
            weight_g = weight * 1000
        else:
            weight_g = weight

        sign = groups.get("sign", "+")
        if sign == "-":
            weight_g = -weight_g

        stable_flag = groups.get("stable", "S")
        stable = stable_flag in ("S", "SD")

        return {
            "weight_g": weight_g,
            "stable": stable,
            "tare": False,
            "unit": unit,
            "raw_value": weight,
        }

    async def tare(self) -> None:
        """去皮（归零当前重量）。"""
        if self.state != ConnectionState.CONNECTED:
            raise ConnectionError("电子秤未连接")
        # Mock: 发送去皮指令
        # 大华: 发送 "T\r\n"
        # DIGI: 发送 ASCII 'T'
        # MT SICS: 发送 "TA\r\n"
        logger.info("scale.tare", port=self._port_path, tenant_id=self.tenant_id)

    async def zero(self) -> None:
        """清零。"""
        if self.state != ConnectionState.CONNECTED:
            raise ConnectionError("电子秤未连接")
        # Mock: 发送清零指令
        # 大华: 发送 "Z\r\n"
        # MT SICS: 发送 "Z\r\n"
        logger.info("scale.zero", port=self._port_path, tenant_id=self.tenant_id)

    async def on_weight_change(self, callback: Callable) -> None:
        """注册重量变化回调。

        Args:
            callback: 异步回调函数，参数为重量数据字典
        """
        self._weight_callback = callback
        logger.info("scale.callback_registered", port=self._port_path, tenant_id=self.tenant_id)

    async def health_check(self) -> bool:
        """健康检查。"""
        return self.state == ConnectionState.CONNECTED


# ─── 扫码枪 HID 协议 ───


class HIDScannerProtocol(ProtocolHandler):
    """扫码枪 HID 协议。

    支持品牌: 新大陆(Newland) / 霍尼韦尔(Honeywell) / 斑马(Zebra) / 商米内置
    模式: 键盘模拟(默认) / 虚拟串口 / HID 原生

    键盘模拟模式下，扫码数据以键盘输入方式发送到系统，
    通常以回车符(CR/LF)结尾。
    """

    def __init__(self, tenant_id: str, device_key: str):
        super().__init__(tenant_id, device_key)
        self._scan_callback: Optional[Callable] = None
        self._prefix: str = ""
        self._suffix: str = "\n"
        self._encoding: str = "utf-8"
        self._buffer: str = ""
        self._listening_task: Optional[asyncio.Task[None]] = None

    async def connect(self, mode: str = "hid_keyboard", **kwargs: Any) -> None:
        """连接扫码设备。

        Args:
            mode: 连接模式 hid_keyboard / virtual_serial / hid_native
        """
        self.state = ConnectionState.CONNECTED
        self.connected_at = datetime.now(timezone.utc)
        logger.info(
            "scanner.connected",
            mode=mode,
            device_key=self.device_key,
            tenant_id=self.tenant_id,
        )

    async def disconnect(self) -> None:
        """断开扫码设备。"""
        if self._listening_task is not None:
            self._listening_task.cancel()
            self._listening_task = None
        self.state = ConnectionState.DISCONNECTED
        logger.info("scanner.disconnected", device_key=self.device_key, tenant_id=self.tenant_id)

    async def on_scan(self, callback: Callable) -> None:
        """注册扫码结果回调。

        Args:
            callback: 异步回调函数，参数为扫码结果字符串

        示例::

            async def handle_scan(barcode: str):
                print(f"扫到: {barcode}")
            await scanner.on_scan(handle_scan)
        """
        self._scan_callback = callback
        logger.info("scanner.callback_registered", device_key=self.device_key, tenant_id=self.tenant_id)

    async def configure(
        self,
        prefix: str = "",
        suffix: str = "\n",
        encoding: str = "utf-8",
    ) -> None:
        """配置扫码参数。

        Args:
            prefix: 扫码数据前缀（用于过滤/识别）
            suffix: 扫码数据后缀（默认换行符）
            encoding: 编码方式
        """
        self._prefix = prefix
        self._suffix = suffix
        self._encoding = encoding
        logger.info(
            "scanner.configured",
            prefix=prefix,
            suffix=suffix,
            encoding=encoding,
            tenant_id=self.tenant_id,
        )

    async def simulate_scan(self, barcode: str) -> None:
        """模拟扫码（测试用）。

        Args:
            barcode: 模拟的条码内容
        """
        if self._scan_callback is not None:
            await self._scan_callback(barcode)
        logger.info("scanner.simulated", barcode=barcode, tenant_id=self.tenant_id)

    async def health_check(self) -> bool:
        """健康检查。"""
        return self.state == ConnectionState.CONNECTED


# ─── 钱箱协议 ───


class CashDrawerProtocol(ProtocolHandler):
    """钱箱协议 -- 通过打印机 ESC p 指令触发弹开。

    钱箱通过 RJ11 线缆连接到打印机的钱箱接口，
    由打印机发送 ESC p 指令触发电磁铁弹开钱箱。

    ESC p 指令格式: 0x1B 0x70 m t1 t2
    - m: 钱箱引脚 (0 或 1)
    - t1: 通电时间 (单位: 2ms)
    - t2: 断电时间 (单位: 2ms)
    """

    # ESC p 0 25 250 — 触发引脚0，通电50ms，断电500ms
    ESC_OPEN_DRAWER = b"\x1b\x70\x00\x19\xfa"

    def __init__(self, tenant_id: str, device_key: str):
        super().__init__(tenant_id, device_key)
        self._printer_ip: Optional[str] = None
        self._printer_port: int = 9100

    async def connect(self, printer_ip: str = "", printer_port: int = 9100, **kwargs: Any) -> None:
        """绑定钱箱到打印机。

        Args:
            printer_ip: 打印机 IP 地址（钱箱通过打印机控制）
            printer_port: 打印机端口
        """
        self._printer_ip = printer_ip
        self._printer_port = printer_port
        self.state = ConnectionState.CONNECTED
        self.connected_at = datetime.now(timezone.utc)
        logger.info(
            "cash_drawer.connected",
            printer_ip=printer_ip,
            printer_port=printer_port,
            tenant_id=self.tenant_id,
        )

    async def disconnect(self) -> None:
        """断开绑定。"""
        self.state = ConnectionState.DISCONNECTED
        logger.info("cash_drawer.disconnected", tenant_id=self.tenant_id)

    async def open(self, printer_ip: str | None = None, printer_port: int = 9100) -> None:
        """弹开钱箱。

        Args:
            printer_ip: 可选，覆盖默认打印机 IP
            printer_port: 可选，覆盖默认端口
        """
        ip = printer_ip or self._printer_ip
        port = printer_port or self._printer_port
        if ip is None:
            raise ValueError("未指定打印机 IP，无法开启钱箱")

        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(ip, port),
                timeout=5,
            )
            writer.write(self.ESC_OPEN_DRAWER)
            await writer.drain()
            writer.close()
            await writer.wait_closed()
            logger.info("cash_drawer.opened", printer_ip=ip, tenant_id=self.tenant_id)
        except asyncio.TimeoutError:
            logger.error("cash_drawer.open_timeout", printer_ip=ip, tenant_id=self.tenant_id)
            raise ConnectionError(f"钱箱打开超时（打印机 {ip} 无响应）")
        except OSError as exc:
            logger.error("cash_drawer.open_failed", printer_ip=ip, error=str(exc), tenant_id=self.tenant_id)
            raise ConnectionError(f"钱箱打开失败: {exc}") from exc

    async def health_check(self) -> bool:
        """健康检查（尝试连接打印机）。"""
        if self._printer_ip is None:
            return False
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(self._printer_ip, self._printer_port),
                timeout=3,
            )
            writer.close()
            await writer.wait_closed()
            return True
        except (asyncio.TimeoutError, OSError):
            return False


# ─── 商米设备 JS Bridge ───


class SUNMIBridge(ProtocolHandler):
    """商米设备 JS Bridge -- 通过 WebView 调用安卓原生 SDK。

    在安卓 POS 环境中，前端 React App 通过 window.TXBridge 接口
    调用商米原生 SDK 实现打印、扫码、称重等功能。

    此类为服务端 mock，实际执行在安卓壳层（android-shell）中。
    服务端通过 HTTP/WebSocket 向安卓 POS 发送指令。

    支持设备:
    - 商米 T2/T2s: 内置打印机 + 外接扫码枪/钱箱
    - 商米 V2 Pro: 内置打印机 + 内置扫码头
    - 商米 D2/D3: 纯显示终端
    """

    def __init__(self, tenant_id: str, device_key: str):
        super().__init__(tenant_id, device_key)
        self._pos_host_url: Optional[str] = None

    async def connect(self, pos_host_url: str = "", **kwargs: Any) -> None:
        """连接到安卓 POS 主机。

        Args:
            pos_host_url: 安卓 POS 主机的 HTTP 地址，如 http://192.168.1.10:8080
        """
        self._pos_host_url = pos_host_url
        self.state = ConnectionState.CONNECTED
        self.connected_at = datetime.now(timezone.utc)
        logger.info(
            "sunmi_bridge.connected",
            pos_host_url=pos_host_url,
            device_key=self.device_key,
            tenant_id=self.tenant_id,
        )

    async def disconnect(self) -> None:
        """断开连接。"""
        self.state = ConnectionState.DISCONNECTED
        logger.info("sunmi_bridge.disconnected", tenant_id=self.tenant_id)

    async def print_receipt(self, content: str) -> None:
        """通过商米 SDK 打印小票。

        Args:
            content: 格式化的打印内容（JSON 或 ESC/POS base64）
        """
        if self.state != ConnectionState.CONNECTED:
            raise ConnectionError("商米设备未连接")
        # Mock: 实际通过 HTTP POST 发送到安卓 POS
        # await httpx.post(f"{self._pos_host_url}/api/print", json={"content": content})
        logger.info("sunmi_bridge.print", content_size=len(content), tenant_id=self.tenant_id)

    async def scan(self) -> str:
        """触发商米扫码。

        Returns:
            扫码结果字符串
        """
        if self.state != ConnectionState.CONNECTED:
            raise ConnectionError("商米设备未连接")
        # Mock: 实际通过 HTTP 触发安卓扫码并等待回调
        logger.info("sunmi_bridge.scan_triggered", tenant_id=self.tenant_id)
        return ""

    async def open_cash_drawer(self) -> None:
        """通过商米 SDK 开钱箱。"""
        if self.state != ConnectionState.CONNECTED:
            raise ConnectionError("商米设备未连接")
        # Mock: 实际通过 HTTP POST 发送到安卓 POS
        logger.info("sunmi_bridge.cash_drawer_opened", tenant_id=self.tenant_id)

    async def get_device_info(self) -> dict:
        """获取商米设备信息。

        Returns:
            {"model": "T2", "serial": "...", "os_version": "..."}
        """
        if self.state != ConnectionState.CONNECTED:
            raise ConnectionError("商米设备未连接")
        # Mock
        return {"model": "SUNMI T2", "serial": "MOCK", "os_version": "Android 9.0"}

    async def health_check(self) -> bool:
        """健康检查。"""
        if self._pos_host_url is None:
            return False
        # Mock: 实际 ping 安卓 POS 主机
        return self.state == ConnectionState.CONNECTED


# ─── 标签打印协议 ───


class LabelPrinterProtocol(ProtocolHandler):
    """标签打印机协议。

    支持 ZPL (Zebra) 和 TSPL (TSC/得力/佳博) 两种指令集。

    ZPL 示例:
        ^XA
        ^FO50,50^A0N,40,40^FD菜品名称^FS
        ^FO50,100^BY2^BCN,60,Y,N,N^FD123456^FS
        ^XZ

    TSPL 示例:
        SIZE 40 mm, 30 mm
        GAP 2 mm, 0 mm
        CLS
        TEXT 10,10,"TSS24.BF2",0,1,1,"菜品名称"
        BARCODE 10,50,"128",60,1,0,2,2,"123456"
        PRINT 1
    """

    def __init__(self, tenant_id: str, device_key: str, protocol: str = "TSPL"):
        super().__init__(tenant_id, device_key)
        self._ip: Optional[str] = None
        self._port: int = 9100
        self._protocol_type = protocol
        self._reader: Optional[asyncio.StreamReader] = None
        self._writer: Optional[asyncio.StreamWriter] = None

    async def connect(self, ip: str = "", port: int = 9100, **kwargs: Any) -> None:
        """连接标签打印机。

        Args:
            ip: 打印机 IP
            port: 端口号，默认 9100
        """
        self._ip = ip
        self._port = port
        self.state = ConnectionState.CONNECTING

        try:
            self._reader, self._writer = await asyncio.wait_for(
                asyncio.open_connection(ip, port),
                timeout=5,
            )
            self.state = ConnectionState.CONNECTED
            self.connected_at = datetime.now(timezone.utc)
            logger.info(
                "label_printer.connected",
                ip=ip,
                port=port,
                protocol=self._protocol_type,
                tenant_id=self.tenant_id,
            )
        except asyncio.TimeoutError:
            self.state = ConnectionState.ERROR
            self.last_error = f"连接超时: {ip}:{port}"
            raise ConnectionError(self.last_error)
        except OSError as exc:
            self.state = ConnectionState.ERROR
            self.last_error = str(exc)
            raise ConnectionError(self.last_error) from exc

    async def disconnect(self) -> None:
        """断开连接。"""
        if self._writer is not None:
            try:
                self._writer.close()
                await self._writer.wait_closed()
            except OSError:
                pass
            finally:
                self._writer = None
                self._reader = None
                self.state = ConnectionState.DISCONNECTED

    async def print_label(
        self,
        item_name: str,
        barcode: str = "",
        price: str = "",
        date: str = "",
        copies: int = 1,
    ) -> None:
        """打印菜品标签。

        Args:
            item_name: 菜品名称
            barcode: 条形码内容
            price: 价格
            date: 日期
            copies: 打印份数
        """
        if self._writer is None:
            raise ConnectionError("标签打印机未连接")

        if self._protocol_type == "ZPL":
            cmd = self._build_zpl_label(item_name, barcode, price, date, copies)
        else:
            cmd = self._build_tspl_label(item_name, barcode, price, date, copies)

        async with self._lock:
            self._writer.write(cmd)
            await self._writer.drain()

        logger.info(
            "label_printer.printed",
            item_name=item_name,
            copies=copies,
            protocol=self._protocol_type,
            tenant_id=self.tenant_id,
        )

    def _build_zpl_label(
        self,
        name: str,
        barcode: str,
        price: str,
        date: str,
        copies: int,
    ) -> bytes:
        """构建 ZPL 标签指令。"""
        zpl = f"""^XA
^CI28
^FO20,20^A0N,30,30^FD{name}^FS
"""
        if price:
            zpl += f"^FO20,60^A0N,25,25^FD价格: {price}^FS\n"
        if date:
            zpl += f"^FO20,90^A0N,20,20^FD日期: {date}^FS\n"
        if barcode:
            zpl += f"^FO20,120^BY2^BCN,50,Y,N,N^FD{barcode}^FS\n"
        zpl += f"^PQ{copies}\n^XZ\n"
        return zpl.encode("utf-8")

    def _build_tspl_label(
        self,
        name: str,
        barcode: str,
        price: str,
        date: str,
        copies: int,
    ) -> bytes:
        """构建 TSPL 标签指令。"""
        tspl = "SIZE 40 mm, 30 mm\nGAP 2 mm, 0 mm\nCLS\n"
        tspl += f'TEXT 10,10,"TSS24.BF2",0,1,1,"{name}"\n'
        if price:
            tspl += f'TEXT 10,40,"TSS24.BF2",0,1,1,"价格: {price}"\n'
        if date:
            tspl += f'TEXT 10,65,"TSS16.BF2",0,1,1,"日期: {date}"\n'
        if barcode:
            tspl += f'BARCODE 10,90,"128",50,1,0,2,2,"{barcode}"\n'
        tspl += f"PRINT {copies}\n"
        return tspl.encode("utf-8")

    async def health_check(self) -> bool:
        """健康检查。"""
        return self._writer is not None and self.state == ConnectionState.CONNECTED


# ─── HTTP API 协议（排队机 / 自助机） ───


class HTTPDeviceProtocol(ProtocolHandler):
    """HTTP API 协议 -- 用于智能设备（排队机/自助机/KDS）。

    这些设备通常运行 Android 系统，暴露 HTTP API 进行控制。
    """

    def __init__(self, tenant_id: str, device_key: str):
        super().__init__(tenant_id, device_key)
        self._base_url: Optional[str] = None

    async def connect(self, base_url: str = "", **kwargs: Any) -> None:
        """连接到设备 HTTP API。

        Args:
            base_url: 设备 HTTP API 基地址，如 http://192.168.1.20:8080
        """
        self._base_url = base_url
        self.state = ConnectionState.CONNECTED
        self.connected_at = datetime.now(timezone.utc)
        logger.info(
            "http_device.connected",
            base_url=base_url,
            device_key=self.device_key,
            tenant_id=self.tenant_id,
        )

    async def disconnect(self) -> None:
        """断开连接。"""
        self.state = ConnectionState.DISCONNECTED
        logger.info("http_device.disconnected", tenant_id=self.tenant_id)

    async def send_command(self, endpoint: str, payload: dict) -> dict:
        """发送 HTTP 指令到设备。

        Args:
            endpoint: API 路径，如 /api/queue/call
            payload: 请求 JSON body

        Returns:
            设备响应
        """
        if self._base_url is None:
            raise ConnectionError("设备未连接")
        # Mock: 实际使用 httpx
        # async with httpx.AsyncClient() as client:
        #     resp = await client.post(f"{self._base_url}{endpoint}", json=payload)
        #     return resp.json()
        logger.info(
            "http_device.command_sent",
            endpoint=endpoint,
            tenant_id=self.tenant_id,
        )
        return {"ok": True}

    async def health_check(self) -> bool:
        """健康检查。"""
        if self._base_url is None:
            return False
        # Mock: 实际 ping /health 端点
        return self.state == ConnectionState.CONNECTED


# ─── 协议工厂 ───

PROTOCOL_MAP: dict[str, type[ProtocolHandler]] = {
    "ESC/POS": ESCPOSProtocol,
    "SUNMI_JS_BRIDGE": SUNMIBridge,
    "DIGI_SERIAL": SerialScaleProtocol,
    "DAHUA_SERIAL": SerialScaleProtocol,
    "CAS_SERIAL": SerialScaleProtocol,
    "MT_SICS": SerialScaleProtocol,
    "HID_KEYBOARD": HIDScannerProtocol,
    "ESC_P_TRIGGER": CashDrawerProtocol,
    "HTTP_API": HTTPDeviceProtocol,
    "ZPL": LabelPrinterProtocol,
    "TSPL": LabelPrinterProtocol,
    "NIIMBOT_BLE": LabelPrinterProtocol,
}


def create_protocol_handler(
    protocol: str,
    tenant_id: str,
    device_key: str,
) -> ProtocolHandler:
    """根据协议类型创建对应的协议处理器。

    Args:
        protocol: 协议标识，如 "ESC/POS", "DAHUA_SERIAL" 等
        tenant_id: 租户 ID
        device_key: 设备标识

    Returns:
        对应的 ProtocolHandler 实例

    Raises:
        ValueError: 不支持的协议
    """
    handler_cls = PROTOCOL_MAP.get(protocol)
    if handler_cls is None:
        raise ValueError(f"不支持的协议: {protocol}，可用协议: {', '.join(PROTOCOL_MAP.keys())}")

    # SerialScaleProtocol 需要传递 protocol 参数
    if handler_cls is SerialScaleProtocol:
        return SerialScaleProtocol(tenant_id, device_key, protocol=protocol)

    # LabelPrinterProtocol 需要传递 protocol 参数
    if handler_cls is LabelPrinterProtocol:
        return LabelPrinterProtocol(tenant_id, device_key, protocol=protocol)

    return handler_cls(tenant_id, device_key)
