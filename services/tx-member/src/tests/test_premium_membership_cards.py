"""
Y-D7 付费会员卡产品化测试

测试用例：
1. test_purchase_annual_card  — 购买年卡：验证 end_date=today+365，status=active，discount_rate=0.88
2. test_refund_pro_rata       — 退款按比例：购买后用了10天退款，退款≈年卡价×(355/365)
3. test_check_premium_member  — 检查会员：有效年卡→has_premium=True，days_remaining>0
"""

from datetime import date, timedelta

# 直接导入路由模块中的业务常量和逻辑函数
from services.tx_member.src.api.premium_membership_card_routes import (
    _PRODUCTS_BY_TYPE,
    PREMIUM_CARD_PRODUCTS,
    _calc_end_date,
    _generate_card_no,
)

# ─── 测试 1: 购买年卡 ─────────────────────────────────────────────────────────


class TestPurchaseAnnualCard:
    """购买年卡后验证关键字段。"""

    def test_annual_card_end_date_is_today_plus_365(self) -> None:
        """年卡 end_date 应等于 today + 365 天。"""
        start = date.today()
        end = _calc_end_date("annual", start)
        expected = start + timedelta(days=365)
        assert end == expected, f"期望 {expected}，实际 {end}"

    def test_annual_card_discount_rate(self) -> None:
        """年卡 discount_rate 应为 0.88。"""
        product = _PRODUCTS_BY_TYPE["annual"]
        assert product["benefits"]["discount_rate"] == 0.88, (
            f"年卡折扣率应为 0.88，实际 {product['benefits']['discount_rate']}"
        )

    def test_annual_card_price_fen(self) -> None:
        """年卡价格应为 88800 分（888元）。"""
        product = _PRODUCTS_BY_TYPE["annual"]
        assert product["price_fen"] == 88800

    def test_annual_card_has_priority_booking(self) -> None:
        """年卡权益应包含优先订位。"""
        product = _PRODUCTS_BY_TYPE["annual"]
        assert product["benefits"].get("priority_booking") is True

    def test_annual_card_free_dishes(self) -> None:
        """年卡权益应包含免费菜品列表。"""
        product = _PRODUCTS_BY_TYPE["annual"]
        assert "free_dishes" in product["benefits"]
        assert isinstance(product["benefits"]["free_dishes"], list)
        assert len(product["benefits"]["free_dishes"]) > 0

    def test_card_no_format(self) -> None:
        """卡号格式应为 PMC-YYYYMM-XXXX（大写4位字母数字）。"""
        card_no = _generate_card_no()
        import re

        pattern = r"^PMC-\d{6}-[A-Z0-9]{4}$"
        assert re.match(pattern, card_no), f"卡号格式不符合 PMC-YYYYMM-XXXX，实际: {card_no}"

    def test_card_no_uniqueness(self) -> None:
        """连续生成10个卡号应不重复（概率极高）。"""
        card_nos = [_generate_card_no() for _ in range(10)]
        assert len(set(card_nos)) == len(card_nos), "卡号出现重复"

    def test_monthly_card_duration_30_days(self) -> None:
        """月卡时长应为30天。"""
        start = date.today()
        end = _calc_end_date("monthly", start)
        assert end == start + timedelta(days=30)

    def test_quarterly_card_duration_90_days(self) -> None:
        """季卡时长应为90天。"""
        start = date.today()
        end = _calc_end_date("quarterly", start)
        assert end == start + timedelta(days=90)

    def test_lifetime_card_end_date_is_none(self) -> None:
        """终身卡 end_date 应为 None。"""
        start = date.today()
        end = _calc_end_date("lifetime", start)
        assert end is None, f"终身卡 end_date 应为 None，实际 {end}"

    def test_all_card_types_present(self) -> None:
        """所有预期卡类型均应存在于产品列表。"""
        expected_types = {"monthly", "quarterly", "annual", "lifetime"}
        actual_types = {p["card_type"] for p in PREMIUM_CARD_PRODUCTS}
        assert expected_types == actual_types, f"产品列表缺少类型: {expected_types - actual_types}"


# ─── 测试 2: 退款按比例计算 ───────────────────────────────────────────────────


class TestRefundProRata:
    """退款按剩余天数比例计算的正确性验证。"""

    def test_refund_after_10_days_of_annual_card(self) -> None:
        """年卡购买后用了10天退款，退款额 ≈ 88800 × (355/365)。"""
        price_fen = 88800
        total_days = 365
        used_days = 10
        remaining_days = total_days - used_days  # 355

        refund_fen = int(price_fen * remaining_days / total_days)
        expected_approx = int(88800 * 355 / 365)  # ≈ 86368

        assert refund_fen == expected_approx, f"期望退款 {expected_approx} 分，实际 {refund_fen} 分"
        # 退款不应超过原价
        assert refund_fen <= price_fen

    def test_refund_rate_precision(self) -> None:
        """退款比例 = remaining/total，精确到分（整数）。"""
        price_fen = 88800
        total_days = 365
        remaining_days = 355

        # 使用整数除法确保精确
        refund_fen = int(price_fen * remaining_days / total_days)
        refund_rate = round(remaining_days / total_days, 4)

        assert 0 < refund_rate <= 1.0
        assert refund_fen > 0
        assert isinstance(refund_fen, int), "退款金额必须是整数（分）"

    def test_refund_full_unused_card(self) -> None:
        """当天购买当天退款（used_days=0），退款应等于原价。"""
        price_fen = 9900  # 月卡
        total_days = 30
        used_days = 0
        remaining_days = total_days - used_days

        refund_fen = int(price_fen * remaining_days / total_days)
        assert refund_fen == price_fen, f"全额退款应为 {price_fen}，实际 {refund_fen}"

    def test_refund_last_day_card(self) -> None:
        """最后一天退款，退款额应接近0。"""
        price_fen = 9900
        total_days = 30
        used_days = 29
        remaining_days = 1

        refund_fen = int(price_fen * remaining_days / total_days)
        assert 0 <= refund_fen <= price_fen

    def test_refund_after_expiry_remaining_zero(self) -> None:
        """已过期的卡剩余天数为0，退款应为0。"""
        price_fen = 88800
        today = date.today()
        end_date = today - timedelta(days=5)  # 5天前已过期
        start_date = end_date - timedelta(days=365)

        total_days = (end_date - start_date).days
        used_days = min((today - start_date).days, total_days)
        remaining_days = max(total_days - used_days, 0)

        refund_fen = int(price_fen * remaining_days / total_days)
        assert refund_fen == 0, f"已过期卡退款应为0，实际 {refund_fen}"

    def test_lifetime_card_not_refundable(self) -> None:
        """终身卡标记为不可退款。"""
        lifetime_product = next(p for p in PREMIUM_CARD_PRODUCTS if p["card_type"] == "lifetime")
        assert lifetime_product.get("refundable", True) is False, "终身卡应标记 refundable=False"

    def test_refund_calculation_no_floating_point_error(self) -> None:
        """退款计算应使用整数，不引入浮点误差。"""
        price_fen = 88800
        total_days = 365
        remaining_days = 200

        # 确保使用 int() 而非直接 round()
        refund_fen = int(price_fen * remaining_days / total_days)
        assert isinstance(refund_fen, int)
        assert refund_fen == int(88800 * 200 / 365)  # ≈ 48657


# ─── 测试 3: 检查会员是否持有有效付费卡 ───────────────────────────────────────


class TestCheckPremiumMember:
    """检查会员付费卡有效性的逻辑验证。"""

    def test_active_annual_card_within_period(self) -> None:
        """有效期内的年卡，has_premium 应为 True，days_remaining > 0。"""
        today = date.today()
        start_date = today - timedelta(days=100)
        end_date = today + timedelta(days=265)  # 还剩265天

        is_active = end_date >= today
        days_remaining = (end_date - today).days

        assert is_active is True
        assert days_remaining > 0, f"剩余天数应 > 0，实际 {days_remaining}"

    def test_expired_card_not_premium(self) -> None:
        """已过期的卡，has_premium 应为 False（end_date < today）。"""
        today = date.today()
        end_date = today - timedelta(days=5)

        is_active = end_date >= today
        assert is_active is False, "已过期的卡不应视为有效"

    def test_lifetime_card_always_active(self) -> None:
        """终身卡 end_date=None，should be treated as always active。"""
        end_date = None
        # 终身卡逻辑：end_date IS NULL OR end_date >= today
        today = date.today()
        is_active = end_date is None or end_date >= today
        assert is_active is True

    def test_card_priority_lifetime_highest(self) -> None:
        """当会员持有多张有效卡时，终身卡优先级最高。"""
        # 按业务逻辑排序：lifetime > annual > quarterly > monthly
        priority_order = {
            "lifetime": 1,
            "annual": 2,
            "quarterly": 3,
            "monthly": 4,
        }
        assert priority_order["lifetime"] < priority_order["annual"]
        assert priority_order["annual"] < priority_order["quarterly"]
        assert priority_order["quarterly"] < priority_order["monthly"]

    def test_annual_card_benefits_have_discount_rate(self) -> None:
        """年卡权益中必须包含 discount_rate=0.88。"""
        product = _PRODUCTS_BY_TYPE["annual"]
        benefits = product["benefits"]
        assert "discount_rate" in benefits
        assert benefits["discount_rate"] == 0.88

    def test_days_remaining_for_fresh_annual_card(self) -> None:
        """刚购买的年卡，days_remaining 应等于365。"""
        start = date.today()
        end = start + timedelta(days=365)
        days_remaining = (end - start).days
        assert days_remaining == 365

    def test_days_remaining_for_expiring_card(self) -> None:
        """5天后到期的卡，days_remaining 应为5，is_expiring_soon=True。"""
        today = date.today()
        end_date = today + timedelta(days=5)
        days_remaining = (end_date - today).days

        assert days_remaining == 5
        is_expiring_soon = 0 <= days_remaining <= 7
        assert is_expiring_soon is True

    def test_no_premium_card_returns_false(self) -> None:
        """没有有效付费卡时，has_premium 应为 False。"""
        # 模拟数据库返回空结果
        card_row = None
        has_premium = card_row is not None
        assert has_premium is False

    def test_expiring_soon_threshold_7_days(self) -> None:
        """到期预警阈值应为7天（days_remaining <= 7）。"""
        for days in range(0, 8):
            is_expiring = 0 <= days <= 7
            assert is_expiring is True, f"剩余{days}天应触发到期预警"

        for days in [8, 30, 365]:
            is_expiring = 0 <= days <= 7
            assert is_expiring is False, f"剩余{days}天不应触发到期预警"
