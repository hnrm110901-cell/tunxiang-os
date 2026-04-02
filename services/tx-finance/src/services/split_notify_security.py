"""分账通道回调 — 共享密钥 HMAC 验签（无 DB / 无 shared 依赖，便于单测）。"""
from __future__ import annotations

import hashlib
import hmac
import os
from typing import Optional


def verify_split_channel_notify_signature(
    body: bytes,
    signature_header: Optional[str],
) -> None:
    """环境变量 ``TX_FINANCE_SPLIT_NOTIFY_SECRET`` 非空时，校验 ``X-Split-Notify-Signature``。

    签名算法：``hex(HMAC-SHA256(secret, raw_body))``，与请求体字节完全一致。
    """
    secret = os.getenv("TX_FINANCE_SPLIT_NOTIFY_SECRET", "").strip()
    if not secret:
        return
    if not signature_header or not signature_header.strip():
        raise ValueError("missing X-Split-Notify-Signature")
    expected = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature_header.strip(), expected):
        raise ValueError("invalid X-Split-Notify-Signature")
