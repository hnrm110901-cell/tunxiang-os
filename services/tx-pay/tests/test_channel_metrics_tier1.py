"""tx-pay 渠道指标 Tier 1 测试

PR #195 的 infra/monitoring/prometheus/rules/tunxiang-alerts.yml 已加
PaymentChannelHighErrorRate 告警规则（消费 payment_channel_requests_total
{channel, status}），但该 metric 未被任何 service 暴露 —— 告警永不触发。

本测试验证：
  1. 每个 channel（wechat / alipay / lakala / shouqianba / stored_value / cash）
     在不同 HTTP 状态码（2xx / 4xx / 5xx / timeout / connect_error）下
     payment_channel_requests_total Counter 的 label 维度递增正确
  2. label 集合与告警规则消费方一致（channel × status 笛卡尔积合规）

Tier 1 评级：
  支付渠道错误率监控直接影响"支付成功率 > 99.9%" Week 8 验收门槛
  指标暴露错误 → 告警黑屏 → 渠道侧故障无法及时降级 → 客户流失
"""

from __future__ import annotations

import httpx
import pytest

from services.tx_pay.src.channels.alipay import AlipayChannel
from services.tx_pay.src.channels.base import (
    PaymentRequest,
    PayMethod,
    TradeType,
)
from services.tx_pay.src.channels.cash import CashChannel
from services.tx_pay.src.channels.lakala import LakalaChannel
from services.tx_pay.src.channels.shouqianba import ShouqianbaChannel
from services.tx_pay.src.channels.stored_value import StoredValueChannel
from services.tx_pay.src.channels.wechat import WechatPayChannel
from services.tx_pay.src.metrics import payment_channel_requests_total


def _counter_value(channel: str, status: str) -> float:
    """读取 payment_channel_requests_total{channel, status} 当前值"""
    return payment_channel_requests_total.labels(channel=channel, status=status)._value.get()


def _delta(channel: str, status: str, before: float) -> float:
    return _counter_value(channel, status) - before


def _make_request(
    method: PayMethod,
    *,
    metadata: dict | None = None,
    trade_type: TradeType = TradeType.B2C,
    auth_code: str | None = "AUTH_CODE_123",
) -> PaymentRequest:
    return PaymentRequest(
        tenant_id="tenant-test",
        store_id="store-test",
        order_id="order-test-001",
        amount_fen=8800,
        method=method,
        trade_type=trade_type,
        auth_code=auth_code,
        description="Tier1 测试订单",
        metadata=metadata or {},
    )


# ─── Mock 客户端（模拟 httpx 异常 / HTTP 状态码） ───────────────────


class _MockHttpResp:
    def __init__(self, status_code: int, body: dict | None = None) -> None:
        self.status_code = status_code
        self._body = body or {}

    def json(self) -> dict:
        return self._body


class _MockHttpClient:
    """模拟 httpx.AsyncClient — 按指定方式响应 / 抛异常"""

    def __init__(self, *, raise_exc: Exception | None = None, resp: _MockHttpResp | None = None) -> None:
        self._raise = raise_exc
        self._resp = resp

    async def post(self, *_args, **_kwargs) -> _MockHttpResp:
        if self._raise is not None:
            raise self._raise
        assert self._resp is not None
        return self._resp


class _MockAggregatorClient:
    """模拟 LakalaClient / ShouqianbaClient — 仅用于 timeout/connect 异常分支"""

    def __init__(self, raise_exc: Exception | None = None) -> None:
        self._raise = raise_exc

    async def micropay(self, **_kwargs) -> dict:
        if self._raise:
            raise self._raise
        return {"trade_state": "SUCCESS", "channel_trade_no": "ok"}

    async def create_qr(self, **_kwargs) -> dict:
        return await self.micropay()

    async def pay(self, **_kwargs) -> dict:
        if self._raise:
            raise self._raise
        return {"order_status": "PAID", "sn": "sn-ok"}

    async def precreate(self, **_kwargs) -> dict:
        return await self.pay()


# ─── Tier 1 测试 ────────────────────────────────────────────────────


class TestChannelMetricsTier1:
    """渠道指标暴露：六个渠道 × 五种状态的 label 维度验证"""

    @pytest.mark.asyncio
    async def test_cash_pay_inc_2xx(self) -> None:
        """现金支付：每次 pay() 必须 inc(channel=cash, status=2xx)"""
        before = _counter_value("cash", "2xx")
        ch = CashChannel()
        await ch.pay(_make_request(PayMethod.CASH, metadata={"tendered_fen": 10000}))
        assert _delta("cash", "2xx", before) == 1.0

    @pytest.mark.asyncio
    async def test_alipay_mock_pay_inc_2xx(self) -> None:
        """支付宝 Mock 骨架：pay() 必须 inc(channel=alipay, status=2xx)"""
        before = _counter_value("alipay", "2xx")
        ch = AlipayChannel()
        await ch.pay(_make_request(PayMethod.ALIPAY))
        assert _delta("alipay", "2xx", before) == 1.0

    @pytest.mark.asyncio
    async def test_wechat_mock_pay_inc_2xx(self) -> None:
        """微信 Mock 模式（无 _service）：pay() 必须 inc(channel=wechat, status=2xx)

        说明：用 __new__ 绕过 __init__，避免在 Python 3.9 测试环境中触发
        shared.integrations.wechat_pay（生产 3.11+）的语法兼容性问题。
        """
        before = _counter_value("wechat", "2xx")
        ch = WechatPayChannel.__new__(WechatPayChannel)
        ch._notify_url = ""
        ch._service = None  # 强制 Mock 路径
        await ch.pay(_make_request(PayMethod.WECHAT))
        assert _delta("wechat", "2xx", before) == 1.0

    @pytest.mark.asyncio
    async def test_lakala_mock_pay_inc_2xx(self) -> None:
        """拉卡拉 Mock 模式（client=None）：pay() 必须 inc(channel=lakala, status=2xx)"""
        before = _counter_value("lakala", "2xx")
        ch = LakalaChannel(client=None)
        await ch.pay(_make_request(PayMethod.WECHAT))
        assert _delta("lakala", "2xx", before) == 1.0

    @pytest.mark.asyncio
    async def test_shouqianba_mock_pay_inc_2xx(self) -> None:
        """收钱吧 Mock 模式（client=None）：pay() 必须 inc(channel=shouqianba, status=2xx)"""
        before = _counter_value("shouqianba", "2xx")
        ch = ShouqianbaChannel(client=None)
        await ch.pay(_make_request(PayMethod.WECHAT))
        assert _delta("shouqianba", "2xx", before) == 1.0

    @pytest.mark.asyncio
    async def test_stored_value_mock_pay_inc_2xx(self) -> None:
        """储值 Mock 模式（http_client=None）：pay() 必须 inc(channel=stored_value, status=2xx)"""
        before = _counter_value("stored_value", "2xx")
        ch = StoredValueChannel(http_client=None)
        await ch.pay(_make_request(PayMethod.MEMBER_BALANCE, metadata={"member_id": "m-1"}))
        assert _delta("stored_value", "2xx", before) == 1.0

    @pytest.mark.asyncio
    async def test_stored_value_4xx_on_missing_member_id(self) -> None:
        """储值缺失 member_id：等价 4xx（HTTP 调用前的入参拒绝）"""
        before = _counter_value("stored_value", "4xx")
        # 必须传一个非 None 的 http_client，否则会先走 Mock 分支
        ch = StoredValueChannel(http_client=_MockHttpClient(resp=_MockHttpResp(200, {"data": {}})))
        await ch.pay(_make_request(PayMethod.MEMBER_BALANCE, metadata={}))
        assert _delta("stored_value", "4xx", before) == 1.0

    @pytest.mark.asyncio
    async def test_stored_value_5xx_on_server_error(self) -> None:
        """储值上游 500：必须 inc(channel=stored_value, status=5xx)"""
        before = _counter_value("stored_value", "5xx")
        ch = StoredValueChannel(
            http_client=_MockHttpClient(resp=_MockHttpResp(503, {"error": {"code": "X", "message": "y"}})),
        )
        await ch.pay(_make_request(PayMethod.MEMBER_BALANCE, metadata={"member_id": "m-1"}))
        assert _delta("stored_value", "5xx", before) == 1.0

    @pytest.mark.asyncio
    async def test_stored_value_timeout_label(self) -> None:
        """httpx.TimeoutException：必须 inc(status=timeout) 且向上抛"""
        before = _counter_value("stored_value", "timeout")
        ch = StoredValueChannel(http_client=_MockHttpClient(raise_exc=httpx.TimeoutException("slow")))
        with pytest.raises(httpx.TimeoutException):
            await ch.pay(_make_request(PayMethod.MEMBER_BALANCE, metadata={"member_id": "m-1"}))
        assert _delta("stored_value", "timeout", before) == 1.0

    @pytest.mark.asyncio
    async def test_lakala_connect_error_label(self) -> None:
        """LakalaChannel 上游连接失败：必须 inc(channel=lakala, status=connect_error)"""
        before = _counter_value("lakala", "connect_error")
        ch = LakalaChannel(client=_MockAggregatorClient(raise_exc=httpx.ConnectError("dns fail")))
        with pytest.raises(httpx.ConnectError):
            await ch.pay(_make_request(PayMethod.WECHAT))
        assert _delta("lakala", "connect_error", before) == 1.0

    @pytest.mark.asyncio
    async def test_shouqianba_timeout_label(self) -> None:
        """ShouqianbaChannel 上游超时：必须 inc(channel=shouqianba, status=timeout)"""
        before = _counter_value("shouqianba", "timeout")
        ch = ShouqianbaChannel(client=_MockAggregatorClient(raise_exc=httpx.TimeoutException("slow")))
        with pytest.raises(httpx.TimeoutException):
            await ch.pay(_make_request(PayMethod.WECHAT))
        assert _delta("shouqianba", "timeout", before) == 1.0

    def test_metric_label_set_matches_alert_rule(self) -> None:
        """label 集合必须与 PaymentChannelHighErrorRate 告警规则消费的维度一致"""
        # Counter 定义：channel × status
        assert payment_channel_requests_total._labelnames == ("channel", "status")
        # 告警规则只用 status="5xx" 计算分子，本测试触达过 5xx label
        # 至少一次 label 实例化，确保 metric 已注册到默认 registry
        payment_channel_requests_total.labels(channel="wechat", status="5xx")
        payment_channel_requests_total.labels(channel="alipay", status="5xx")
        # 不抛异常即视为合规


# ─── Follow-up（verifier 第三轮 P1）：query / refund / verify_callback inc ───
#
# 上面的 TestChannelMetricsTier1 仅覆盖 pay() 路径，verifier 指出多阶段支付
# (查单/退款/回调) 的 5xx 也应触发 PaymentChannelHighErrorRate 告警，否则
# 监控存在盲区。本 class 覆盖 7 渠道 × {query, refund} + wechat verify_callback。


class _MockAggregatorClientWithQueryRefund:
    """模拟 LakalaClient / ShouqianbaClient — 含 query/refund 异常分支"""

    def __init__(self, raise_exc: Exception | None = None) -> None:
        self._raise = raise_exc

    async def query(self, **_kwargs) -> dict:
        if self._raise:
            raise self._raise
        return {"trade_state": "SUCCESS", "order_status": "PAID", "channel_trade_no": "ok", "sn": "ok"}

    async def refund(self, **_kwargs) -> dict:
        if self._raise:
            raise self._raise
        return {"result_code": "SUCCESS", "refund_trade_no": "ref-ok", "sn": "ok"}


class _MockWechatService:
    """模拟 shared.integrations.wechat_pay.WechatPayService"""

    def __init__(self, raise_exc: Exception | None = None, callback_data: dict | None = None) -> None:
        self._raise = raise_exc
        self._callback = callback_data or {
            "out_trade_no": "WX123",
            "transaction_id": "txn_ok",
            "amount": {"total": 100},
        }

    async def query_order(self, _payment_id: str) -> dict:
        if self._raise:
            raise self._raise
        return {
            "trade_state": "SUCCESS",
            "amount": {"total": 100},
            "transaction_id": "txn_ok",
        }

    async def refund(self, **_kwargs) -> dict:
        if self._raise:
            raise self._raise
        return {"status": "SUCCESS", "refund_id": "rid_ok"}

    async def verify_callback(self, _headers: dict, _body: bytes) -> dict:
        if self._raise:
            raise self._raise
        return self._callback


class TestQueryRefundCallbackBlindspots:
    """query / refund / verify_callback 路径的 metric inc 覆盖 — verifier P1"""

    # ─── Mock 路径：query/refund 应 inc(2xx) ──────────────────────────

    @pytest.mark.asyncio
    async def test_alipay_query_mock_inc_2xx(self) -> None:
        before = _counter_value("alipay", "2xx")
        ch = AlipayChannel()
        await ch.query("p-1")
        assert _delta("alipay", "2xx", before) == 1.0

    @pytest.mark.asyncio
    async def test_alipay_refund_mock_inc_2xx(self) -> None:
        before = _counter_value("alipay", "2xx")
        ch = AlipayChannel()
        await ch.refund("p-1", 100)
        assert _delta("alipay", "2xx", before) == 1.0

    @pytest.mark.asyncio
    async def test_cash_query_inc_2xx(self) -> None:
        before = _counter_value("cash", "2xx")
        ch = CashChannel()
        await ch.query("p-1")
        assert _delta("cash", "2xx", before) == 1.0

    @pytest.mark.asyncio
    async def test_cash_refund_inc_2xx(self) -> None:
        before = _counter_value("cash", "2xx")
        ch = CashChannel()
        await ch.refund("p-1", 100)
        assert _delta("cash", "2xx", before) == 1.0

    @pytest.mark.asyncio
    async def test_stored_value_query_mock_inc_2xx(self) -> None:
        before = _counter_value("stored_value", "2xx")
        ch = StoredValueChannel(http_client=None)
        await ch.query("p-1")
        assert _delta("stored_value", "2xx", before) == 1.0

    @pytest.mark.asyncio
    async def test_stored_value_refund_mock_inc_2xx(self) -> None:
        before = _counter_value("stored_value", "2xx")
        ch = StoredValueChannel(http_client=None)
        await ch.refund("p-1", 100)
        assert _delta("stored_value", "2xx", before) == 1.0

    @pytest.mark.asyncio
    async def test_lakala_query_mock_inc_2xx(self) -> None:
        before = _counter_value("lakala", "2xx")
        ch = LakalaChannel(client=None)
        await ch.query("p-1")
        assert _delta("lakala", "2xx", before) == 1.0

    @pytest.mark.asyncio
    async def test_lakala_refund_mock_inc_2xx(self) -> None:
        before = _counter_value("lakala", "2xx")
        ch = LakalaChannel(client=None)
        await ch.refund("p-1", 100)
        assert _delta("lakala", "2xx", before) == 1.0

    @pytest.mark.asyncio
    async def test_shouqianba_query_mock_inc_2xx(self) -> None:
        before = _counter_value("shouqianba", "2xx")
        ch = ShouqianbaChannel(client=None)
        await ch.query("p-1")
        assert _delta("shouqianba", "2xx", before) == 1.0

    @pytest.mark.asyncio
    async def test_shouqianba_refund_mock_inc_2xx(self) -> None:
        before = _counter_value("shouqianba", "2xx")
        ch = ShouqianbaChannel(client=None)
        await ch.refund("p-1", 100)
        assert _delta("shouqianba", "2xx", before) == 1.0

    # ─── 真 client 异常分支：query/refund timeout / connect_error ─────

    @pytest.mark.asyncio
    async def test_lakala_query_timeout_inc(self) -> None:
        before = _counter_value("lakala", "timeout")
        ch = LakalaChannel(client=_MockAggregatorClientWithQueryRefund(raise_exc=httpx.TimeoutException("slow")))
        with pytest.raises(httpx.TimeoutException):
            await ch.query("p-1")
        assert _delta("lakala", "timeout", before) == 1.0

    @pytest.mark.asyncio
    async def test_lakala_refund_connect_error_inc(self) -> None:
        before = _counter_value("lakala", "connect_error")
        ch = LakalaChannel(client=_MockAggregatorClientWithQueryRefund(raise_exc=httpx.ConnectError("dns fail")))
        with pytest.raises(httpx.ConnectError):
            await ch.refund("p-1", 100)
        assert _delta("lakala", "connect_error", before) == 1.0

    @pytest.mark.asyncio
    async def test_shouqianba_query_timeout_inc(self) -> None:
        before = _counter_value("shouqianba", "timeout")
        ch = ShouqianbaChannel(client=_MockAggregatorClientWithQueryRefund(raise_exc=httpx.TimeoutException("slow")))
        with pytest.raises(httpx.TimeoutException):
            await ch.query("p-1")
        assert _delta("shouqianba", "timeout", before) == 1.0

    @pytest.mark.asyncio
    async def test_shouqianba_refund_connect_error_inc(self) -> None:
        before = _counter_value("shouqianba", "connect_error")
        ch = ShouqianbaChannel(
            client=_MockAggregatorClientWithQueryRefund(raise_exc=httpx.ConnectError("dns fail"))
        )
        with pytest.raises(httpx.ConnectError):
            await ch.refund("p-1", 100)
        assert _delta("shouqianba", "connect_error", before) == 1.0

    @pytest.mark.asyncio
    async def test_stored_value_refund_timeout_inc(self) -> None:
        before = _counter_value("stored_value", "timeout")
        ch = StoredValueChannel(http_client=_MockHttpClient(raise_exc=httpx.TimeoutException("slow")))
        with pytest.raises(httpx.TimeoutException):
            await ch.refund("p-1", 100)
        assert _delta("stored_value", "timeout", before) == 1.0

    @pytest.mark.asyncio
    async def test_stored_value_refund_5xx_inc(self) -> None:
        before = _counter_value("stored_value", "5xx")
        ch = StoredValueChannel(http_client=_MockHttpClient(resp=_MockHttpResp(503)))
        await ch.refund("p-1", 100)
        assert _delta("stored_value", "5xx", before) == 1.0

    # ─── wechat 三方法（query/refund/verify_callback）路径 ────────────

    @pytest.mark.asyncio
    async def test_wechat_mock_query_inc_2xx(self) -> None:
        before = _counter_value("wechat", "2xx")
        ch = WechatPayChannel.__new__(WechatPayChannel)
        ch._notify_url = ""
        ch._service = None
        await ch.query("WX123")
        assert _delta("wechat", "2xx", before) == 1.0

    @pytest.mark.asyncio
    async def test_wechat_mock_refund_inc_2xx(self) -> None:
        before = _counter_value("wechat", "2xx")
        ch = WechatPayChannel.__new__(WechatPayChannel)
        ch._notify_url = ""
        ch._service = None
        await ch.refund("WX123", 100)
        assert _delta("wechat", "2xx", before) == 1.0

    @pytest.mark.asyncio
    async def test_wechat_real_query_timeout_inc(self) -> None:
        before = _counter_value("wechat", "timeout")
        ch = WechatPayChannel.__new__(WechatPayChannel)
        ch._notify_url = ""
        ch._service = _MockWechatService(raise_exc=httpx.TimeoutException("slow"))
        with pytest.raises(httpx.TimeoutException):
            await ch.query("WX123")
        assert _delta("wechat", "timeout", before) == 1.0

    @pytest.mark.asyncio
    async def test_wechat_real_refund_connect_error_inc(self) -> None:
        before = _counter_value("wechat", "connect_error")
        ch = WechatPayChannel.__new__(WechatPayChannel)
        ch._notify_url = ""
        ch._service = _MockWechatService(raise_exc=httpx.ConnectError("dns fail"))
        with pytest.raises(httpx.ConnectError):
            await ch.refund("WX123", 100)
        assert _delta("wechat", "connect_error", before) == 1.0

    @pytest.mark.asyncio
    async def test_wechat_real_query_2xx(self) -> None:
        before = _counter_value("wechat", "2xx")
        ch = WechatPayChannel.__new__(WechatPayChannel)
        ch._notify_url = ""
        ch._service = _MockWechatService()  # 正常返回
        await ch.query("WX123")
        assert _delta("wechat", "2xx", before) == 1.0

    @pytest.mark.asyncio
    async def test_wechat_verify_callback_signature_invalid_4xx(self) -> None:
        """微信回调签名校验失败 → ValueError → inc(4xx)"""
        before = _counter_value("wechat", "4xx")
        ch = WechatPayChannel.__new__(WechatPayChannel)
        ch._notify_url = ""
        ch._service = _MockWechatService(raise_exc=ValueError("bad sig"))
        with pytest.raises(ValueError):
            await ch.verify_callback({}, b"")
        assert _delta("wechat", "4xx", before) == 1.0

    @pytest.mark.asyncio
    async def test_wechat_verify_callback_2xx(self) -> None:
        before = _counter_value("wechat", "2xx")
        ch = WechatPayChannel.__new__(WechatPayChannel)
        ch._notify_url = ""
        ch._service = _MockWechatService()
        await ch.verify_callback({}, b"")
        assert _delta("wechat", "2xx", before) == 1.0

    # ─── credit_account（PR #200 漏加 inc 的渠道） ────────────────────

    @pytest.mark.asyncio
    async def test_credit_account_query_inc_2xx(self) -> None:
        from services.tx_pay.src.channels.credit_account import CreditAccountChannel

        before = _counter_value("credit_account", "2xx")
        ch = CreditAccountChannel(http_client=None)
        await ch.query("TAB123")
        assert _delta("credit_account", "2xx", before) == 1.0

    @pytest.mark.asyncio
    async def test_credit_account_refund_inc_2xx(self) -> None:
        from services.tx_pay.src.channels.credit_account import CreditAccountChannel

        before = _counter_value("credit_account", "2xx")
        ch = CreditAccountChannel(http_client=None)
        await ch.refund("TAB123", 100)
        assert _delta("credit_account", "2xx", before) == 1.0
