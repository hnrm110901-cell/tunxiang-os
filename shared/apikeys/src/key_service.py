"""API Key CRUD 服务 — 管理第三方开发者密钥"""
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

import structlog
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from .key_generator import generate_api_key, hash_api_key

logger = structlog.get_logger()

# 允许的权限范围
VALID_PERMISSIONS = {
    "orders:read",
    "orders:write",
    "menu:read",
    "menu:write",
    "members:read",
    "members:write",
    "inventory:read",
    "inventory:write",
    "finance:read",
    "webhooks:manage",
}

API_KEYS_TABLE = "api_keys"


class APIKeyNotFoundError(LookupError):
    """API 密钥不存在"""


class APIKeyPermissionError(ValueError):
    """权限范围不合法"""


class APIKeyService:
    """API 密钥管理服务"""

    def __init__(self, db: AsyncSession, tenant_id: str):
        self.db = db
        self.tenant_id = tenant_id

    async def create_key(
        self,
        name: str,
        permissions: Optional[list[str]] = None,
        rate_limit_rps: int = 10,
        expires_at: Optional[datetime] = None,
    ) -> dict[str, Any]:
        """创建新的 API 密钥。

        Returns:
            包含 full_key（仅此一次）、key_prefix、id、name 等
        """
        perms = permissions or ["orders:read"]
        invalid = set(perms) - VALID_PERMISSIONS
        if invalid:
            raise APIKeyPermissionError(f"无效权限: {invalid}")

        full_key, key_prefix, key_hash = generate_api_key()
        key_id = uuid.uuid4()

        await self.db.execute(
            f"INSERT INTO {API_KEYS_TABLE} "
            f"(id, tenant_id, name, key_prefix, key_hash, permissions, rate_limit_rps, status, expires_at) "
            f"VALUES (:id, :tenant_id, :name, :key_prefix, :key_hash, :permissions, :rps, 'active', :expires_at)",
            {
                "id": key_id,
                "tenant_id": self.tenant_id,
                "name": name,
                "key_prefix": key_prefix,
                "key_hash": key_hash,
                "permissions": perms,
                "rps": rate_limit_rps,
                "expires_at": expires_at,
            },
        )
        await self.db.commit()

        logger.info(
            "apikey.created",
            key_id=str(key_id),
            tenant_id=self.tenant_id,
            name=name,
        )

        return {
            "id": str(key_id),
            "full_key": full_key,  # 唯一一次返回完整密钥
            "key_prefix": key_prefix,
            "name": name,
            "permissions": perms,
            "rate_limit_rps": rate_limit_rps,
            "status": "active",
            "expires_at": expires_at.isoformat() if expires_at else None,
        }

    async def list_keys(self) -> list[dict[str, Any]]:
        """列出租户下所有 API 密钥（不返回 full_key）。"""
        result = await self.db.execute(
            f"SELECT id, name, key_prefix, permissions, rate_limit_rps, "
            f"status, expires_at, last_used_at, created_at "
            f"FROM {API_KEYS_TABLE} "
            f"WHERE tenant_id = :tenant_id AND is_deleted = FALSE "
            f"ORDER BY created_at DESC",
            {"tenant_id": self.tenant_id},
        )
        rows = result.fetchall()
        return [dict(row._mapping) for row in rows]

    async def revoke_key(self, key_id: uuid.UUID) -> None:
        """吊销 API 密钥。"""
        result = await self.db.execute(
            f"UPDATE {API_KEYS_TABLE} SET status = 'revoked', updated_at = :now "
            f"WHERE id = :id AND tenant_id = :tenant_id AND is_deleted = FALSE "
            f"RETURNING id",
            {
                "id": key_id,
                "tenant_id": self.tenant_id,
                "now": datetime.now(timezone.utc),
            },
        )
        if not result.fetchone():
            raise APIKeyNotFoundError(f"密钥 {key_id} 不存在或不属于租户 {self.tenant_id}")
        await self.db.commit()
        logger.info("apikey.revoked", key_id=str(key_id), tenant_id=self.tenant_id)

    @staticmethod
    async def authenticate(full_key: str, db: AsyncSession) -> Optional[dict[str, Any]]:
        """验证 API 密钥并返回密钥信息。

        根据 key_prefix 定位记录，比对 SHA-256 哈希。
        """
        if len(full_key) < 10:
            return None
        key_prefix = full_key[:10]

        result = await db.execute(
            f"SELECT id, tenant_id, name, key_hash, permissions, rate_limit_rps, "
            f"status, expires_at "
            f"FROM {API_KEYS_TABLE} "
            f"WHERE key_prefix = :prefix AND is_deleted = FALSE",
            {"prefix": key_prefix},
        )
        row = result.fetchone()
        if not row:
            return None

        key_hash = hash_api_key(full_key)
        if row.key_hash != key_hash:
            return None

        if row.status != "active":
            return None

        if row.expires_at and row.expires_at < datetime.now(timezone.utc):
            return None

        # 更新 last_used_at
        await db.execute(
            f"UPDATE {API_KEYS_TABLE} SET last_used_at = :now WHERE id = :id",
            {"now": datetime.now(timezone.utc), "id": row.id},
        )
        await db.commit()

        return {
            "id": str(row.id),
            "tenant_id": str(row.tenant_id),
            "name": row.name,
            "permissions": row.permissions,
            "rate_limit_rps": row.rate_limit_rps,
        }
