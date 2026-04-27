"""优惠券引擎测试 — 7种券类型 + 叠加 + 计算 + 统计 + API"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.coupon_engine import (
    CouponType,
    _CouponInstanceStore,
    _CouponTemplateStore,
    _RevenueRuleStore,
    batch_issue,
    calculate_discount,
    check_stacking_rules,
    create_coupon,
    get_coupon_stats,
    redeem_coupon,
    set_revenue_rule,
    verify_coupon,
)

TENANT = "t-test-001"


@pytest.fixture(autouse=True)
def _clear_stores():
    _CouponTemplateStore.clear()
    _CouponInstanceStore.clear()
    _RevenueRuleStore.clear()
    yield
    _CouponTemplateStore.clear()
    _CouponInstanceStore.clear()
    _RevenueRuleStore.clear()


# ---------------------------------------------------------------------------
# 1. 创建券模板
# ---------------------------------------------------------------------------


class TestCreateCoupon:
    @pytest.mark.asyncio
    async def test_create_cash_coupon(self):
        result = await create_coupon(
            coupon_type="cash",
            config={"name": "满100减10", "face_value_fen": 1000, "min_order_amount_fen": 10000},
            tenant_id=TENANT,
        )
        assert result["coupon_type"] == "cash"
        assert result["face_value_fen"] == 1000
        assert result["min_order_amount_fen"] == 10000
        assert result["status"] == "active"

    @pytest.mark.asyncio
    async def test_create_discount_coupon(self):
        result = await create_coupon(
            coupon_type="discount",
            config={"name": "8折券", "discount_rate": 80},
            tenant_id=TENANT,
        )
        assert result["coupon_type"] == "discount"
        assert result["discount_rate"] == 80

    @pytest.mark.asyncio
    async def test_create_free_item_coupon(self):
        result = await create_coupon(
            coupon_type="free_item",
            config={"name": "免费甜品", "item_dish_id": "dish_001"},
            tenant_id=TENANT,
        )
        assert result["coupon_type"] == "free_item"
        assert result["item_dish_id"] == "dish_001"

    @pytest.mark.asyncio
    async def test_create_delivery_coupon(self):
        result = await create_coupon(
            coupon_type="delivery",
            config={"name": "免配送费", "face_value_fen": 500},
            tenant_id=TENANT,
        )
        assert result["coupon_type"] == "delivery"
        assert result["face_value_fen"] == 500

    @pytest.mark.asyncio
    async def test_invalid_type(self):
        with pytest.raises(ValueError, match="不支持的券类型"):
            await create_coupon(coupon_type="invalid", config={}, tenant_id=TENANT)

    @pytest.mark.asyncio
    async def test_create_all_seven_types(self):
        for ct in CouponType:
            result = await create_coupon(
                coupon_type=ct.value,
                config={"name": f"测试{ct.value}"},
                tenant_id=TENANT,
            )
            assert result["coupon_type"] == ct.value


# ---------------------------------------------------------------------------
# 2. 批量发放
# ---------------------------------------------------------------------------


class TestBatchIssue:
    @pytest.mark.asyncio
    async def test_issue_to_customers(self):
        tpl = await create_coupon("cash", {"face_value_fen": 500}, TENANT)
        result = await batch_issue(tpl["coupon_id"], ["c1", "c2", "c3"], TENANT)
        assert result["issued_count"] == 3
        assert len(result["issued"]) == 3
        for item in result["issued"]:
            assert "code" in item

    @pytest.mark.asyncio
    async def test_issue_exceeds_max(self):
        tpl = await create_coupon("cash", {"face_value_fen": 500, "max_issue_count": 2}, TENANT)
        with pytest.raises(ValueError, match="超出最大发放量"):
            await batch_issue(tpl["coupon_id"], ["c1", "c2", "c3"], TENANT)

    @pytest.mark.asyncio
    async def test_issue_wrong_tenant(self):
        tpl = await create_coupon("cash", {"face_value_fen": 500}, TENANT)
        with pytest.raises(ValueError, match="租户不匹配"):
            await batch_issue(tpl["coupon_id"], ["c1"], "other-tenant")


# ---------------------------------------------------------------------------
# 3. 验证券
# ---------------------------------------------------------------------------


class TestVerifyCoupon:
    @pytest.mark.asyncio
    async def test_verify_valid(self):
        tpl = await create_coupon("cash", {"face_value_fen": 500}, TENANT)
        issued = await batch_issue(tpl["coupon_id"], ["c1"], TENANT)
        code = issued["issued"][0]["code"]
        result = await verify_coupon(code, "order_001", TENANT)
        assert result["valid"] is True

    @pytest.mark.asyncio
    async def test_verify_not_exists(self):
        result = await verify_coupon("FAKE-CODE", "order_001", TENANT)
        assert result["valid"] is False
        assert "不存在" in result["reason"]

    @pytest.mark.asyncio
    async def test_verify_wrong_tenant(self):
        tpl = await create_coupon("cash", {"face_value_fen": 500}, TENANT)
        issued = await batch_issue(tpl["coupon_id"], ["c1"], TENANT)
        code = issued["issued"][0]["code"]
        result = await verify_coupon(code, "order_001", "other-tenant")
        assert result["valid"] is False

    @pytest.mark.asyncio
    async def test_verify_expired(self):
        tpl = await create_coupon("cash", {"face_value_fen": 500, "expires_at": "2020-01-01T00:00:00+00:00"}, TENANT)
        issued = await batch_issue(tpl["coupon_id"], ["c1"], TENANT)
        code = issued["issued"][0]["code"]
        # Manually set expires_at on instance
        inst = _CouponInstanceStore.get(code)
        inst["expires_at"] = "2020-01-01T00:00:00+00:00"
        _CouponInstanceStore.save(code, inst)
        result = await verify_coupon(code, "order_001", TENANT)
        assert result["valid"] is False
        assert "过期" in result["reason"]


# ---------------------------------------------------------------------------
# 4. 核销券
# ---------------------------------------------------------------------------


class TestRedeemCoupon:
    @pytest.mark.asyncio
    async def test_redeem_success(self):
        tpl = await create_coupon("cash", {"face_value_fen": 500}, TENANT)
        issued = await batch_issue(tpl["coupon_id"], ["c1"], TENANT)
        code = issued["issued"][0]["code"]
        result = await redeem_coupon(code, "order_001", TENANT)
        assert result["code"] == code
        assert result["order_id"] == "order_001"
        # Check instance status
        inst = _CouponInstanceStore.get(code)
        assert inst["status"] == "redeemed"

    @pytest.mark.asyncio
    async def test_redeem_twice_fails(self):
        tpl = await create_coupon("cash", {"face_value_fen": 500}, TENANT)
        issued = await batch_issue(tpl["coupon_id"], ["c1"], TENANT)
        code = issued["issued"][0]["code"]
        await redeem_coupon(code, "order_001", TENANT)
        with pytest.raises(ValueError, match="核销失败"):
            await redeem_coupon(code, "order_002", TENANT)


# ---------------------------------------------------------------------------
# 5. 叠加规则
# ---------------------------------------------------------------------------


class TestStackingRules:
    @pytest.mark.asyncio
    async def test_same_type_conflict(self):
        coupons = [
            {"coupon_type": "cash", "face_value_fen": 500},
            {"coupon_type": "cash", "face_value_fen": 300},
        ]
        result = await check_stacking_rules(coupons, "order_001", TENANT)
        assert result["has_conflict"] is True
        assert len(result["conflicts"]) == 1
        assert result["conflicts"][0]["coupon_type"] == "cash"

    @pytest.mark.asyncio
    async def test_different_types_ok(self):
        coupons = [
            {"coupon_type": "cash", "face_value_fen": 500},
            {"coupon_type": "discount", "discount_rate": 90},
        ]
        result = await check_stacking_rules(coupons, "order_001", TENANT)
        assert result["has_conflict"] is False
        assert len(result["applicable_coupons"]) == 2

    @pytest.mark.asyncio
    async def test_priority_order(self):
        coupons = [
            {"coupon_type": "cash", "face_value_fen": 500},
            {"coupon_type": "free_item", "item_dish_id": "d1"},
            {"coupon_type": "discount", "discount_rate": 80},
        ]
        result = await check_stacking_rules(coupons, "order_001", TENANT)
        types_order = [c["coupon_type"] for c in result["applicable_coupons"]]
        assert types_order.index("free_item") < types_order.index("discount")
        assert types_order.index("discount") < types_order.index("cash")


# ---------------------------------------------------------------------------
# 6. 计算优惠
# ---------------------------------------------------------------------------


class TestCalculateDiscount:
    @pytest.mark.asyncio
    async def test_cash_coupon_discount(self):
        order = {"order_id": "o1", "total_fen": 10000, "items": [], "delivery_fee_fen": 0}
        coupons = [{"coupon_type": "cash", "face_value_fen": 1500}]
        result = await calculate_discount(coupons, order, TENANT)
        assert result["total_discount_fen"] == 1500
        assert result["final_amount_fen"] == 8500

    @pytest.mark.asyncio
    async def test_discount_coupon(self):
        order = {"order_id": "o1", "total_fen": 10000, "items": [], "delivery_fee_fen": 0}
        coupons = [{"coupon_type": "discount", "discount_rate": 80}]
        result = await calculate_discount(coupons, order, TENANT)
        assert result["total_discount_fen"] == 2000
        assert result["final_amount_fen"] == 8000

    @pytest.mark.asyncio
    async def test_cash_no_change(self):
        """代金券不找零：优惠不超过订单金额"""
        order = {"order_id": "o1", "total_fen": 500, "items": [], "delivery_fee_fen": 0}
        coupons = [{"coupon_type": "cash", "face_value_fen": 1000}]
        result = await calculate_discount(coupons, order, TENANT)
        assert result["total_discount_fen"] == 500
        assert result["final_amount_fen"] == 0

    @pytest.mark.asyncio
    async def test_delivery_coupon(self):
        order = {"order_id": "o1", "total_fen": 5000, "items": [], "delivery_fee_fen": 600}
        coupons = [{"coupon_type": "delivery", "face_value_fen": 600}]
        result = await calculate_discount(coupons, order, TENANT)
        assert result["total_discount_fen"] == 600

    @pytest.mark.asyncio
    async def test_free_item_coupon(self):
        order = {
            "order_id": "o1",
            "total_fen": 5000,
            "items": [{"dish_id": "d1", "price_fen": 2000, "quantity": 1}],
            "delivery_fee_fen": 0,
        }
        coupons = [{"coupon_type": "free_item", "item_dish_id": "d1"}]
        result = await calculate_discount(coupons, order, TENANT)
        assert result["total_discount_fen"] == 2000

    @pytest.mark.asyncio
    async def test_min_amount_not_met(self):
        order = {"order_id": "o1", "total_fen": 5000, "items": [], "delivery_fee_fen": 0}
        coupons = [{"coupon_type": "cash", "face_value_fen": 1000, "min_order_amount_fen": 10000}]
        result = await calculate_discount(coupons, order, TENANT)
        assert result["total_discount_fen"] == 0
        assert "未达门槛" in result["details"][0]["reason"]

    @pytest.mark.asyncio
    async def test_multi_type_stacking(self):
        """不同类型叠加：商品券 + 折扣券 + 代金券"""
        order = {
            "order_id": "o1",
            "total_fen": 10000,
            "items": [{"dish_id": "d1", "price_fen": 3000, "quantity": 1}],
            "delivery_fee_fen": 0,
        }
        coupons = [
            {"coupon_type": "free_item", "item_dish_id": "d1"},  # -3000
            {"coupon_type": "discount", "discount_rate": 90},  # 7000 * 10% = -700
            {"coupon_type": "cash", "face_value_fen": 500},  # -500
        ]
        result = await calculate_discount(coupons, order, TENANT)
        assert result["total_discount_fen"] == 3000 + 700 + 500


# ---------------------------------------------------------------------------
# 7. 收入规则
# ---------------------------------------------------------------------------


class TestRevenueRule:
    @pytest.mark.asyncio
    async def test_set_rule(self):
        tpl = await create_coupon("cash", {"face_value_fen": 1000}, TENANT)
        result = await set_revenue_rule(
            tpl["coupon_id"],
            {"count_as_revenue": True, "revenue_ratio": 0.5},
            TENANT,
        )
        assert result["count_as_revenue"] is True
        assert result["revenue_ratio"] == 0.5

    @pytest.mark.asyncio
    async def test_set_rule_wrong_tenant(self):
        tpl = await create_coupon("cash", {"face_value_fen": 1000}, TENANT)
        with pytest.raises(ValueError, match="租户不匹配"):
            await set_revenue_rule(tpl["coupon_id"], {}, "other")


# ---------------------------------------------------------------------------
# 8. 统计
# ---------------------------------------------------------------------------


class TestCouponStats:
    @pytest.mark.asyncio
    async def test_stats_basic(self):
        tpl = await create_coupon("cash", {"face_value_fen": 500}, TENANT)
        await batch_issue(tpl["coupon_id"], ["c1", "c2"], TENANT)
        result = await get_coupon_stats(TENANT, ("2020-01-01", "2030-12-31"))
        assert result["total_issued"] == 2

    @pytest.mark.asyncio
    async def test_stats_with_redemption(self):
        tpl = await create_coupon("cash", {"face_value_fen": 500}, TENANT)
        issued = await batch_issue(tpl["coupon_id"], ["c1"], TENANT)
        code = issued["issued"][0]["code"]
        await redeem_coupon(code, "order_001", TENANT)
        result = await get_coupon_stats(TENANT, ("2020-01-01", "2030-12-31"))
        assert result["total_redeemed"] == 1
        assert result["total_cost_fen"] == 500
