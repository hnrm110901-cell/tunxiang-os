"""开发者管理服务 — PostgreSQL 异步实现"""

from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

import structlog

from ..constants import DEV_TYPES

log = structlog.get_logger(__name__)


class ForgeDeveloperService:
    """开发者注册、查询、更新"""

    _ALLOWED_UPDATE_FIELDS = {"name", "email", "company", "description"}

    # ── 注册 ─────────────────────────────────────────────────
    async def register_developer(
        self,
        db: AsyncSession,
        *,
        name: str,
        email: str,
        company: str,
        dev_type: str,
        description: str = "",
    ) -> dict:
        if dev_type not in DEV_TYPES:
            raise HTTPException(
                status_code=422,
                detail=f"无效的开发者类型: {dev_type}，可选: {sorted(DEV_TYPES)}",
            )

        developer_id = f"dev_{uuid4().hex[:12]}"

        result = await db.execute(
            text("""
                INSERT INTO forge_developers
                    (id, tenant_id, developer_id, name, email, company, dev_type, description, status)
                VALUES
                    (gen_random_uuid(), current_setting('app.tenant_id')::uuid,
                     :developer_id, :name, :email, :company, :dev_type, :description, 'active')
                RETURNING developer_id, name, email, company, dev_type, status, created_at
            """),
            {
                "developer_id": developer_id,
                "name": name,
                "email": email,
                "company": company,
                "dev_type": dev_type,
                "description": description,
            },
        )
        row = result.mappings().one()
        log.info("developer_registered", developer_id=developer_id, dev_type=dev_type)
        return dict(row)

    # ── 详情 ─────────────────────────────────────────────────
    async def get_developer_profile(self, db: AsyncSession, developer_id: str) -> dict:
        result = await db.execute(
            text("""
                SELECT
                    d.developer_id, d.name, d.email, d.company, d.dev_type,
                    d.description, d.status, d.avatar_url, d.website,
                    d.created_at, d.updated_at,
                    COALESCE(stats.app_count, 0)       AS app_count,
                    COALESCE(stats.total_installs, 0)   AS total_installs
                FROM forge_developers d
                LEFT JOIN LATERAL (
                    SELECT
                        COUNT(*)                    AS app_count,
                        COALESCE(SUM(install_count), 0) AS total_installs
                    FROM forge_apps
                    WHERE developer_id = d.developer_id
                      AND is_deleted = false
                ) stats ON true
                WHERE d.developer_id = :did
                  AND d.is_deleted = false
            """),
            {"did": developer_id},
        )
        row = result.mappings().first()
        if not row:
            raise HTTPException(status_code=404, detail=f"开发者不存在: {developer_id}")
        return dict(row)

    # ── 更新 ─────────────────────────────────────────────────
    async def update_developer(
        self, db: AsyncSession, developer_id: str, updates: dict
    ) -> dict:
        filtered = {k: v for k, v in updates.items() if k in self._ALLOWED_UPDATE_FIELDS}
        if not filtered:
            raise HTTPException(
                status_code=422,
                detail=f"无有效更新字段，允许: {sorted(self._ALLOWED_UPDATE_FIELDS)}",
            )

        set_clauses = ", ".join(f"{k} = :{k}" for k in filtered)
        filtered["did"] = developer_id

        result = await db.execute(
            text(f"""
                UPDATE forge_developers
                SET {set_clauses}, updated_at = NOW()
                WHERE developer_id = :did AND is_deleted = false
                RETURNING developer_id, name, email, company, dev_type,
                          description, status, avatar_url, website,
                          created_at, updated_at
            """),
            filtered,
        )
        row = result.mappings().first()
        if not row:
            raise HTTPException(status_code=404, detail=f"开发者不存在: {developer_id}")

        log.info("developer_updated", developer_id=developer_id, fields=list(filtered.keys()))
        return dict(row)

    # ── 列表 ─────────────────────────────────────────────────
    async def list_developers(
        self,
        db: AsyncSession,
        *,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> dict:
        where = "WHERE is_deleted = false"
        params: dict = {"limit": size, "offset": (page - 1) * size}

        if status:
            where += " AND status = :status"
            params["status"] = status

        count_result = await db.execute(
            text(f"SELECT COUNT(*) FROM forge_developers {where}"),
            params,
        )
        total = count_result.scalar_one()

        result = await db.execute(
            text(f"""
                SELECT developer_id, name, email, company, dev_type,
                       status, created_at
                FROM forge_developers
                {where}
                ORDER BY created_at DESC
                LIMIT :limit OFFSET :offset
            """),
            params,
        )
        items = [dict(r) for r in result.mappings().all()]
        return {"items": items, "total": total}
