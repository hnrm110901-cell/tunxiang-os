"""ESC/POS 打印模板测试套件

覆盖：
1. 58mm 纸宽：每行 GBK 字节宽度 ≤ 32
2. 80mm 纸宽：每行 GBK 字节宽度 ≤ 48
3. 输出以 ESC_INIT (b'\\x1b\\x40') 开头
4. 输出可被 base64 解码回字节
5. 宴席通知单包含所有节的菜品名
6. 中文 GBK 编码不报错
7. 挂账单包含签字栏
8. 空分节宴席通知单不崩溃
9. 称重单包含金额合计行
10. 工具函数单元测试（_gbk_len / _fmt_yuan 等）

无需数据库连接，直接测试纯函数。
"""
import base64
import os
import sys

import pytest

# 将 tx-trade/src 加入路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../src"))


# ─── 共享测试数据 ──────────────────────────────────────────────────────────────

WEIGH_RECORD_BASE = {
    "store_name": "屯象徐记海鲜总店",
    "table_no": "A8",
    "waiter_name": "小李",
    "weigh_time": "2026-04-02 12:30:00",
    "dish_name": "澳洲大龙虾",
    "tank_name": "海鲜区A缸1号",
    "weight_gram": 850.0,
    "unit_price_fen": 38000,
    "price_unit": "500g",
    "amount_fen": 64600,
    "ticket_no": "WGH-2026040200123",
}

BANQUET_SESSION_BASE = {
    "store_name": "屯象徐记海鲜宴会厅",
    "contract_no": "BQ-2026-0001",
    "customer_name": "李总",
    "customer_phone": "13800138000",
    "start_time": "2026-04-05 18:00",
    "table_count": 10,
    "pax_per_table": 12,
    "banquet_type": "商务宴",
    "menu_name": "珍品宴·10800元/桌",
    "special_notes": "请准备红酒杯",
    "printed_by": "前台王小姐",
}

BANQUET_SECTIONS_BASE = [
    {
        "section_type": "cold",
        "section_name": "凉菜",
        "sort_order": 1,
        "dishes": [
            {"dish_name": "夫妻肺片", "quantity": 1, "unit": "份", "notes": ""},
            {"dish_name": "口水鸡", "quantity": 1, "unit": "份", "notes": "微辣"},
        ],
    },
    {
        "section_type": "hot",
        "section_name": "热菜",
        "sort_order": 2,
        "dishes": [
            {"dish_name": "清蒸石斑鱼", "quantity": 1, "unit": "条", "notes": ""},
            {"dish_name": "蒜蓉粉丝扇贝", "quantity": 10, "unit": "个", "notes": ""},
        ],
    },
    {
        "section_type": "soup",
        "section_name": "汤品",
        "sort_order": 3,
        "dishes": [
            {"dish_name": "佛跳墙", "quantity": 1, "unit": "位", "notes": ""},
        ],
    },
]

ORDER_BASE = {
    "store_name": "屯象徐记海鲜总店",
    "order_no": "ORD-2026040200456",
    "table_no": "B12",
    "order_time": "2026-04-02 19:45:00",
    "items": [
        {"item_name": "白灼活虾", "quantity": 2, "unit_price_fen": 8800, "subtotal_fen": 17600},
        {"item_name": "清蒸鲈鱼", "quantity": 1, "unit_price_fen": 18800, "subtotal_fen": 18800},
    ],
    "total_amount_fen": 36400,
    "final_amount_fen": 36400,
    "discount_amount_fen": 0,
    "cashier_name": "收银小张",
}

CREDIT_INFO_BASE = {
    "company_name": "长沙某科技有限公司",
    "company_code": "CST-001",
    "contact_name": "赵经理",
    "contact_phone": "13900139000",
    "credit_limit_fen": 500000,
    "current_balance_fen": 120000,
    "notes": "月结账期30天",
}


# ─── 辅助函数 ──────────────────────────────────────────────────────────────────

def decode_b64_to_bytes(encoded: str) -> bytes:
    """将 base64 字符串解码为字节，可能抛出 binascii.Error"""
    return base64.b64decode(encoded)


def get_text_lines_from_ticket(encoded: str) -> list[str]:
    """从 base64 票据中提取文本行（过滤ESC/POS控制字节后解码GBK）。

    用于宽度和内容验证。此函数按 LF(0x0a) 分割字节流。
    """
    raw = decode_b64_to_bytes(encoded)
    lines_bytes = raw.split(b"\x0a")
    text_lines = []
    for line_b in lines_bytes:
        # 过滤控制字节（0x00-0x1f，排除可见中文GBK范围）
        # 简单策略：直接尝试解码GBK，忽略错误
        try:
            # 过滤掉 ESC/POS 命令字节（以ESC=0x1b、GS=0x1d、FS=0x1c开头的序列）
            # 用 errors="ignore" 处理无法解码的控制字节
            text = line_b.decode("gbk", errors="ignore")
            # 去掉ASCII控制字符
            clean = "".join(c for c in text if ord(c) >= 0x20 or c in "\t")
            text_lines.append(clean)
        except Exception:
            text_lines.append("")
    return text_lines


# ─── 工具函数单元测试 ──────────────────────────────────────────────────────────

class TestUtilFunctions:
    """测试 print_template_service 内部工具函数"""

    def test_gbk_len_ascii(self):
        """ASCII 字符 GBK 长度 = 字符数"""
        from services.print_template_service import _gbk_len
        assert _gbk_len("hello") == 5
        assert _gbk_len("12345") == 5

    def test_gbk_len_chinese(self):
        """中文字符 GBK 长度 = 字符数 × 2"""
        from services.print_template_service import _gbk_len
        assert _gbk_len("屯象") == 4   # 2个中文 = 4字节
        assert _gbk_len("活鲜海鲜") == 8

    def test_gbk_len_mixed(self):
        """中英混合 GBK 长度正确"""
        from services.print_template_service import _gbk_len
        # "A菜" = 1 + 2 = 3字节
        assert _gbk_len("A菜") == 3

    def test_fmt_yuan_integer(self):
        """整数金额格式化：18800分 → 含¥的188.00"""
        from services.print_template_service import _fmt_yuan
        result = _fmt_yuan(18800)
        # \xa5 是 GBK 的 ¥
        assert "188.00" in result

    def test_fmt_yuan_zero(self):
        """零金额格式化：0分 → 0.00"""
        from services.print_template_service import _fmt_yuan
        result = _fmt_yuan(0)
        assert "0.00" in result

    def test_fmt_weight_grams_under_500(self):
        """克重 < 500g 显示为克"""
        from services.print_template_service import _fmt_weight
        assert _fmt_weight(300) == "300g"

    def test_fmt_weight_grams_over_500(self):
        """克重 >= 500g 显示为 kg"""
        from services.print_template_service import _fmt_weight
        result = _fmt_weight(850)
        assert "kg" in result
        assert "0.850" in result

    def test_get_width_58mm(self):
        """58mm 配置返回 32 字符宽度"""
        from services.print_template_service import _get_width
        assert _get_width({"paper_width_mm": 58}) == 32

    def test_get_width_80mm(self):
        """80mm 配置返回 48 字符宽度"""
        from services.print_template_service import _get_width
        assert _get_width({"paper_width_mm": 80}) == 48

    def test_get_width_default(self):
        """无配置时默认 48 字符（80mm）"""
        from services.print_template_service import _get_width
        assert _get_width(None) == 48
        assert _get_width({}) == 48

    def test_two_col_padding(self):
        """两列对齐：左右文本加空格填满指定宽度"""
        from services.print_template_service import _gbk_len, _two_col
        result = _two_col("时间:2026-04-02", "桌号:A8", 48)
        assert _gbk_len(result) >= 48

    def test_line_separator_length(self):
        """分割线长度等于指定宽度"""
        from services.print_template_service import _line
        result = _line(32, "-")
        assert len(result) == 32
        result80 = _line(48, "=")
        assert len(result80) == 48


# ─── 称重单测试 ────────────────────────────────────────────────────────────────

class TestWeighTicket:
    """活鲜称重单 (generate_weigh_ticket) 测试"""

    def test_weigh_ticket_contains_esc_init(self):
        """输出必须以 ESC_INIT (b'\\x1b\\x40') 开头，即 base64 解码后字节流头部

        ESC/POS 打印机初始化指令，所有票据必须以此开头。
        """
        from services.print_template_service import generate_weigh_ticket
        encoded = generate_weigh_ticket(WEIGH_RECORD_BASE)
        raw = decode_b64_to_bytes(encoded)
        assert raw[:2] == b"\x1b\x40", f"输出应以 ESC_INIT 开头，实际头2字节：{raw[:2].hex()}"

    def test_weigh_ticket_base64_decodable(self):
        """输出字符串可被 base64 解码为字节（格式合法性验证）"""
        import binascii

        from services.print_template_service import generate_weigh_ticket
        encoded = generate_weigh_ticket(WEIGH_RECORD_BASE)
        try:
            raw = decode_b64_to_bytes(encoded)
            assert isinstance(raw, bytes)
            assert len(raw) > 0
        except binascii.Error as e:
            pytest.fail(f"base64 解码失败：{e}")

    def test_weigh_ticket_58mm_line_width(self):
        """58mm 纸宽：每个纯文本行 GBK 字节宽度应 ≤ 32

        注意：ESC/POS 控制序列本身不计入行宽，仅验证文本内容部分。
        店名行使用双倍宽，但 ESC 指令控制硬件渲染，字节流中字符本身不超宽。
        """
        from services.print_template_service import _gbk_len, generate_weigh_ticket
        store_config_58mm = {"paper_width_mm": 58}
        encoded = generate_weigh_ticket(WEIGH_RECORD_BASE, store_config_58mm)
        raw = decode_b64_to_bytes(encoded)

        # 按 LF 分割后检查每行文本长度
        lines = raw.split(b"\x0a")
        violations = []
        for i, line_b in enumerate(lines):
            # 过滤控制字节段（ESC/POS 命令通常以 0x1b/0x1d/0x1c 开头）
            # 提取纯文本段（GBK 可见字符范围）
            text_only = bytes(b for b in line_b if b >= 0x20 or b in (0x0d,))
            try:
                text = text_only.decode("gbk", errors="ignore")
                w = _gbk_len(text)
                if w > 32:
                    violations.append(f"第{i+1}行超宽({w}字节): {text[:30]!r}")
            except Exception:
                pass

        assert len(violations) == 0, "58mm模式存在超宽行：\n" + "\n".join(violations)

    def test_weigh_ticket_80mm_line_width(self):
        """80mm 纸宽：每个纯文本行 GBK 字节宽度应 ≤ 48"""
        from services.print_template_service import _gbk_len, generate_weigh_ticket
        store_config_80mm = {"paper_width_mm": 80}
        encoded = generate_weigh_ticket(WEIGH_RECORD_BASE, store_config_80mm)
        raw = decode_b64_to_bytes(encoded)

        lines = raw.split(b"\x0a")
        violations = []
        for i, line_b in enumerate(lines):
            text_only = bytes(b for b in line_b if b >= 0x20)
            try:
                text = text_only.decode("gbk", errors="ignore")
                w = _gbk_len(text)
                if w > 48:
                    violations.append(f"第{i+1}行超宽({w}字节): {text[:40]!r}")
            except Exception:
                pass

        assert len(violations) == 0, "80mm模式存在超宽行：\n" + "\n".join(violations)

    def test_weigh_ticket_contains_dish_name(self):
        """称重单应包含菜品名称（GBK编码后可在字节流中找到）"""
        from services.print_template_service import generate_weigh_ticket
        encoded = generate_weigh_ticket(WEIGH_RECORD_BASE)
        raw = decode_b64_to_bytes(encoded)
        dish_name_gbk = "澳洲大龙虾".encode("gbk")
        assert dish_name_gbk in raw, "称重单字节流中未找到菜品名称"

    def test_weigh_ticket_contains_amount(self):
        """称重单应包含金额信息（646.00 元）"""
        from services.print_template_service import generate_weigh_ticket
        encoded = generate_weigh_ticket(WEIGH_RECORD_BASE)
        raw = decode_b64_to_bytes(encoded)
        # amount_fen=64600 → 646.00
        amount_str = "646.00".encode("gbk")
        assert amount_str in raw, "称重单中未找到金额"

    def test_weigh_ticket_contains_signature_line(self):
        """称重单应包含顾客签字栏

        源码第242行：'顾客确认签字：'
        """
        from services.print_template_service import generate_weigh_ticket
        encoded = generate_weigh_ticket(WEIGH_RECORD_BASE)
        raw = decode_b64_to_bytes(encoded)
        sig_text = "顾客确认签字".encode("gbk")
        assert sig_text in raw, "称重单中未找到签字栏"

    def test_weigh_ticket_default_no_store_config(self):
        """不传 store_config 时不崩溃，默认使用80mm宽度"""
        from services.print_template_service import generate_weigh_ticket
        # 不传 store_config
        encoded = generate_weigh_ticket(WEIGH_RECORD_BASE)
        raw = decode_b64_to_bytes(encoded)
        assert len(raw) > 100


# ─── 宴席通知单测试 ────────────────────────────────────────────────────────────

class TestBanquetNotice:
    """宴席通知单 (generate_banquet_notice) 测试"""

    def test_banquet_notice_base64_decodable(self):
        """宴席通知单输出可被 base64 解码"""
        from services.print_template_service import generate_banquet_notice
        encoded = generate_banquet_notice(BANQUET_SESSION_BASE, BANQUET_SECTIONS_BASE)
        raw = decode_b64_to_bytes(encoded)
        assert isinstance(raw, bytes) and len(raw) > 0

    def test_banquet_notice_contains_esc_init(self):
        """宴席通知单以 ESC_INIT 开头"""
        from services.print_template_service import generate_banquet_notice
        encoded = generate_banquet_notice(BANQUET_SESSION_BASE, BANQUET_SECTIONS_BASE)
        raw = decode_b64_to_bytes(encoded)
        assert raw[:2] == b"\x1b\x40"

    def test_banquet_notice_sections_contain_all_dish_names(self):
        """宴席通知单应包含所有分节菜品名（GBK编码字节流验证）

        验证菜品：夫妻肺片、口水鸡、清蒸石斑鱼、蒜蓉粉丝扇贝、佛跳墙
        """
        from services.print_template_service import generate_banquet_notice
        encoded = generate_banquet_notice(BANQUET_SESSION_BASE, BANQUET_SECTIONS_BASE)
        raw = decode_b64_to_bytes(encoded)

        expected_dishes = ["夫妻肺片", "口水鸡", "清蒸石斑鱼", "蒜蓉粉丝扇贝", "佛跳墙"]
        for dish_name in expected_dishes:
            dish_gbk = dish_name.encode("gbk")
            assert dish_gbk in raw, f"宴席通知单中未找到菜品：{dish_name}"

    def test_banquet_notice_utf8_chinese_gbk_encoding_no_error(self):
        """中文字段使用 GBK 编码不报错（常见中文字符的 GBK 兼容性验证）

        测试包含特殊中文的场景（如：繁体字、生僻字用 errors='replace' 替代）。
        """
        from services.print_template_service import generate_banquet_notice
        session_with_complex_chinese = {
            **BANQUET_SESSION_BASE,
            "customer_name": "谢鑫炜（主办）",
            "special_notes": "贵宾专属·珍品宴席",
            "menu_name": "至尊海鲜宴·¥12800/桌",
        }
        # 不抛出异常即通过
        try:
            encoded = generate_banquet_notice(
                session_with_complex_chinese,
                BANQUET_SECTIONS_BASE,
            )
            raw = decode_b64_to_bytes(encoded)
            assert len(raw) > 0
        except UnicodeEncodeError as e:
            pytest.fail(f"GBK 编码中文时抛出异常（应使用 errors='replace'）: {e}")

    def test_banquet_notice_section_order_sorted_by_sort_order(self):
        """宴席通知单各节应按 sort_order 排序输出

        验证凉菜（sort_order=1）出现在热菜（sort_order=2）之前。
        """
        from services.print_template_service import generate_banquet_notice
        encoded = generate_banquet_notice(BANQUET_SESSION_BASE, BANQUET_SECTIONS_BASE)
        raw = decode_b64_to_bytes(encoded)

        cold_pos = raw.find("凉菜".encode("gbk"))
        hot_pos = raw.find("热菜".encode("gbk"))
        assert cold_pos < hot_pos, f"凉菜(pos={cold_pos}) 应排在热菜(pos={hot_pos}) 之前"

    def test_empty_sections_banquet_no_crash(self):
        """空分节（dishes=[]）的宴席通知单不崩溃

        边界测试：menu_sections 为空列表时应正常生成票据。
        """
        from services.print_template_service import generate_banquet_notice
        try:
            encoded = generate_banquet_notice(BANQUET_SESSION_BASE, [])
            raw = decode_b64_to_bytes(encoded)
            assert len(raw) > 50
        except Exception as e:
            pytest.fail(f"空分节列表导致崩溃：{e}")

    def test_empty_dishes_in_section_no_crash(self):
        """分节存在但 dishes=[] 时不崩溃"""
        from services.print_template_service import generate_banquet_notice
        sections_with_empty = [
            {
                "section_type": "cold",
                "section_name": "凉菜",
                "sort_order": 1,
                "dishes": [],  # 空菜品列表
            }
        ]
        try:
            encoded = generate_banquet_notice(BANQUET_SESSION_BASE, sections_with_empty)
            raw = decode_b64_to_bytes(encoded)
            assert len(raw) > 50
        except Exception as e:
            pytest.fail(f"空菜品列表分节导致崩溃：{e}")

    def test_banquet_notice_contains_contract_no(self):
        """宴席通知单应包含合同号"""
        from services.print_template_service import generate_banquet_notice
        encoded = generate_banquet_notice(BANQUET_SESSION_BASE, BANQUET_SECTIONS_BASE)
        raw = decode_b64_to_bytes(encoded)
        contract_gbk = "BQ-2026-0001".encode("gbk")  # ASCII，GBK与UTF8一致
        assert contract_gbk in raw


# ─── 挂账单测试 ────────────────────────────────────────────────────────────────

class TestCreditAccountTicket:
    """企业挂账单 (generate_credit_account_ticket) 测试"""

    def test_credit_ticket_base64_decodable(self):
        """挂账单输出可被 base64 解码"""
        from services.print_template_service import generate_credit_account_ticket
        encoded = generate_credit_account_ticket(ORDER_BASE, CREDIT_INFO_BASE)
        raw = decode_b64_to_bytes(encoded)
        assert isinstance(raw, bytes) and len(raw) > 0

    def test_credit_ticket_contains_esc_init(self):
        """挂账单以 ESC_INIT 开头"""
        from services.print_template_service import generate_credit_account_ticket
        encoded = generate_credit_account_ticket(ORDER_BASE, CREDIT_INFO_BASE)
        raw = decode_b64_to_bytes(encoded)
        assert raw[:2] == b"\x1b\x40"

    def test_credit_ticket_structure_contains_signature(self):
        """挂账单应包含签字栏（含"签字"两字）

        源码第549行：'（签字）                          （日期）'
        """
        from services.print_template_service import generate_credit_account_ticket
        encoded = generate_credit_account_ticket(ORDER_BASE, CREDIT_INFO_BASE)
        raw = decode_b64_to_bytes(encoded)
        sig_gbk = "签字".encode("gbk")
        assert sig_gbk in raw, "挂账单中未找到签字栏"

    def test_credit_ticket_contains_company_name(self):
        """挂账单应包含挂账单位名称"""
        from services.print_template_service import generate_credit_account_ticket
        encoded = generate_credit_account_ticket(ORDER_BASE, CREDIT_INFO_BASE)
        raw = decode_b64_to_bytes(encoded)
        company_gbk = "长沙某科技有限公司".encode("gbk")
        assert company_gbk in raw

    def test_credit_ticket_contains_final_amount(self):
        """挂账单应包含挂账金额（364.00元）"""
        from services.print_template_service import generate_credit_account_ticket
        encoded = generate_credit_account_ticket(ORDER_BASE, CREDIT_INFO_BASE)
        raw = decode_b64_to_bytes(encoded)
        amount_str = "364.00".encode("gbk")
        assert amount_str in raw

    def test_credit_ticket_58mm_width(self):
        """58mm 纸宽挂账单每行不超宽"""
        from services.print_template_service import _gbk_len, generate_credit_account_ticket
        store_config_58mm = {"paper_width_mm": 58}
        encoded = generate_credit_account_ticket(ORDER_BASE, CREDIT_INFO_BASE, store_config_58mm)
        raw = decode_b64_to_bytes(encoded)

        lines = raw.split(b"\x0a")
        violations = []
        for i, line_b in enumerate(lines):
            text_only = bytes(b for b in line_b if b >= 0x20)
            try:
                text = text_only.decode("gbk", errors="ignore")
                w = _gbk_len(text)
                if w > 32:
                    violations.append(f"第{i+1}行超宽({w}): {text[:30]!r}")
            except Exception:
                pass
        assert len(violations) == 0, "\n".join(violations)

    def test_credit_ticket_no_items_no_crash(self):
        """挂账单 items 为空列表时不崩溃"""
        from services.print_template_service import generate_credit_account_ticket
        order_no_items = {**ORDER_BASE, "items": []}
        try:
            encoded = generate_credit_account_ticket(order_no_items, CREDIT_INFO_BASE)
            raw = decode_b64_to_bytes(encoded)
            assert len(raw) > 50
        except Exception as e:
            pytest.fail(f"空菜品列表导致挂账单崩溃：{e}")

    def test_credit_ticket_balance_calculation(self):
        """挂账单余额计算：原余额 + 本次挂账金额 = 新余额

        原挂账余额：120000分（1200元）
        本次挂账：36400分（364元）
        新余额：156400分（1564.00元）
        """
        from services.print_template_service import generate_credit_account_ticket
        encoded = generate_credit_account_ticket(ORDER_BASE, CREDIT_INFO_BASE)
        raw = decode_b64_to_bytes(encoded)
        # 1200 + 364 = 1564
        new_balance_str = "1564.00".encode("gbk")
        assert new_balance_str in raw, "挂账单中未找到正确的新余额"
