"""支付渠道 mock 模式 E2E walkthrough integration test

目的
----
验证 4 个第三方 channel（alipay/wechat/shouqianba/unionpay）+ 4 个 callback endpoint
在 mock 模式下的端到端行为，作为 5/13 demo 兜底 + 真实凭据未到时的回归基线。

测试矩阵
--------
- 4 channel × {pay, query, refund} mock 路径行为
- 4 channel × verify_callback mock 路径（部分抛 NotImplementedError，结构差异需暴露）
- ChannelRegistry 8 channel 注册 topology
- callback_routes /api/v1/pay/callback/* 4 endpoint TX_PAY_MOCK_MODE 拦截

不在本测试范围
--------------
- 真实凭据下的真验签：已在 services/tx-pay/tests/test_*_callback_tier1.py 覆盖
- 跨服务订单 → 支付 → 状态推进：候选 2 (test_pos_core_flow_e2e_mock.py) 范围
- channel 内部 silent bug 修复：仅记录到 docs/walkthrough/payment-channels-mock-2026-05-12.md
"""
from __future__ import annotations

import importlib
from unittest.mock import patch

import pytest

from services.tx_pay.src.channels.alipay import AlipayChannel
from services.tx_pay.src.channels.base import (
    PayMethod,
    PaymentRequest,
    PayStatus,
    TradeType,
)
from services.tx_pay.src.channels.registry import ChannelRegistry
from services.tx_pay.src.channels.shouqianba import ShouqianbaChannel
from services.tx_pay.src.channels.unionpay import UnionPayChannel
from services.tx_pay.src.channels.wechat import WechatPayChannel


# ─── Fixtures ──────────────────────────────────────────────────────────


@pytest.fixture
def mock_request() -> PaymentRequest:
    return PaymentRequest(
        tenant_id="tenant_walkthrough",
        store_id="store_walkthrough",
        order_id="order_walkthrough_001",
        amount_fen=8800,
        method=PayMethod.WECHAT,
        trade_type=TradeType.B2C,
        description="walkthrough mock 订单",
    )


def _force_mock_mode(channel_class):
    """构造 channel 实例并强制 mock 模式（_service / _client 置 None）。

    用 ``__new__`` bypass ``__init__`` 避免触发 SDK import：
    - alipay/shouqianba SDK 已实现 → 正常 ``__init__`` 会拿到真 service，
      mock 路径需手动置 None
    - wechat shared/integrations/wechat_pay.py 用 PEP 604 ``dict | None`` syntax
      (Python 3.10+)，本地 3.9 会 TypeError 而非 ImportError，channel 的
      ``except ImportError`` 接不住 → 必须 bypass

    手动 set 通用属性 (_service / _client / _notify_url) 覆盖各 channel 需要的字段。
    """
    instance = channel_class.__new__(channel_class)
    instance._service = None
    instance._client = None
    instance._notify_url = ""
    return instance


# ─── Block A: 4 channel × pay() mock 路径 ───────────────────────────────


@pytest.mark.asyncio
async def test_alipay_pay_mock_returns_success(mock_request: PaymentRequest) -> None:
    channel = _force_mock_mode(AlipayChannel)
    result = await channel.pay(mock_request)

    assert result.status == PayStatus.SUCCESS
    assert result.method == PayMethod.ALIPAY
    assert result.amount_fen == 8800
    assert result.trade_no.startswith("MOCK_ALI_")
    assert result.payment_id.startswith("ALI")
    assert result.channel_data == {"mock": True}
    assert result.paid_at is not None


@pytest.mark.asyncio
async def test_wechat_pay_mock_returns_success(mock_request: PaymentRequest) -> None:
    channel = _force_mock_mode(WechatPayChannel)
    result = await channel.pay(mock_request)

    assert result.status == PayStatus.SUCCESS
    assert result.method == PayMethod.WECHAT
    assert result.amount_fen == 8800
    assert result.trade_no.startswith("MOCK_WX_")
    assert result.payment_id.startswith("WX")
    assert result.channel_data["mock"] is True
    assert "prepay_id" in result.channel_data
    assert result.channel_data["prepay_id"].startswith("wx_mock_")


@pytest.mark.asyncio
async def test_shouqianba_pay_mock_returns_success(mock_request: PaymentRequest) -> None:
    channel = _force_mock_mode(ShouqianbaChannel)
    result = await channel.pay(mock_request)

    assert result.status == PayStatus.SUCCESS
    assert result.method == PayMethod.WECHAT
    assert result.amount_fen == 8800
    assert result.trade_no.startswith("MOCK_SQB_")
    assert result.payment_id.startswith("SQB")
    assert result.channel_data == {"mock": True, "provider": "shouqianba"}


@pytest.mark.asyncio
async def test_unionpay_pay_mock_returns_success(mock_request: PaymentRequest) -> None:
    channel = _force_mock_mode(UnionPayChannel)
    request = mock_request.model_copy(update={"method": PayMethod.UNIONPAY})
    result = await channel.pay(request)

    assert result.status == PayStatus.SUCCESS
    assert result.method == PayMethod.UNIONPAY
    assert result.amount_fen == 8800
    assert result.trade_no.startswith("MOCK_UP_")
    assert result.payment_id.startswith("UP")
    assert result.channel_data == {"mock": True, "provider": "unionpay"}


# ─── Block B: 4 channel × query() mock 路径 + 漂移 finding 锁定 ─────────


@pytest.mark.asyncio
async def test_alipay_query_mock_returns_success_amount_zero() -> None:
    """FINDING #3 (P3): alipay mock query 总返 amount_fen=0，与 pay() 返的金额脱节。

    walkthrough 记录此 finding 后该测试锁定当前行为。修复 PR 落地后改为 amount > 0
    断言（或返回 pay() 时记录的真实金额）。"""
    channel = _force_mock_mode(AlipayChannel)
    result = await channel.query(payment_id="ALI_TEST_001", trade_no="MOCK_ALI_test")

    assert result.status == PayStatus.SUCCESS
    assert result.method == PayMethod.ALIPAY
    assert result.amount_fen == 0  # 当前 mock 行为；finding #3 锁定


@pytest.mark.asyncio
async def test_wechat_query_mock_returns_success() -> None:
    channel = _force_mock_mode(WechatPayChannel)
    result = await channel.query(payment_id="WX_TEST_001", trade_no="MOCK_WX_test")

    assert result.status == PayStatus.SUCCESS
    assert result.method == PayMethod.WECHAT
    assert result.amount_fen == 0
    assert result.channel_data == {"mock": True}


@pytest.mark.asyncio
async def test_shouqianba_query_mock_method_drift_to_wechat() -> None:
    """FINDING #2 (P2): shouqianba mock query 硬编码 method=WECHAT。

    实际收钱吧 channel 支持 WECHAT/ALIPAY/UNIONPAY 三种 method（聚合支付）；mock query
    无法知道原 pay() 用的 method（query 入参没有 method 字段），强制 WECHAT 是实现简化
    但语义上漂移：用 ALIPAY 走收钱吧 pay 后 query 出来 method 变 WECHAT。
    walkthrough 记录此 finding 后该测试锁定当前行为。"""
    channel = _force_mock_mode(ShouqianbaChannel)
    result = await channel.query(payment_id="SQB_TEST_001", trade_no="MOCK_SQB_test")

    assert result.status == PayStatus.SUCCESS
    assert result.method == PayMethod.WECHAT  # 漂移 finding #2 锁定
    assert result.amount_fen == 0


@pytest.mark.asyncio
async def test_unionpay_query_mock_trade_no_fallback() -> None:
    """unionpay 是 4 channel 中唯一 mock query 提供 trade_no fallback 的（5/12 中午 reviewer 修）。

    其他 channel mock query trade_no 直接用入参（可能 None），unionpay 是 `trade_no or f"MOCK_UP_..."` —
    防下游 NPE。本测试锁定 unionpay 唯一行为，walkthrough 建议未来对齐 4 channel。"""
    channel = _force_mock_mode(UnionPayChannel)

    # trade_no 入参 None 时，unionpay 回填 mock
    result_none = await channel.query(payment_id="UP_TEST_001", trade_no=None)
    assert result_none.trade_no is not None
    assert result_none.trade_no.startswith("MOCK_UP_")

    # trade_no 入参非 None 时，unionpay 用入参
    result_given = await channel.query(payment_id="UP_TEST_002", trade_no="GIVEN_TRADE_NO")
    assert result_given.trade_no == "GIVEN_TRADE_NO"


# ─── Block C: 4 channel × refund() mock 路径 ────────────────────────────


@pytest.mark.asyncio
async def test_alipay_refund_mock_returns_success() -> None:
    channel = _force_mock_mode(AlipayChannel)
    result = await channel.refund(payment_id="ALI_TEST_001", refund_amount_fen=4400)

    assert result.status == "success"
    assert result.amount_fen == 4400
    assert result.refund_id.startswith("REFALI")
    assert result.refund_trade_no.startswith("MOCK_REFALI_")


@pytest.mark.asyncio
async def test_wechat_refund_mock_returns_success() -> None:
    channel = _force_mock_mode(WechatPayChannel)
    result = await channel.refund(payment_id="WX_TEST_001", refund_amount_fen=4400)

    assert result.status == "success"
    assert result.amount_fen == 4400
    assert result.refund_id.startswith("REF")
    assert result.refund_trade_no.startswith("MOCK_REFUND_")


@pytest.mark.asyncio
async def test_shouqianba_refund_mock_returns_success() -> None:
    channel = _force_mock_mode(ShouqianbaChannel)
    result = await channel.refund(payment_id="SQB_TEST_001", refund_amount_fen=4400)

    assert result.status == "success"
    assert result.amount_fen == 4400
    assert result.refund_id.startswith("REFSQB")
    assert result.refund_trade_no.startswith("MOCK_REFSQB_")


@pytest.mark.asyncio
async def test_unionpay_refund_mock_returns_success() -> None:
    channel = _force_mock_mode(UnionPayChannel)
    result = await channel.refund(payment_id="UP_TEST_001", refund_amount_fen=4400)

    assert result.status == "success"
    assert result.amount_fen == 4400
    assert result.refund_id.startswith("REFUP")
    assert result.refund_trade_no.startswith("MOCK_REFUP_")


# ─── Block D: 4 channel × verify_callback mock 行为差异 ────────────────


@pytest.mark.asyncio
async def test_alipay_verify_callback_raises_when_service_none() -> None:
    """alipay verify_callback mock 模式抛 NotImplementedError（_service None）。

    callback_routes.py wechat/alipay/lakala/shouqianba endpoint 都 catch
    NotImplementedError 并返 400 + log error，不会静默 fallback success。"""
    channel = _force_mock_mode(AlipayChannel)
    with pytest.raises(NotImplementedError, match="AlipayService 未初始化"):
        await channel.verify_callback(headers={}, body=b"{}")


@pytest.mark.asyncio
async def test_wechat_verify_callback_raises_when_service_none() -> None:
    channel = _force_mock_mode(WechatPayChannel)
    with pytest.raises(NotImplementedError, match="Mock 模式不支持回调验证"):
        await channel.verify_callback(headers={}, body=b"{}")


@pytest.mark.asyncio
async def test_shouqianba_verify_callback_raises_when_service_none() -> None:
    channel = _force_mock_mode(ShouqianbaChannel)
    with pytest.raises(NotImplementedError, match="ShouqianbaService 未初始化"):
        await channel.verify_callback(headers={}, body=b"{}")


@pytest.mark.asyncio
async def test_unionpay_verify_callback_always_raises() -> None:
    """unionpay verify_callback 设计就是 audit signal — 无 mock 路径，永远抛错。

    防止伪造 callback 静默通过。等创始人提供商户证书链 + 测试 merId 后另起 PR 落地。"""
    channel = UnionPayChannel()  # 不需要 force mock，verify_callback 总抛错
    with pytest.raises(NotImplementedError, match="商户证书链"):
        await channel.verify_callback(headers={}, body=b"{}")


# ─── Block E: ChannelRegistry topology ──────────────────────────────────


@pytest.mark.asyncio
async def test_registry_register_and_get_4_third_party_channels() -> None:
    """4 第三方 channel 注册 + get 还原。`channel_name` 必须与 callback_routes
    `registry.get(...)` 字符串完全对齐（5/12 中午 shouqianba_direct E2 fix 教训）。"""
    registry = ChannelRegistry()
    registry.register(_force_mock_mode(AlipayChannel))
    registry.register(_force_mock_mode(WechatPayChannel))
    registry.register(_force_mock_mode(ShouqianbaChannel))
    registry.register(_force_mock_mode(UnionPayChannel))

    assert set(registry.channel_names) == {
        "alipay_direct",
        "wechat_direct",
        "shouqianba_direct",
        "unionpay",
    }
    assert registry.get("alipay_direct") is not None
    assert registry.get("wechat_direct") is not None
    assert registry.get("shouqianba_direct") is not None
    assert registry.get("unionpay") is not None


@pytest.mark.asyncio
async def test_registry_find_by_method_and_trade_type() -> None:
    """RoutingEngine 用 find(method, trade_type) 选 channel。
    本测试覆盖典型组合，验证 supports() 矩阵正确。"""
    registry = ChannelRegistry()
    registry.register(_force_mock_mode(AlipayChannel))
    registry.register(_force_mock_mode(WechatPayChannel))
    registry.register(_force_mock_mode(ShouqianbaChannel))
    registry.register(_force_mock_mode(UnionPayChannel))

    # WECHAT + JSAPI → wechat_direct（shouqianba 不支持 JSAPI）
    wechat_jsapi = registry.find(PayMethod.WECHAT, TradeType.JSAPI)
    assert wechat_jsapi is not None
    assert wechat_jsapi.channel_name == "wechat_direct"

    # ALIPAY + B2C → alipay_direct（先注册，先匹配；shouqianba 也支持 ALIPAY+B2C 但靠后）
    alipay_b2c = registry.find(PayMethod.ALIPAY, TradeType.B2C)
    assert alipay_b2c is not None
    assert alipay_b2c.channel_name == "alipay_direct"

    # UNIONPAY + B2C → unionpay（unionpay 支持 UNIONPAY+B2C；shouqianba 也支持但靠后）
    unionpay_b2c = registry.find(PayMethod.UNIONPAY, TradeType.B2C)
    assert unionpay_b2c is not None
    # 注意：shouqianba 也支持 UNIONPAY+B2C 且先注册 → 实际返 shouqianba_direct
    assert unionpay_b2c.channel_name == "shouqianba_direct"


@pytest.mark.asyncio
async def test_registry_get_unknown_channel_raises_keyerror() -> None:
    """callback_routes 拿到错误 channel_name（如旧版 "shouqianba" 不带 _direct 后缀）→ KeyError 立即暴露。
    5/12 中午 E2 fix 的 silent bug 防御点：channel_name 漂移会被 registry 拒绝，不再静默 500。"""
    registry = ChannelRegistry()
    registry.register(_force_mock_mode(ShouqianbaChannel))

    with pytest.raises(KeyError, match="shouqianba"):
        registry.get("shouqianba")  # 旧名错误，应抛错


# ─── Block F: callback_routes /api/v1/pay/callback/* TX_PAY_MOCK_MODE 拦截 ─


def _reload_callback_routes_with_mock_mode(mock_mode: bool):
    """重新 import callback_routes 模块以触发 _MOCK_MODE 单例重读 env。

    callback_routes._MOCK_MODE 是模块级常量（os.getenv 一次永久锁），
    切换 TX_PAY_MOCK_MODE 必须 importlib.reload 才生效。本辅助函数封装此模式。

    walkthrough finding #4：safe-default singleton（default False = 强制验签），
    与 channel `_mock_mode` 已修为 _is_mock_mode() 方法重读 env 不同 — pattern 不一致。"""
    env_value = "true" if mock_mode else "false"
    with patch.dict("os.environ", {"TX_PAY_MOCK_MODE": env_value}):
        from services.tx_pay.src.api import callback_routes
        importlib.reload(callback_routes)
        return callback_routes


@pytest.mark.asyncio
async def test_callback_routes_4_endpoints_registered() -> None:
    """callback_routes 注册 4 endpoint：wechat/alipay/lakala/shouqianba。
    unionpay **没有** callback endpoint — 凭据未到，PR4 决策 B 沉淀的 audit 边界。"""
    callback_routes = _reload_callback_routes_with_mock_mode(False)

    paths = [route.path for route in callback_routes.router.routes]
    assert "/api/v1/pay/callback/wechat" in paths
    assert "/api/v1/pay/callback/alipay" in paths
    assert "/api/v1/pay/callback/lakala" in paths
    assert "/api/v1/pay/callback/shouqianba" in paths
    # finding #5: unionpay endpoint 缺失（凭据前置，PR4 决策 B）
    assert "/api/v1/pay/callback/unionpay" not in paths


@pytest.mark.asyncio
async def test_callback_routes_module_mock_mode_singleton_snapshot() -> None:
    """_MOCK_MODE 是模块级单例快照（os.getenv 一次永久锁）。

    与 5/12 中午 reviewer 揭露的 channel `_mock_mode` 同款 pattern，但 default 不同：
    - channel _mock_mode default = True（缺凭据 → mock 静默 bypass）→ 已修为方法重读
    - callback _MOCK_MODE default = False（缺 env → 强制验签）→ safe-default，未修

    finding #4 walkthrough 记录 pattern 差异。"""
    # default False（env 不设）
    callback_routes = _reload_callback_routes_with_mock_mode(False)
    assert callback_routes._MOCK_MODE is False

    # 设 true 后 reload 才生效
    callback_routes = _reload_callback_routes_with_mock_mode(True)
    assert callback_routes._MOCK_MODE is True

    # 切回 false 必须再 reload，否则锁定 True
    callback_routes = _reload_callback_routes_with_mock_mode(False)
    assert callback_routes._MOCK_MODE is False
