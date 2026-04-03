"""支付直连测试

覆盖场景：
1. 微信支付下单
2. 支付宝支付下单
3. 银联支付下单
4. 查询支付状态
5. 查询不存在的支付报错
6. 退款（全额）
7. 退款（部分）
8. 退款金额超出报错
9. 并发支付（多渠道）
10. 风控检查 — 正常
11. 风控检查 — 大额预警
12. 风控检查 — 零金额拒绝
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import uuid

import pytest


def _uid() -> str:
    return str(uuid.uuid4())


TENANT_ID = _uid()


@pytest.fixture(autouse=True)
def _clear_stores():
    from services.payment_direct import _payments, _risk_records
    _payments.clear()
    _risk_records.clear()


@pytest.mark.asyncio
async def test_wechat_payment():
    """微信支付下单"""
    from services.payment_direct import create_wechat_payment

    result = await create_wechat_payment(
        order_id=_uid(), amount_fen=5000, tenant_id=TENANT_ID,
        openid="oXXX_mock_openid",
    )
    assert "prepay_id" in result
    assert result["appId"] == "wx_mock_app_id"
    assert result["signType"] == "RSA"
    assert "payment_id" in result


@pytest.mark.asyncio
async def test_alipay_payment():
    """支付宝支付下单"""
    from services.payment_direct import create_alipay_payment

    result = await create_alipay_payment(
        order_id=_uid(), amount_fen=8800, tenant_id=TENANT_ID,
        subject="测试订单",
    )
    assert result["trade_status"] == "TRADE_SUCCESS"
    assert result["total_amount"] == "88.00"
    assert "trade_no" in result


@pytest.mark.asyncio
async def test_unionpay_payment():
    """银联支付下单"""
    from services.payment_direct import create_unionpay_payment

    result = await create_unionpay_payment(
        order_id=_uid(), amount_fen=12000, tenant_id=TENANT_ID,
        card_no_masked="6222****1234",
    )
    assert result["respCode"] == "00"
    assert result["txnAmt"] == "12000"


@pytest.mark.asyncio
async def test_query_payment_status():
    """查询支付状态"""
    from services.payment_direct import create_wechat_payment, query_payment_status

    pay = await create_wechat_payment(
        order_id=_uid(), amount_fen=3000, tenant_id=TENANT_ID,
    )
    result = await query_payment_status(pay["payment_id"], TENANT_ID)
    assert result["status"] == "success"
    assert result["amount_fen"] == 3000


@pytest.mark.asyncio
async def test_query_payment_not_found():
    """查询不存在的支付"""
    from services.payment_direct import query_payment_status

    with pytest.raises(ValueError, match="Payment not found"):
        await query_payment_status("nonexistent", TENANT_ID)


@pytest.mark.asyncio
async def test_full_refund():
    """全额退款"""
    from services.payment_direct import create_wechat_payment, process_refund, query_payment_status

    pay = await create_wechat_payment(
        order_id=_uid(), amount_fen=5000, tenant_id=TENANT_ID,
    )
    result = await process_refund(pay["payment_id"], 5000, "客户要求", TENANT_ID)
    assert result["status"] == "refund_success"
    assert result["amount_fen"] == 5000

    status = await query_payment_status(pay["payment_id"], TENANT_ID)
    assert status["status"] == "refunded"


@pytest.mark.asyncio
async def test_partial_refund():
    """部分退款"""
    from services.payment_direct import create_alipay_payment, process_refund, query_payment_status

    pay = await create_alipay_payment(
        order_id=_uid(), amount_fen=10000, tenant_id=TENANT_ID,
    )
    result = await process_refund(pay["payment_id"], 3000, "部分退款", TENANT_ID)
    assert result["amount_fen"] == 3000

    status = await query_payment_status(pay["payment_id"], TENANT_ID)
    assert status["status"] == "partial_refund"


@pytest.mark.asyncio
async def test_refund_exceeds_amount():
    """退款金额超出"""
    from services.payment_direct import create_wechat_payment, process_refund

    pay = await create_wechat_payment(
        order_id=_uid(), amount_fen=5000, tenant_id=TENANT_ID,
    )
    with pytest.raises(ValueError, match="exceeds payment amount"):
        await process_refund(pay["payment_id"], 9999, "超额退款", TENANT_ID)


@pytest.mark.asyncio
async def test_concurrent_payment():
    """并发支付（多渠道）"""
    from services.payment_direct import handle_concurrent_payment

    result = await handle_concurrent_payment(
        order_id=_uid(),
        payments=[
            {"channel": "wechat", "amount_fen": 5000},
            {"channel": "alipay", "amount_fen": 3000},
        ],
        tenant_id=TENANT_ID,
    )
    assert result["all_success"] is True
    assert result["total_fen"] == 8000
    assert len(result["payments"]) == 2
    assert len(result["failed"]) == 0


@pytest.mark.asyncio
async def test_risk_check_normal():
    """风控检查 — 正常"""
    from services.payment_direct import get_payment_risk_check

    result = await get_payment_risk_check(
        order_id=_uid(), tenant_id=TENANT_ID,
        amount_fen=5000, payment_count_today=3,
    )
    assert result["risk_level"] == "low"
    assert result["allow"] is True
    assert result["requires_confirmation"] is False


@pytest.mark.asyncio
async def test_risk_check_large_amount():
    """风控检查 — 大额预警"""
    from services.payment_direct import get_payment_risk_check

    result = await get_payment_risk_check(
        order_id=_uid(), tenant_id=TENANT_ID,
        amount_fen=200000,
    )
    assert result["risk_level"] == "high"
    assert result["allow"] is True
    assert result["requires_confirmation"] is True


@pytest.mark.asyncio
async def test_risk_check_zero_amount():
    """风控检查 — 零金额拒绝"""
    from services.payment_direct import get_payment_risk_check

    result = await get_payment_risk_check(
        order_id=_uid(), tenant_id=TENANT_ID,
        amount_fen=0,
    )
    assert result["risk_level"] == "rejected"
    assert result["allow"] is False
