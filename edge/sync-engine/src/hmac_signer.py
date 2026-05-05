"""Edge sync HMAC 签名器 — 客户端侧

审计 NEW-P0：服务端 sync_ingest_router 三个端点（ingest/changes/pull）启用了
verify_edge_sync_auth 强制校验（PR #195）；本签名器在客户端发送请求时附加
5 个 X-Edge-* headers 让服务端 cutover (EDGE_SYNC_HMAC_REQUIRED=true) 后仍能
正常工作。

签名内容（与服务端 verify_edge_sync_auth 完全对应）：
    HMAC_SHA256(EDGE_SYNC_HMAC_SECRET,
                f"{store_id}.{tenant_id}.{ts}.{nonce}")

⚠️ ts 必须是 send-time 而非 write-time —— 否则边缘离线 4h 后回传时所有
积压请求 ts 都是 4h 前的，会被服务端时间戳窗口拒绝。
本 signer 在 sign_headers() 调用时即时生成 ts + nonce，已满足 send-time 要求。

环境变量：
    EDGE_SYNC_HMAC_SECRET — 共享密钥（K8s Secret 注入；本地 dev 可用 launchd plist）
    EDGE_STORE_ID         — 本店唯一标识（UUID 或 ASCII slug）

dev/staging 兼容：
    任一 env 缺失 → from_env() 返回 None；调用方应跳过签名，仅发 X-Tenant-ID。
    服务端默认 EDGE_SYNC_HMAC_REQUIRED=false 即兼容，新部署需先验证 client 发的
    token 能通过校验，再翻 required=true 真切 cutover。
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
import time
import uuid
from typing import Optional

logger = logging.getLogger(__name__)


class EdgeHmacSigner:
    """每实例对应"本店 + 本租户"，每次 sign_headers() 生成新 nonce + ts。"""

    __slots__ = ("_store_id", "_tenant_id", "_secret")

    def __init__(self, store_id: str, tenant_id: str, secret: str) -> None:
        if not store_id or not tenant_id or not secret:
            raise ValueError("EdgeHmacSigner: store_id / tenant_id / secret 都不能为空")
        self._store_id = store_id
        self._tenant_id = tenant_id
        self._secret = secret

    @classmethod
    def from_env(cls, tenant_id: str) -> Optional["EdgeHmacSigner"]:
        """读 EDGE_SYNC_HMAC_SECRET + EDGE_STORE_ID env；任一缺失返回 None。

        返回 None 时调用方只发 X-Tenant-ID（dev/staging 兼容）；
        服务端默认 required=false 接受兼容回退。
        """
        secret = os.environ.get("EDGE_SYNC_HMAC_SECRET", "").strip()
        store_id = os.environ.get("EDGE_STORE_ID", "").strip()
        if not secret or not store_id:
            logger.debug(
                "edge_hmac_signer_disabled",
                has_secret=bool(secret),
                has_store_id=bool(store_id),
            )
            return None
        if not tenant_id:
            return None
        return cls(store_id, tenant_id, secret)

    def sign_headers(
        self,
        *,
        ts: Optional[int] = None,
        nonce: Optional[str] = None,
    ) -> dict[str, str]:
        """生成 5 个签名 header；每次调用 ts + nonce 都新生成。

        参数 ts / nonce 仅供测试注入；生产应让默认值（time.time / uuid4）生效。
        """
        if ts is None:
            ts = int(time.time())
        if nonce is None:
            nonce = uuid.uuid4().hex
        msg = f"{self._store_id}.{self._tenant_id}.{ts}.{nonce}".encode("utf-8")
        token = hmac.new(self._secret.encode("utf-8"), msg, hashlib.sha256).hexdigest()
        return {
            "X-Edge-Store-Id": self._store_id,
            "X-Edge-Tenant-Id": self._tenant_id,
            "X-Edge-Sync-Ts": str(ts),
            "X-Edge-Sync-Nonce": nonce,
            "X-Edge-Store-Token": token,
        }


def build_sync_headers(tenant_id: str) -> dict[str, str]:
    """便捷函数：返回带 X-Tenant-ID + 可能的 5 个 X-Edge-* 签名 header 的 dict。

    集成方在每次 HTTP 调用前调一次本函数即可，不需要管 signer 是否启用。
    """
    headers = {"X-Tenant-ID": tenant_id}
    signer = EdgeHmacSigner.from_env(tenant_id)
    if signer is not None:
        headers.update(signer.sign_headers())
    return headers
