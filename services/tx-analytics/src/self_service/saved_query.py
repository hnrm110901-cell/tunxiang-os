"""保存/分享/定时刷新查询

BI-1.2: 业务用户自助保存和分享查询配置。

存储：使用 PostgreSQL 表 saved_queries（如无法建表则回退到内存字典 MVP）。
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4

import structlog
from sqlalchemy import text
from sqlalchemy.exc import OperationalError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from .query_compiler import QueryConfig, QueryFilter, QueryOrder, QueryValue

log = structlog.get_logger(__name__)


class SavedQuery:
    """保存的查询配置"""

    def __init__(
        self,
        id: str,
        tenant_id: str,
        name: str,
        config: QueryConfig,
        description: str = "",
        created_by: str = "",
        created_at: str = "",
        updated_at: str = "",
        is_public: bool = False,
        refresh_interval_min: Optional[int] = None,
        tags: Optional[list[str]] = None,
    ):
        self.id = id
        self.tenant_id = tenant_id
        self.name = name
        self.description = description
        self.config = config
        self.created_by = created_by
        self.created_at = created_at
        self.updated_at = updated_at
        self.is_public = is_public
        self.refresh_interval_min = refresh_interval_min
        self.tags = tags or []

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "tenant_id": self.tenant_id,
            "name": self.name,
            "description": self.description,
            "config": {
                "rows": self.config.rows,
                "columns": self.config.columns,
                "values": [
                    {"field_id": v.field_id, "aggregation": v.aggregation, "alias": v.alias}
                    for v in self.config.values
                ],
                "filters": [
                    {"field_id": f.field_id, "operator": f.operator, "value": f.value, "value2": f.value2}
                    for f in self.config.filters
                ],
                "order_by": [
                    {"field_id": o.field_id, "direction": o.direction}
                    for o in self.config.order_by
                ],
                "limit": self.config.limit,
                "offset": self.config.offset,
            },
            "created_by": self.created_by,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "is_public": self.is_public,
            "refresh_interval_min": self.refresh_interval_min,
            "tags": self.tags,
        }


class SavedQueryService:
    """保存查询的 CRUD 服务。

    存储策略：
    - 优先使用 PostgreSQL saved_queries 表
    - 如表不存在，回退到内存字典（MVP 阶段可接受）
    """

    def __init__(self):
        self._memory_store: dict[str, SavedQuery] = {}
        self._db_available: Optional[bool] = None

    async def _ensure_table(self, db: AsyncSession) -> bool:
        """确保 saved_queries 表存在。"""
        if self._db_available is not None:
            return self._db_available
        try:
            await db.execute(text("""
                CREATE TABLE IF NOT EXISTS saved_queries (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    tenant_id UUID NOT NULL,
                    name VARCHAR(200) NOT NULL,
                    description TEXT DEFAULT '',
                    config JSONB NOT NULL DEFAULT '{}',
                    created_by VARCHAR(100) DEFAULT '',
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    updated_at TIMESTAMPTZ DEFAULT NOW(),
                    is_public BOOLEAN DEFAULT FALSE,
                    refresh_interval_min INTEGER,
                    tags JSONB DEFAULT '[]'
                )
            """))
            await db.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_saved_queries_tenant
                ON saved_queries(tenant_id)
            """))
            await db.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_saved_queries_updated
                ON saved_queries(updated_at DESC)
            """))
            self._db_available = True
            log.info("saved_query.table_ready")
        except (OperationalError, SQLAlchemyError) as exc:
            self._db_available = False
            log.warning("saved_query.db_unavailable", reason=str(exc),
                        fallback="memory_store")
        return self._db_available

    def _config_to_json(self, config: QueryConfig) -> dict:
        """将 QueryConfig 序列化为 JSON。"""
        return {
            "rows": config.rows,
            "columns": config.columns,
            "values": [
                {"field_id": v.field_id, "aggregation": v.aggregation, "alias": v.alias}
                for v in config.values
            ],
            "filters": [
                {"field_id": f.field_id, "operator": f.operator, "value": f.value, "value2": f.value2}
                for f in config.filters
            ],
            "order_by": [
                {"field_id": o.field_id, "direction": o.direction}
                for o in config.order_by
            ],
            "limit": config.limit,
            "offset": config.offset,
        }

    def _json_to_config(self, data: dict) -> QueryConfig:
        """从 JSON 重建 QueryConfig。"""
        return QueryConfig(
            rows=data.get("rows", []),
            columns=data.get("columns", []),
            values=data.get("values", []),
            filters=data.get("filters", []),
            order_by=data.get("order_by", []),
            limit=data.get("limit", 100),
            offset=data.get("offset", 0),
        )

    # ─── CRUD ───────────────────────────────────────────────────

    async def save(self, db: AsyncSession, query: SavedQuery) -> SavedQuery:
        """保存/更新查询。"""
        now = datetime.now(timezone.utc).isoformat()

        if not query.id:
            query.id = str(uuid4())
        if not query.created_at:
            query.created_at = now
        query.updated_at = now

        db_ok = await self._ensure_table(db)

        if db_ok:
            try:
                config_json = json.dumps(self._config_to_json(query.config))
                tags_json = json.dumps(query.tags)
                await db.execute(
                    text("""
                        INSERT INTO saved_queries
                            (id, tenant_id, name, description, config, created_by,
                             created_at, updated_at, is_public, refresh_interval_min, tags)
                        VALUES
                            (:id, :tenant_id, :name, :description, :config::jsonb, :created_by,
                             :created_at, :updated_at, :is_public, :refresh_interval_min, :tags::jsonb)
                        ON CONFLICT (id) DO UPDATE SET
                            name = EXCLUDED.name,
                            description = EXCLUDED.description,
                            config = EXCLUDED.config,
                            is_public = EXCLUDED.is_public,
                            refresh_interval_min = EXCLUDED.refresh_interval_min,
                            tags = EXCLUDED.tags,
                            updated_at = EXCLUDED.updated_at
                    """),
                    {
                        "id": query.id,
                        "tenant_id": query.tenant_id,
                        "name": query.name,
                        "description": query.description,
                        "config": config_json,
                        "created_by": query.created_by,
                        "created_at": query.created_at,
                        "updated_at": query.updated_at,
                        "is_public": query.is_public,
                        "refresh_interval_min": query.refresh_interval_min,
                        "tags": tags_json,
                    },
                )
                await db.commit()
                return query
            except (OperationalError, SQLAlchemyError) as exc:
                await db.rollback()
                log.error("saved_query.save_db_error", exc_info=True)
                # 回退到内存存储
                self._memory_store[query.id] = query
                return query
        else:
            self._memory_store[query.id] = query
            return query

    async def list(self, db: AsyncSession, tenant_id: str) -> list[SavedQuery]:
        """列出保存的查询（含公开共享的）。"""
        db_ok = await self._ensure_table(db)

        if db_ok:
            try:
                result = await db.execute(
                    text("""
                        SELECT id, tenant_id, name, description, config, created_by,
                               created_at, updated_at, is_public, refresh_interval_min, tags
                        FROM saved_queries
                        WHERE tenant_id = :tenant_id
                        ORDER BY updated_at DESC
                        LIMIT 200
                    """),
                    {"tenant_id": tenant_id},
                )
                rows = result.fetchall()
                return [
                    SavedQuery(
                        id=str(r[0]), tenant_id=str(r[1]), name=r[2],
                        description=r[3] or "",
                        config=self._json_to_config(r[4] if isinstance(r[4], dict) else json.loads(r[4])),
                        created_by=r[5] or "",
                        created_at=r[6].isoformat() if r[6] else "",
                        updated_at=r[7].isoformat() if r[7] else "",
                        is_public=r[8] or False,
                        refresh_interval_min=r[9],
                        tags=r[10] if isinstance(r[10], list) else (json.loads(r[10]) if r[10] else []),
                    )
                    for r in rows
                ]
            except (OperationalError, SQLAlchemyError):
                pass  # 回退到内存存储

        return [q for q in self._memory_store.values() if q.tenant_id == tenant_id]

    async def get(self, db: AsyncSession, query_id: str) -> Optional[SavedQuery]:
        """获取单个保存的查询。"""
        db_ok = await self._ensure_table(db)

        if db_ok:
            try:
                result = await db.execute(
                    text("""
                        SELECT id, tenant_id, name, description, config, created_by,
                               created_at, updated_at, is_public, refresh_interval_min, tags
                        FROM saved_queries
                        WHERE id = :id
                    """),
                    {"id": query_id},
                )
                row = result.fetchone()
                if row:
                    return SavedQuery(
                        id=str(row[0]), tenant_id=str(row[1]), name=row[2],
                        description=row[3] or "",
                        config=self._json_to_config(
                            row[4] if isinstance(row[4], dict) else json.loads(row[4])
                        ),
                        created_by=row[5] or "",
                        created_at=row[6].isoformat() if row[6] else "",
                        updated_at=row[7].isoformat() if row[7] else "",
                        is_public=row[8] or False,
                        refresh_interval_min=row[9],
                        tags=row[10] if isinstance(row[10], list)
                        else (json.loads(row[10]) if row[10] else []),
                    )
            except (OperationalError, SQLAlchemyError):
                pass

        return self._memory_store.get(query_id)

    async def delete(self, db: AsyncSession, query_id: str) -> None:
        """删除保存的查询。"""
        db_ok = await self._ensure_table(db)

        if db_ok:
            try:
                await db.execute(
                    text("DELETE FROM saved_queries WHERE id = :id"),
                    {"id": query_id},
                )
                await db.commit()
            except (OperationalError, SQLAlchemyError) as exc:
                await db.rollback()
                log.error("saved_query.delete_db_error", exc_info=True)

        self._memory_store.pop(query_id, None)

    async def share(self, db: AsyncSession, query_id: str, is_public: bool) -> Optional[SavedQuery]:
        """切换查询的公开/私有状态。"""
        saved = await self.get(db, query_id)
        if saved is None:
            return None

        saved.is_public = is_public
        return await self.save(db, saved)
