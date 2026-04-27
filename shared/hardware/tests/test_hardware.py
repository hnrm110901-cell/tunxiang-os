"""硬件配置中心测试

覆盖：设备注册表查询、协议创建、门店配置管理、模板管理、API 路由。
"""

import pytest
import pytest_asyncio

from shared.hardware.device_registry import (
    DEVICE_CATEGORIES,
    DEVICE_REGISTRY,
    get_all_brands,
    get_device,
    get_devices_by_category,
    get_recommended_config,
    search_devices,
)
from shared.hardware.protocol_support import (
    CashDrawerProtocol,
    ConnectionState,
    ESCPOSProtocol,
    HIDScannerProtocol,
    HTTPDeviceProtocol,
    LabelPrinterProtocol,
    SerialScaleProtocol,
    SUNMIBridge,
    create_protocol_handler,
)
from shared.hardware.store_hardware_config import (
    StoreHardwareConfig,
)

# ════════════════════════════════════════════
# 1. 设备注册表测试
# ════════════════════════════════════════════


class TestDeviceRegistry:
    """设备注册表查询测试。"""

    def test_registry_not_empty(self) -> None:
        """注册表非空。"""
        assert len(DEVICE_REGISTRY) > 0, "设备注册表为空"

    def test_all_categories_have_devices(self) -> None:
        """每个品类至少有一个设备。"""
        for cat_key in DEVICE_CATEGORIES:
            devices = get_devices_by_category(cat_key)
            assert len(devices) > 0, f"品类 {cat_key} 没有任何设备"

    def test_get_device_valid(self) -> None:
        """获取存在的设备。"""
        device = get_device("beiyang_98np")
        assert device["brand"] == "北洋(SNBC)"
        assert device["model"] == "BTP-98NP"
        assert device["category"] == "printer"
        assert device["protocol"] == "ESC/POS"

    def test_get_device_invalid(self) -> None:
        """获取不存在的设备应抛异常。"""
        with pytest.raises(ValueError, match="设备不存在"):
            get_device("nonexistent_device")

    def test_search_by_brand(self) -> None:
        """按品牌搜索设备。"""
        results = search_devices(brand="商米")
        assert len(results) > 0
        for dev in results.values():
            assert "商米" in dev["brand"]

    def test_search_by_category(self) -> None:
        """按品类搜索设备。"""
        results = search_devices(category="printer")
        assert len(results) >= 5  # 至少5款打印机
        for dev in results.values():
            assert dev["category"] == "printer"

    def test_search_by_interface(self) -> None:
        """按接口搜索设备。"""
        results = search_devices(interface="ethernet")
        assert len(results) > 0
        for dev in results.values():
            assert "ethernet" in dev.get("interfaces", [])

    def test_search_by_protocol(self) -> None:
        """按协议搜索设备。"""
        results = search_devices(protocol="ESC/POS")
        assert len(results) > 0
        for dev in results.values():
            assert dev["protocol"] == "ESC/POS"

    def test_get_all_brands(self) -> None:
        """获取所有品牌。"""
        brands = get_all_brands()
        assert len(brands) > 0
        assert any("北洋" in b for b in brands)
        assert any("商米" in b for b in brands)

    def test_recommended_config_sizes(self) -> None:
        """推荐配置包含所有门店规模。"""
        for size in ("small", "medium", "large"):
            config = get_recommended_config(size)
            assert len(config) > 0, f"{size} 配置为空"
            assert "pos_terminal" in config or "printer" in config

    def test_device_fields_complete(self) -> None:
        """所有设备必须有 brand, model, category 字段。"""
        for key, dev in DEVICE_REGISTRY.items():
            assert "brand" in dev, f"{key} 缺少 brand"
            assert "model" in dev, f"{key} 缺少 model"
            assert "category" in dev, f"{key} 缺少 category"
            assert dev["category"] in DEVICE_CATEGORIES, (
                f"{key} 的 category '{dev['category']}' 不在 DEVICE_CATEGORIES 中"
            )

    def test_printer_category_count(self) -> None:
        """打印机品类至少有 5 个型号。"""
        printers = get_devices_by_category("printer")
        assert len(printers) >= 5


# ════════════════════════════════════════════
# 2. 协议支持层测试
# ════════════════════════════════════════════


class TestProtocolSupport:
    """协议支持层测试。"""

    def test_create_escpos_protocol(self) -> None:
        """创建 ESC/POS 协议处理器。"""
        handler = create_protocol_handler("ESC/POS", "tenant-1", "beiyang_98np")
        assert isinstance(handler, ESCPOSProtocol)
        assert handler.state == ConnectionState.DISCONNECTED
        assert handler.tenant_id == "tenant-1"

    def test_create_serial_scale_protocol(self) -> None:
        """创建电子秤串口协议处理器。"""
        handler = create_protocol_handler("DAHUA_SERIAL", "tenant-1", "dahua_tm30")
        assert isinstance(handler, SerialScaleProtocol)

    def test_create_hid_scanner_protocol(self) -> None:
        """创建扫码枪 HID 协议处理器。"""
        handler = create_protocol_handler("HID_KEYBOARD", "tenant-1", "newland_fr80")
        assert isinstance(handler, HIDScannerProtocol)

    def test_create_cash_drawer_protocol(self) -> None:
        """创建钱箱协议处理器。"""
        handler = create_protocol_handler("ESC_P_TRIGGER", "tenant-1", "cash_drawer_405")
        assert isinstance(handler, CashDrawerProtocol)

    def test_create_sunmi_bridge(self) -> None:
        """创建商米 JS Bridge 处理器。"""
        handler = create_protocol_handler("SUNMI_JS_BRIDGE", "tenant-1", "sunmi_builtin_printer")
        assert isinstance(handler, SUNMIBridge)

    def test_create_label_printer_protocol(self) -> None:
        """创建标签打印机协议处理器。"""
        handler = create_protocol_handler("ZPL", "tenant-1", "zebra_gk888t")
        assert isinstance(handler, LabelPrinterProtocol)

    def test_create_http_device_protocol(self) -> None:
        """创建 HTTP 设备协议处理器。"""
        handler = create_protocol_handler("HTTP_API", "tenant-1", "meiou_qms")
        assert isinstance(handler, HTTPDeviceProtocol)

    def test_create_unsupported_protocol(self) -> None:
        """不支持的协议应抛异常。"""
        with pytest.raises(ValueError, match="不支持的协议"):
            create_protocol_handler("UNKNOWN_PROTOCOL", "tenant-1", "test")

    def test_protocol_get_status(self) -> None:
        """协议处理器状态查询。"""
        handler = create_protocol_handler("ESC/POS", "tenant-1", "beiyang_98np")
        status = handler.get_status()
        assert status["state"] == "disconnected"
        assert status["device_key"] == "beiyang_98np"
        assert status["tenant_id"] == "tenant-1"

    def test_scale_parse_frame(self) -> None:
        """电子秤数据帧解析。"""
        handler = SerialScaleProtocol("tenant-1", "dahua_tm30", "DAHUA_SERIAL")
        result = handler._parse_frame("+  1.234 kg S")
        assert result["weight_g"] == 1234.0
        assert result["stable"] is True
        assert result["unit"] == "kg"

    def test_scale_parse_negative(self) -> None:
        """电子秤负值解析。"""
        handler = SerialScaleProtocol("tenant-1", "dahua_tm30", "DAHUA_SERIAL")
        result = handler._parse_frame("-0.500 kg S")
        assert result["weight_g"] == -500.0

    def test_scale_parse_mt_sics(self) -> None:
        """梅特勒-托利多 SICS 协议解析。"""
        handler = SerialScaleProtocol("tenant-1", "mettler_bba231", "MT_SICS")
        result = handler._parse_frame("S SD    250.5 g")
        assert result["weight_g"] == 250.5
        assert result["stable"] is True


# ════════════════════════════════════════════
# 3. 门店硬件配置管理测试
# ════════════════════════════════════════════


class TestStoreHardwareConfig:
    """门店硬件配置管理测试。"""

    @pytest_asyncio.fixture
    async def config(self) -> StoreHardwareConfig:
        """创建测试用配置管理器。"""
        return StoreHardwareConfig()

    @pytest.mark.asyncio
    async def test_configure_store(self, config: StoreHardwareConfig) -> None:
        """配置门店设备。"""
        devices = [
            {
                "device_key": "beiyang_98np",
                "connection_params": {"ip": "192.168.1.100", "port": 9100},
                "role": "cashier",
                "name": "前台收银打印机",
            },
            {
                "device_key": "gainscha_sd80s",
                "connection_params": {"ip": "192.168.1.101", "port": 9100},
                "role": "kitchen",
                "name": "厨房打印机",
                "dept_id": "dept-hot",
            },
        ]
        result = await config.configure_store("store-1", devices, "tenant-1")
        assert len(result) == 2
        assert result[0]["brand"] == "北洋(SNBC)"
        assert result[0]["role"] == "cashier"
        assert result[1]["role"] == "kitchen"

    @pytest.mark.asyncio
    async def test_get_store_config(self, config: StoreHardwareConfig) -> None:
        """获取门店配置。"""
        devices = [
            {
                "device_key": "sunmi_t2",
                "connection_params": {},
                "role": "pos",
                "name": "收银POS",
            },
        ]
        await config.configure_store("store-1", devices, "tenant-1")
        result = await config.get_store_config("store-1", "tenant-1")
        assert len(result) == 1
        assert result[0]["device_key"] == "sunmi_t2"

    @pytest.mark.asyncio
    async def test_add_and_remove_device(self, config: StoreHardwareConfig) -> None:
        """添加和移除设备。"""
        result = await config.add_device(
            store_id="store-1",
            device_key="newland_fr80",
            connection_params={},
            tenant_id="tenant-1",
            role="scanner",
            name="扫码盒",
        )
        instance_id = result["instance_id"]
        assert result["device_key"] == "newland_fr80"

        devices = await config.get_store_config("store-1", "tenant-1")
        assert len(devices) == 1

        await config.remove_device("store-1", instance_id, "tenant-1")
        devices = await config.get_store_config("store-1", "tenant-1")
        assert len(devices) == 0

    @pytest.mark.asyncio
    async def test_remove_nonexistent_device(self, config: StoreHardwareConfig) -> None:
        """移除不存在的设备应抛异常。"""
        with pytest.raises(ValueError, match="设备实例不存在"):
            await config.remove_device("store-1", "nonexistent", "tenant-1")

    @pytest.mark.asyncio
    async def test_tenant_isolation(self, config: StoreHardwareConfig) -> None:
        """租户隔离。"""
        await config.add_device(
            store_id="store-1",
            device_key="beiyang_98np",
            connection_params={"ip": "10.0.0.1"},
            tenant_id="tenant-1",
        )
        await config.add_device(
            store_id="store-1",
            device_key="gainscha_sd80s",
            connection_params={"ip": "10.0.0.2"},
            tenant_id="tenant-2",
        )

        tenant1_devices = await config.get_store_config("store-1", "tenant-1")
        tenant2_devices = await config.get_store_config("store-1", "tenant-2")
        assert len(tenant1_devices) == 1
        assert len(tenant2_devices) == 1
        assert tenant1_devices[0]["device_key"] != tenant2_devices[0]["device_key"]

    @pytest.mark.asyncio
    async def test_create_and_apply_template(self, config: StoreHardwareConfig) -> None:
        """创建和应用硬件模板。"""
        template_devices = [
            {
                "device_key": "beiyang_98np",
                "connection_params": {"ip": "PLACEHOLDER", "port": 9100},
                "role": "cashier",
                "name": "收银打印机",
            },
            {
                "device_key": "newland_fr80",
                "connection_params": {},
                "role": "scanner",
                "name": "扫码盒",
            },
        ]
        template = await config.create_store_template(
            template_name="标准店配置",
            devices=template_devices,
            tenant_id="tenant-1",
            description="适用于50-100平标准门店",
        )
        assert template["template_name"] == "标准店配置"
        assert template["device_count"] == 2

        # 应用模板到门店，覆盖 IP 地址
        result = await config.apply_template(
            template_id=template["template_id"],
            store_id="store-new",
            tenant_id="tenant-1",
            connection_overrides={
                "beiyang_98np": {"ip": "192.168.1.200"},
            },
        )
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_list_templates(self, config: StoreHardwareConfig) -> None:
        """列出模板。"""
        await config.create_store_template(
            template_name="模板A",
            devices=[{"device_key": "beiyang_98np", "connection_params": {}}],
            tenant_id="tenant-1",
        )
        await config.create_store_template(
            template_name="模板B",
            devices=[{"device_key": "sunmi_t2", "connection_params": {}}],
            tenant_id="tenant-1",
        )
        templates = await config.list_templates("tenant-1")
        assert len(templates) == 2

    @pytest.mark.asyncio
    async def test_apply_nonexistent_template(self, config: StoreHardwareConfig) -> None:
        """应用不存在的模板应抛异常。"""
        with pytest.raises(ValueError, match="模板不存在"):
            await config.apply_template("nonexistent", "store-1", "tenant-1")

    @pytest.mark.asyncio
    async def test_configure_invalid_device(self, config: StoreHardwareConfig) -> None:
        """配置不存在的设备应抛异常。"""
        with pytest.raises(ValueError, match="设备不存在"):
            await config.configure_store(
                "store-1",
                [{"device_key": "fake_device", "connection_params": {}}],
                "tenant-1",
            )


# ════════════════════════════════════════════
# 4. 异步协议操作测试
# ════════════════════════════════════════════


class TestAsyncProtocolOps:
    """异步协议操作测试。"""

    @pytest.mark.asyncio
    async def test_scanner_connect_disconnect(self) -> None:
        """扫码枪连接与断开。"""
        scanner = HIDScannerProtocol("tenant-1", "newland_fr80")
        await scanner.connect(mode="hid_keyboard")
        assert scanner.state == ConnectionState.CONNECTED
        assert scanner.connected_at is not None

        await scanner.disconnect()
        assert scanner.state == ConnectionState.DISCONNECTED

    @pytest.mark.asyncio
    async def test_scanner_configure(self) -> None:
        """扫码枪配置。"""
        scanner = HIDScannerProtocol("tenant-1", "newland_fr80")
        await scanner.connect()
        await scanner.configure(prefix="", suffix="\r\n", encoding="utf-8")
        assert scanner._suffix == "\r\n"

    @pytest.mark.asyncio
    async def test_scanner_simulate_scan(self) -> None:
        """模拟扫码回调。"""
        scanner = HIDScannerProtocol("tenant-1", "newland_fr80")
        await scanner.connect()

        scanned_codes: list[str] = []

        async def on_scan(barcode: str) -> None:
            scanned_codes.append(barcode)

        await scanner.on_scan(on_scan)
        await scanner.simulate_scan("wxp://f2f0000000")
        assert scanned_codes == ["wxp://f2f0000000"]

    @pytest.mark.asyncio
    async def test_scale_connect(self) -> None:
        """电子秤连接。"""
        scale = SerialScaleProtocol("tenant-1", "dahua_tm30", "DAHUA_SERIAL")
        await scale.connect(port="/dev/ttyUSB0", baudrate=9600)
        assert scale.state == ConnectionState.CONNECTED
        health = await scale.health_check()
        assert health is True
        await scale.disconnect()
        assert scale.state == ConnectionState.DISCONNECTED

    @pytest.mark.asyncio
    async def test_sunmi_bridge_connect(self) -> None:
        """商米 JS Bridge 连接。"""
        bridge = SUNMIBridge("tenant-1", "sunmi_builtin_printer")
        await bridge.connect(pos_host_url="http://192.168.1.10:8080")
        assert bridge.state == ConnectionState.CONNECTED

        info = await bridge.get_device_info()
        assert "model" in info

        await bridge.disconnect()
        assert bridge.state == ConnectionState.DISCONNECTED

    @pytest.mark.asyncio
    async def test_http_device_send_command(self) -> None:
        """HTTP 设备发送指令。"""
        device = HTTPDeviceProtocol("tenant-1", "meiou_qms")
        await device.connect(base_url="http://192.168.1.20:8080")
        result = await device.send_command("/api/queue/call", {"number": "A001"})
        assert result["ok"] is True
        await device.disconnect()

    @pytest.mark.asyncio
    async def test_label_printer_build_zpl(self) -> None:
        """标签打印机 ZPL 构建。"""
        printer = LabelPrinterProtocol("tenant-1", "zebra_gk888t", protocol="ZPL")
        cmd = printer._build_zpl_label("宫保鸡丁", "123456", "38.00", "2026-03-27", 1)
        assert b"^XA" in cmd
        assert b"^XZ" in cmd
        assert "宫保鸡丁".encode("utf-8") in cmd

    @pytest.mark.asyncio
    async def test_label_printer_build_tspl(self) -> None:
        """标签打印机 TSPL 构建。"""
        printer = LabelPrinterProtocol("tenant-1", "deli_dl_888b", protocol="TSPL")
        cmd = printer._build_tspl_label("水煮鱼", "789012", "68.00", "2026-03-27", 2)
        assert b"SIZE" in cmd
        assert b"PRINT 2" in cmd
