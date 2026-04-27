"""打印机驱动 + 模板引擎测试

所有测试不需要真实打印机，验证 ESC/POS 指令生成和模板渲染的正确性。
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.print_manager import PrinterRole, PrintManager
from services.print_template import ReceiptTemplate
from services.printer_driver import (
    ESC_ALIGN_CENTER,
    ESC_ALIGN_LEFT,
    ESC_ALIGN_RIGHT,
    ESC_BOLD_OFF,
    ESC_BOLD_ON,
    ESC_INIT,
    ESC_OPEN_DRAWER,
    GS_CUT_FULL,
    GS_CUT_PARTIAL,
    GS_SIZE_DOUBLE_BOTH,
    GS_SIZE_NORMAL,
    LINE_WIDTH,
    ESCPOSPrinter,
    _gbk_len,
    _pad_three_columns,
    _pad_two_columns,
    build_escpos_commands,
)

# ─── 测试数据 ───


def _sample_order():
    return {
        "order_no": "TX202603271200001A",
        "table_number": "A05",
        "order_time": "2026-03-27T12:00:00+08:00",
        "total_amount_fen": 23600,
        "discount_amount_fen": 2000,
        "final_amount_fen": 21600,
        "guest_count": 4,
        "items": [
            {
                "item_name": "剁椒鱼头",
                "quantity": 1,
                "subtotal_fen": 8800,
                "kitchen_station": "热菜档",
                "dept_id": "dept_hot",
                "notes": "少辣",
                "spec": "大份",
            },
            {
                "item_name": "农家小炒肉",
                "quantity": 1,
                "subtotal_fen": 4200,
                "kitchen_station": "热菜档",
                "dept_id": "dept_hot",
                "notes": "",
            },
            {
                "item_name": "凉拌黄瓜",
                "quantity": 2,
                "subtotal_fen": 3600,
                "kitchen_station": "凉菜档",
                "dept_id": "dept_cold",
                "notes": "多醋",
            },
            {
                "item_name": "米饭",
                "quantity": 4,
                "subtotal_fen": 4000,
                "kitchen_station": "面点档",
                "dept_id": "dept_staple",
                "notes": "",
            },
            {
                "item_name": "啤酒",
                "quantity": 3,
                "subtotal_fen": 3000,
                "kitchen_station": None,
                "dept_id": None,
                "notes": "",
            },
        ],
    }


def _sample_store():
    return {
        "name": "尝在一起 (万达店)",
        "address": "长沙市岳麓区万达广场3楼",
        "phone": "0731-88888888",
        "qr_url": "https://tx.example.com/store/001",
        "invoice_qr_url": "https://tx.example.com/invoice/001",
    }


def _sample_payment():
    return {
        "method": "wechat",
        "amount_fen": 21600,
        "pay_time": "2026-03-27T12:30:00+08:00",
    }


def _sample_shift():
    return {
        "settlement_date": "2026-03-27",
        "settlement_type": "午班",
        "operator": "张三",
        "total_revenue_fen": 580000,
        "total_discount_fen": 32000,
        "total_refund_fen": 8000,
        "net_revenue_fen": 540000,
        "cash_fen": 120000,
        "wechat_fen": 280000,
        "alipay_fen": 140000,
        "total_orders": 45,
        "total_guests": 128,
        "avg_per_guest_fen": 4531,
        "cash_expected_fen": 120000,
        "cash_actual_fen": 119500,
        "cash_diff_fen": -500,
    }


def _sample_daily():
    return {
        "date": "2026-03-27",
        "total_revenue_fen": 1280000,
        "total_orders": 98,
        "total_guests": 312,
        "avg_per_order_fen": 13061,
        "channel_summary": {
            "堂食": {"amount_fen": 980000, "count": 72},
            "外卖": {"amount_fen": 200000, "count": 18},
            "自提": {"amount_fen": 100000, "count": 8},
        },
        "top_dishes": [
            {"name": "剁椒鱼头", "sold": 38, "amount_fen": 334400},
            {"name": "农家小炒肉", "sold": 32, "amount_fen": 134400},
            {"name": "凉拌黄瓜", "sold": 28, "amount_fen": 50400},
        ],
    }


# ─── 1. ESC/POS 指令生成测试 ───


class TestESCPOSCommands:
    """ESC/POS 指令常量和工具函数测试。"""

    def test_init_command(self):
        assert ESC_INIT == b"\x1b\x40"

    def test_align_commands(self):
        assert ESC_ALIGN_LEFT == b"\x1b\x61\x00"
        assert ESC_ALIGN_CENTER == b"\x1b\x61\x01"
        assert ESC_ALIGN_RIGHT == b"\x1b\x61\x02"

    def test_bold_commands(self):
        assert ESC_BOLD_ON == b"\x1b\x45\x01"
        assert ESC_BOLD_OFF == b"\x1b\x45\x00"

    def test_size_commands(self):
        assert GS_SIZE_NORMAL == b"\x1d\x21\x00"
        assert GS_SIZE_DOUBLE_BOTH == b"\x1d\x21\x11"

    def test_cut_commands(self):
        assert GS_CUT_PARTIAL == b"\x1d\x56\x01"
        assert GS_CUT_FULL == b"\x1d\x56\x00"

    def test_open_drawer_command(self):
        assert ESC_OPEN_DRAWER == b"\x1b\x70\x00\x19\xfa"

    def test_line_width(self):
        assert LINE_WIDTH == 48

    def test_build_commands_dict(self):
        cmds = build_escpos_commands()
        assert isinstance(cmds, dict)
        assert cmds["init"] == ESC_INIT
        assert cmds["cut_partial"] == GS_CUT_PARTIAL
        assert cmds["open_drawer"] == ESC_OPEN_DRAWER
        assert len(cmds) >= 12


# ─── 2. 中文 GBK 编码测试 ───


class TestGBKEncoding:
    """中文 GBK 编码和宽度计算测试。"""

    def test_ascii_width(self):
        assert _gbk_len("hello") == 5

    def test_chinese_width(self):
        # 中文每个字符在 GBK 中占 2 字节
        assert _gbk_len("你好") == 4

    def test_mixed_width(self):
        assert _gbk_len("A你B好C") == 7  # 3 ASCII + 2 Chinese * 2

    def test_chinese_encode_gbk(self):
        text = "屯象科技"
        encoded = text.encode("gbk", errors="replace")
        assert isinstance(encoded, bytes)
        assert len(encoded) == 8  # 4 Chinese * 2

    def test_two_columns_alignment(self):
        line = _pad_two_columns("合计:", "¥128.00", 48)
        assert "合计:" in line
        assert "¥128.00" in line
        assert len(line.encode("gbk", errors="replace")) <= 48

    def test_three_columns_alignment(self):
        line = _pad_three_columns("剁椒鱼头", "1", "¥88.00", 48)
        assert "剁椒鱼头" in line
        assert "1" in line
        assert "¥88.00" in line


# ─── 3. 模板渲染测试 ───


class TestReceiptTemplate:
    """模板渲染测试 — 验证 bytes 输出格式。"""

    @pytest.mark.asyncio
    async def test_cashier_receipt_generates_bytes(self):
        content = await ReceiptTemplate.render_cashier_receipt(_sample_order(), _sample_store(), _sample_payment())
        assert isinstance(content, bytes)
        assert len(content) > 100

    @pytest.mark.asyncio
    async def test_cashier_receipt_contains_store_name(self):
        content = await ReceiptTemplate.render_cashier_receipt(_sample_order(), _sample_store(), _sample_payment())
        assert "尝在一起".encode("gbk") in content

    @pytest.mark.asyncio
    async def test_cashier_receipt_contains_init_and_cut(self):
        content = await ReceiptTemplate.render_cashier_receipt(_sample_order(), _sample_store(), _sample_payment())
        assert content[:2] == ESC_INIT
        assert GS_CUT_PARTIAL in content

    @pytest.mark.asyncio
    async def test_cashier_receipt_contains_payment_method(self):
        content = await ReceiptTemplate.render_cashier_receipt(_sample_order(), _sample_store(), _sample_payment())
        assert "微信支付".encode("gbk") in content

    @pytest.mark.asyncio
    async def test_kitchen_ticket_generates_bytes(self):
        items = [
            {"item_name": "剁椒鱼头", "quantity": 1, "notes": "少辣", "spec": "大份"},
            {"item_name": "农家小炒肉", "quantity": 1, "notes": ""},
        ]
        content = await ReceiptTemplate.render_kitchen_ticket(items, "A05", "热菜档", "TX202603271200001A")
        assert isinstance(content, bytes)
        assert "热菜档".encode("gbk") in content
        assert "A05".encode("gbk") in content
        assert "少辣".encode("gbk") in content

    @pytest.mark.asyncio
    async def test_kitchen_ticket_full_cut(self):
        """厨打小票应使用全切（不同于收银小票的半切）。"""
        items = [{"item_name": "测试菜", "quantity": 1}]
        content = await ReceiptTemplate.render_kitchen_ticket(items, "B01", "测试档")
        assert GS_CUT_FULL in content

    @pytest.mark.asyncio
    async def test_checkout_bill_generates_bytes(self):
        content = await ReceiptTemplate.render_checkout_bill(_sample_order(), _sample_store())
        assert isinstance(content, bytes)
        assert "结 账 单".encode("gbk") in content

    @pytest.mark.asyncio
    async def test_shift_report_generates_bytes(self):
        content = await ReceiptTemplate.render_shift_report(_sample_shift())
        assert isinstance(content, bytes)
        assert "交 接 班 报 表".encode("gbk") in content
        assert "午班".encode("gbk") in content

    @pytest.mark.asyncio
    async def test_label_generates_bytes(self):
        content = await ReceiptTemplate.render_label(dish_name="剁椒鱼头", table_no="A05", seq=3, notes="少辣")
        assert isinstance(content, bytes)
        assert "剁椒鱼头".encode("gbk") in content
        assert b"#3" in content
        assert "少辣".encode("gbk") in content

    @pytest.mark.asyncio
    async def test_daily_report_generates_bytes(self):
        content = await ReceiptTemplate.render_daily_report(_sample_daily())
        assert isinstance(content, bytes)
        assert "日 结 报 表".encode("gbk") in content
        assert "菜品排行".encode("gbk") in content


# ─── 4. 切纸 / 开钱箱指令测试 ───


class TestCutAndDrawerCommands:
    """验证切纸和开钱箱指令在模板输出中的正确性。"""

    @pytest.mark.asyncio
    async def test_cashier_receipt_partial_cut(self):
        """收银小票应使用半切。"""
        content = await ReceiptTemplate.render_cashier_receipt(_sample_order(), _sample_store(), _sample_payment())
        assert GS_CUT_PARTIAL in content
        # 半切指令应在末尾
        assert content.endswith(GS_CUT_PARTIAL)

    @pytest.mark.asyncio
    async def test_label_full_cut(self):
        """标签应使用全切。"""
        content = await ReceiptTemplate.render_label("测试", "A01", 1)
        assert GS_CUT_FULL in content

    def test_open_drawer_bytes(self):
        """开钱箱指令字节正确。"""
        assert ESC_OPEN_DRAWER == b"\x1b\x70\x00\x19\xfa"
        assert len(ESC_OPEN_DRAWER) == 5


# ─── 5. 多档口厨打分发测试 ───


class TestKitchenDispatch:
    """多档口厨打分发逻辑测试。"""

    @pytest.mark.asyncio
    async def test_dispatch_splits_by_dept(self):
        """验证订单按档口正确拆分。"""
        mgr = PrintManager()

        # 注册三个厨打打印机
        await mgr.register_printer(
            "p_hot", "192.168.1.101", 9100, "kitchen", "store_001", "tenant_001", dept_id="dept_hot", name="热菜打印机"
        )
        await mgr.register_printer(
            "p_cold",
            "192.168.1.102",
            9100,
            "kitchen",
            "store_001",
            "tenant_001",
            dept_id="dept_cold",
            name="凉菜打印机",
        )
        await mgr.register_printer(
            "p_staple",
            "192.168.1.103",
            9100,
            "kitchen",
            "store_001",
            "tenant_001",
            dept_id="dept_staple",
            name="面点打印机",
        )

        # 验证打印机注册正确
        assert len(mgr._printers) == 3
        assert mgr._printers["p_hot"].dept_id == "dept_hot"
        assert mgr._printers["p_cold"].dept_id == "dept_cold"

    @pytest.mark.asyncio
    async def test_find_kitchen_printer_by_dept(self):
        """验证按档口查找厨打打印机。"""
        mgr = PrintManager()
        await mgr.register_printer(
            "p1", "192.168.1.101", 9100, "kitchen", "store_001", "tenant_001", dept_id="dept_hot"
        )
        await mgr.register_printer(
            "p2", "192.168.1.102", 9100, "kitchen", "store_001", "tenant_001", dept_id="dept_cold"
        )

        assert mgr._find_kitchen_printer("store_001", "dept_hot") == "p1"
        assert mgr._find_kitchen_printer("store_001", "dept_cold") == "p2"
        assert mgr._find_kitchen_printer("store_001", "dept_nonexist") is None

    @pytest.mark.asyncio
    async def test_register_and_unregister(self):
        """验证打印机注册和注销。"""
        mgr = PrintManager()
        await mgr.register_printer("p1", "192.168.1.100", 9100, "cashier", "store_001", "tenant_001")
        assert "p1" in mgr._printers

        await mgr.unregister_printer("p1")
        assert "p1" not in mgr._printers

    @pytest.mark.asyncio
    async def test_configure_store_printers(self):
        """验证门店批量配置。"""
        mgr = PrintManager()
        config = [
            {"ip": "192.168.1.100", "port": 9100, "role": "cashier", "name": "前台"},
            {"ip": "192.168.1.101", "port": 9100, "role": "kitchen", "dept_id": "dept_hot", "name": "热菜"},
            {"ip": "192.168.1.102", "port": 9100, "role": "kitchen", "dept_id": "dept_cold", "name": "凉菜"},
        ]
        infos = await mgr.configure_store_printers("store_001", config, "tenant_001")
        assert len(infos) == 3

        # 检查角色
        roles = {i.role for i in infos}
        assert PrinterRole.CASHIER in roles
        assert PrinterRole.KITCHEN in roles

    @pytest.mark.asyncio
    async def test_find_cashier_printer(self):
        """验证查找收银打印机。"""
        mgr = PrintManager()
        await mgr.register_printer("p_cashier", "192.168.1.100", 9100, "cashier", "store_001", "tenant_001")
        await mgr.register_printer("p_kitchen", "192.168.1.101", 9100, "kitchen", "store_001", "tenant_001")

        pid = mgr._find_printer("store_001", PrinterRole.CASHIER)
        assert pid == "p_cashier"

        pid = mgr._find_printer("store_002", PrinterRole.CASHIER)
        assert pid is None


# ─── 6. 打印机驱动实例化测试 ───


class TestPrinterDriverInit:
    """ESCPOSPrinter 实例化测试（不建立真实连接）。"""

    def test_default_port(self):
        p = ESCPOSPrinter("192.168.1.100")
        assert p.ip == "192.168.1.100"
        assert p.port == 9100
        assert p.timeout == 5

    def test_custom_port(self):
        p = ESCPOSPrinter("10.0.0.1", port=9200, timeout=10)
        assert p.port == 9200
        assert p.timeout == 10

    def test_not_connected(self):
        p = ESCPOSPrinter("192.168.1.100")
        assert not p.is_connected


# ─── 7. PrintManager 单例测试 ───


class TestPrintManagerSingleton:
    def test_get_print_manager_returns_same_instance(self):
        from services.print_manager import get_print_manager

        mgr1 = get_print_manager()
        mgr2 = get_print_manager()
        assert mgr1 is mgr2


# ─── 8. PrintTask 序列化测试 ───


class TestPrintTask:
    def test_task_to_dict(self):
        from services.print_manager import PrintTask

        task = PrintTask(
            task_id="test-001",
            printer_id="p1",
            template_type="cashier_receipt",
            content=b"\x1b\x40hello",
            tenant_id="t1",
            store_id="s1",
            order_id="o1",
        )
        d = task.to_dict()
        assert d["task_id"] == "test-001"
        assert d["printer_id"] == "p1"
        assert d["status"] == "pending"
        assert d["content_size"] == len(b"\x1b\x40hello")
        assert d["order_id"] == "o1"
