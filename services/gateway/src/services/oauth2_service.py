"""OAuth2 Service — client_credentials流程

负责ISV应用注册、token颁发/验证/吊销、secret轮换。
所有secret/token只存PBKDF2-SHA256哈希，明文只在生成时返回一次。
"""

import hashlib
import hmac
import os
import secrets
from datetime import datetime, timedelta, timezone
from uuid import UUID

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger()


class OAuth2Service:
    TOKEN_EXPIRE_HOURS = 24
    TOKEN_PREFIX = "txat_"  # tx access token

    # ── 应用管理 ──────────────────────────────────────────────────

    async def create_application(
        self,
        tenant_id: UUID,
        app_name: str,
        scopes: list[str],
        contact_email: str | None,
        db: AsyncSession,
        description: str | None = None,
        rate_limit_per_min: int = 60,
        created_by: UUID | None = None,
    ) -> dict:
        """注册ISV应用，生成app_key + app_secret。

        明文secret只在此刻返回一次，之后无法恢复。
        数据库只存PBKDF2-SHA256哈希。
        """
        app_key = f"txapp_{secrets.token_urlsafe(24)}"
        app_secret = secrets.token_urlsafe(32)
        secret_hash = self._hash_secret(app_secret)

        result = await db.execute(
            text("""
                INSERT INTO api_applications
                    (tenant_id, app_name, app_key, app_secret_hash,
                     description, scopes, rate_limit_per_min,
                     contact_email, created_by)
                VALUES
                    (:tenant_id, :app_name, :app_key, :secret_hash,
                     :description, :scopes::jsonb, :rate_limit_per_min,
                     :contact_email, :created_by)
                RETURNING id
            """),
            {
                "tenant_id": str(tenant_id),
                "app_name": app_name,
                "app_key": app_key,
                "secret_hash": secret_hash,
                "description": description,
                "scopes": str(scopes).replace("'", '"'),
                "rate_limit_per_min": rate_limit_per_min,
                "contact_email": contact_email,
                "created_by": str(created_by) if created_by else None,
            },
        )
        row = result.fetchone()
        app_id = str(row[0])
        await db.commit()

        logger.info(
            "api_application_created",
            app_id=app_id,
            app_key=app_key,
            tenant_id=str(tenant_id),
        )

        # ⚠️ 明文secret只返回这一次，之后无法恢复
        return {
            "app_id": app_id,
            "app_key": app_key,
            "app_secret": app_secret,
            "warning": "app_secret只显示一次，请立即保存，丢失后需要重置",
        }

    async def get_application(
        self, app_id: UUID, tenant_id: UUID, db: AsyncSession
    ) -> dict | None:
        """获取应用详情（不含secret哈希）"""
        result = await db.execute(
            text("""
                SELECT id, tenant_id, app_name, app_key, description,
                       status, scopes, rate_limit_per_min, webhook_url,
                       contact_email, created_by, last_active_at, created_at, updated_at
                FROM api_applications
                WHERE id = :app_id
                  AND tenant_id = :tenant_id
                  AND is_deleted = FALSE
            """),
            {"app_id": str(app_id), "tenant_id": str(tenant_id)},
        )
        row = result.mappings().fetchone()
        return dict(row) if row else None

    async def list_applications(
        self,
        tenant_id: UUID,
        db: AsyncSession,
        page: int = 1,
        size: int = 20,
        status: str | None = None,
    ) -> dict:
        """列出租户的所有应用（分页）"""
        offset = (page - 1) * size
        where_extra = "AND status = :status" if status else ""
        params: dict = {"tenant_id": str(tenant_id), "limit": size, "offset": offset}
        if status:
            params["status"] = status

        result = await db.execute(
            text(f"""
                SELECT id, app_name, app_key, status, scopes,
                       rate_limit_per_min, contact_email, last_active_at, created_at
                FROM api_applications
                WHERE tenant_id = :tenant_id
                  AND is_deleted = FALSE
                  {where_extra}
                ORDER BY created_at DESC
                LIMIT :limit OFFSET :offset
            """),
            params,
        )
        items = [dict(r) for r in result.mappings().fetchall()]

        count_result = await db.execute(
            text(f"""
                SELECT COUNT(*) FROM api_applications
                WHERE tenant_id = :tenant_id AND is_deleted = FALSE {where_extra}
            """),
            params,
        )
        total = count_result.scalar_one()
        return {"items": items, "total": total, "page": page, "size": size}

    async def revoke_application(
        self, app_id: UUID, tenant_id: UUID, db: AsyncSession
    ) -> bool:
        """吊销应用，同时吊销所有关联token"""
        result = await db.execute(
            text("""
                UPDATE api_applications
                SET status = 'revoked', updated_at = NOW()
                WHERE id = :app_id
                  AND tenant_id = :tenant_id
                  AND is_deleted = FALSE
                RETURNING id
            """),
            {"app_id": str(app_id), "tenant_id": str(tenant_id)},
        )
        if not result.fetchone():
            return False

        # 吊销所有关联的有效token
        await db.execute(
            text("""
                UPDATE api_access_tokens
                SET revoked_at = NOW()
                WHERE app_id = :app_id
                  AND revoked_at IS NULL
                  AND is_deleted = FALSE
            """),
            {"app_id": str(app_id)},
        )
        await db.commit()
        logger.info("api_application_revoked", app_id=str(app_id), tenant_id=str(tenant_id))
        return True

    # ── Token 生命周期 ─────────────────────────────────────────────

    async def issue_token(
        self,
        app_key: str,
        app_secret: str,
        requested_scopes: list[str],
        db: AsyncSession,
    ) -> dict:
        """OAuth2 client_credentials流程，返回access_token。

        Raises:
            ValueError: app_key不存在
            PermissionError: secret错误或app状态不符
        """
        # 1. 查app_key
        result = await db.execute(
            text("""
                SELECT id, tenant_id, app_secret_hash, status, scopes, rate_limit_per_min
                FROM api_applications
                WHERE app_key = :app_key AND is_deleted = FALSE
            """),
            {"app_key": app_key},
        )
        row = result.mappings().fetchone()
        if not row:
            logger.warning("issue_token_app_not_found", app_key=app_key)
            raise ValueError("app_key不存在")

        # 2. 验证secret
        if not self._verify_secret(app_secret, row["app_secret_hash"]):
            logger.warning("issue_token_invalid_secret", app_key=app_key)
            raise PermissionError("app_secret验证失败")

        # 3. 检查app状态
        if row["status"] != "active":
            logger.warning(
                "issue_token_app_not_active",
                app_key=app_key,
                status=row["status"],
            )
            raise PermissionError(f"应用状态为{row['status']}，无法颁发token")

        # 4. 验证requested_scopes是allowed_scopes的子集
        allowed_scopes: list[str] = row["scopes"] if row["scopes"] else []
        if requested_scopes and not set(requested_scopes).issubset(set(allowed_scopes)):
            unauthorized = set(requested_scopes) - set(allowed_scopes)
            logger.warning(
                "issue_token_scope_exceeded",
                app_key=app_key,
                unauthorized_scopes=list(unauthorized),
            )
            raise PermissionError(f"请求的scope超出应用授权范围: {unauthorized}")

        effective_scopes = requested_scopes if requested_scopes else allowed_scopes

        # 5. 生成token
        raw_token = secrets.token_urlsafe(32)
        token_prefix = self.TOKEN_PREFIX + raw_token[:8]
        token_hash = self._hash_secret(raw_token)
        expires_at = datetime.now(timezone.utc) + timedelta(hours=self.TOKEN_EXPIRE_HOURS)

        # 6. 存token_hash，返回明文token
        token_result = await db.execute(
            text("""
                INSERT INTO api_access_tokens
                    (tenant_id, app_id, token_hash, token_prefix, scopes, expires_at)
                VALUES
                    (:tenant_id, :app_id, :token_hash, :token_prefix,
                     :scopes::jsonb, :expires_at)
                RETURNING id
            """),
            {
                "tenant_id": str(row["tenant_id"]),
                "app_id": str(row["id"]),
                "token_hash": token_hash,
                "token_prefix": token_prefix,
                "scopes": str(effective_scopes).replace("'", '"'),
                "expires_at": expires_at.isoformat(),
            },
        )
        token_id = str(token_result.fetchone()[0])

        # 更新last_active_at
        await db.execute(
            text("""
                UPDATE api_applications
                SET last_active_at = NOW(), updated_at = NOW()
                WHERE id = :app_id
            """),
            {"app_id": str(row["id"])},
        )
        await db.commit()

        logger.info(
            "token_issued",
            token_id=token_id,
            token_prefix=token_prefix,
            app_id=str(row["id"]),
            expires_at=expires_at.isoformat(),
        )

        return {
            "access_token": raw_token,
            "token_type": "Bearer",
            "expires_in": self.TOKEN_EXPIRE_HOURS * 3600,
            "expires_at": expires_at.isoformat(),
            "scopes": effective_scopes,
            "token_prefix": token_prefix,
        }

    async def verify_token(
        self,
        token: str,
        required_scope: str | None,
        db: AsyncSession,
    ) -> dict | None:
        """验证token有效性。

        Returns:
            dict: {app_id, tenant_id, scopes, token_id} 或 None（无效/过期/吊销）
        """
        token_hash = self._hash_secret(token)
        now = datetime.now(timezone.utc)

        result = await db.execute(
            text("""
                SELECT t.id, t.tenant_id, t.app_id, t.scopes,
                       t.expires_at, t.revoked_at
                FROM api_access_tokens t
                WHERE t.token_hash = :token_hash
                  AND t.is_deleted = FALSE
            """),
            {"token_hash": token_hash},
        )
        row = result.mappings().fetchone()

        if not row:
            return None

        # 检查是否过期
        if row["expires_at"] <= now:
            logger.debug("token_expired", token_id=str(row["id"]))
            return None

        # 检查是否已吊销
        if row["revoked_at"] is not None:
            logger.debug("token_revoked", token_id=str(row["id"]))
            return None

        # 检查required_scope
        token_scopes: list[str] = row["scopes"] if row["scopes"] else []
        if required_scope and required_scope not in token_scopes:
            logger.warning(
                "token_insufficient_scope",
                token_id=str(row["id"]),
                required=required_scope,
                granted=token_scopes,
            )
            return None

        # 异步更新last_active_at（非阻塞，不等结果）
        try:
            await db.execute(
                text("""
                    UPDATE api_applications
                    SET last_active_at = NOW()
                    WHERE id = :app_id
                """),
                {"app_id": str(row["app_id"])},
            )
            await db.commit()
        except Exception as exc:  # noqa: BLE001 — 更新失败不阻塞验证结果
            logger.warning("token_verify_update_last_active_failed", error=str(exc))

        return {
            "token_id": str(row["id"]),
            "app_id": str(row["app_id"]),
            "tenant_id": str(row["tenant_id"]),
            "scopes": token_scopes,
        }

    async def revoke_token(self, token: str, db: AsyncSession) -> bool:
        """吊销指定token"""
        token_hash = self._hash_secret(token)

        result = await db.execute(
            text("""
                UPDATE api_access_tokens
                SET revoked_at = NOW()
                WHERE token_hash = :token_hash
                  AND revoked_at IS NULL
                  AND is_deleted = FALSE
                RETURNING id
            """),
            {"token_hash": token_hash},
        )
        row = result.fetchone()
        if not row:
            return False

        await db.commit()
        logger.info("token_revoked", token_id=str(row[0]))
        return True

    async def rotate_secret(
        self, app_id: UUID, tenant_id: UUID, db: AsyncSession
    ) -> dict:
        """重置app_secret，同时吊销该app的所有现存token。

        明文new_secret只返回这一次。
        """
        # 验证应用存在且属于该租户
        result = await db.execute(
            text("""
                SELECT id FROM api_applications
                WHERE id = :app_id
                  AND tenant_id = :tenant_id
                  AND is_deleted = FALSE
                  AND status != 'revoked'
            """),
            {"app_id": str(app_id), "tenant_id": str(tenant_id)},
        )
        if not result.fetchone():
            raise ValueError("应用不存在或已吊销")

        new_secret = secrets.token_urlsafe(32)
        new_secret_hash = self._hash_secret(new_secret)

        # 更新secret哈希
        await db.execute(
            text("""
                UPDATE api_applications
                SET app_secret_hash = :new_hash, updated_at = NOW()
                WHERE id = :app_id
            """),
            {"new_hash": new_secret_hash, "app_id": str(app_id)},
        )

        # 吊销所有现存有效token
        revoke_result = await db.execute(
            text("""
                UPDATE api_access_tokens
                SET revoked_at = NOW()
                WHERE app_id = :app_id
                  AND revoked_at IS NULL
                  AND is_deleted = FALSE
                RETURNING id
            """),
            {"app_id": str(app_id)},
        )
        revoked_count = len(revoke_result.fetchall())

        await db.commit()
        logger.info(
            "app_secret_rotated",
            app_id=str(app_id),
            revoked_token_count=revoked_count,
        )

        return {
            "app_id": str(app_id),
            "new_app_secret": new_secret,
            "revoked_token_count": revoked_count,
            "warning": "new_app_secret只显示一次，请立即保存",
        }

    # ── 私有方法 ──────────────────────────────────────────────────

    def _hash_secret(self, secret: str) -> str:
        """PBKDF2-SHA256，100000轮，返回hex字符串"""
        salt = os.environ.get("API_SECRET_SALT", "tunxiang-api-salt-v1")
        dk = hashlib.pbkdf2_hmac("sha256", secret.encode(), salt.encode(), 100000)
        return dk.hex()

    def _verify_secret(self, secret: str, secret_hash: str) -> bool:
        """恒时比较，防时序攻击"""
        return hmac.compare_digest(self._hash_secret(secret), secret_hash)
