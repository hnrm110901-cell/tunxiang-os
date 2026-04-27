"""应用安装服务 — PostgreSQL 异步实现"""

import json
from uuid import uuid4

import structlog
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

log = structlog.get_logger(__name__)


class ForgeInstallationService:
    """应用安装、卸载、已装列表、安装状态"""

    # ── 安装 ─────────────────────────────────────────────────
    async def install_app(
        self,
        db: AsyncSession,
        *,
        tenant_id: str,
        app_id: str,
        store_ids: list[str] | None = None,
    ) -> dict:
        # ── 验证应用存在且已发布 ──
        app_check = await db.execute(
            text("""
                SELECT app_id, current_version, status
                FROM forge_apps
                WHERE app_id = :aid AND is_deleted = false
            """),
            {"aid": app_id},
        )
        app_row = app_check.mappings().first()
        if not app_row:
            raise HTTPException(status_code=404, detail=f"应用不存在: {app_id}")
        if app_row["status"] != "published":
            raise HTTPException(
                status_code=422,
                detail=f"应用当前状态为 {app_row['status']}，仅已发布应用可安装",
            )

        # ── 检查是否已安装 ──
        dup_check = await db.execute(
            text("""
                SELECT install_id
                FROM forge_installations
                WHERE tenant_id = :tid::uuid
                  AND app_id = :aid
                  AND status = 'active'
                  AND is_deleted = false
            """),
            {"tid": tenant_id, "aid": app_id},
        )
        if dup_check.first():
            raise HTTPException(status_code=409, detail=f"应用已安装: {app_id}")

        install_id = f"inst_{uuid4().hex[:12]}"
        store_ids_json = json.dumps(store_ids or [], ensure_ascii=False)

        # ── 插入安装记录 ──
        result = await db.execute(
            text("""
                INSERT INTO forge_installations
                    (id, tenant_id, install_id, app_id, store_ids,
                     status, installed_version, installed_at)
                VALUES
                    (gen_random_uuid(), :tid::uuid,
                     :install_id, :aid, :store_ids::jsonb,
                     'active', :version, NOW())
                RETURNING install_id, app_id, store_ids, status,
                          installed_version, installed_at
            """),
            {
                "tid": tenant_id,
                "install_id": install_id,
                "aid": app_id,
                "store_ids": store_ids_json,
                "version": app_row["current_version"],
            },
        )
        install_row = dict(result.mappings().one())

        # ── 递增安装计数 ──
        await db.execute(
            text("""
                UPDATE forge_apps
                SET install_count = install_count + 1, updated_at = NOW()
                WHERE app_id = :aid
            """),
            {"aid": app_id},
        )

        log.info("app_installed", install_id=install_id, app_id=app_id, tenant_id=tenant_id)
        return install_row

    # ── 卸载 ─────────────────────────────────────────────────
    async def uninstall_app(
        self,
        db: AsyncSession,
        *,
        tenant_id: str,
        app_id: str,
    ) -> dict:
        result = await db.execute(
            text("""
                UPDATE forge_installations
                SET status = 'uninstalled', uninstalled_at = NOW(), updated_at = NOW()
                WHERE tenant_id = :tid::uuid
                  AND app_id = :aid
                  AND status = 'active'
                  AND is_deleted = false
                RETURNING install_id, app_id, status, uninstalled_at
            """),
            {"tid": tenant_id, "aid": app_id},
        )
        row = result.mappings().first()
        if not row:
            raise HTTPException(
                status_code=404,
                detail=f"未找到活跃安装记录: tenant={tenant_id}, app={app_id}",
            )

        # ── 递减安装计数（最低为 0） ──
        await db.execute(
            text("""
                UPDATE forge_apps
                SET install_count = GREATEST(install_count - 1, 0),
                    updated_at = NOW()
                WHERE app_id = :aid
            """),
            {"aid": app_id},
        )

        log.info("app_uninstalled", app_id=app_id, tenant_id=tenant_id)
        return dict(row)

    # ── 已安装列表 ───────────────────────────────────────────
    async def list_installed_apps(
        self,
        db: AsyncSession,
        tenant_id: str,
        *,
        page: int = 1,
        size: int = 20,
    ) -> dict:
        params: dict = {
            "tid": tenant_id,
            "limit": size,
            "offset": (page - 1) * size,
        }

        count_result = await db.execute(
            text("""
                SELECT COUNT(*)
                FROM forge_installations i
                WHERE i.tenant_id = :tid::uuid
                  AND i.status = 'active'
                  AND i.is_deleted = false
            """),
            params,
        )
        total = count_result.scalar_one()

        result = await db.execute(
            text("""
                SELECT
                    i.install_id, i.app_id, i.store_ids, i.status,
                    i.installed_version, i.installed_at,
                    a.app_name, a.category, a.icon_url, a.price_display,
                    a.description
                FROM forge_installations i
                LEFT JOIN forge_apps a ON a.app_id = i.app_id
                    AND a.is_deleted = false
                WHERE i.tenant_id = :tid::uuid
                  AND i.status = 'active'
                  AND i.is_deleted = false
                ORDER BY i.installed_at DESC
                LIMIT :limit OFFSET :offset
            """),
            params,
        )
        items = [dict(r) for r in result.mappings().all()]
        return {"items": items, "total": total}

    # ── 安装状态 ─────────────────────────────────────────────
    async def get_installation_status(self, db: AsyncSession, tenant_id: str, app_id: str) -> dict:
        result = await db.execute(
            text("""
                SELECT install_id, app_id, store_ids, status,
                       installed_version, installed_at, uninstalled_at
                FROM forge_installations
                WHERE tenant_id = :tid::uuid
                  AND app_id = :aid
                  AND is_deleted = false
                ORDER BY installed_at DESC
                LIMIT 1
            """),
            {"tid": tenant_id, "aid": app_id},
        )
        row = result.mappings().first()
        if not row:
            return {
                "installed": False,
                "status": None,
                "installed_at": None,
                "store_ids": [],
            }
        return {
            "installed": row["status"] == "active",
            "status": row["status"],
            "installed_at": row["installed_at"],
            "store_ids": row["store_ids"] or [],
            "install_id": row["install_id"],
            "installed_version": row["installed_version"],
            "uninstalled_at": row["uninstalled_at"],
        }
