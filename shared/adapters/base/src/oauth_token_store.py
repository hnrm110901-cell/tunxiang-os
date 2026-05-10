"""统一渠道 OAuth Token 存储 + 自动续期

CH-01（channel-aggregation milestone, issue #375）：
为美团 / 抖音 / 饿了么 / 微信 / 小红书等渠道平台的 OAuth token 提供统一存取。

加密策略：
  - 应用层 Fernet 加密（cryptography lib），不依赖 pgcrypto
  - 密钥从 OS env `OAUTH_TOKEN_ENCRYPTION_KEY`（base64 32-byte），不入库不入代码
  - 同一密钥生成的 BYTEA 可跨服务解密（gateway / tx-trade / 自动续期 job）

接入点：
  - 各渠道 adapter 在拿到新 token 后调 `OAuthTokenStore.upsert()`
  - 调 API 前调 `OAuthTokenStore.get_or_refresh()` 获取有效 token
  - 自动续期 job 周期性调 `OAuthTokenStore.list_expiring_within()` 批量续期
"""

from __future__ import annotations

import base64
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Awaitable, Callable, Optional
from uuid import UUID

import structlog
from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger(__name__)

# ─────────────────────────────────────────────────────────────────
# 数据模型
# ─────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class OAuthToken:
    """渠道 OAuth token 业务对象（明文 token）。

    DB 层 access_token / refresh_token 是 BYTEA 加密形态，
    经 OAuthTokenStore 解密后返回本对象。
    """

    token_id: UUID
    tenant_id: UUID
    store_id: UUID
    platform: str
    account_id: str
    access_token: str  # 明文
    refresh_token: Optional[str]  # 明文，可空
    token_type: str
    expires_at: datetime
    refresh_expires_at: Optional[datetime]
    scope: Optional[str]
    last_refreshed_at: datetime
    refresh_failure_count: int

    def is_expiring_within(self, seconds: int) -> bool:
        """token 是否在 seconds 秒内过期。"""
        threshold = datetime.now(timezone.utc) + timedelta(seconds=seconds)
        return self.expires_at <= threshold


class OAuthTokenStoreError(Exception):
    """OAuthTokenStore 业务异常基类。"""


class TokenNotFoundError(OAuthTokenStoreError):
    """未找到对应 (tenant_id, store_id, platform, account_id) 的 token。"""


class TokenDecryptError(OAuthTokenStoreError):
    """解密失败 — 通常是密钥不匹配或数据被篡改。"""


# ─────────────────────────────────────────────────────────────────
# 加密层
# ─────────────────────────────────────────────────────────────────


def _load_fernet() -> Fernet:
    """从 OS env 加载 Fernet 密钥。

    env `OAUTH_TOKEN_ENCRYPTION_KEY` 必须是 base64 编码的 32-byte key。
    生成方式：python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    """
    key_b64 = os.environ.get("OAUTH_TOKEN_ENCRYPTION_KEY")
    if not key_b64:
        raise OAuthTokenStoreError(
            "OAUTH_TOKEN_ENCRYPTION_KEY env 未配置 — "
            "禁止以无密钥启动 OAuthTokenStore"
        )
    try:
        return Fernet(key_b64.encode() if isinstance(key_b64, str) else key_b64)
    except (ValueError, base64.binascii.Error) as exc:
        raise OAuthTokenStoreError(
            f"OAUTH_TOKEN_ENCRYPTION_KEY 格式错误（需 base64 32-byte）: {exc}"
        ) from exc


def _encrypt(fernet: Fernet, plain: Optional[str]) -> Optional[bytes]:
    if plain is None:
        return None
    return fernet.encrypt(plain.encode("utf-8"))


def _decrypt(fernet: Fernet, enc: Optional[bytes]) -> Optional[str]:
    if enc is None:
        return None
    try:
        return fernet.decrypt(bytes(enc)).decode("utf-8")
    except InvalidToken as exc:
        raise TokenDecryptError(
            "OAuth token 解密失败 — 密钥不匹配或数据被篡改"
        ) from exc


# ─────────────────────────────────────────────────────────────────
# Store
# ─────────────────────────────────────────────────────────────────


class OAuthTokenStore:
    """渠道 OAuth Token 持久化层。

    使用方式（AsyncSession 上下文需调用方建立 + 设置 app.tenant_id GUC）：

        store = OAuthTokenStore(session)
        token = await store.get(tenant_id, store_id, "meituan", "POI001")
        # 或
        token = await store.get_or_refresh(
            tenant_id, store_id, "meituan", "POI001",
            refresh_callback=lambda old: meituan_client.refresh_token(old.refresh_token),
        )
    """

    _TABLE = "channel_oauth_tokens"

    def __init__(self, session: AsyncSession, *, fernet: Optional[Fernet] = None) -> None:
        self._session = session
        self._fernet = fernet or _load_fernet()

    async def get(
        self,
        tenant_id: UUID,
        store_id: UUID,
        platform: str,
        account_id: str,
    ) -> Optional[OAuthToken]:
        """按业务键查 token。RLS 由 session 已设的 app.tenant_id GUC 保障。

        返回 None 表示该业务键尚未存过 token。
        """
        result = await self._session.execute(
            text(f"""
                SELECT token_id, tenant_id, store_id, platform, account_id,
                       access_token_enc, refresh_token_enc, token_type,
                       expires_at, refresh_expires_at, scope,
                       last_refreshed_at, refresh_failure_count
                FROM {self._TABLE}
                WHERE tenant_id = :tenant_id
                  AND store_id = :store_id
                  AND platform = :platform
                  AND account_id = :account_id
                  AND is_deleted = FALSE
                LIMIT 1
            """),
            {
                "tenant_id": str(tenant_id),
                "store_id": str(store_id),
                "platform": platform,
                "account_id": account_id,
            },
        )
        row = result.mappings().first()
        if row is None:
            return None
        return self._row_to_token(row)

    async def upsert(
        self,
        *,
        tenant_id: UUID,
        store_id: UUID,
        platform: str,
        account_id: str,
        access_token: str,
        refresh_token: Optional[str],
        expires_at: datetime,
        refresh_expires_at: Optional[datetime] = None,
        token_type: str = "Bearer",
        scope: Optional[str] = None,
    ) -> OAuthToken:
        """upsert token — 同业务键存在则更新，否则插入。

        upsert 同时把 refresh_failure_count 重置为 0（成功获取新 token 即视为续期成功）。
        """
        access_enc = _encrypt(self._fernet, access_token)
        refresh_enc = _encrypt(self._fernet, refresh_token)

        result = await self._session.execute(
            text(f"""
                INSERT INTO {self._TABLE}
                    (tenant_id, store_id, platform, account_id,
                     access_token_enc, refresh_token_enc, token_type,
                     expires_at, refresh_expires_at, scope,
                     last_refreshed_at, refresh_failure_count, last_refresh_error)
                VALUES
                    (:tenant_id, :store_id, :platform, :account_id,
                     :access_enc, :refresh_enc, :token_type,
                     :expires_at, :refresh_expires_at, :scope,
                     NOW(), 0, NULL)
                ON CONFLICT (tenant_id, store_id, platform, account_id) DO UPDATE SET
                    access_token_enc = EXCLUDED.access_token_enc,
                    refresh_token_enc = EXCLUDED.refresh_token_enc,
                    token_type = EXCLUDED.token_type,
                    expires_at = EXCLUDED.expires_at,
                    refresh_expires_at = EXCLUDED.refresh_expires_at,
                    scope = EXCLUDED.scope,
                    last_refreshed_at = NOW(),
                    refresh_failure_count = 0,
                    last_refresh_error = NULL,
                    updated_at = NOW()
                RETURNING token_id, tenant_id, store_id, platform, account_id,
                          access_token_enc, refresh_token_enc, token_type,
                          expires_at, refresh_expires_at, scope,
                          last_refreshed_at, refresh_failure_count
            """),
            {
                "tenant_id": str(tenant_id),
                "store_id": str(store_id),
                "platform": platform,
                "account_id": account_id,
                "access_enc": access_enc,
                "refresh_enc": refresh_enc,
                "token_type": token_type,
                "expires_at": expires_at,
                "refresh_expires_at": refresh_expires_at,
                "scope": scope,
            },
        )
        row = result.mappings().first()
        logger.info(
            "oauth_token_upserted",
            tenant_id=str(tenant_id),
            store_id=str(store_id),
            platform=platform,
            account_id=account_id,
            expires_at=expires_at.isoformat(),
        )
        return self._row_to_token(row)

    async def get_or_refresh(
        self,
        tenant_id: UUID,
        store_id: UUID,
        platform: str,
        account_id: str,
        *,
        refresh_callback: Callable[[OAuthToken], Awaitable[dict]],
        threshold_seconds: int = 300,
    ) -> OAuthToken:
        """拿 token，若 threshold_seconds 内将过期则触发续期。

        refresh_callback(old_token) 必须返回 dict 含至少：
            {access_token, refresh_token (可空), expires_at}
        可选：refresh_expires_at / token_type / scope
        """
        token = await self.get(tenant_id, store_id, platform, account_id)
        if token is None:
            raise TokenNotFoundError(
                f"未找到 token：tenant={tenant_id} store={store_id} "
                f"platform={platform} account={account_id}"
            )
        if not token.is_expiring_within(threshold_seconds):
            return token

        # 触发续期
        try:
            new_payload = await refresh_callback(token)
        except Exception as exc:
            await self._record_refresh_failure(token.token_id, str(exc))
            raise

        return await self.upsert(
            tenant_id=tenant_id,
            store_id=store_id,
            platform=platform,
            account_id=account_id,
            access_token=new_payload["access_token"],
            refresh_token=new_payload.get("refresh_token"),
            expires_at=new_payload["expires_at"],
            refresh_expires_at=new_payload.get("refresh_expires_at"),
            token_type=new_payload.get("token_type", "Bearer"),
            scope=new_payload.get("scope"),
        )

    async def list_expiring_within(
        self, tenant_id: UUID, within_seconds: int
    ) -> list[OAuthToken]:
        """扫即将过期的 token，供自动续期 job 用。"""
        threshold = datetime.now(timezone.utc) + timedelta(seconds=within_seconds)
        result = await self._session.execute(
            text(f"""
                SELECT token_id, tenant_id, store_id, platform, account_id,
                       access_token_enc, refresh_token_enc, token_type,
                       expires_at, refresh_expires_at, scope,
                       last_refreshed_at, refresh_failure_count
                FROM {self._TABLE}
                WHERE tenant_id = :tenant_id
                  AND is_deleted = FALSE
                  AND expires_at <= :threshold
                ORDER BY expires_at ASC
            """),
            {"tenant_id": str(tenant_id), "threshold": threshold},
        )
        return [self._row_to_token(row) for row in result.mappings().all()]

    async def _record_refresh_failure(self, token_id: UUID, error: str) -> None:
        """续期失败 — 累加计数 + 记录原因。"""
        await self._session.execute(
            text(f"""
                UPDATE {self._TABLE}
                SET refresh_failure_count = refresh_failure_count + 1,
                    last_refresh_error = :error,
                    updated_at = NOW()
                WHERE token_id = :token_id
            """),
            {"token_id": str(token_id), "error": error[:1000]},
        )
        logger.warning(
            "oauth_token_refresh_failed", token_id=str(token_id), error=error[:200]
        )

    def _row_to_token(self, row) -> OAuthToken:
        return OAuthToken(
            token_id=row["token_id"],
            tenant_id=row["tenant_id"],
            store_id=row["store_id"],
            platform=row["platform"],
            account_id=row["account_id"],
            access_token=_decrypt(self._fernet, row["access_token_enc"]),
            refresh_token=_decrypt(self._fernet, row["refresh_token_enc"]),
            token_type=row["token_type"],
            expires_at=row["expires_at"],
            refresh_expires_at=row["refresh_expires_at"],
            scope=row["scope"],
            last_refreshed_at=row["last_refreshed_at"],
            refresh_failure_count=row["refresh_failure_count"],
        )
