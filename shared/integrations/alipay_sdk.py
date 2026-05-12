"""支付宝开放平台 SDK — 异步通知验签

环境变量：
  ALIPAY_APP_ID            — 应用 AppID（必填）
  ALIPAY_PUBLIC_KEY_PATH   — 支付宝公钥 PEM 文件路径（必填，用于验签）
  ALIPAY_SELLER_ID         — 商户收款 PID（强烈建议填，启用收款方校验防钓鱼）

未配置环境变量时进入 Mock 模式；生产环境（ENVIRONMENT/ENV ∈ {production, prod}）
默认拒绝实例化，需显式 TX_ALIPAY_ALLOW_MOCK=1 才能放行（仅限灰度/演练）。

当前仅实现 verify_callback；pay/query/refund 真实接入留 follow-up。

设计说明（reviewer P0-B fix）：
  所有环境变量通过方法访问（_app_id/_public_key_path/_seller_id），不在模块加载时
  绑定，避免"模块先加载 + 后续 setenv/monkeypatch 不生效"的测试/生产语义不一致。
"""

from __future__ import annotations

import base64
import logging
import os
from typing import Any
from urllib.parse import parse_qsl

logger = logging.getLogger(__name__)


# ─── 环境变量（每次访问重读，避免模块加载时快照） ─────────────────────────


def _app_id() -> str:
    return os.environ.get("ALIPAY_APP_ID", "")


def _public_key_path() -> str:
    return os.environ.get("ALIPAY_PUBLIC_KEY_PATH", "")


def _seller_id() -> str:
    return os.environ.get("ALIPAY_SELLER_ID", "")


def _is_configured() -> bool:
    return bool(_app_id() and _public_key_path())


def _is_production_env() -> bool:
    env = (os.environ.get("ENVIRONMENT") or os.environ.get("ENV") or "").strip().lower()
    return env in ("production", "prod")


def _mock_explicitly_allowed() -> bool:
    return os.environ.get("TX_ALIPAY_ALLOW_MOCK", "").strip().lower() in (
        "1", "true", "yes", "on",
    )


def _load_public_key(path: str) -> Any:
    from cryptography.hazmat.primitives.serialization import load_pem_public_key

    with open(path, "rb") as f:
        return load_pem_public_key(f.read())


# ─── 主入口：AlipayService ───────────────────────────────────────────────


class AlipayService:
    """支付宝开放平台服务

    - 未配置时：非生产为 Mock；生产默认拒绝实例化（除非 TX_ALIPAY_ALLOW_MOCK=1）
    - 签名算法：RSA2 = SHA256withRSA（弃用 RSA(SHA1)，防降级攻击）
    - 验签公钥：支付宝公钥（不是商户公钥）
    """

    def __init__(self) -> None:
        self._mock_mode = not _is_configured()
        self._public_key: Any = None
        if self._mock_mode:
            if _is_production_env() and not _mock_explicitly_allowed():
                raise RuntimeError(
                    "生产环境禁止支付宝 Mock：请配置 ALIPAY_APP_ID / ALIPAY_PUBLIC_KEY_PATH；"
                    "若仅为灰度演练需 Mock，请显式设置 TX_ALIPAY_ALLOW_MOCK=1"
                )
            logger.warning(
                "AlipayService 进入 Mock 模式：请配置 ALIPAY_APP_ID / ALIPAY_PUBLIC_KEY_PATH"
            )
        else:
            self._public_key = _load_public_key(_public_key_path())

    # ─── 验证异步通知（notify）签名 ───

    async def verify_callback(self, headers: dict, body: bytes) -> dict[str, str]:
        """验证支付宝异步通知签名并返回字段字典。

        步骤（与官方 rsaCheckV1 等价）：
          1. 解析 form-encoded body；**检测重复 key 直接拒绝**（reviewer P1-1）
          2. 校验 sign_type == "RSA2"（拒绝弃用的 RSA / SHA1，防降级攻击）
          3. 取出 sign，剔除 sign + sign_type，剩余按 key 字典序排序
          4. 拼接 "k1=v1&k2=v2&..."（value 已 URL decode，不再 quote）
          5. 用支付宝公钥 SHA256withRSA 验签
          6. 业务校验 app_id（必）；若配置了 _seller_id() 则 seller_id 必须存在且匹配
             （reviewer P0-A：禁止字段缺失时静默豁免）
        """
        if self._mock_mode:
            return self._mock_callback_response(body)

        from cryptography.exceptions import InvalidSignature
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import padding

        body_str = body.decode("utf-8") if isinstance(body, bytes) else body

        # P1-1: 重复 key 检测（防 sign=X&sign=Y 注入噪声字段绕过签名范围）
        raw_pairs = parse_qsl(body_str, keep_blank_values=True)
        keys_seen = [k for k, _ in raw_pairs]
        if len(keys_seen) != len(set(keys_seen)):
            raise ValueError("支付宝回调 body 含重复 key，拒绝处理")
        params = dict(raw_pairs)

        sign_b64 = params.pop("sign", None)
        sign_type = params.pop("sign_type", "RSA2")

        if not sign_b64:
            raise ValueError("支付宝回调缺少签名字段 sign")
        if sign_type != "RSA2":
            raise ValueError(
                f"支付宝回调拒绝弃用签名算法 sign_type={sign_type}（仅接受 RSA2）"
            )

        sorted_pairs = sorted(params.items())
        sign_str = "&".join(f"{k}={v}" for k, v in sorted_pairs)

        try:
            sig = base64.b64decode(sign_b64)
        except (ValueError, TypeError) as exc:
            raise ValueError("支付宝回调 sign 非合法 Base64") from exc

        try:
            self._public_key.verify(
                sig, sign_str.encode("utf-8"), padding.PKCS1v15(), hashes.SHA256()
            )
        except InvalidSignature as exc:
            raise ValueError("支付宝回调验签失败") from exc

        # 业务字段校验（防回放 + 防钓鱼）
        expected_app_id = _app_id()
        if params.get("app_id") != expected_app_id:
            raise ValueError(
                f"支付宝回调 app_id 不匹配：expected={expected_app_id} got={params.get('app_id')}"
            )

        # P0-A: seller_id 校验严格化 — 配置了就必须存在且匹配，禁止字段缺失豁免
        expected_seller_id = _seller_id()
        if expected_seller_id:
            got_seller_id = params.get("seller_id")
            if got_seller_id != expected_seller_id:
                raise ValueError(
                    f"支付宝回调 seller_id 不匹配或缺失："
                    f"expected={expected_seller_id} got={got_seller_id}"
                )

        return params

    # ─── Mock 响应 ───

    def _mock_callback_response(self, body: bytes) -> dict[str, str]:
        body_str = body.decode("utf-8") if isinstance(body, bytes) else body
        params = dict(parse_qsl(body_str, keep_blank_values=True))
        params.setdefault("trade_status", "TRADE_SUCCESS")
        params.setdefault("out_trade_no", "MOCK_ALI_TRADE")
        return params


# ─── 全局单例 ───

_instance: AlipayService | None = None


def get_alipay_service() -> AlipayService:
    global _instance
    if _instance is None:
        _instance = AlipayService()
    return _instance
