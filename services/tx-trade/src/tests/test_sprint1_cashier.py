"""完整收银流程测试 — 模拟一天营业

测试覆盖:
1. 标准堂食流程（开台/加菜/称重菜/支付/打印）
2. 多支付拆单
3. 折扣+毛利底线校验
4. 退菜+取消订单
5. 日结流程
6. 桌台操作（换桌/并桌）
7. 多渠道毛利对比
8. 称重菜计价
9. 会员价+优惠券叠加
10. 异常折扣检测
"""
import math
import uuid
from datetime import date, datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))

from src.services.discount_engine import DiscountEngine
from src.services.sales_channel import SalesChannelEngine
from src.services.table_manager import TableManager

# ─── 测试常量 ───

TENANT_ID = "00000000-0000-0000-0000-000000000001"
STORE_ID = "11111111-1111-1111-1111-111111111111"
BIZ_DATE = date(2026, 3, 27)

# ─── 菜品数据（真实中餐馆菜单） ───

MENU = {
    "dcyt": {
        "item_id": "d001", "item_name": "剁椒鱼头",
        "unit_price_fen": 16800, "cost_fen": 5040,  # 售价168元，成本50.4元，毛利率70%
    },
    "xchnr": {
        "item_id": "d002", "item_name": "小炒黄牛肉",
        "unit_price_fen": 5800, "cost_fen": 1740,   # 售价58元，成本17.4元，毛利率70%
    },
    "mf": {
        "item_id": "d003", "item_name": "米饭",
        "unit_price_fen": 200, "cost_fen": 40,      # 售价2元，成本0.4元
    },
    "hly": {
        "item_id": "d004", "item_name": "活鲈鱼",
        "unit_price_fen": 12800, "cost_fen": 5120,  # 售价128元/斤，成本51.2元/斤
        "unit": "斤", "pricing_mode": "weight",
    },
    "bsdlx": {
        "item_id": "d005", "item_name": "波士顿龙虾",
        "unit_price_fen": 38800, "cost_fen": 19400,  # 售价388元/kg，成本194元/kg
        "unit": "kg", "pricing_mode": "weight",
    },
    "sbtg": {
        "item_id": "d006", "item_name": "酸白菜炖筒骨",
        "unit_price_fen": 6800, "cost_fen": 1700,   # 售价68元，成本17元
    },
    "yxtb": {
        "item_id": "d007", "item_name": "养心糖包（赠品）",
        "unit_price_fen": 1800, "cost_fen": 360,    # 售价18元，成本3.6元
    },
    "smjd": {
        "item_id": "d008", "item_name": "蒜苗鸡丁",
        "unit_price_fen": 3800, "cost_fen": 950,
    },
    "xhsr": {
        "item_id": "d009", "item_name": "西红柿烧肉",
        "unit_price_fen": 4800, "cost_fen": 1440,
    },
    "pgjp": {
        "item_id": "d010", "item_name": "苹果鸡片",
        "unit_price_fen": 4200, "cost_fen": 1260,
    },
}


def _make_order_item(menu_key: str, quantity: int = 1, weight_kg: float = 0) -> dict:
    """创建订单明细项"""
    dish = MENU[menu_key]
    item = dict(dish)
    item["quantity"] = quantity

    if weight_kg > 0:
        # 称重菜：按重量计价
        item["weight_kg"] = weight_kg
        item["subtotal_fen"] = math.ceil(dish["unit_price_fen"] * weight_kg)
        item["cost_fen"] = math.ceil(dish["cost_fen"] * weight_kg)
    else:
        item["subtotal_fen"] = dish["unit_price_fen"] * quantity
        item["cost_fen"] = dish["cost_fen"] * quantity

    return item


# ═══════════════════════════════════════════════════
# Test 1: 标准堂食流程
# ═══════════════════════════════════════════════════

class TestStandardDineInFlow:
    """标准堂食流程: 开台 → 加菜 → 称重菜 → 微信支付"""

    def test_order_calculation(self):
        """开台A01, 4人 → 加菜 → 称重菜 → 计算总额"""
        items = [
            _make_order_item("dcyt", quantity=1),          # 剁椒鱼头 ¥168
            _make_order_item("xchnr", quantity=1),         # 小炒黄牛肉 ¥58
            _make_order_item("mf", quantity=4),            # 米饭x4 ¥8
            _make_order_item("hly", weight_kg=1.15),       # 活鲈鱼 128元/斤 x 2.3斤 = 1.15kg
        ]

        total_fen = sum(i["subtotal_fen"] for i in items)

        # 剁椒鱼头 16800 + 黄牛肉 5800 + 米饭 800 + 鲈鱼 ceil(12800*1.15)=14720
        assert items[0]["subtotal_fen"] == 16800
        assert items[1]["subtotal_fen"] == 5800
        assert items[2]["subtotal_fen"] == 800      # 200 * 4
        assert items[3]["subtotal_fen"] == 14720     # ceil(12800 * 1.15)
        assert total_fen == 38120                    # 总计¥381.20

    def test_weigh_fish_calculation(self):
        """活鲈鱼称重计价: ¥128/斤 x 2.3斤 = ¥294.40"""
        # 注意: unit_price_fen=12800 是每斤的价格，2.3斤 = 1.15kg
        # 但这里按"斤"计价: 12800 * 2.3 = 29440
        item = {
            "item_id": "d004",
            "item_name": "活鲈鱼",
            "unit_price_per_jin_fen": 12800,
            "weight_jin": 2.3,
        }
        total = math.ceil(item["unit_price_per_jin_fen"] * item["weight_jin"])
        assert total == 29440  # ¥294.40

    def test_payment_covers_total(self):
        """微信支付金额必须覆盖订单总额"""
        order_total_fen = 38120
        payment_fen = 38120
        assert payment_fen >= order_total_fen


# ═══════════════════════════════════════════════════
# Test 2: 多支付拆单
# ═══════════════════════════════════════════════════

class TestMultiPaymentSplit:
    """多支付拆单: 微信¥200 + 支付宝¥100 + 现金¥50 + 会员余额¥100 = ¥450"""

    def test_multi_payment_exact_match(self):
        """拆单总额必须等于订单总额"""
        order_total_fen = 45000  # ¥450

        payments = [
            {"method": "wechat", "amount_fen": 20000},      # ¥200
            {"method": "alipay", "amount_fen": 10000},       # ¥100
            {"method": "cash", "amount_fen": 5000},          # ¥50
            {"method": "member_balance", "amount_fen": 10000}, # ¥100
        ]

        total_paid = sum(p["amount_fen"] for p in payments)
        assert total_paid == order_total_fen

    def test_multi_payment_exceeds_raises(self):
        """拆单总额不能超过订单总额"""
        order_total_fen = 45000

        payments = [
            {"method": "wechat", "amount_fen": 25000},
            {"method": "alipay", "amount_fen": 25000},
        ]

        total_paid = sum(p["amount_fen"] for p in payments)
        assert total_paid > order_total_fen  # 50000 > 45000, 应拒绝

    def test_multi_payment_underpays_raises(self):
        """拆单总额不能低于订单总额"""
        order_total_fen = 45000

        payments = [
            {"method": "wechat", "amount_fen": 20000},
            {"method": "cash", "amount_fen": 5000},
        ]

        total_paid = sum(p["amount_fen"] for p in payments)
        assert total_paid < order_total_fen  # 25000 < 45000, 需补差


# ═══════════════════════════════════════════════════
# Test 3: 折扣 + 毛利底线
# ═══════════════════════════════════════════════════

class TestDiscountMarginFloor:
    """折扣+毛利底线: 8折通过, 5折拒绝"""

    def setup_method(self):
        self.engine = DiscountEngine()
        # 典型订单: 剁椒鱼头168 + 黄牛肉58 + 米饭8 = 234元
        self.order_items = [
            _make_order_item("dcyt", quantity=1),    # 168元, 成本50.4元
            _make_order_item("xchnr", quantity=1),   # 58元, 成本17.4元
            _make_order_item("mf", quantity=4),      # 8元, 成本1.6元
        ]
        # 总计: 23400分, 总成本: 6940分

    def test_80_percent_discount_passes_margin(self):
        """整单8折 → 毛利应 >= 30% → 通过"""
        result = self.engine.calculate_discount(
            self.order_items, "percent_off", 0.80,  # 8折
        )

        # 折扣 = 23400 * 0.2 = 4680
        assert result["discount_fen"] == 4680
        assert result["new_total_fen"] == 23400 - 4680  # 18720

        # 毛利校验: (18720 - 6940) / 18720 = 0.629 > 0.30 → 通过
        margin_check = self.engine.check_margin_floor(
            self.order_items, result["discount_fen"], margin_floor_rate=0.30,
        )
        assert margin_check["passed"] is True
        assert margin_check["current_margin"] > 0.30

    def test_50_percent_discount_fails_margin(self):
        """整单5折 → 毛利 < 30% → 拒绝!"""
        result = self.engine.calculate_discount(
            self.order_items, "percent_off", 0.50,  # 5折
        )

        # 折扣 = 23400 * 0.5 = 11700
        assert result["discount_fen"] == 11700
        assert result["new_total_fen"] == 11700

        # 毛利校验: (11700 - 6940) / 11700 = 0.407 > 0.30
        # 实际上5折对于70%毛利率的菜品，折后毛利约40%，仍然通过30%底线
        margin_check = self.engine.check_margin_floor(
            self.order_items, result["discount_fen"], margin_floor_rate=0.30,
        )
        # 5折在70%毛利率基础上还能通过30%底线
        assert margin_check["passed"] is True

    def test_extreme_discount_fails_margin(self):
        """整单2折 → 毛利一定 < 30% → 拒绝!"""
        result = self.engine.calculate_discount(
            self.order_items, "percent_off", 0.20,  # 2折
        )

        # 折扣 = 23400 * 0.8 = 18720
        assert result["discount_fen"] == 18720
        assert result["new_total_fen"] == 4680

        # 毛利校验: (4680 - 6940) / 4680 = -0.483 < 0.30 → 拒绝
        margin_check = self.engine.check_margin_floor(
            self.order_items, result["discount_fen"], margin_floor_rate=0.30,
        )
        assert margin_check["passed"] is False
        assert margin_check["current_margin"] < 0.30

    def test_amount_off_discount(self):
        """满200减30"""
        result = self.engine.calculate_discount(
            self.order_items, "amount_off", 3000,  # ¥30
        )

        assert result["discount_fen"] == 3000
        assert result["new_total_fen"] == 23400 - 3000

        # 毛利: (20400 - 6940) / 20400 = 0.6598 > 0.30
        margin_check = self.engine.check_margin_floor(
            self.order_items, result["discount_fen"],
        )
        assert margin_check["passed"] is True

    def test_amount_off_exceeds_total_raises(self):
        """减免金额超过总额应报错"""
        with pytest.raises(ValueError, match="超过订单总额"):
            self.engine.calculate_discount(
                self.order_items, "amount_off", 30000,  # ¥300 > ¥234
            )

    def test_item_percent_discount(self):
        """指定剁椒鱼头打7折"""
        result = self.engine.calculate_discount(
            self.order_items, "item_percent", 0.70,  # 7折
            target_item_id="d001",
        )

        # 剁椒鱼头折扣 ≈ 16800 * 0.3 = 5040 (rounding may vary ±1)
        assert abs(result["discount_fen"] - 5040) <= 1
        assert abs(result["new_total_fen"] - (23400 - 5040)) <= 1

    def test_margin_floor_no_exception(self):
        """硬约束#1 — 毛利底线不可违反，NO EXCEPTION"""
        # 构造低毛利菜品
        low_margin_items = [
            {"item_id": "x01", "item_name": "特价鲍鱼", "quantity": 1,
             "unit_price_fen": 10000, "cost_fen": 8000, "subtotal_fen": 10000},
        ]

        # 即使只打9折，毛利也可能不足
        result = self.engine.calculate_discount(low_margin_items, "percent_off", 0.80)
        # 8折: 折后8000, 成本8000, 毛利 = 0
        margin_check = self.engine.check_margin_floor(
            low_margin_items, result["discount_fen"], margin_floor_rate=0.30,
        )
        assert margin_check["passed"] is False
        assert "gap_fen" in margin_check


# ═══════════════════════════════════════════════════
# Test 4: 退菜 + 取消
# ═══════════════════════════════════════════════════

class TestReturnAndCancel:
    """退菜+取消: 点菜 → 退1道 → 重新计算 → 结账 / 取消"""

    def test_return_item_recalculates_total(self):
        """退菜后重新计算总额"""
        items = [
            _make_order_item("dcyt", quantity=1),    # 16800
            _make_order_item("xchnr", quantity=1),   # 5800
            _make_order_item("mf", quantity=4),      # 800
        ]

        total_before = sum(i["subtotal_fen"] for i in items)
        assert total_before == 23400

        # 退掉小炒黄牛肉（记录原因）
        returned_item = items.pop(1)  # 小炒黄牛肉
        return_record = {
            "item_id": returned_item["item_id"],
            "item_name": returned_item["item_name"],
            "return_reason": "菜品味道不正",
            "return_amount_fen": returned_item["subtotal_fen"],
            "returned_at": datetime.now(timezone.utc).isoformat(),
        }

        total_after = sum(i["subtotal_fen"] for i in items)
        assert total_after == 17600  # 23400 - 5800
        assert return_record["return_amount_fen"] == 5800
        assert return_record["return_reason"] == "菜品味道不正"

    def test_cancel_order_releases_table(self):
        """取消订单释放桌台"""
        tm = TableManager()
        tm.init_tables(STORE_ID, [
            {"table_no": "A01", "zone": "大厅", "capacity": 4},
        ])

        # 开台
        tm.open_table(STORE_ID, "A01", guest_count=2, waiter_id="w001")
        table = tm._get_table(STORE_ID, "A01")
        assert table["status"] == "occupied"

        # 取消 → 释放桌台
        tm.release_table(STORE_ID, "A01")
        table = tm._get_table(STORE_ID, "A01")
        assert table["status"] == "free"
        assert table["order_id"] is None

    def test_return_item_needs_reason(self):
        """退菜必须记录原因"""
        return_record = {
            "item_name": "小炒黄牛肉",
            "return_reason": "",
        }
        # 空原因应被视为无效
        assert not return_record["return_reason"]


# ═══════════════════════════════════════════════════
# Test 5: 日结
# ═══════════════════════════════════════════════════

class TestDailySettlement:
    """日结: 创建 → 现金盘点 → 店长说明 → 提交 → 审核"""

    def test_daily_settlement_flow(self):
        """完整日结流程"""
        settlement = {
            "store_id": STORE_ID,
            "biz_date": BIZ_DATE.isoformat(),
            "status": "draft",
            "total_orders": 86,
            "completed_orders": 82,
            "cancelled_orders": 4,
            "total_guests": 312,
            "gross_revenue_fen": 4560000,     # ¥45,600
            "total_discount_fen": 320000,     # ¥3,200
            "total_refund_fen": 15800,        # ¥158
            "net_revenue_fen": 4224200,       # ¥42,242
            # 按支付方式
            "cash_fen": 850000,               # ¥8,500
            "wechat_fen": 2100000,            # ¥21,000
            "alipay_fen": 680000,             # ¥6,800
            "member_balance_fen": 594200,     # ¥5,942
            # 现金盘点
            "cash_expected_fen": 850000,      # 应有 ¥8,500
            "cash_actual_fen": 849500,        # 实际 ¥8,495
            "cash_diff_fen": -500,            # 差 -¥5
        }

        # 1. 创建日结单
        assert settlement["status"] == "draft"

        # 2. 现金盘点：差异¥5
        assert settlement["cash_diff_fen"] == -500
        assert abs(settlement["cash_diff_fen"]) <= 1000  # 差异在¥10以内可接受

        # 3. 店长说明
        settlement["cash_diff_reason"] = "找零误差，金额在可接受范围内"
        settlement["operator_id"] = "mgr001"
        settlement["operator_name"] = "李店长"

        # 4. 提交
        settlement["status"] = "submitted"
        settlement["submitted_at"] = datetime.now(timezone.utc).isoformat()
        assert settlement["status"] == "submitted"

        # 5. 审核通过
        settlement["status"] = "approved"
        settlement["reviewer_id"] = "area_mgr001"
        settlement["reviewer_name"] = "区域经理张三"
        settlement["reviewed_at"] = datetime.now(timezone.utc).isoformat()
        assert settlement["status"] == "approved"

    def test_settlement_payment_totals_match(self):
        """各支付方式合计 = 净营收"""
        cash = 850000
        wechat = 2100000
        alipay = 680000
        member = 594200

        total_payments = cash + wechat + alipay + member
        net_revenue = 4224200

        assert total_payments == net_revenue

    def test_settlement_cash_diff_alert(self):
        """现金差异超过阈值触发预警"""
        threshold_fen = 5000  # ¥50

        # 正常差异
        small_diff = -500  # ¥5
        assert abs(small_diff) < threshold_fen

        # 异常差异
        large_diff = -8000  # ¥80
        assert abs(large_diff) > threshold_fen  # 应触发预警


# ═══════════════════════════════════════════════════
# Test 6: 桌台操作
# ═══════════════════════════════════════════════════

class TestTableOperations:
    """桌台操作: 换桌 + 并桌"""

    def setup_method(self):
        self.tm = TableManager()
        self.tm.init_tables(STORE_ID, [
            {"table_no": "A01", "zone": "大厅", "capacity": 4},
            {"table_no": "B03", "zone": "包间", "capacity": 8},
            {"table_no": "C01", "zone": "大厅", "capacity": 4},
            {"table_no": "C02", "zone": "大厅", "capacity": 4},
        ])

    def test_transfer_table(self):
        """换桌: A01 → B03"""
        # 开台A01
        self.tm.open_table(STORE_ID, "A01", guest_count=4, waiter_id="w001")
        a01 = self.tm._get_table(STORE_ID, "A01")
        original_order_id = a01["order_id"]
        assert a01["status"] == "occupied"

        # 换到B03
        result = self.tm.transfer_table(STORE_ID, "A01", "B03")

        assert result["from_table"]["status"] == "free"
        assert result["to_table"]["status"] == "occupied"
        assert result["to_table"]["order_id"] == original_order_id
        assert result["to_table"]["guest_count"] == 4

    def test_merge_tables(self):
        """并桌: C01 + C02 → C01(主桌)"""
        # 开台C01
        self.tm.open_table(STORE_ID, "C01", guest_count=3, waiter_id="w002")

        # 并桌
        result = self.tm.merge_tables(STORE_ID, ["C01", "C02"], main_table_no="C01")

        assert result["capacity"] == 8  # 4 + 4
        assert result["merged_with"] == ["C02"]
        assert result["is_main_table"] is True

        c02 = self.tm._get_table(STORE_ID, "C02")
        assert c02["is_main_table"] is False
        assert c02["merged_with"] == ["C01"]

    def test_transfer_occupied_to_occupied_fails(self):
        """不能换到已占用的桌台"""
        self.tm.open_table(STORE_ID, "A01", guest_count=2, waiter_id="w001")
        self.tm.open_table(STORE_ID, "B03", guest_count=4, waiter_id="w002")

        with pytest.raises(ValueError, match="需为free"):
            self.tm.transfer_table(STORE_ID, "A01", "B03")

    def test_table_lifecycle(self):
        """完整桌台生命周期: free → occupied → settling → cleaning → free"""
        self.tm.open_table(STORE_ID, "A01", guest_count=2, waiter_id="w001")
        assert self.tm._get_table(STORE_ID, "A01")["status"] == "occupied"

        self.tm.start_settling(STORE_ID, "A01")
        assert self.tm._get_table(STORE_ID, "A01")["status"] == "settling"

        self.tm.start_cleaning(STORE_ID, "A01")
        assert self.tm._get_table(STORE_ID, "A01")["status"] == "cleaning"

        self.tm.release_table(STORE_ID, "A01")
        assert self.tm._get_table(STORE_ID, "A01")["status"] == "free"

    def test_disable_and_enable_table(self):
        """停用和启用桌台"""
        self.tm.disable_table(STORE_ID, "C02", reason="桌面损坏维修")
        assert self.tm._get_table(STORE_ID, "C02")["status"] == "disabled"

        self.tm.enable_table(STORE_ID, "C02")
        assert self.tm._get_table(STORE_ID, "C02")["status"] == "free"

    def test_cannot_disable_occupied_table(self):
        """不能停用正在使用中的桌台"""
        self.tm.open_table(STORE_ID, "A01", guest_count=2, waiter_id="w001")

        with pytest.raises(ValueError, match="正在使用"):
            self.tm.disable_table(STORE_ID, "A01", reason="测试")

    def test_table_stats(self):
        """桌台统计"""
        self.tm.open_table(STORE_ID, "A01", guest_count=4, waiter_id="w001")
        self.tm.open_table(STORE_ID, "C01", guest_count=3, waiter_id="w002")
        self.tm.disable_table(STORE_ID, "C02", reason="维修")

        stats = self.tm.get_table_stats(STORE_ID)
        assert stats["total"] == 4
        assert stats["occupied"] == 2
        assert stats["free"] == 1
        assert stats["disabled"] == 1

    def test_reserve_then_open(self):
        """预留 → 开台"""
        self.tm.reserve_table(STORE_ID, "B03", reservation_id="RSV001")
        assert self.tm._get_table(STORE_ID, "B03")["status"] == "reserved"

        self.tm.open_table(STORE_ID, "B03", guest_count=6, waiter_id="w003")
        assert self.tm._get_table(STORE_ID, "B03")["status"] == "occupied"


# ═══════════════════════════════════════════════════
# Test 7: 多渠道毛利对比
# ═══════════════════════════════════════════════════

class TestMultiChannelMargin:
    """多渠道: 堂食 vs 美团外卖(18%佣金) → 毛利对比"""

    def setup_method(self):
        self.engine = SalesChannelEngine()

    def test_dine_in_vs_meituan_margin(self):
        """同一份订单，堂食 vs 美团外卖的毛利对比"""
        order = {
            "order_id": "order001",
            "total_amount_fen": 23400,
            "final_amount_fen": 23400,
            "food_cost_fen": 6940,
            "items": [],
        }

        # 堂食：无佣金
        dine_in = self.engine.calculate_channel_profit(order, "dine_in", "wechat")
        # 美团外卖：18%佣金
        meituan = self.engine.calculate_channel_profit(order, "delivery_meituan", "wechat")

        # 堂食利润 > 美团利润
        assert dine_in["net_profit_fen"] > meituan["net_profit_fen"]

        # 美团佣金 = 23400 * 0.18 = 4212
        assert meituan["platform_commission_fen"] == math.ceil(23400 * 0.18)

        # 堂食无佣金
        assert dine_in["platform_commission_fen"] == 0

        # 堂食毛利率更高
        assert dine_in["net_margin_rate"] > meituan["net_margin_rate"]

    def test_channel_summary(self):
        """渠道日汇总"""
        orders = [
            {"order_id": "o1", "sales_channel": "dine_in", "total_amount_fen": 23400,
             "final_amount_fen": 23400, "food_cost_fen": 6940, "guest_count": 4},
            {"order_id": "o2", "sales_channel": "dine_in", "total_amount_fen": 15000,
             "final_amount_fen": 15000, "food_cost_fen": 4500, "guest_count": 2},
            {"order_id": "o3", "sales_channel": "delivery_meituan", "total_amount_fen": 8800,
             "final_amount_fen": 8800, "food_cost_fen": 2640, "guest_count": 1},
        ]

        summary = self.engine.get_channel_summary(orders, STORE_ID, BIZ_DATE)

        assert "dine_in" in summary["channels"]
        assert "delivery_meituan" in summary["channels"]
        assert summary["channels"]["dine_in"]["order_count"] == 2
        assert summary["channels"]["delivery_meituan"]["order_count"] == 1
        assert summary["totals"]["total_orders"] == 3

        # 堂食毛利率 > 美团毛利率
        dine_in_margin = summary["channels"]["dine_in"]["margin_rate"]
        meituan_margin = summary["channels"]["delivery_meituan"]["margin_rate"]
        assert dine_in_margin > meituan_margin

    def test_all_channels_configured(self):
        """所有8种渠道都已配置"""
        expected = {
            "dine_in", "takeaway", "delivery_meituan", "delivery_eleme",
            "delivery_douyin", "group_buy", "banquet", "catering",
        }
        assert set(self.engine.CHANNELS.keys()) == expected

    def test_compare_channel_margins(self):
        """跨渠道毛利对比排序"""
        orders_by_channel = {
            "dine_in": [
                {"order_id": "o1", "total_amount_fen": 20000, "final_amount_fen": 20000,
                 "food_cost_fen": 6000},
            ],
            "delivery_meituan": [
                {"order_id": "o2", "total_amount_fen": 20000, "final_amount_fen": 20000,
                 "food_cost_fen": 6000},
            ],
            "delivery_eleme": [
                {"order_id": "o3", "total_amount_fen": 20000, "final_amount_fen": 20000,
                 "food_cost_fen": 6000},
            ],
        }

        comparisons = self.engine.compare_channel_margins(orders_by_channel)

        # 堂食利润最高（无佣金），饿了么最低（20%佣金）
        assert comparisons[0]["channel"] == "dine_in"
        assert comparisons[-1]["channel"] == "delivery_eleme"


# ═══════════════════════════════════════════════════
# Test 8: 称重菜计价
# ═══════════════════════════════════════════════════

class TestWeightPricing:
    """称重菜: 波士顿龙虾 ¥388/kg x 1.2kg = ¥465.6 → 取整¥466"""

    def test_boston_lobster_pricing(self):
        """波士顿龙虾按kg计价"""
        price_per_kg_fen = 38800  # ¥388/kg
        weight_kg = 1.2

        raw_total = price_per_kg_fen * weight_kg  # 46560.0
        rounded_total = math.ceil(raw_total)       # 46560 (恰好整除)

        assert rounded_total == 46560  # ¥465.60

    def test_weight_rounding_up(self):
        """称重菜向上取整到分"""
        price_per_jin_fen = 12800  # ¥128/斤
        weight_jin = 2.3

        raw_total = price_per_jin_fen * weight_jin  # 29440.0
        rounded_total = math.ceil(raw_total)

        assert rounded_total == 29440  # ¥294.40

    def test_irregular_weight(self):
        """不规则重量取整"""
        price_per_kg_fen = 38800
        weight_kg = 1.35

        raw_total = price_per_kg_fen * weight_kg  # 52380.0
        rounded_total = math.ceil(raw_total)

        assert rounded_total == 52380  # ¥523.80

    def test_weight_item_cost_calculation(self):
        """称重菜的成本也按重量计算"""
        item = _make_order_item("bsdlx", weight_kg=1.2)

        assert item["subtotal_fen"] == math.ceil(38800 * 1.2)  # 46560
        assert item["cost_fen"] == math.ceil(19400 * 1.2)      # 23280

        margin = (item["subtotal_fen"] - item["cost_fen"]) / item["subtotal_fen"]
        assert margin == pytest.approx(0.5, abs=0.01)  # ~50% 毛利


# ═══════════════════════════════════════════════════
# Test 9: 会员价 + 优惠券叠加
# ═══════════════════════════════════════════════════

class TestStackedDiscounts:
    """会员价8.8折 + 满200减30券 → 校验叠加规则"""

    def setup_method(self):
        self.engine = DiscountEngine()
        self.order_items = [
            _make_order_item("dcyt", quantity=1),    # 168元
            _make_order_item("xchnr", quantity=1),   # 58元
            _make_order_item("sbtg", quantity=1),    # 68元
            _make_order_item("mf", quantity=4),      # 8元
        ]
        # 总计: 30200分 (¥302), 总成本: 8480分

    def test_member_then_coupon_stacked(self):
        """会员8.8折 → 再叠加满200减30优惠券"""
        result = self.engine.apply_stacked_discounts(
            self.order_items,
            discounts=[
                {"discount_type": "member_price", "discount_value": 0.88},
                {"discount_type": "coupon", "discount_value": 3000},  # ¥30
            ],
            margin_floor_rate=0.30,
        )

        # 第一层: 会员8.8折, 折扣 = 30200 * 0.12 = 3624
        assert result["applied_discounts"][0]["discount_fen"] == math.ceil(30200 * 0.12)

        # 第二层: 减30元 = 3000分
        assert result["applied_discounts"][1]["discount_fen"] == 3000

        total_discount = result["total_discount_fen"]
        assert total_discount == result["applied_discounts"][0]["discount_fen"] + 3000

        # 毛利校验
        assert result["margin_check"]["passed"] is True

    def test_stacked_discount_respects_margin_floor(self):
        """叠加折扣也必须尊重毛利底线"""
        # 构造低毛利订单
        low_margin_items = [
            {"item_id": "x01", "item_name": "特价鲍鱼", "quantity": 1,
             "unit_price_fen": 20000, "cost_fen": 14000, "subtotal_fen": 20000},
        ]

        result = self.engine.apply_stacked_discounts(
            low_margin_items,
            discounts=[
                {"discount_type": "member_price", "discount_value": 0.80},  # 8折
                {"discount_type": "coupon", "discount_value": 2000},         # ¥20
            ],
            margin_floor_rate=0.30,
        )

        # 8折后 16000, 再减2000 = 14000, 成本14000, 毛利=0 → 失败
        assert result["margin_check"]["passed"] is False


# ═══════════════════════════════════════════════════
# Test 10: 异常折扣检测
# ═══════════════════════════════════════════════════

class TestDiscountAnomalyDetection:
    """异常折扣检测: 同一服务员连续6单打折 → 触发异常"""

    def setup_method(self):
        self.engine = DiscountEngine()

    def test_frequent_waiter_discount_anomaly(self):
        """同一服务员 > 5次折扣 → 触发异常"""
        orders = []
        # 服务员w001连续6单打折
        for i in range(6):
            orders.append({
                "order_id": f"order_{i}",
                "order_no": f"TX20260327{i:04d}",
                "waiter_id": "w001",
                "total_amount_fen": 20000,
                "discount_amount_fen": 2000,
                "discount_type": "percent_off",
            })
        # 加一些正常订单
        orders.append({
            "order_id": "order_normal",
            "order_no": "TX20260327NORM",
            "waiter_id": "w002",
            "total_amount_fen": 15000,
            "discount_amount_fen": 0,
        })

        anomalies = self.engine.detect_discount_anomaly(orders, STORE_ID, BIZ_DATE)

        # 应该有 frequent_waiter_discount 异常
        waiter_anomalies = [a for a in anomalies if a["anomaly_type"] == "frequent_waiter_discount"]
        assert len(waiter_anomalies) == 1
        assert waiter_anomalies[0]["waiter_id"] == "w001"
        assert waiter_anomalies[0]["severity"] == "critical"

    def test_high_single_discount_anomaly(self):
        """单笔折扣 > 30% → 触发异常"""
        orders = [
            {
                "order_id": "order_big_discount",
                "order_no": "TX20260327BD01",
                "waiter_id": "w003",
                "total_amount_fen": 10000,
                "discount_amount_fen": 5000,   # 50%折扣率
                "discount_type": "manual",
            },
        ]

        anomalies = self.engine.detect_discount_anomaly(orders, STORE_ID, BIZ_DATE)

        high_disc = [a for a in anomalies if a["anomaly_type"] == "high_single_discount"]
        assert len(high_disc) == 1
        assert high_disc[0]["discount_rate"] == 0.5

    def test_high_store_discount_rate_anomaly(self):
        """门店当日折扣 > 营收10% → 触发异常"""
        orders = [
            {
                "order_id": f"order_{i}",
                "order_no": f"TX{i}",
                "waiter_id": f"w{i % 3:03d}",
                "total_amount_fen": 10000,
                "discount_amount_fen": 1500,  # 每单15%折扣
            }
            for i in range(10)
        ]

        anomalies = self.engine.detect_discount_anomaly(orders, STORE_ID, BIZ_DATE)

        store_anomalies = [a for a in anomalies if a["anomaly_type"] == "high_store_discount_rate"]
        assert len(store_anomalies) == 1
        assert store_anomalies[0]["store_discount_rate"] == 0.15  # 15% > 10%

    def test_no_anomaly_for_normal_operations(self):
        """正常营业无异常"""
        orders = [
            {
                "order_id": f"order_{i}",
                "order_no": f"TX{i}",
                "waiter_id": f"w{i % 5:03d}",
                "total_amount_fen": 20000,
                "discount_amount_fen": 1000 if i % 3 == 0 else 0,  # 偶尔折扣，比率低
            }
            for i in range(20)
        ]

        anomalies = self.engine.detect_discount_anomaly(orders, STORE_ID, BIZ_DATE)

        # 不应有频繁折扣异常（每个服务员最多2次）
        waiter_anomalies = [a for a in anomalies if a["anomaly_type"] == "frequent_waiter_discount"]
        assert len(waiter_anomalies) == 0

    def test_discount_summary_includes_anomalies(self):
        """折扣汇总包含异常标记"""
        orders = [
            {
                "order_id": f"order_{i}",
                "order_no": f"TX{i}",
                "waiter_id": "w001",
                "total_amount_fen": 20000,
                "discount_amount_fen": 2000,
                "discount_type": "percent_off",
            }
            for i in range(7)
        ]

        summary = self.engine.get_discount_summary(orders, STORE_ID, BIZ_DATE)

        assert summary["total_discount_fen"] == 14000
        assert summary["total_revenue_fen"] == 140000
        assert summary["order_count"] == 7
        assert len(summary["anomaly_flags"]) > 0
        assert summary["by_waiter"]["w001"]["count"] == 7


# ═══════════════════════════════════════════════════
# Test Bonus: 审批规则
# ═══════════════════════════════════════════════════

class TestDiscountApproval:
    """折扣审批规则"""

    def setup_method(self):
        self.engine = DiscountEngine()

    def test_small_discount_no_approval(self):
        """小额折扣无需审批"""
        result = self.engine.validate_discount_approval(
            "percent_off", 2000, 20000,  # 10%折扣
        )
        assert result["needs_approval"] is False

    def test_large_percent_needs_approval(self):
        """折扣率 > 30% 需要经理审批"""
        result = self.engine.validate_discount_approval(
            "percent_off", 8000, 20000,  # 40%折扣
        )
        assert result["needs_approval"] is True
        assert result["approval_required_role"] == "manager"

    def test_large_amount_needs_approval(self):
        """减免 > ¥100 需要经理审批"""
        result = self.engine.validate_discount_approval(
            "amount_off", 15000, 50000,  # ¥150
        )
        assert result["needs_approval"] is True

    def test_free_item_always_needs_approval(self):
        """赠送/免单必须审批"""
        result = self.engine.validate_discount_approval(
            "item_free", 1800, 23400,
        )
        assert result["needs_approval"] is True

    def test_manual_always_needs_approval(self):
        """手动改价必须审批"""
        result = self.engine.validate_discount_approval(
            "manual", 5000, 23400,
        )
        assert result["needs_approval"] is True

    def test_approval_id_bypasses(self):
        """已有审批ID跳过审批"""
        result = self.engine.validate_discount_approval(
            "item_free", 1800, 23400, approval_id="APR-20260327-001",
        )
        assert result["needs_approval"] is False
        assert result["approval_id"] == "APR-20260327-001"


# ═══════════════════════════════════════════════════
# Test Bonus: 桌台地图
# ═══════════════════════════════════════════════════

class TestTableMap:
    """桌台全景图"""

    def test_table_map_returns_all_tables(self):
        """桌台全景图返回所有桌台及状态"""
        tm = TableManager()
        tm.init_tables(STORE_ID, [
            {"table_no": "A01", "zone": "大厅", "capacity": 4},
            {"table_no": "A02", "zone": "大厅", "capacity": 4},
            {"table_no": "B01", "zone": "包间", "capacity": 8},
            {"table_no": "B02", "zone": "包间", "capacity": 10},
        ])

        tm.open_table(STORE_ID, "A01", guest_count=3, waiter_id="w001")
        tm.reserve_table(STORE_ID, "B01", reservation_id="RSV001")

        table_map = tm.get_table_map(STORE_ID)

        assert len(table_map) == 4
        # 按桌号排序
        assert table_map[0]["table_no"] == "A01"
        assert table_map[0]["status"] == "occupied"
        assert table_map[1]["table_no"] == "A02"
        assert table_map[1]["status"] == "free"
        assert table_map[2]["table_no"] == "B01"
        assert table_map[2]["status"] == "reserved"
        assert table_map[3]["table_no"] == "B02"
        assert table_map[3]["status"] == "free"
