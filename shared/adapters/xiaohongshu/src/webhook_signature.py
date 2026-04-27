"""Sprint E3 — 小红书 webhook HMAC-SHA256 签名校验

小红书核销 webhook 推送时会带以下 headers：
  · X-Xhs-Signature   — HMAC-SHA256(webhook_secret, timestamp + nonce + body)
  · X-Xhs-Timestamp   — unix 秒
  · X-Xhs-Nonce       — 一次性随机串（防重放，一般 16 字符）

本模块提供：
  · compute_signature(secret, timestamp, nonce, body) — 签名计算
  · verify_signature(secret, signature, timestamp, nonce, body, max_skew) — 验证
    · 时间偏差超过 max_skew 视为重放攻击
    · 签名不一致视为篡改

注：小红书真实签名算法可能因版本微调（如改用 hex / base64 编码、添加 app_id 等），
此实现基于 2025 版开放平台文档。上线前需对齐最新版本。
"""
from __future__ import annotations

import hashlib
import hmac
import time
from dataclasses import dataclass
from typing import Optional, Union

# 默认允许的时间偏差：5 分钟
DEFAULT_MAX_SKEW_SECONDS = 300


# ─────────────────────────────────────────────────────────────
# 错误类型
# ─────────────────────────────────────────────────────────────


class SignatureError(Exception):
    """签名校验失败（通用基类）"""


class TimestampSkewError(SignatureError):
    """时间戳偏差过大，疑似重放攻击"""


class SignatureMismatchError(SignatureError):
    """签名 HMAC 不匹配"""


class MissingHeaderError(SignatureError):
    """必需 header 缺失"""


# ─────────────────────────────────────────────────────────────
# 校验结果
# ─────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class VerificationResult:
    ok: bool
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    timestamp: Optional[int] = None
    nonce: Optional[str] = None

    @classmethod
    def success(cls, timestamp: int, nonce: str) -> "VerificationResult":
        return cls(ok=True, timestamp=timestamp, nonce=nonce)

    @classmethod
    def failure(cls, code: str, message: str) -> "VerificationResult":
        return cls(ok=False, error_code=code, error_message=message)


# ─────────────────────────────────────────────────────────────
# 签名计算 + 校验
# ─────────────────────────────────────────────────────────────


def compute_signature(
    *,
    secret: str,
    timestamp: Union[str, int],
    nonce: str,
    body: Union[str, bytes],
) -> str:
    """计算 HMAC-SHA256 签名，返回 hex 字符串

    拼接规则：`f"{timestamp}\\n{nonce}\\n{body}"`
    然后 HMAC-SHA256(secret, message) → hexdigest
    """
    if isinstance(body, bytes):
        body_str = body.decode("utf-8", errors="replace")
    else:
        body_str = body

    message = f"{timestamp}\n{nonce}\n{body_str}".encode("utf-8")
    key = secret.encode("utf-8")
    return hmac.new(key, message, hashlib.sha256).hexdigest()


def verify_signature(
    *,
    secret: str,
    signature: Optional[str],
    timestamp: Optional[Union[str, int]],
    nonce: Optional[str],
    body: Union[str, bytes],
    max_skew_seconds: int = DEFAULT_MAX_SKEW_SECONDS,
    now_seconds: Optional[int] = None,
) -> VerificationResult:
    """校验 webhook 签名

    返回 VerificationResult，失败时 error_code 标明原因。

    error_code 取值：
      · MISSING_HEADER — 缺 signature/timestamp/nonce
      · INVALID_TIMESTAMP — timestamp 不是整数
      · TIMESTAMP_TOO_OLD — 与服务器时差 > max_skew_seconds
      · HMAC_MISMATCH — 签名不一致
    """
    if not signature:
        return VerificationResult.failure(
            "MISSING_HEADER", "X-Xhs-Signature header 缺失"
        )
    if timestamp is None or timestamp == "":
        return VerificationResult.failure(
            "MISSING_HEADER", "X-Xhs-Timestamp header 缺失"
        )
    if not nonce:
        return VerificationResult.failure(
            "MISSING_HEADER", "X-Xhs-Nonce header 缺失"
        )

    try:
        ts_int = int(timestamp)
    except (TypeError, ValueError):
        return VerificationResult.failure(
            "INVALID_TIMESTAMP", f"timestamp 必须是整数秒，收到 {timestamp!r}"
        )

    current = now_seconds if now_seconds is not None else int(time.time())
    skew = abs(current - ts_int)
    if skew > max_skew_seconds:
        return VerificationResult.failure(
            "TIMESTAMP_TOO_OLD",
            f"时间偏差 {skew}s 超过上限 {max_skew_seconds}s，疑似重放",
        )

    expected = compute_signature(
        secret=secret, timestamp=ts_int, nonce=nonce, body=body
    )
    # 常量时间比较，避免 timing attack
    if not hmac.compare_digest(expected, signature.lower()):
        return VerificationResult.failure(
            "HMAC_MISMATCH", "签名与预期不符"
        )

    return VerificationResult.success(timestamp=ts_int, nonce=nonce)


def extract_xhs_headers(headers: dict) -> dict:
    """从 HTTP headers 中提取小红书签名相关字段

    支持大小写混合的 header key（FastAPI 默认小写，但原始请求可能混合）。
    返回：{'signature', 'timestamp', 'nonce'}，缺失项为 None
    """
    def _find(key: str) -> Optional[str]:
        # 先精确匹配，再大小写不敏感
        for k, v in headers.items():
            if k.lower() == key.lower():
                return v
        return None

    return {
        "signature": _find("X-Xhs-Signature"),
        "timestamp": _find("X-Xhs-Timestamp"),
        "nonce": _find("X-Xhs-Nonce"),
    }
