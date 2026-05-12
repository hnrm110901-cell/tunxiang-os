"""收钱吧服务商支付 SDK — 终端通知验签

官方 spec: https://doc.shouqianba.com/zh-cn/api/sign.html

签名机制（与微信/支付宝完全不同 — 对称密钥 MD5 而非 RSA）：
  - Authorization: `<sn> <sign>`（sn 与 sign 用一个空格分隔，非 Bearer scheme）
  - 算法：`sign = MD5(utf8_body_bytes + terminal_key)`（拼接后 MD5，**非 HMAC**）
  - sn：激活后用 terminal_sn，激活前用 vendor_sn
  - 商户验签时用对应的 terminal_key（对称密钥，泄露 = 验签可被绕过）

环境变量：
  SHOUQIANBA_TERMINAL_SN   — 终端激活后获取的终端流水号（必填）
  SHOUQIANBA_TERMINAL_KEY  — 终端激活后获取的密钥（必填）

设计说明（沿用 alipay_sdk.py 的 P0-B 修复模式）：
  环境变量通过方法 _terminal_sn() / _terminal_key() 读取，每次重读 os.environ，
  避免模块加载快照与 setenv/monkeypatch 不一致。
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os

logger = logging.getLogger(__name__)


# ─── 环境变量（每次访问重读） ────────────────────────────────────────────


def _terminal_sn() -> str:
    return os.environ.get("SHOUQIANBA_TERMINAL_SN", "")


def _terminal_key() -> str:
    return os.environ.get("SHOUQIANBA_TERMINAL_KEY", "")


def _is_configured() -> bool:
    return bool(_terminal_sn() and _terminal_key())


def _is_production_env() -> bool:
    env = (os.environ.get("ENVIRONMENT") or os.environ.get("ENV") or "").strip().lower()
    return env in ("production", "prod")


def _mock_explicitly_allowed() -> bool:
    return os.environ.get("TX_SHOUQIANBA_ALLOW_MOCK", "").strip().lower() in (
        "1", "true", "yes", "on",
    )


def _get_authorization(headers: dict) -> str:
    """读取 Authorization header（不区分大小写）。"""
    for k, v in headers.items():
        if k.lower() == "authorization":
            return str(v)
    return ""


# ─── 主入口：ShouqianbaService ──────────────────────────────────────────


class ShouqianbaService:
    """收钱吧服务商支付服务

    - 未配置时：非生产为 Mock；生产默认拒绝实例化（除非 TX_SHOUQIANBA_ALLOW_MOCK=1）
    - 签名算法：MD5(body + terminal_key) — 对称密钥拼接 MD5，非 HMAC
    """

    def __init__(self) -> None:
        # P0 fix: 启动时检查生产环境配置（早 fail），但**不固化 _mock_mode**。
        # _mock_mode 改为方法 _is_mock_mode() 每次访问重读 env，与 _terminal_key()
        # 热更新设计一致；防止 K8s init container 竞态 / docker-compose 启动顺序
        # 导致单例固化 mock 模式后静默绕过验签。
        if not _is_configured():
            if _is_production_env() and not _mock_explicitly_allowed():
                raise RuntimeError(
                    "生产环境禁止收钱吧 Mock：请配置 SHOUQIANBA_TERMINAL_SN / "
                    "SHOUQIANBA_TERMINAL_KEY；若仅为灰度演练需 Mock，请显式设置 "
                    "TX_SHOUQIANBA_ALLOW_MOCK=1"
                )
            logger.warning(
                "ShouqianbaService 进入 Mock 模式：请配置 SHOUQIANBA_TERMINAL_SN / "
                "SHOUQIANBA_TERMINAL_KEY"
            )

    def _is_mock_mode(self) -> bool:
        """P0 fix: 每次调用重读 env，避免单例快照与热更新矛盾。"""
        return not _is_configured()

    async def verify_callback(self, headers: dict, body: bytes) -> dict:
        """验证收钱吧终端通知签名并返回 body JSON dict。

        步骤：
          1. 读 Authorization header（空格分隔的 sn 和 sign）
          2. 校验 sn 与本商户 terminal_sn 匹配（防别家商户回放）
          3. 计算 expected_sign = MD5(body_bytes + terminal_key)
          4. 常量时间比较 expected_sign vs 收到的 sign
          5. 解析 JSON body 返回（业务字段校验由上层 Saga 处理）
        """
        if self._is_mock_mode():
            return self._mock_callback_response(body)

        auth = _get_authorization(headers)
        if not auth:
            raise ValueError("收钱吧回调缺少 Authorization 签名头")
        if " " not in auth:
            raise ValueError("收钱吧回调 Authorization 格式错（应为 '<sn> <sign>'）")

        sn, _, sign_hex = auth.partition(" ")
        sn = sn.strip()
        sign_hex = sign_hex.strip().lower()

        expected_sn = _terminal_sn()
        if sn != expected_sn:
            # P1-B fix: 不在错误消息中暴露本商户 expected_sn（密钥管理）
            raise ValueError(f"收钱吧回调 terminal_sn 与本商户不匹配 got={sn}")

        body_bytes = body if isinstance(body, bytes) else body.encode("utf-8")
        expected_sign = hashlib.md5(
            body_bytes + _terminal_key().encode("utf-8")
        ).hexdigest().lower()

        # 常量时间比较防侧信道
        if not hmac.compare_digest(expected_sign, sign_hex):
            raise ValueError("收钱吧回调签名验签失败")

        # 解析 JSON body
        import json

        try:
            return json.loads(body_bytes.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise ValueError(f"收钱吧回调 body 非合法 JSON：{exc}") from exc

    # ─── Mock 响应 ───

    def _mock_callback_response(self, body: bytes) -> dict:
        import json

        body_bytes = body if isinstance(body, bytes) else body.encode("utf-8")
        try:
            data = json.loads(body_bytes.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            data = {}
        data.setdefault("order_status", "PAID")
        data.setdefault("client_sn", "MOCK_SQB_CLIENT_SN")
        return data


# ─── 全局单例 ───

_instance: ShouqianbaService | None = None


def get_shouqianba_service() -> ShouqianbaService:
    global _instance
    if _instance is None:
        _instance = ShouqianbaService()
    return _instance
