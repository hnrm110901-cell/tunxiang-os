"""支付宝回调验签 Tier 1 测试（餐厅收银员视角）

场景动机：
  收银员扫顾客支付宝付款码后，支付宝异步推送 notify 到 /api/v1/pay/callback/alipay。
  若签名验对了且 trade_status=TRADE_SUCCESS，必须发射 PaymentConfirmed 事件，让
  桌台状态、库存、会员积分继续推进；若签名错或业务字段不符，必须拒收并返回 400，
  防止伪造回调使资金状态污染。

涉及 Tier 1 路径：支付补偿 Saga（§17）+ 权限/认证逻辑（§19）— TDD 红绿双 commit。

本文件仅做 unit fixture 反测：用测试 RSA 密钥对模拟支付宝公钥/私钥，对 form-encoded
回调 body 签名 → 调 AlipayChannel.verify_callback → 断言行为。
真实 sandbox 联调在 5/13 资质上线后单独 issue 追踪。
"""

from __future__ import annotations

import base64
from urllib.parse import quote_plus

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from services.tx_pay.src.channels.alipay import AlipayChannel
from services.tx_pay.src.channels.base import PayStatus


# ─── 测试 fixture：生成 RSA 密钥对模拟"支付宝公钥/商户私钥" ──────────────


@pytest.fixture(scope="module")
def alipay_keypair() -> tuple[bytes, bytes]:
    """生成一对 RSA 2048 密钥用于测试。

    在生产中：
      - 私钥归"支付宝平台"持有，用于对 notify 签名
      - 公钥是商户后台下载的"支付宝公钥"，用于商户端验签
    本测试翻转角色：测试代码持有私钥代演支付宝平台，公钥喂给 AlipayChannel。
    """
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    public_pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return private_pem, public_pem


@pytest.fixture
def alipay_channel(
    alipay_keypair: tuple[bytes, bytes],
    tmp_path,
    monkeypatch,
) -> AlipayChannel:
    """注入测试公钥到 AlipayChannel。"""
    _, public_pem = alipay_keypair
    pub_path = tmp_path / "alipay_public_key.pem"
    pub_path.write_bytes(public_pem)

    monkeypatch.setenv("ALIPAY_APP_ID", "2021000000000001")
    monkeypatch.setenv("ALIPAY_PUBLIC_KEY_PATH", str(pub_path))
    monkeypatch.setenv("ALIPAY_SELLER_ID", "2088000000000001")
    return AlipayChannel()


# ─── helper：用测试私钥构造"合法回调" body + 签名 ──────────────────────────


def _build_signed_callback(
    private_pem: bytes,
    fields: dict[str, str],
    sign_type: str = "RSA2",
) -> bytes:
    """模拟支付宝 notify：对 fields 字典序排序拼接 → SHA256withRSA 签 → 嵌入 sign + sign_type。

    返回 form-encoded body（bytes），与真实 notify 一致。
    """
    private_key = serialization.load_pem_private_key(private_pem, password=None)
    sorted_pairs = sorted(fields.items())
    sign_str = "&".join(f"{k}={v}" for k, v in sorted_pairs)

    if sign_type == "RSA2":
        sig = private_key.sign(
            sign_str.encode("utf-8"), padding.PKCS1v15(), hashes.SHA256()
        )
    else:  # RSA (SHA1)
        sig = private_key.sign(
            sign_str.encode("utf-8"), padding.PKCS1v15(), hashes.SHA1()
        )
    sign_b64 = base64.b64encode(sig).decode("ascii")

    body_pairs = sorted_pairs + [("sign", sign_b64), ("sign_type", sign_type)]
    return "&".join(f"{k}={quote_plus(v)}" for k, v in body_pairs).encode("utf-8")


def _valid_fields() -> dict[str, str]:
    """构造一组合法的支付宝 notify 字段。"""
    return {
        "app_id": "2021000000000001",
        "out_trade_no": "TX20260512120000ABCDEF",
        "trade_no": "2026051222001400000000000001",
        "trade_status": "TRADE_SUCCESS",
        "total_amount": "88.00",  # 元（注意：支付宝 notify 是元，转分要 *100）
        "seller_id": "2088000000000001",
        "notify_time": "2026-05-12 12:00:00",
        "notify_type": "trade_status_sync",
        "notify_id": "ac05099524730693a8b330c5ecf72da9786",
    }


# ─── 测试 ─────────────────────────────────────────────────────────────


class TestAlipayCallbackTier1:
    """支付宝异步通知验签 — Tier 1 餐厅场景反测"""

    @pytest.mark.asyncio
    async def test_legit_callback_returns_success_payload(
        self,
        alipay_channel: AlipayChannel,
        alipay_keypair: tuple[bytes, bytes],
    ) -> None:
        """场景：顾客用支付宝扫码付款 88 元成功，支付宝推送合法 notify。

        预期：channel 返回 CallbackPayload，金额单位转分（8800），状态 SUCCESS。
        """
        private_pem, _ = alipay_keypair
        body = _build_signed_callback(private_pem, _valid_fields())

        payload = await alipay_channel.verify_callback(headers={}, body=body)

        assert payload.payment_id == "TX20260512120000ABCDEF"
        assert payload.trade_no == "2026051222001400000000000001"
        assert payload.status == PayStatus.SUCCESS
        assert payload.amount_fen == 8800, "金额必须从元转换为分"

    @pytest.mark.asyncio
    async def test_trade_finished_also_treated_as_success(
        self,
        alipay_channel: AlipayChannel,
        alipay_keypair: tuple[bytes, bytes],
    ) -> None:
        """场景：超过退款期限后支付宝补推 TRADE_FINISHED 终态通知，与 SUCCESS 等价处理。"""
        private_pem, _ = alipay_keypair
        fields = _valid_fields()
        fields["trade_status"] = "TRADE_FINISHED"
        body = _build_signed_callback(private_pem, fields)

        payload = await alipay_channel.verify_callback(headers={}, body=body)
        assert payload.status == PayStatus.SUCCESS

    @pytest.mark.asyncio
    async def test_pending_status_not_treated_as_paid(
        self,
        alipay_channel: AlipayChannel,
        alipay_keypair: tuple[bytes, bytes],
    ) -> None:
        """场景：支付宝推送 WAIT_BUYER_PAY，未实际付款 — 必须 PENDING 不进入资金确认。"""
        private_pem, _ = alipay_keypair
        fields = _valid_fields()
        fields["trade_status"] = "WAIT_BUYER_PAY"
        body = _build_signed_callback(private_pem, fields)

        payload = await alipay_channel.verify_callback(headers={}, body=body)
        assert payload.status == PayStatus.PENDING, (
            "未完成支付的 notify 不能算作 SUCCESS，否则会误确认资金"
        )

    @pytest.mark.asyncio
    async def test_tampered_signature_rejected(
        self,
        alipay_channel: AlipayChannel,
        alipay_keypair: tuple[bytes, bytes],
    ) -> None:
        """场景：攻击者伪造 notify 想白嫖订单状态 — 签名错必须 ValueError，绝不放过。"""
        private_pem, _ = alipay_keypair
        fields = _valid_fields()
        body = _build_signed_callback(private_pem, fields)
        # 篡改金额（攻击者改大值企图骗到资金确认）
        body = body.replace(b"total_amount=88.00", b"total_amount=8800.00")

        with pytest.raises(ValueError, match="验签失败|签名"):
            await alipay_channel.verify_callback(headers={}, body=body)

    @pytest.mark.asyncio
    async def test_missing_sign_field_rejected(
        self,
        alipay_channel: AlipayChannel,
    ) -> None:
        """场景：notify body 里没有 sign 字段（伪造请求或格式异常） — 必须拒。"""
        body = b"app_id=2021000000000001&out_trade_no=X&trade_status=TRADE_SUCCESS"
        with pytest.raises(ValueError, match="缺少签名|sign"):
            await alipay_channel.verify_callback(headers={}, body=body)

    @pytest.mark.asyncio
    async def test_legacy_rsa_sign_type_rejected(
        self,
        alipay_channel: AlipayChannel,
        alipay_keypair: tuple[bytes, bytes],
    ) -> None:
        """场景：支付宝早已弃用 RSA（SHA1）；新接入必须仅接受 RSA2，防止降级攻击。"""
        private_pem, _ = alipay_keypair
        body = _build_signed_callback(private_pem, _valid_fields(), sign_type="RSA")
        with pytest.raises(ValueError, match="RSA2|签名算法|sign_type"):
            await alipay_channel.verify_callback(headers={}, body=body)

    @pytest.mark.asyncio
    async def test_app_id_mismatch_rejected(
        self,
        alipay_channel: AlipayChannel,
        alipay_keypair: tuple[bytes, bytes],
    ) -> None:
        """场景：合法签名 + 错 app_id（攻击者用别家商户私钥的回放）— 必须拒。"""
        private_pem, _ = alipay_keypair
        fields = _valid_fields()
        fields["app_id"] = "9999999999999999"
        body = _build_signed_callback(private_pem, fields)
        with pytest.raises(ValueError, match="app_id"):
            await alipay_channel.verify_callback(headers={}, body=body)

    @pytest.mark.asyncio
    async def test_seller_id_mismatch_rejected(
        self,
        alipay_channel: AlipayChannel,
        alipay_keypair: tuple[bytes, bytes],
    ) -> None:
        """场景：合法签名 + 错 seller_id（钓鱼到别家商户的收款）— 必须拒。"""
        private_pem, _ = alipay_keypair
        fields = _valid_fields()
        fields["seller_id"] = "2088999999999999"
        body = _build_signed_callback(private_pem, fields)
        with pytest.raises(ValueError, match="seller"):
            await alipay_channel.verify_callback(headers={}, body=body)

    @pytest.mark.asyncio
    async def test_seller_id_field_absent_rejected_when_configured(
        self,
        alipay_channel: AlipayChannel,
        alipay_keypair: tuple[bytes, bytes],
    ) -> None:
        """场景（reviewer P0-A 防回归）：商户已配置 seller_id 但 notify 中字段缺失。
        不能因字段缺失而静默豁免 — 攻击者可能用别商户合法私钥构造缺 seller_id 的 notify
        来绕过收款方校验。
        """
        private_pem, _ = alipay_keypair
        fields = _valid_fields()
        del fields["seller_id"]
        body = _build_signed_callback(private_pem, fields)
        with pytest.raises(ValueError, match="seller"):
            await alipay_channel.verify_callback(headers={}, body=body)

    @pytest.mark.asyncio
    async def test_duplicate_key_in_body_rejected(
        self,
        alipay_channel: AlipayChannel,
        alipay_keypair: tuple[bytes, bytes],
    ) -> None:
        """场景（reviewer P1-1 防回归）：body 含重复 key（sign=X&...&sign=Y）。
        parse_qsl 默认后者覆盖前者，可被注入噪声字段绕过签名范围 — 必须直接拒。
        """
        private_pem, _ = alipay_keypair
        body = _build_signed_callback(private_pem, _valid_fields())
        # 注入一个重复的 app_id 字段
        tampered_body = body + b"&app_id=evil_extra"
        with pytest.raises(ValueError, match="重复"):
            await alipay_channel.verify_callback(headers={}, body=tampered_body)

    @pytest.mark.asyncio
    async def test_mock_mode_disengages_after_env_configured(
        self,
        monkeypatch,
        tmp_path,
        alipay_keypair: tuple[bytes, bytes],
    ) -> None:
        """场景（cross-fix PR #461 reviewer P0 防回归）：启动时 env 未配置 →
        service 进入 mock；运行时 K8s/docker 注入 env 完成 → 后续 callback 必须
        走真实验签，不能因 _mock_mode 单例固化而继续放行 mock 假数据。
        """
        from shared.integrations.alipay_sdk import AlipayService

        # 启动：未配置（mock 模式）
        monkeypatch.delenv("ALIPAY_APP_ID", raising=False)
        monkeypatch.delenv("ALIPAY_PUBLIC_KEY_PATH", raising=False)
        service = AlipayService()
        assert service._is_mock_mode() is True

        # 运行时注入 env（模拟 sidecar 异步配置完成）
        _, public_pem = alipay_keypair
        pub_path = tmp_path / "alipay_public_key_runtime.pem"
        pub_path.write_bytes(public_pem)
        monkeypatch.setenv("ALIPAY_APP_ID", "2021000000000001")
        monkeypatch.setenv("ALIPAY_PUBLIC_KEY_PATH", str(pub_path))
        assert service._is_mock_mode() is False, (
            "env 注入后 _is_mock_mode() 必须返回 False，不能因单例快照继续 mock"
        )

        # 注入后必须真实验签：错误签名抛 ValueError 而不是 mock 假数据
        body = b"app_id=2021000000000001&out_trade_no=X&trade_status=TRADE_SUCCESS"
        with pytest.raises(ValueError, match="缺少签名|sign"):
            await service.verify_callback({}, body)

    @pytest.mark.asyncio
    async def test_decimal_precision_at_boundary(
        self,
        alipay_channel: AlipayChannel,
        alipay_keypair: tuple[bytes, bytes],
    ) -> None:
        """场景（reviewer P1-2 防回归）：金额在浮点边界（2.85 元 = 285 分）。
        改用 Decimal 后边界必须精确转换为分整数。
        """
        private_pem, _ = alipay_keypair
        fields = _valid_fields()
        fields["total_amount"] = "2.85"
        body = _build_signed_callback(private_pem, fields)
        payload = await alipay_channel.verify_callback(headers={}, body=body)
        assert payload.amount_fen == 285, (
            "2.85 元必须精确转 285 分（不能因 float 精度变成 284）"
        )
