"""券权益与会员识别服务测试

覆盖场景：
1. 会员识别 — 未找到
2. 储值卡开卡
3. 储值充值
4. 储值消费（余额充足）
5. 储值消费（余额不足）
6. 券验证 — 不存在
7. 券验证 + 核销流程
8. 权益冲突校验（同类型不叠加）
9. 权益冲突校验（不同类型可叠加）
10. 会员价计算（S1 VIP 8.5折）
11. 券核销审计
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import uuid
from datetime import datetime, timedelta, timezone

import pytest

# ─── 模拟对象 ───


def _uid() -> str:
    return str(uuid.uuid4())


TENANT_ID = _uid()


class FakeRow:
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)


class FakeResult:
    def __init__(self, scalar=None):
        self._scalar = scalar

    def scalar_one_or_none(self):
        return self._scalar


class FakeSession:
    def __init__(self):
        self._execute_results = []
        self._idx = 0

    async def execute(self, stmt, *args, **kwargs):
        if self._idx < len(self._execute_results):
            r = self._execute_results[self._idx]
            self._idx += 1
            return r
        return FakeResult()

    async def flush(self):
        pass


# ─── 测试：会员识别 ───


@pytest.mark.asyncio
async def test_identify_member_not_found():
    """会员识别 — 手机号不存在"""
    from services.coupon_service import identify_member

    db = FakeSession()
    db._execute_results = [FakeResult(scalar=None)]

    result = await identify_member("13800000000", TENANT_ID, db)
    assert result["found"] is False


# ─── 测试：储值卡 ───


@pytest.mark.asyncio
async def test_create_stored_value_card():
    """储值卡开卡"""
    from services.coupon_service import _StoredValueStore, create_stored_value_card

    _StoredValueStore._cards.clear()
    db = FakeSession()

    result = await create_stored_value_card(
        customer_id=_uid(),
        initial_amount_fen=50000,
        tenant_id=TENANT_ID,
        db=db,
    )
    assert result["balance_fen"] == 50000
    assert result["status"] == "active"
    assert result["card_id"] is not None


@pytest.mark.asyncio
async def test_recharge():
    """储值充值"""
    from services.coupon_service import _StoredValueStore, create_stored_value_card, recharge

    _StoredValueStore._cards.clear()
    db = FakeSession()

    card = await create_stored_value_card(_uid(), 10000, TENANT_ID, db)
    result = await recharge(card["card_id"], 20000, "wechat", TENANT_ID, db)
    assert result["balance_fen"] == 30000


@pytest.mark.asyncio
async def test_deduct_stored_value_success():
    """储值消费 — 余额充足"""
    from services.coupon_service import _StoredValueStore, create_stored_value_card, deduct_stored_value

    _StoredValueStore._cards.clear()
    db = FakeSession()

    card = await create_stored_value_card(_uid(), 50000, TENANT_ID, db)
    result = await deduct_stored_value(card["card_id"], 20000, _uid(), TENANT_ID, db)
    assert result["balance_fen"] == 30000
    assert result["deducted_fen"] == 20000


@pytest.mark.asyncio
async def test_deduct_stored_value_insufficient():
    """储值消费 — 余额不足"""
    from services.coupon_service import _StoredValueStore, create_stored_value_card, deduct_stored_value

    _StoredValueStore._cards.clear()
    db = FakeSession()

    card = await create_stored_value_card(_uid(), 5000, TENANT_ID, db)
    with pytest.raises(ValueError, match="余额不足"):
        await deduct_stored_value(card["card_id"], 10000, _uid(), TENANT_ID, db)


# ─── 测试：券验证与核销 ───


@pytest.mark.asyncio
async def test_verify_coupon_not_found():
    """券验证 — 券不存在"""
    from services.coupon_service import verify_coupon

    db = FakeSession()
    result = await verify_coupon("INVALID_CODE", _uid(), TENANT_ID, db)
    assert result["valid"] is False
    assert "不存在" in result["reason"]


@pytest.mark.asyncio
async def test_verify_and_redeem_coupon():
    """券验证 + 核销流程"""
    from services.coupon_service import _CouponStore, redeem_coupon, verify_coupon

    _CouponStore._coupons.clear()

    coupon_code = "COUPON2026"
    _CouponStore.save(
        coupon_code,
        {
            "coupon_code": coupon_code,
            "tenant_id": TENANT_ID,
            "status": "active",
            "coupon_type": "general",
            "discount_fen": 1500,
            "min_order_amount_fen": 0,
            "stackable": True,
            "expires_at": (datetime.now(timezone.utc) + timedelta(days=30)).isoformat(),
        },
    )

    db = FakeSession()

    # 验证
    v = await verify_coupon(coupon_code, _uid(), TENANT_ID, db)
    assert v["valid"] is True
    assert v["discount_fen"] == 1500

    # 核销
    r = await redeem_coupon(coupon_code, _uid(), TENANT_ID, db)
    assert r["coupon_code"] == coupon_code
    assert r["discount_fen"] == 1500

    # 核销后再次验证应失败（状态已变为redeemed）
    v2 = await verify_coupon(coupon_code, _uid(), TENANT_ID, db)
    assert v2["valid"] is False


# ─── 测试：权益冲突校验 ───


@pytest.mark.asyncio
async def test_benefit_conflict_same_type():
    """同类型权益不叠加"""
    from services.coupon_service import check_benefit_conflict

    db = FakeSession()
    benefits = [
        {"benefit_type": "general", "code": "C1"},
        {"benefit_type": "general", "code": "C2"},
    ]
    result = await check_benefit_conflict(benefits, _uid(), TENANT_ID, db)
    assert result["has_conflict"] is True
    assert len(result["conflicts"]) == 1
    assert result["conflicts"][0]["benefit_type"] == "general"


@pytest.mark.asyncio
async def test_benefit_conflict_different_types():
    """不同类型权益可叠加"""
    from services.coupon_service import check_benefit_conflict

    db = FakeSession()
    benefits = [
        {"benefit_type": "member_price", "code": "MP1"},
        {"benefit_type": "activity", "code": "AC1"},
        {"benefit_type": "general", "code": "GC1"},
    ]
    result = await check_benefit_conflict(benefits, _uid(), TENANT_ID, db)
    assert result["has_conflict"] is False
    assert len(result["applicable_benefits"]) == 3
    # 验证优先级排序
    types = [b["benefit_type"] for b in result["applicable_benefits"]]
    assert types == ["member_price", "activity", "general"]


# ─── 测试：会员价计算 ───


@pytest.mark.asyncio
async def test_member_price_s1_vip():
    """S1 VIP 会员价 — 8.5折"""
    from services.coupon_service import calculate_member_price

    db = FakeSession()
    result = await calculate_member_price(_uid(), "S1", TENANT_ID, db)
    assert result["has_member_price"] is True
    assert result["discount_rate"] == 0.85


@pytest.mark.asyncio
async def test_member_price_s5_no_discount():
    """S5 普通会员 — 无折扣"""
    from services.coupon_service import calculate_member_price

    db = FakeSession()
    result = await calculate_member_price(_uid(), "S5", TENANT_ID, db)
    assert result["has_member_price"] is False
    assert result["discount_rate"] == 1.0


# ─── 测试：券核销审计 ───


@pytest.mark.asyncio
async def test_coupon_audit_empty():
    """券核销审计 — 无记录"""
    from services.coupon_service import _CouponStore, get_coupon_audit

    _CouponStore._coupons.clear()
    db = FakeSession()

    result = await get_coupon_audit(
        store_id=_uid(),
        date_range=("2026-03-01", "2026-03-31"),
        tenant_id=TENANT_ID,
        db=db,
    )
    assert result["record_count"] == 0
    assert result["total_discount_fen"] == 0
