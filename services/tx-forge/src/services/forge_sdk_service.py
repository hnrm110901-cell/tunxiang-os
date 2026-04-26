"""Forge SDK 服务 — API 密钥管理 & 用量统计

职责：
  1. generate_api_key()  — 生成开发者 API 密钥（密钥仅返回一次）
  2. revoke_api_key()    — 吊销密钥
  3. list_api_keys()     — 列出密钥（脱敏显示）
  4. get_api_usage()     — 用量汇总（按配额计算）
"""

from __future__ import annotations

import hashlib
import secrets
from uuid import uuid4

import structlog
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger(__name__)

# 配额：company 10万/月, individual 1万/月
_QUOTA_MAP = {
    "company": 100_000,
    "individual": 10_000,
    "internal": 100_000,
}


class ForgeSDKService:
    """API 密钥生命周期管理"""

    async def generate_api_key(
        self,
        db: AsyncSession,
        *,
        developer_id: str,
        key_name: str,
        permissions: list[str] | None = None,
    ) -> dict:
        """生成 API 密钥，raw_key 仅此一次返回。"""
        key_id = f"key_{uuid4().hex[:12]}"
        raw_key = f"txforge_{secrets.token_urlsafe(32)}"
        api_key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
        api_key_prefix = raw_key[:16]

        result = await db.execute(
            text("""
                INSERT INTO forge_api_keys
                    (key_id, developer_id, key_name, api_key_hash,
                     api_key_prefix, permissions, status, usage_count)
                VALUES
                    (:key_id, :developer_id, :key_name, :api_key_hash,
                     :api_key_prefix, :permissions, 'active', 0)
                RETURNING id, key_id, key_name, api_key_prefix,
                          permissions, status, created_at
            """),
            {
                "key_id": key_id,
                "developer_id": developer_id,
                "key_name": key_name,
                "api_key_hash": api_key_hash,
                "api_key_prefix": api_key_prefix,
                "permissions": permissions or [],
            },
        )
        row = result.mappings().one()
        await db.commit()

        logger.info(
            "api_key_generated",
            key_id=key_id,
            developer_id=developer_id,
            key_name=key_name,
        )

        return {
            **dict(row),
            "api_key": raw_key,  # 唯一一次明文返回
        }

    async def revoke_api_key(self, db: AsyncSession, key_id: str) -> dict:
        """吊销 API 密钥。"""
        result = await db.execute(
            text("""
                UPDATE forge_api_keys
                SET status = 'revoked', revoked_at = NOW()
                WHERE key_id = :key_id AND status = 'active'
                RETURNING key_id, status, revoked_at
            """),
            {"key_id": key_id},
        )
        row = result.mappings().first()
        if not row:
            raise HTTPException(status_code=404, detail="密钥不存在或已吊销")
        await db.commit()

        logger.info("api_key_revoked", key_id=key_id)
        return dict(row)

    async def list_api_keys(
        self, db: AsyncSession, developer_id: str
    ) -> list[dict]:
        """列出开发者的所有密钥（前缀脱敏显示）。"""
        result = await db.execute(
            text("""
                SELECT key_id, key_name, api_key_prefix, permissions,
                       status, usage_count, last_used_at, created_at, revoked_at
                FROM forge_api_keys
                WHERE developer_id = :developer_id
                ORDER BY created_at DESC
            """),
            {"developer_id": developer_id},
        )
        rows = result.mappings().all()
        return [
            {**dict(r), "api_key_display": f"{r['api_key_prefix']}..."}
            for r in rows
        ]

    async def get_api_usage(
        self,
        db: AsyncSession,
        developer_id: str,
        *,
        period: str = "month",
    ) -> dict:
        """汇总开发者 API 用量及配额。"""
        # 获取开发者类型以确定配额
        dev_result = await db.execute(
            text("""
                SELECT dev_type
                FROM forge_developers
                WHERE developer_id = :developer_id
            """),
            {"developer_id": developer_id},
        )
        dev_row = dev_result.mappings().first()
        dev_type = dev_row["dev_type"] if dev_row else "individual"
        quota = _QUOTA_MAP.get(dev_type, 10_000)

        # 汇总用量
        result = await db.execute(
            text("""
                SELECT
                    COALESCE(SUM(usage_count), 0) AS total_calls,
                    COUNT(*) FILTER (WHERE status = 'active') AS active_keys
                FROM forge_api_keys
                WHERE developer_id = :developer_id
            """),
            {"developer_id": developer_id},
        )
        agg = result.mappings().one()
        total_calls = int(agg["total_calls"])

        # 逐 key 明细
        breakdown_result = await db.execute(
            text("""
                SELECT key_id, key_name, api_key_prefix, usage_count,
                       status, last_used_at
                FROM forge_api_keys
                WHERE developer_id = :developer_id AND status = 'active'
                ORDER BY usage_count DESC
            """),
            {"developer_id": developer_id},
        )
        key_breakdown = [dict(r) for r in breakdown_result.mappings().all()]

        usage_rate = round(total_calls / quota, 4) if quota > 0 else 0.0

        logger.info(
            "api_usage_queried",
            developer_id=developer_id,
            total_calls=total_calls,
            quota=quota,
            usage_rate=usage_rate,
        )

        return {
            "developer_id": developer_id,
            "dev_type": dev_type,
            "period": period,
            "total_calls": total_calls,
            "quota": quota,
            "usage_rate": usage_rate,
            "active_keys": int(agg["active_keys"]),
            "key_breakdown": key_breakdown,
        }
