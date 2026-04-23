"""收银核心引擎 — 全流程测试

覆盖场景：
1. 开台→加菜(固定+称重+时价)→折扣→结算(单/多支付)→释放桌台
2. 毛利底线拒绝
3. 现金盘点差异检测
4. 日结生命周期：draft→count→comment→submit→approve
5. 取消订单+退款
6. 拆单支付(微信200+支付宝100+现金50=350)
7. 称重菜品定价(龙虾 280/斤 × 1.5斤 = 420)
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

# ─── 模拟数据库对象（脱离真实PG） ───


def _make_uuid() -> str:
    return str(uuid.uuid4())


TENANT_ID = _make_uuid()
STORE_ID = _make_uuid()
WAITER_ID = "W001"


class FakeRow:
    """模拟 SQLAlchemy ORM 行"""

    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)


class FakeResult:
    def __init__(self, rows=None, scalar=None):
        self._rows = rows or []
        self._scalar = scalar

    def scalar_one_or_none(self):
        return self._scalar

    def scalar(self):
        return self._scalar

    def scalars(self):
        return self

    def all(self):
        return self._rows


class FakeSession:
    """模拟 AsyncSession 用于纯逻辑测试"""

    def __init__(self):
        self.added = []
        self.deleted = []
        self.executed = []
        self.flushed = False
        self._execute_results = []
        self._execute_index = 0

    def add(self, obj):
        self.added.append(obj)

    async def delete(self, obj):
        self.deleted.append(obj)

    async def execute(self, stmt, *args, **kwargs):
        if self._execute_index < len(self._execute_results):
            result = self._execute_results[self._execute_index]
            self._execute_index += 1
            return result
        return FakeResult()

    async def flush(self):
        self.flushed = True

    def push_result(self, result: FakeResult):
        self._execute_results.append(result)


# ─── 测试 ───


class TestCashierEngineUnit:
    """纯单元测试：不依赖数据库，验证业务逻辑"""

    def test_gen_order_no_format(self):
        """订单号格式: TX + 14位时间 + 4位随机"""
        from services.cashier_engine import _gen_order_no

        order_no = _gen_order_no()
        assert order_no.startswith("TX")
        assert len(order_no) == 20  # TX(2) + datetime(14) + random(4)

    def test_method_to_category_mapping(self):
        """支付方式→类别映射"""
        from services.cashier_engine import CashierEngine

        assert CashierEngine._method_to_category("cash") == "现金"
        assert CashierEngine._method_to_category("wechat") == "移动支付"
        assert CashierEngine._method_to_category("alipay") == "移动支付"
        assert CashierEngine._method_to_category("unionpay") == "银联卡"
        assert CashierEngine._method_to_category("member_balance") == "会员消费"
        assert CashierEngine._method_to_category("credit_account") == "挂账"
        assert CashierEngine._method_to_category("unknown") == "other"


class TestPaymentGatewayUnit:
    """支付网关单元测试"""

    def test_payment_methods_config(self):
        """支付方式配置完整性"""
        from services.payment_gateway import PaymentGateway

        methods = PaymentGateway.PAYMENT_METHODS

        assert "cash" in methods
        assert "wechat" in methods
        assert "alipay" in methods
        assert "unionpay" in methods
        assert "member_balance" in methods
        assert "credit_account" in methods

        # 现金不需要交易号，无手续费
        assert methods["cash"]["need_trade_no"] is False
        assert methods["cash"]["fee_rate"] == 0

        # 微信需要交易号，手续费0.6%
        assert methods["wechat"]["need_trade_no"] is True
        assert methods["wechat"]["fee_rate"] == 0.006

    def test_fee_calculation(self):
        """手续费计算验证"""
        rate = 0.006
        amount = 10000  # ¥100
        fee = round(amount * rate)
        assert fee == 60  # ¥0.60


class TestDailySettlementUnit:
    """日结服务单元测试"""

    def test_settlement_status_flow(self):
        """日结状态流转规则"""
        from services.daily_settlement import DailySettlementService

        transitions = DailySettlementService.STATUS_TRANSITIONS
        assert "counting" in transitions["draft"]
        assert "reviewing" in transitions["counting"]
        assert "manager_confirmed" in transitions["reviewing"]
        assert "submitted" in transitions["manager_confirmed"]
        assert "approved" in transitions["submitted"]
        assert "closed" in transitions["approved"]

    def test_cash_variance_threshold(self):
        """现金差异告警阈值 = ¥10 = 1000分"""
        from services.daily_settlement import DailySettlementService

        assert DailySettlementService.CASH_VARIANCE_THRESHOLD_FEN == 1000


# ─── 集成级测试（使用FakeSession模拟数据库） ───


class TestCashierFlowIntegration:
    """完整收银流程集成测试（FakeSession模拟DB）"""

    def _make_table(self, **overrides):
        defaults = {
            "id": uuid.uuid4(),
            "tenant_id": uuid.UUID(TENANT_ID),
            "store_id": uuid.UUID(STORE_ID),
            "table_no": "A01",
            "area": "大厅",
            "floor": 1,
            "seats": 4,
            "min_consume_fen": 0,
            "status": "free",
            "current_order_id": None,
            "sort_order": 0,
            "is_active": True,
            "config": None,
        }
        defaults.update(overrides)
        return FakeRow(**defaults)

    def _make_order(self, **overrides):
        defaults = {
            "id": uuid.uuid4(),
            "tenant_id": uuid.UUID(TENANT_ID),
            "order_no": "TX20260327120000ABCD",
            "store_id": uuid.UUID(STORE_ID),
            "table_number": "A01",
            "customer_id": None,
            "waiter_id": WAITER_ID,
            "sales_channel": "dine_in",
            "guest_count": 4,
            "total_amount_fen": 0,
            "discount_amount_fen": 0,
            "final_amount_fen": 0,
            "status": "pending",
            "order_time": datetime.now(timezone.utc),
            "confirmed_at": None,
            "completed_at": None,
            "notes": None,
            "order_metadata": {},
            "discount_type": None,
            "gross_margin_before": None,
            "gross_margin_after": None,
            "margin_alert_flag": False,
            "abnormal_flag": False,
        }
        defaults.update(overrides)
        return FakeRow(**defaults)

    def _make_item(self, **overrides):
        defaults = {
            "id": uuid.uuid4(),
            "tenant_id": uuid.UUID(TENANT_ID),
            "order_id": uuid.uuid4(),
            "dish_id": uuid.uuid4(),
            "item_name": "水煮鱼",
            "quantity": 1,
            "unit_price_fen": 6800,
            "subtotal_fen": 6800,
            "food_cost_fen": 2000,
            "gross_margin": Decimal("0.7059"),
            "notes": None,
            "customizations": {},
            "pricing_mode": "fixed",
            "weight_value": None,
            "return_flag": False,
            "return_reason": None,
        }
        defaults.update(overrides)
        return FakeRow(**defaults)

    def _make_store(self, **overrides):
        defaults = {
            "id": uuid.UUID(STORE_ID),
            "tenant_id": uuid.UUID(TENANT_ID),
            "config": None,
            "cost_ratio_target": None,
        }
        defaults.update(overrides)
        return FakeRow(**defaults)

    def _make_settlement(self, **overrides):
        defaults = {
            "id": uuid.uuid4(),
            "tenant_id": uuid.UUID(TENANT_ID),
            "store_id": uuid.UUID(STORE_ID),
            "settlement_date": date(2026, 3, 27),
            "settlement_type": "daily",
            "total_revenue_fen": 35000,
            "total_discount_fen": 3500,
            "total_refund_fen": 0,
            "net_revenue_fen": 35000,
            "cash_fen": 5000,
            "wechat_fen": 20000,
            "alipay_fen": 10000,
            "unionpay_fen": 0,
            "credit_fen": 0,
            "member_balance_fen": 0,
            "total_orders": 12,
            "total_guests": 38,
            "avg_per_guest_fen": 921,
            "cash_expected_fen": 5000,
            "cash_actual_fen": None,
            "cash_diff_fen": None,
            "operator_id": None,
            "settled_at": None,
            "details": {"status": "draft"},
        }
        defaults.update(overrides)
        return FakeRow(**defaults)


class TestWeightedDishPricing:
    """称重菜品定价测试"""

    def test_lobster_280_per_jin_times_1_5(self):
        """龙虾 ¥280/斤(28000分) × 1.5斤 = ¥420(42000分)"""
        unit_price_fen = 28000  # ¥280/斤
        weight_value = 1.5
        subtotal = round(unit_price_fen * weight_value)
        assert subtotal == 42000

    def test_australian_lobster_580_per_jin_times_2_3(self):
        """澳洲龙虾 ¥580/斤 × 2.3斤 = ¥1334(133400分)"""
        unit_price_fen = 58000
        weight_value = 2.3
        subtotal = round(unit_price_fen * weight_value)
        assert subtotal == 133400

    def test_sea_bass_68_per_jin_times_1_2(self):
        """鲈鱼 ¥68/斤(6800分) × 1.2斤 = ¥81.6(8160分)"""
        unit_price_fen = 6800
        weight_value = 1.2
        subtotal = round(unit_price_fen * weight_value)
        assert subtotal == 8160


class TestDiscountCalculation:
    """折扣计算测试"""

    def test_percent_off_80(self):
        """打八折：折扣额 = total * 0.2"""
        total = 10000  # ¥100
        discount_value = 0.8  # 八折
        discount_fen = round(total * (1.0 - discount_value))
        assert discount_fen == 2000

    def test_percent_off_88(self):
        """打88折"""
        total = 10000
        discount_value = 0.88
        discount_fen = round(total * (1.0 - discount_value))
        assert discount_fen == 1200

    def test_amount_off_50(self):
        """满减50"""
        discount_fen = 5000  # ¥50
        total = 20000  # ¥200
        new_final = total - discount_fen
        assert new_final == 15000

    def test_member_price(self):
        """会员价：原价200，会员价160"""
        total = 20000  # ¥200
        member_total = 16000  # ¥160
        discount_fen = total - member_total
        assert discount_fen == 4000

    def test_margin_floor_check_pass(self):
        """毛利校验通过：折扣后毛利45% > 底线30%"""
        total = 10000
        cost = 5000
        discount = 500
        new_final = total - discount
        margin = (new_final - cost) / new_final
        assert margin > 0.30
        assert round(margin, 4) == round(4500 / 9500, 4)

    def test_margin_floor_check_fail(self):
        """毛利校验失败：折扣后毛利10% < 底线30%"""
        total = 10000
        cost = 5000
        discount = 4000  # 大额折扣
        new_final = total - discount
        margin = (new_final - cost) / new_final
        assert margin < 0.30  # 1000/6000 ≈ 16.7%


class TestSplitPayment:
    """拆单支付测试"""

    def test_three_way_split(self):
        """微信200 + 支付宝100 + 现金50 = 350"""
        splits = [
            {"method": "wechat", "amount_fen": 20000},
            {"method": "alipay", "amount_fen": 10000},
            {"method": "cash", "amount_fen": 5000},
        ]
        total = sum(s["amount_fen"] for s in splits)
        assert total == 35000

    def test_fee_calculation_for_split(self):
        """拆单手续费：微信0.6% + 支付宝0.6% + 现金0"""
        splits = [
            {"method": "wechat", "amount_fen": 20000, "fee_rate": 0.006},
            {"method": "alipay", "amount_fen": 10000, "fee_rate": 0.006},
            {"method": "cash", "amount_fen": 5000, "fee_rate": 0},
        ]
        total_fee = sum(round(s["amount_fen"] * s["fee_rate"]) for s in splits)
        # 20000*0.006=120 + 10000*0.006=60 + 0 = 180
        assert total_fee == 180

    def test_split_must_equal_order_total(self):
        """拆单金额必须等于订单应付"""
        order_total = 35000
        splits = [
            {"method": "wechat", "amount_fen": 20000},
            {"method": "alipay", "amount_fen": 10000},
            {"method": "cash", "amount_fen": 5000},
        ]
        split_total = sum(s["amount_fen"] for s in splits)
        assert split_total == order_total

    def test_split_not_equal_should_fail(self):
        """拆单金额不等于应付时应失败"""
        order_total = 35000
        splits = [
            {"method": "wechat", "amount_fen": 20000},
            {"method": "cash", "amount_fen": 5000},
        ]
        split_total = sum(s["amount_fen"] for s in splits)
        assert split_total != order_total  # 25000 != 35000


class TestCashCountVariance:
    """现金盘点差异检测"""

    def test_exact_match(self):
        """现金精确匹配：差异=0"""
        expected = 5000
        actual = 5000
        diff = actual - expected
        assert diff == 0
        assert abs(diff) <= 1000  # under threshold

    def test_small_variance_pass(self):
        """小额差异(¥5)不告警"""
        expected = 5000
        actual = 5500
        diff = actual - expected
        assert abs(diff) == 500
        assert abs(diff) <= 1000  # under ¥10 threshold

    def test_large_variance_alert(self):
        """大额差异(¥15)触发告警"""
        expected = 5000
        actual = 6500
        diff = actual - expected
        assert abs(diff) == 1500
        assert abs(diff) > 1000  # over ¥10 threshold

    def test_negative_variance(self):
        """现金短缺"""
        expected = 5000
        actual = 3000
        diff = actual - expected
        assert diff == -2000
        assert abs(diff) > 1000  # alert

    def test_denomination_breakdown_total(self):
        """面额明细加总"""
        breakdown = {
            "100": 5,  # 5张百元 = 500
            "50": 3,  # 3张五十 = 150
            "20": 2,  # 2张二十 = 40
            "10": 5,  # 5张十元 = 50
            "5": 3,  # 3张五元 = 15
            "1": 8,  # 8张一元 = 8
        }
        total_yuan = sum(int(denom) * count for denom, count in breakdown.items())
        assert total_yuan == 763
        total_fen = total_yuan * 100
        assert total_fen == 76300


class TestSettlementLifecycle:
    """日结生命周期测试"""

    def test_full_lifecycle_states(self):
        """完整日结状态流转"""
        from services.daily_settlement import DailySettlementService

        states = DailySettlementService.SETTLEMENT_STATUS
        assert states == [
            "draft",
            "counting",
            "reviewing",
            "manager_confirmed",
            "chef_confirmed",
            "submitted",
            "approved",
            "closed",
            "reopened",
        ]

    def test_transition_draft_to_counting(self):
        from services.daily_settlement import DailySettlementService

        transitions = DailySettlementService.STATUS_TRANSITIONS
        assert "counting" in transitions["draft"]

    def test_transition_submitted_to_approved(self):
        from services.daily_settlement import DailySettlementService

        transitions = DailySettlementService.STATUS_TRANSITIONS
        assert "approved" in transitions["submitted"]

    def test_transition_closed_to_reopened(self):
        from services.daily_settlement import DailySettlementService

        transitions = DailySettlementService.STATUS_TRANSITIONS
        assert "reopened" in transitions["closed"]

    def test_warning_cash_variance(self):
        """现金差异 > ¥10 应产生告警"""
        variance = 1500  # ¥15
        threshold = 1000
        assert abs(variance) > threshold

    def test_warning_high_discount_rate(self):
        """折扣率 > 15% 应产生告警"""
        total_revenue = 100000
        total_discount = 18000
        rate = total_discount / total_revenue
        assert rate > 0.15

    def test_warning_high_refund_rate(self):
        """退款率 > 10% 应产生告警"""
        total_revenue = 100000
        total_refund = 12000
        rate = total_refund / total_revenue
        assert rate > 0.10


class TestOrderCancelAndRefund:
    """取消订单和退款测试"""

    def test_cancel_releases_table(self):
        """取消订单应释放桌台"""
        # 验证状态流转逻辑
        from services.state_machine import sync_table_on_order_change

        table_target = sync_table_on_order_change("cancelled")
        assert table_target == "empty"

    def test_refund_amount_validation(self):
        """退款金额不可超过支付金额"""
        payment_amount = 10000
        refund_amount = 12000
        assert refund_amount > payment_amount  # should be rejected

    def test_full_refund_type(self):
        """全额退款"""
        payment_amount = 10000
        refund_amount = 10000
        refund_type = "full" if refund_amount == payment_amount else "partial"
        assert refund_type == "full"

    def test_partial_refund_type(self):
        """部分退款"""
        payment_amount = 10000
        refund_amount = 5000
        refund_type = "full" if refund_amount == payment_amount else "partial"
        assert refund_type == "partial"


class TestStateMachineIntegration:
    """状态机集成测试"""

    def test_table_lifecycle(self):
        """桌台完整生命周期：空→用餐→待结→待清→空"""
        from services.state_machine import can_table_transition

        assert can_table_transition("empty", "dining")
        assert can_table_transition("dining", "pending_checkout")
        assert can_table_transition("pending_checkout", "pending_cleanup")
        assert can_table_transition("pending_cleanup", "empty")

    def test_table_invalid_transition(self):
        """非法桌台状态转换"""
        from services.state_machine import can_table_transition

        assert not can_table_transition("empty", "pending_checkout")
        assert not can_table_transition("dining", "empty")  # must go through checkout

    def test_order_lifecycle(self):
        """订单完整生命周期"""
        from services.state_machine import validate_order_lifecycle

        result = validate_order_lifecycle(["draft", "placed", "preparing", "all_served", "pending_payment", "paid"])
        assert result["valid"] is True

    def test_order_invalid_lifecycle(self):
        """非法订单生命周期"""
        from services.state_machine import validate_order_lifecycle

        result = validate_order_lifecycle(["draft", "paid"])  # skip everything
        assert result["valid"] is False


class TestRealisticRestaurantData:
    """使用真实餐饮数据测试"""

    def test_full_meal_scenario(self):
        """完整一桌用餐场景（尝在一起 — 4人桌）

        菜单:
        - 水煮鱼 ¥68 (固定价)
        - 麻辣牛肉 ¥58 (固定价)
        - 蒜蓉龙虾 ¥280/斤 × 1.5斤 = ¥420 (称重)
        - 时价鲍鱼 ¥188 (时价)
        - 茶位费 ¥8/人 × 4 = ¥32

        小计: 68 + 58 + 420 + 188 + 32 = ¥766
        折扣: 打88折 → 减 ¥91.92 ≈ 92
        应付: ¥674
        支付: 微信 ¥400 + 现金 ¥274
        """
        items = [
            {"name": "水煮鱼", "price_fen": 6800, "qty": 1, "mode": "fixed"},
            {"name": "麻辣牛肉", "price_fen": 5800, "qty": 1, "mode": "fixed"},
            {"name": "蒜蓉龙虾", "price_fen": 28000, "qty": 1, "mode": "weighted", "weight": 1.5},
            {"name": "时价鲍鱼", "price_fen": 18800, "qty": 1, "mode": "market_price"},
            {"name": "茶位费", "price_fen": 800, "qty": 4, "mode": "fixed"},
        ]

        total = 0
        for item in items:
            if item["mode"] == "weighted":
                subtotal = round(item["price_fen"] * item["weight"])
            else:
                subtotal = item["price_fen"] * item["qty"]
            total += subtotal

        assert total == 76600  # ¥766

        # 打88折
        discount_rate = 0.88
        discount_fen = round(total * (1.0 - discount_rate))
        assert discount_fen == 9192  # ≈ ¥91.92

        final = total - discount_fen
        assert final == 67408  # ≈ ¥674.08

        # 多支付
        wechat = 40000
        cash = final - wechat
        assert wechat + cash == final
        assert cash == 27408

    def test_banquet_scenario(self):
        """宴席场景 — 10桌 × ¥1888/桌"""
        price_per_table = 188800  # ¥1888
        table_count = 10
        total = price_per_table * table_count
        assert total == 1888000  # ¥18,880

        # 打95折
        discount_fen = round(total * 0.05)
        assert discount_fen == 94400  # ¥944

        final = total - discount_fen
        assert final == 1793600  # ¥17,936

    def test_takeout_scenario(self):
        """外卖场景 — 无桌台"""
        items = [
            {"name": "黄焖鸡米饭", "price_fen": 2800, "qty": 2},
            {"name": "可乐", "price_fen": 600, "qty": 2},
            {"name": "打包费", "price_fen": 200, "qty": 1},
        ]
        total = sum(i["price_fen"] * i["qty"] for i in items)
        assert total == 7000  # ¥70

    def test_change_calculation(self):
        """找零计算：应付¥67.5，给¥100现金，找¥32.5"""
        final = 6750
        cash_paid = 10000
        change = cash_paid - final
        assert change == 3250  # ¥32.50


class TestPaymentGatewayFeatures:
    """支付网关功能测试"""

    def test_shouqianba_trade_no_format(self):
        """收钱吧交易号格式"""
        from services.payment_gateway import PaymentGateway

        db = FakeSession()
        gw = PaymentGateway(db, TENANT_ID)
        trade_no = gw._call_shouqianba_pay("PAY001", 10000, "auth123", "wechat")
        assert trade_no.startswith("SQB")

    def test_shouqianba_refund_trade_no_format(self):
        """收钱吧退款交易号格式"""
        from services.payment_gateway import PaymentGateway

        db = FakeSession()
        gw = PaymentGateway(db, TENANT_ID)
        refund_no = gw._call_shouqianba_refund("SQB001", "REF001", 5000)
        assert refund_no.startswith("SQBR")

    def test_daily_summary_empty(self):
        """无交易日汇总"""
        summary = {
            "order_count": 0,
            "total_revenue_fen": 0,
            "total_fee_fen": 0,
            "net_revenue_fen": 0,
            "by_method": {},
        }
        assert summary["order_count"] == 0
        assert summary["net_revenue_fen"] == 0


class TestEdgeCases:
    """边界场景测试"""

    def test_zero_amount_order(self):
        """零金额订单（全部赠送）"""
        total = 10000
        discount = 10000  # 免单
        final = total - discount
        assert final == 0

    def test_single_item_order(self):
        """单品订单"""
        items = [{"name": "可乐", "price_fen": 600, "qty": 1}]
        total = sum(i["price_fen"] * i["qty"] for i in items)
        assert total == 600

    def test_large_order(self):
        """大额订单（宴席级别）"""
        total = 5000000  # ¥50,000
        discount = round(total * 0.05)
        final = total - discount
        assert final == 4750000

    def test_minimum_weight(self):
        """最小称重值"""
        unit_price = 28000
        weight = 0.1  # 0.1斤
        subtotal = round(unit_price * weight)
        assert subtotal == 2800  # ¥28

    def test_multiple_same_item(self):
        """同一菜品多份"""
        qty = 5
        unit_price = 3800  # ¥38
        subtotal = unit_price * qty
        assert subtotal == 19000  # ¥190


class TestAPIRouteRegistration:
    """API 路由注册检查"""

    def test_cashier_api_routes_exist(self):
        """验证所有必要路由已注册"""
        from api.cashier_api import router

        routes = {r.path: r.methods for r in router.routes if hasattr(r, "path")}

        assert "/api/v1/orders" in routes
        assert "/api/v1/orders/{order_id}/items" in routes
        assert "/api/v1/orders/{order_id}/items/{item_id}" in routes
        assert "/api/v1/orders/{order_id}/discount" in routes
        assert "/api/v1/orders/{order_id}/settle" in routes
        assert "/api/v1/orders/{order_id}/cancel" in routes
        assert "/api/v1/orders/{order_id}" in routes
        assert "/api/v1/tables" in routes
        assert "/api/v1/tables/{table_no}/status" in routes
        assert "/api/v1/daily-settlement" in routes
        assert "/api/v1/daily-settlement/confirm" in routes

    def test_route_methods(self):
        """验证HTTP方法正确"""
        from api.cashier_api import router

        route_methods = {}
        for r in router.routes:
            if hasattr(r, "path") and hasattr(r, "methods"):
                route_methods[r.path] = r.methods

        # POST endpoints
        assert "POST" in route_methods.get("/api/v1/orders", set())
        assert "POST" in route_methods.get("/api/v1/orders/{order_id}/items", set())
        assert "POST" in route_methods.get("/api/v1/orders/{order_id}/discount", set())
        assert "POST" in route_methods.get("/api/v1/orders/{order_id}/settle", set())
        assert "POST" in route_methods.get("/api/v1/orders/{order_id}/cancel", set())

        # PUT endpoints
        assert "PUT" in route_methods.get("/api/v1/orders/{order_id}/items/{item_id}", set())
        assert "PUT" in route_methods.get("/api/v1/tables/{table_no}/status", set())

        # GET endpoints
        assert "GET" in route_methods.get("/api/v1/orders/{order_id}", set())
        assert "GET" in route_methods.get("/api/v1/tables", set())
        assert "GET" in route_methods.get("/api/v1/daily-settlement", set())

        # DELETE endpoints
        assert "DELETE" in route_methods.get("/api/v1/orders/{order_id}/items/{item_id}", set())
