"""小红书 POI 门店同步服务

职责：
  1. 绑定屯象门店 ↔ 小红书 POI
  2. 同步门店信息（名称/地址/营业时间/菜品）到小红书
  3. 批量同步所有已绑定门店
  4. 查询同步状态

所有操作带 tenant_id RLS 隔离。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from .xhs_client import XHSClient

logger = structlog.get_logger(__name__)


class XHSPOISyncService:
    """小红书 POI 门店同步"""

    def __init__(self, app_id: str, app_secret: str) -> None:
        self.client = XHSClient(app_id=app_id, app_secret=app_secret)

    async def bind_store(
        self,
        store_id: str,
        xhs_poi_id: str,
        tenant_id: str,
        db: AsyncSession,
    ) -> dict[str, Any]:
        """绑定屯象门店与小红书 POI"""
        tid = uuid.UUID(tenant_id)
        sid = uuid.UUID(store_id)
        await db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": tenant_id},
        )

        existing = await db.execute(
            text("""
                SELECT id FROM xhs_poi_mappings
                WHERE tenant_id = :tid AND store_id = :sid AND is_deleted = false
            """),
            {"tid": tid, "sid": sid},
        )
        if existing.fetchone():
            await db.execute(
                text("""
                    UPDATE xhs_poi_mappings
                    SET xhs_poi_id = :poi, synced_at = NOW(), updated_at = NOW()
                    WHERE tenant_id = :tid AND store_id = :sid AND is_deleted = false
                """),
                {"poi": xhs_poi_id, "tid": tid, "sid": sid},
            )
            await db.flush()
            logger.info("xhs.poi_updated", store_id=store_id, xhs_poi_id=xhs_poi_id)
            return {"action": "updated", "store_id": store_id, "xhs_poi_id": xhs_poi_id}

        mapping_id = uuid.uuid4()
        now = datetime.now(timezone.utc)
        await db.execute(
            text("""
                INSERT INTO xhs_poi_mappings
                    (id, tenant_id, store_id, xhs_poi_id, xhs_poi_name,
                     sync_status, synced_at, created_at, updated_at)
                VALUES
                    (:id, :tid, :sid, :poi, '', 'bound', :now, :now, :now)
            """),
            {"id": mapping_id, "tid": tid, "sid": sid, "poi": xhs_poi_id, "now": now},
        )
        await db.flush()

        logger.info("xhs.poi_bound", store_id=store_id, xhs_poi_id=xhs_poi_id)
        return {"action": "created", "mapping_id": str(mapping_id), "store_id": store_id, "xhs_poi_id": xhs_poi_id}

    async def sync_store_info(
        self,
        store_id: str,
        store_info: dict[str, Any],
        tenant_id: str,
        db: AsyncSession,
    ) -> dict[str, Any]:
        """同步门店信息到小红书

        Args:
            store_info: 包含 name, address, phone, business_hours, dishes 等字段
        """
        tid = uuid.UUID(tenant_id)
        await db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": tenant_id},
        )

        poi_row = await db.execute(
            text("""
                SELECT xhs_poi_id FROM xhs_poi_mappings
                WHERE tenant_id = :tid AND store_id = :sid AND is_deleted = false
            """),
            {"tid": tid, "sid": uuid.UUID(store_id)},
        )
        poi = poi_row.fetchone()
        if not poi:
            return {"synced": False, "error": "store_not_bound"}

        result = await self.client.sync_poi(poi.xhs_poi_id, store_info)

        await db.execute(
            text("""
                UPDATE xhs_poi_mappings
                SET sync_status = 'synced', synced_at = NOW(),
                    xhs_poi_name = COALESCE(:name, xhs_poi_name), updated_at = NOW()
                WHERE tenant_id = :tid AND store_id = :sid AND is_deleted = false
            """),
            {"name": store_info.get("name"), "tid": tid, "sid": uuid.UUID(store_id)},
        )
        await db.flush()

        logger.info("xhs.poi_synced", store_id=store_id)
        return {"synced": True, "store_id": store_id, "api_response": result}

    async def list_bindings(
        self,
        tenant_id: str,
        db: AsyncSession,
        page: int = 1,
        size: int = 50,
    ) -> dict[str, Any]:
        """查询所有 POI 绑定关系"""
        tid = uuid.UUID(tenant_id)
        await db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": tenant_id},
        )
        offset = (page - 1) * size

        rows = await db.execute(
            text("""
                SELECT id, store_id, xhs_poi_id, xhs_poi_name,
                       sync_status, synced_at, created_at
                FROM xhs_poi_mappings
                WHERE tenant_id = :tid AND is_deleted = false
                ORDER BY created_at DESC
                LIMIT :lim OFFSET :off
            """),
            {"tid": tid, "lim": size, "off": offset},
        )

        items = [
            {
                "mapping_id": str(r.id),
                "store_id": str(r.store_id),
                "xhs_poi_id": r.xhs_poi_id,
                "xhs_poi_name": r.xhs_poi_name,
                "sync_status": r.sync_status,
                "synced_at": r.synced_at.isoformat() if r.synced_at else None,
            }
            for r in rows
        ]

        count_row = await db.execute(
            text("""
                SELECT count(*) as total FROM xhs_poi_mappings
                WHERE tenant_id = :tid AND is_deleted = false
            """),
            {"tid": tid},
        )
        total = count_row.scalar() or 0

        return {"items": items, "total": total, "page": page, "size": size}

    async def batch_sync(
        self,
        tenant_id: str,
        db: AsyncSession,
    ) -> dict[str, Any]:
        """批量同步所有已绑定门店的信息"""
        bindings = await self.list_bindings(tenant_id, db, page=1, size=500)
        synced = 0
        failed = 0

        for binding in bindings["items"]:
            if not binding["xhs_poi_id"]:
                continue
            result = await self.client.sync_poi(binding["xhs_poi_id"], {})
            if result.get("code") == 0:
                synced += 1
            else:
                failed += 1

        logger.info("xhs.batch_sync_done", synced=synced, failed=failed, tenant_id=tenant_id)
        return {"synced": synced, "failed": failed, "total": bindings["total"]}
