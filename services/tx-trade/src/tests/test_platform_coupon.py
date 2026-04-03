"""平台团购核销引擎测试

覆盖场景：
1. 券码平台识别 — 美团(18位数字)
2. 券码平台识别 — 抖音(DY开头)
3. 券码平台识别 — 口碑(KB开头)
4. 券码平台识别 — 广发银行(GF开头)
5. 券码平台识别 — 无法识别
6. 聚合验证 — 自动识别美团并验证
7. 聚合验证 — 无法识别平台
8. 核销 — 关联 order_id 成功
9. 核销 — 缺少 order_id 报错
10. 核销 — 已核销的券不可重复核销
11. 核销对账报告 — 按平台汇总
12. 平台对账 — 金额比对
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import uuid
from datetime import datetime, timezone

import pytest

# ─── 辅助 ───


def _uid() -> str:
    return str(uuid.uuid4())


TENANT_ID = _uid()
STORE_ID = _uid()


class FakeResult:
    def __init__(self, scalar=None):
        self._scalar = scalar

    def scalar_one_or_none(self):
        return self._scalar


class FakeSession:
    async def execute(self, stmt, *args, **kwargs):
        return FakeResult()

    async def flush(self):
        pass


# ─── 1-5: 券码平台识别 ───


def test_identify_platform_meituan():
    """识别美团券码 — 18位纯数字"""
    from services.coupon_platform_service import identify_platform

    assert identify_platform("123456789012345678") == "meituan"


def test_identify_platform_douyin():
    """识别抖音券码 — DY 开头"""
    from services.coupon_platform_service import identify_platform

    assert identify_platform("DY20260327ABC123") == "douyin"


def test_identify_platform_koubei():
    """识别口碑券码 — KB 开头"""
    from services.coupon_platform_service import identify_platform

    assert identify_platform("KB98765432100") == "koubei"


def test_identify_platform_bank_gf():
    """识别广发银行券码 — GF 开头"""
    from services.coupon_platform_service import identify_platform

    assert identify_platform("GF2026032700001") == "bank_gf"


def test_identify_platform_unknown():
    """无法识别的券码格式"""
    from services.coupon_platform_service import identify_platform

    assert identify_platform("UNKNOWN12345") is None
    assert identify_platform("") is None
    assert identify_platform("12345") is None  # 不足18位纯数字


# ─── 6-7: 聚合验证 ───


@pytest.mark.asyncio
async def test_aggregate_verify_meituan():
    """聚合验证 — 自动识别美团并验证"""
    from services.coupon_platform_service import _PlatformCouponStore, aggregate_verify

    _PlatformCouponStore.clear()
    db = FakeSession()

    code = "123456789012345678"
    result = await aggregate_verify(code, STORE_ID, TENANT_ID, db)

    assert result["valid"] is True
    assert result["platform"] == "meituan"
    assert result["platform_name"] == "美团"
    assert result["deal_amount_fen"] > 0


@pytest.mark.asyncio
async def test_aggregate_verify_unknown_platform():
    """聚合验证 — 无法识别平台"""
    from services.coupon_platform_service import _PlatformCouponStore, aggregate_verify

    _PlatformCouponStore.clear()
    db = FakeSession()

    result = await aggregate_verify("BADCODE", STORE_ID, TENANT_ID, db)
    assert result["valid"] is False
    assert result["platform"] is None
    assert "无法识别" in result["reason"]


# ─── 8-10: 核销 ───


@pytest.mark.asyncio
async def test_redeem_coupon_success():
    """核销 — 关联 order_id 成功"""
    from services.coupon_platform_service import (
        _PlatformCouponStore,
        aggregate_verify,
        redeem_coupon,
    )

    _PlatformCouponStore.clear()
    db = FakeSession()
    order_id = _uid()
    code = "DYredeemtest001"

    # 先验证（触发 mock 创建）
    verify_result = await aggregate_verify(code, STORE_ID, TENANT_ID, db)
    assert verify_result["valid"] is True

    # 核销
    result = await redeem_coupon("douyin", code, order_id, TENANT_ID, db)
    assert result["order_id"] == order_id
    assert result["platform"] == "douyin"
    assert result["redeemed_at"] is not None


@pytest.mark.asyncio
async def test_redeem_coupon_missing_order_id():
    """核销 — 缺少 order_id 报错"""
    from services.coupon_platform_service import _PlatformCouponStore, redeem_coupon

    _PlatformCouponStore.clear()
    db = FakeSession()

    with pytest.raises(ValueError, match="order_id"):
        await redeem_coupon("meituan", "123456789012345678", "", TENANT_ID, db)


@pytest.mark.asyncio
async def test_redeem_coupon_already_redeemed():
    """核销 — 已核销的券不可重复核销"""
    from services.coupon_platform_service import (
        _PlatformCouponStore,
        aggregate_verify,
        redeem_coupon,
    )

    _PlatformCouponStore.clear()
    db = FakeSession()
    code = "KBredeemtwice01"
    order_id = _uid()

    await aggregate_verify(code, STORE_ID, TENANT_ID, db)
    await redeem_coupon("koubei", code, order_id, TENANT_ID, db)

    # 第二次核销应失败
    with pytest.raises(ValueError, match="状态异常"):
        await redeem_coupon("koubei", code, _uid(), TENANT_ID, db)


# ─── 11: 核销对账报告 ───


@pytest.mark.asyncio
async def test_redemption_report():
    """核销对账报告 — 按平台汇总"""
    from services.coupon_platform_service import (
        _PlatformCouponStore,
        aggregate_verify,
        get_redemption_report,
        redeem_coupon,
    )

    _PlatformCouponStore.clear()
    db = FakeSession()

    # 核销两张不同平台的券
    code_mt = "111111111111111111"
    code_dy = "DYreport0000001"

    await aggregate_verify(code_mt, STORE_ID, TENANT_ID, db)
    await redeem_coupon("meituan", code_mt, _uid(), TENANT_ID, db)

    await aggregate_verify(code_dy, STORE_ID, TENANT_ID, db)
    await redeem_coupon("douyin", code_dy, _uid(), TENANT_ID, db)

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    report = await get_redemption_report(
        STORE_ID, (today, today), TENANT_ID, db,
    )

    assert report["record_count"] == 2
    assert report["total_amount_fen"] > 0
    assert "meituan" in report["by_platform"]
    assert "douyin" in report["by_platform"]
    assert report["by_platform"]["meituan"]["count"] == 1
    assert report["by_platform"]["douyin"]["count"] == 1


# ─── 12: 平台对账 ───


@pytest.mark.asyncio
async def test_reconcile_platform():
    """平台对账 — 金额比对"""
    from services.coupon_platform_service import (
        _PlatformCouponStore,
        aggregate_verify,
        reconcile_platform,
        redeem_coupon,
    )

    _PlatformCouponStore.clear()
    db = FakeSession()

    code = "GFreconcile0001"
    await aggregate_verify(code, STORE_ID, TENANT_ID, db)
    await redeem_coupon("bank_gf", code, _uid(), TENANT_ID, db)

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    result = await reconcile_platform("bank_gf", STORE_ID, today, TENANT_ID, db)

    assert result["is_matched"] is True
    assert result["platform"] == "bank_gf"
    assert result["system"]["count"] == 1
    assert result["diff"]["amount_fen"] == 0
