"""跨渠道身份解析服务 — CDP 渠道部分（CH-13）

CH-13（channel-aggregation milestone, issue #393）：
负责把 phone / openid / card_no / email 反向映射到统一 member_id，
让 mv_member_clv 全渠道版（CH-15）能算"老客复购率"。

与既有 `identity_resolver.py` 的分工：
  - 既有 IdentityResolver：S2W5 CDP WiFi 时间关联匹配（resolve_wifi_visit / resolve_external_order）
  - 本模块 ChannelIdentityResolver：渠道 OAuth identity（phone / openid 等）确定性映射
  - 两者共享 member_identity_map 表（v413），但解析路径完全不同
  - 后续可合并到统一的 CDP IdentityService（独立 issue）

依赖表：member_identity_map（v413）

哈希策略：
  - phone / card_no / email 全部 SHA256 哈希后存储，不存原文
  - salt 从 OS env `IDENTITY_HASH_SALT` 读取，防彩虹表
  - 标准化在哈希前完成（详见 _normalize_*）
"""

from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Optional
from uuid import UUID, uuid4

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger(__name__)

VALID_IDENTITY_TYPES = ("phone", "openid", "card_no", "email")


@dataclass(frozen=True)
class ChannelIdentity:
    identity_id: UUID
    tenant_id: UUID
    member_id: UUID
    identity_type: str
    identity_value_hash: str
    platform: Optional[str]
    confidence: float
    first_seen_at: datetime
    last_seen_at: datetime
    source: Optional[str]


class ChannelIdentityResolverError(Exception):
    """ChannelIdentityResolver 业务异常基类。"""


class InvalidIdentityTypeError(ChannelIdentityResolverError):
    """identity_type 不在 VALID_IDENTITY_TYPES。"""


class MissingPlatformError(ChannelIdentityResolverError):
    """openid 类型必须指定 platform。"""


# ─────────────────────────────────────────────────────────────────
# 标准化
# ─────────────────────────────────────────────────────────────────


def _normalize_phone(value: str) -> str:
    """中国大陆手机号标准化：去 +86 / 前导 0 / 空格 / 横线 → 11 位裸号。"""
    cleaned = re.sub(r"[\s\-]", "", value.strip())
    cleaned = re.sub(r"^\+?86", "", cleaned)
    cleaned = re.sub(r"^0+", "", cleaned)
    return cleaned


def _normalize_email(value: str) -> str:
    return value.strip().lower()


def _normalize_card_no(value: str) -> str:
    return re.sub(r"[\s\-]", "", value.strip())


def _normalize_openid(value: str) -> str:
    return value.strip()


_NORMALIZERS = {
    "phone": _normalize_phone,
    "email": _normalize_email,
    "card_no": _normalize_card_no,
    "openid": _normalize_openid,
}


def normalize(identity_type: str, value: str) -> str:
    """按 identity_type 标准化 value（哈希前必做）。"""
    if identity_type not in _NORMALIZERS:
        raise InvalidIdentityTypeError(
            f"identity_type={identity_type!r} 不支持，"
            f"允许：{VALID_IDENTITY_TYPES}"
        )
    return _NORMALIZERS[identity_type](value)


# ─────────────────────────────────────────────────────────────────
# 哈希
# ─────────────────────────────────────────────────────────────────


def _load_salt() -> bytes:
    salt = os.environ.get("IDENTITY_HASH_SALT")
    if not salt:
        raise ChannelIdentityResolverError(
            "IDENTITY_HASH_SALT env 未配置 — 禁止以无 salt 哈希身份"
        )
    return salt.encode("utf-8")


def hash_identity(
    identity_type: str, value: str, *, salt: Optional[bytes] = None
) -> str:
    """对 (identity_type, value) 计算 SHA256 哈希（hex 64 字符）。

    标准化由本函数内部完成 — 调用方传原始 value 即可。
    """
    normalized = normalize(identity_type, value)
    salt_bytes = salt if salt is not None else _load_salt()
    h = hashlib.sha256()
    h.update(salt_bytes)
    h.update(identity_type.encode("utf-8"))
    h.update(b":")
    h.update(normalized.encode("utf-8"))
    return h.hexdigest()


# ─────────────────────────────────────────────────────────────────
# Resolver
# ─────────────────────────────────────────────────────────────────


class ChannelIdentityResolver:
    """跨渠道身份解析。

    使用方式（AsyncSession 上下文需调用方建立 + 设置 app.tenant_id GUC）：

        resolver = ChannelIdentityResolver(session)
        member_id = await resolver.resolve(
            tenant_id=tid, identity_type="phone", value="13900001111", platform=None
        )
    """

    _TABLE = "member_identity_map"

    def __init__(
        self, session: AsyncSession, *, salt: Optional[bytes] = None
    ) -> None:
        self._session = session
        self._salt = salt if salt is not None else _load_salt()

    def _validate(self, identity_type: str, platform: Optional[str]) -> None:
        if identity_type not in VALID_IDENTITY_TYPES:
            raise InvalidIdentityTypeError(
                f"identity_type={identity_type!r} 不支持，"
                f"允许：{VALID_IDENTITY_TYPES}"
            )
        if identity_type == "openid" and not platform:
            raise MissingPlatformError(
                "openid 类型必须指定 platform — openid 仅在 platform 内唯一"
            )

    async def resolve(
        self,
        tenant_id: UUID,
        identity_type: str,
        value: str,
        platform: Optional[str] = None,
    ) -> Optional[UUID]:
        """按 (identity_type, value, platform) 查找已映射的 member_id。

        返回 None 表示未注册过。
        """
        self._validate(identity_type, platform)
        identity_hash = hash_identity(identity_type, value, salt=self._salt)

        result = await self._session.execute(
            text(f"""
                SELECT member_id
                FROM {self._TABLE}
                WHERE tenant_id = :tenant_id
                  AND identity_type = :identity_type
                  AND identity_value_hash = :hash
                  AND platform IS NOT DISTINCT FROM :platform
                  AND is_deleted = FALSE
                LIMIT 1
            """),
            {
                "tenant_id": str(tenant_id),
                "identity_type": identity_type,
                "hash": identity_hash,
                "platform": platform,
            },
        )
        row = result.mappings().first()
        return row["member_id"] if row else None

    async def link(
        self,
        tenant_id: UUID,
        member_id: UUID,
        identity_type: str,
        value: str,
        platform: Optional[str] = None,
        *,
        confidence: float = 1.0,
        source: Optional[str] = None,
    ) -> None:
        """upsert 一条 identity 记录，关联到给定 member_id。

        同业务键再次 link → 更新 last_seen_at + confidence（取大值）。
        """
        self._validate(identity_type, platform)
        if not 0 <= confidence <= 1:
            raise ChannelIdentityResolverError(
                f"confidence 必须在 [0,1]，收到 {confidence}"
            )
        identity_hash = hash_identity(identity_type, value, salt=self._salt)

        await self._session.execute(
            text(f"""
                INSERT INTO {self._TABLE}
                    (tenant_id, member_id, identity_type, identity_value_hash,
                     platform, confidence, first_seen_at, last_seen_at, source)
                VALUES
                    (:tenant_id, :member_id, :identity_type, :hash,
                     :platform, :confidence, NOW(), NOW(), :source)
                ON CONFLICT (tenant_id, identity_type, identity_value_hash, platform)
                DO UPDATE SET
                    last_seen_at = NOW(),
                    confidence = GREATEST(
                        {self._TABLE}.confidence, EXCLUDED.confidence
                    ),
                    updated_at = NOW()
            """),
            {
                "tenant_id": str(tenant_id),
                "member_id": str(member_id),
                "identity_type": identity_type,
                "hash": identity_hash,
                "platform": platform,
                "confidence": confidence,
                "source": source,
            },
        )
        logger.info(
            "channel_identity_linked",
            tenant_id=str(tenant_id),
            member_id=str(member_id),
            identity_type=identity_type,
            platform=platform,
            confidence=confidence,
            source=source,
        )

    async def get_or_create_member(
        self,
        tenant_id: UUID,
        identity_type: str,
        value: str,
        platform: Optional[str] = None,
        *,
        source: Optional[str] = None,
    ) -> tuple[UUID, bool]:
        """查找 member_id，未找到则创建新 member 并 link。

        返回 (member_id, was_created)。
        was_created=True 表示这一调用新建了 member（调用方可能需要后续填充 customer 主表）。
        """
        existing = await self.resolve(tenant_id, identity_type, value, platform)
        if existing is not None:
            await self.link(
                tenant_id, existing, identity_type, value, platform,
                source=source,
            )
            return existing, False

        new_member_id = uuid4()
        await self.link(
            tenant_id, new_member_id, identity_type, value, platform,
            source=source,
        )
        return new_member_id, True

    async def list_member_identities(
        self, tenant_id: UUID, member_id: UUID
    ) -> list[ChannelIdentity]:
        """反向列出某 member 的所有 identity（CH-15 mv_member_clv 全渠道版用）。"""
        result = await self._session.execute(
            text(f"""
                SELECT identity_id, tenant_id, member_id, identity_type,
                       identity_value_hash, platform, confidence,
                       first_seen_at, last_seen_at, source
                FROM {self._TABLE}
                WHERE tenant_id = :tenant_id
                  AND member_id = :member_id
                  AND is_deleted = FALSE
                ORDER BY first_seen_at ASC
            """),
            {"tenant_id": str(tenant_id), "member_id": str(member_id)},
        )
        return [
            ChannelIdentity(
                identity_id=row["identity_id"],
                tenant_id=row["tenant_id"],
                member_id=row["member_id"],
                identity_type=row["identity_type"],
                identity_value_hash=row["identity_value_hash"],
                platform=row["platform"],
                confidence=float(row["confidence"]),
                first_seen_at=row["first_seen_at"],
                last_seen_at=row["last_seen_at"],
                source=row["source"],
            )
            for row in result.mappings().all()
        ]
