"""收钱吧回调验签 Tier 1 测试（餐厅收银员视角）

场景动机：
  收银员让顾客扫收钱吧扫码枪付款，收钱吧服务端推送支付结果 notify 到
  /api/v1/pay/callback/shouqianba。若签名 + 业务字段正确，必须发射
  PaymentConfirmed 事件让桌台/库存/积分继续推进；签名错或字段不符必须拒收。

涉及 Tier 1 路径：支付补偿 Saga（§17）+ 权限/认证逻辑（§19）— TDD 红绿双 commit。

签名机制（官方 doc.shouqianba.com/zh-cn/api/sign.html）：
  - Header: `Authorization: <sn> <sign>`（sn 与 sign 空格分隔，非 Bearer）
  - 算法：`sign = MD5(utf8_body + terminal_key)`
  - 单位：total_amount 即"分"（与其他渠道一致，无需 元→分 转换）
  - 响应：服务端必须返 **`success` 纯文本**（非 JSON）

本 PR 同时修复：
  - channel_name 从 `"shouqianba"` → `"shouqianba_direct"`（与 callback_routes.py registry.get 一致）
  - callback_routes.py 成功响应从 JSON `{"result_code":"200"}` → 纯文本 `success`
"""

from __future__ import annotations

import hashlib
import json
import os

import pytest

from services.tx_pay.src.channels.base import PayStatus
from services.tx_pay.src.channels.shouqianba import ShouqianbaChannel


# ─── 测试固定密钥（仅本测试使用） ────────────────────────────────────────

_TEST_TERMINAL_SN = "00101010029201012912"
_TEST_TERMINAL_KEY = "test_terminal_key_31_chars_xxxx"  # 测试用，非真实生产凭据


# ─── helper：构造收钱吧合法 callback body + Authorization ──────────────


def _make_signed_callback(
    body_dict: dict,
    terminal_sn: str = _TEST_TERMINAL_SN,
    terminal_key: str = _TEST_TERMINAL_KEY,
) -> tuple[dict, bytes]:
    """构造合法签名的回调（headers + body）。

    Returns:
        (headers, body_bytes) — 与真实 notify 一致
    """
    body_bytes = json.dumps(body_dict, ensure_ascii=False).encode("utf-8")
    sign = hashlib.md5(body_bytes + terminal_key.encode("utf-8")).hexdigest()
    headers = {"authorization": f"{terminal_sn} {sign}"}
    return headers, body_bytes


def _valid_callback_dict() -> dict:
    """构造一组合法的收钱吧 callback body。"""
    return {
        "terminal_sn": _TEST_TERMINAL_SN,
        "client_sn": "TX20260512120000ABCDEF",
        "sn": "759039650023400000",  # 收钱吧流水号
        "trade_no": "4200002088202605120000000001",  # 渠道流水号（微信/支付宝）
        "order_status": "PAID",
        "total_amount": "8800",  # 单位：分（与其他渠道一致）
        "net_amount": "8800",
        "payway": "3",  # 1=支付宝 3=微信 4=银联
        "subject": "屯象OS订单",
        "finish_time": "1747028400000",
    }


# ─── Fixture ──────────────────────────────────────────────────────────


@pytest.fixture
def shouqianba_channel(monkeypatch) -> ShouqianbaChannel:
    """注入测试凭据到 ShouqianbaChannel。"""
    monkeypatch.setenv("SHOUQIANBA_TERMINAL_SN", _TEST_TERMINAL_SN)
    monkeypatch.setenv("SHOUQIANBA_TERMINAL_KEY", _TEST_TERMINAL_KEY)
    return ShouqianbaChannel()


# ─── 测试 ─────────────────────────────────────────────────────────────


class TestShouqianbaCallbackTier1:
    """收钱吧回调验签 — Tier 1 餐厅场景反测"""

    def test_channel_name_aligned_with_callback_routes(
        self,
        shouqianba_channel: ShouqianbaChannel,
    ) -> None:
        """场景：callback_routes.py 调 registry.get('shouqianba_direct')，channel_name
        必须对齐否则 lookup 失败导致 500 — 即使签名实现对了 callback 也走不到。
        """
        assert shouqianba_channel.channel_name == "shouqianba_direct", (
            "channel_name 必须与 callback_routes.py registry.get 的 key 一致"
        )

    @pytest.mark.asyncio
    async def test_legit_paid_callback_returns_success(
        self,
        shouqianba_channel: ShouqianbaChannel,
    ) -> None:
        """场景：顾客扫收钱吧扫码枪付 88 元成功，收钱吧推 PAID notify。"""
        headers, body = _make_signed_callback(_valid_callback_dict())
        payload = await shouqianba_channel.verify_callback(headers, body)

        assert payload.payment_id == "TX20260512120000ABCDEF"
        assert payload.trade_no == "759039650023400000", "trade_no 应是收钱吧 sn"
        assert payload.status == PayStatus.SUCCESS
        assert payload.amount_fen == 8800

    @pytest.mark.asyncio
    async def test_pay_success_status_treated_as_success(
        self,
        shouqianba_channel: ShouqianbaChannel,
    ) -> None:
        """场景：收钱吧用 PAY_SUCCESS 而不是 PAID（不同接口版本差异）— 等价处理。"""
        body_dict = _valid_callback_dict()
        body_dict["order_status"] = "PAY_SUCCESS"
        headers, body = _make_signed_callback(body_dict)
        payload = await shouqianba_channel.verify_callback(headers, body)
        assert payload.status == PayStatus.SUCCESS

    @pytest.mark.asyncio
    async def test_pay_canceled_treated_as_closed(
        self,
        shouqianba_channel: ShouqianbaChannel,
    ) -> None:
        """场景：顾客付款过程中点了取消 — PAY_CANCELED 必须映射 CLOSED 不能 SUCCESS。"""
        body_dict = _valid_callback_dict()
        body_dict["order_status"] = "PAY_CANCELED"
        headers, body = _make_signed_callback(body_dict)
        payload = await shouqianba_channel.verify_callback(headers, body)
        assert payload.status == PayStatus.CLOSED

    @pytest.mark.asyncio
    async def test_tampered_body_rejected(
        self,
        shouqianba_channel: ShouqianbaChannel,
    ) -> None:
        """场景：攻击者改大金额企图骗到资金确认 — 签名失配必须 ValueError。"""
        headers, body = _make_signed_callback(_valid_callback_dict())
        # 篡改：把金额从 8800 改成 88000（多 1 个 0）
        tampered_body = body.replace(b'"total_amount": "8800"', b'"total_amount": "88000"')
        with pytest.raises(ValueError, match="验签|签名"):
            await shouqianba_channel.verify_callback(headers, tampered_body)

    @pytest.mark.asyncio
    async def test_missing_authorization_rejected(
        self,
        shouqianba_channel: ShouqianbaChannel,
    ) -> None:
        """场景：notify 缺 Authorization header（伪造请求）— 必须拒。"""
        _, body = _make_signed_callback(_valid_callback_dict())
        with pytest.raises(ValueError, match="Authorization|签名头"):
            await shouqianba_channel.verify_callback({}, body)

    @pytest.mark.asyncio
    async def test_wrong_terminal_sn_rejected(
        self,
        shouqianba_channel: ShouqianbaChannel,
    ) -> None:
        """场景：攻击者用别家商户的 sn 重放 — 本商户 terminal_key 与之不匹配，签名失配。"""
        headers, body = _make_signed_callback(
            _valid_callback_dict(), terminal_sn="99999999999999999999"
        )
        with pytest.raises(ValueError, match="terminal_sn|sn"):
            await shouqianba_channel.verify_callback(headers, body)

    @pytest.mark.asyncio
    async def test_malformed_authorization_rejected(
        self,
        shouqianba_channel: ShouqianbaChannel,
    ) -> None:
        """场景：Authorization 格式错（没有空格分隔 sn 和 sign）— 必须拒。"""
        _, body = _make_signed_callback(_valid_callback_dict())
        with pytest.raises(ValueError, match="Authorization|格式"):
            await shouqianba_channel.verify_callback(
                {"authorization": "no_space_separator"}, body
            )

    @pytest.mark.asyncio
    async def test_mock_mode_disengages_after_env_configured(
        self,
        monkeypatch,
    ) -> None:
        """场景（reviewer P0 防回归）：启动时环境变量未配置 → service 进入 mock；
        运行时 K8s/docker 注入 env 完成（如 sidecar 异步加载密钥）→ 后续 callback
        必须走真实验签，不能因 _mock_mode 固化而继续放行 mock 假数据。

        修复前 self._mock_mode 在 __init__ 固化，注入后 callback 仍走 mock。
        修复后 _is_mock_mode() 每次重读 env，自动切换到真实验签。
        """
        from shared.integrations.shouqianba_sdk import ShouqianbaService

        # 启动：未配置（mock 模式）
        monkeypatch.delenv("SHOUQIANBA_TERMINAL_SN", raising=False)
        monkeypatch.delenv("SHOUQIANBA_TERMINAL_KEY", raising=False)
        service = ShouqianbaService()
        assert service._is_mock_mode() is True

        # 运行时注入 env（模拟 sidecar 异步配置完成）
        monkeypatch.setenv("SHOUQIANBA_TERMINAL_SN", _TEST_TERMINAL_SN)
        monkeypatch.setenv("SHOUQIANBA_TERMINAL_KEY", _TEST_TERMINAL_KEY)
        assert service._is_mock_mode() is False, (
            "env 注入后 _is_mock_mode() 必须返回 False，不能因单例快照而继续 mock"
        )

        # 注入后必须真实验签：错误签名应抛 ValueError 而不是 mock 假数据
        body = b'{"client_sn":"X","order_status":"PAID"}'
        with pytest.raises(ValueError, match="Authorization"):
            await service.verify_callback({}, body)

    @pytest.mark.asyncio
    async def test_error_msg_does_not_leak_expected_terminal_sn(
        self,
        shouqianba_channel: ShouqianbaChannel,
    ) -> None:
        """场景（reviewer P1-B 防回归）：sn 不匹配的错误消息不能暴露本商户的
        expected terminal_sn（密钥管理），否则攻击者可从 4xx 日志中嗅探本商户 sn。
        """
        headers, body = _make_signed_callback(
            _valid_callback_dict(), terminal_sn="99999999999999999999"
        )
        try:
            await shouqianba_channel.verify_callback(headers, body)
            pytest.fail("应抛 ValueError")
        except ValueError as exc:
            err_msg = str(exc)
            assert _TEST_TERMINAL_SN not in err_msg, (
                f"错误消息不能暴露本商户 expected terminal_sn，got: {err_msg!r}"
            )
