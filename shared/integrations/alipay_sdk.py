"""支付宝开放平台 SDK — 异步通知验签

环境变量：
  ALIPAY_APP_ID            — 应用 AppID（必填）
  ALIPAY_PUBLIC_KEY_PATH   — 支付宝公钥 PEM 文件路径（必填，用于验签）
  ALIPAY_SELLER_ID         — 商户收款 PID（建议填，启用收款方校验防钓鱼）

未配置环境变量时进入 Mock 模式；生产环境（ENVIRONMENT/ENV ∈ {production, prod}）
默认拒绝实例化，需显式 TX_ALIPAY_ALLOW_MOCK=1 才能放行（仅限灰度/演练）。

当前仅实现 verify_callback；pay/query/refund 真实接入留 follow-up。
"""

from __future__ import annotations

import base64
import logging
import os
from typing import Any
from urllib.parse import parse_qsl

logger = logging.getLogger(__name__)


# ─── 环境变量 ────────────────────────────────────────────────────────────

_APP_ID = os.environ.get("ALIPAY_APP_ID", "")
_PUBLIC_KEY_PATH = os.environ.get("ALIPAY_PUBLIC_KEY_PATH", "")
_SELLER_ID = os.environ.get("ALIPAY_SELLER_ID", "")


def _is_configured() -> bool:
    return bool(_APP_ID and _PUBLIC_KEY_PATH)


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
            self._public_key = _load_public_key(_PUBLIC_KEY_PATH)

    # ─── 验证异步通知（notify）签名 ───

    async def verify_callback(self, headers: dict, body: bytes) -> dict[str, str]:
        """验证支付宝异步通知签名并返回字段字典。

        步骤（与官方 rsaCheckV1 等价）：
          1. 解析 form-encoded body（keep_blank_values=True 保留空值键）
          2. 校验 sign_type == "RSA2"（拒绝弃用的 RSA / SHA1）
          3. 取出 sign，剔除 sign + sign_type，剩余按 key 字典序排序
          4. 拼接 "k1=v1&k2=v2&..."（value 已 URL decode，不再 quote）
          5. 用支付宝公钥 SHA256withRSA 验签
          6. 业务校验 app_id（必）+ seller_id（若已配置）
        """
        if self._mock_mode:
            return self._mock_callback_response(body)

        from cryptography.exceptions import InvalidSignature
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import padding

        body_str = body.decode("utf-8") if isinstance(body, bytes) else body
        params = dict(parse_qsl(body_str, keep_blank_values=True))

        sign_b64 = params.pop("sign", None)
        sign_type = params.pop("sign_type", "RSA2")

        if not sign_b64:
            raise ValueError("支付宝回调缺少签名字段 sign")
        if sign_type != "RSA2":
            raise ValueError(
                f"支付宝回调拒绝弃用签名算法 sign_type={sign_type}（仅接受 RSA2）"
            )

        # 字典序排序后拼接（注意 value 已经过 parse_qsl 自动 URL decode）
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
        if params.get("app_id") != _APP_ID:
            raise ValueError(
                f"支付宝回调 app_id 不匹配：expected={_APP_ID} got={params.get('app_id')}"
            )
        if _SELLER_ID and params.get("seller_id") and params.get("seller_id") != _SELLER_ID:
            raise ValueError(
                f"支付宝回调 seller_id 不匹配：expected={_SELLER_ID} got={params.get('seller_id')}"
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
