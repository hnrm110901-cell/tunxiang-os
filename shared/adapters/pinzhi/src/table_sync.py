"""
品智桌台同步模块
拉取品智桌台数据并以 UPSERT 模式写入屯象 tables 表
"""
from __future__ import annotations

import uuid
from typing import Any

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger()


class PinzhiTableSync:
    """品智桌台同步器"""

    def __init__(self, adapter: Any) -> None:
        """
        Args:
            adapter: PinzhiAdapter 实例
        """
        self.adapter = adapter

    async def fetch_tables(self, store_id: str) -> list[dict]:
        """
        从品智拉取指定门店的桌台列表。

        Args:
            store_id: 门店 ognid

        Returns:
            品智原始桌台列表
        """
        tables = await self.adapter.get_tables(ognid=store_id)
        logger.info("pinzhi_tables_fetched", store_id=store_id, count=len(tables))
        return tables

    @staticmethod
    def map_to_tunxiang_table(pinzhi_table: dict, tenant_id: str, store_uuid: str) -> dict:
        """
        将品智原始桌台映射为屯象 tables 格式（纯函数）。

        Args:
            pinzhi_table: 品智原始桌台字典
            tenant_id: 屯象租户ID（UUID 字符串）
            store_uuid: 屯象门店ID（UUID 字符串）

        Returns:
            屯象标准桌台字典
        """
        # 品智桌台状态：1=空闲, 2=开桌, 0=不可用
        status_map = {1: "free", 2: "occupied", 0: "inactive"}
        raw_status = pinzhi_table.get("tableStatus", pinzhi_table.get("status", 1))
        status = status_map.get(int(raw_status), "free")

        return {
            "id": str(uuid.uuid5(
                uuid.NAMESPACE_DNS,
                f"pinzhi:{tenant_id}:{pinzhi_table.get('tableId', pinzhi_table.get('id', ''))}",
            )),
            "tenant_id": tenant_id,
            "store_id": store_uuid,
            "table_no": str(pinzhi_table.get("tableName", pinzhi_table.get("tableNo", ""))),
            "area": str(pinzhi_table.get("areaName", pinzhi_table.get("area", "")) or ""),
            "floor": int(pinzhi_table.get("floor", 1) or 1),
            "seats": int(pinzhi_table.get("personNum", pinzhi_table.get("seats", 4)) or 4),
            "min_consume_fen": int(pinzhi_table.get("minConsume", 0) or 0),
            "status": status,
            "sort_order": int(pinzhi_table.get("sortOrder", pinzhi_table.get("tableSort", 0)) or 0),
            "is_active": status != "inactive",
            "config": {
                "source_system": "pinzhi",
                "pinzhi_table_id": str(pinzhi_table.get("tableId", pinzhi_table.get("id", ""))),
                "pinzhi_area_id": str(pinzhi_table.get("areaId", "") or ""),
            },
        }

    async def upsert_tables(
        self,
        db: AsyncSession,
        tenant_id: str,
        store_uuid: str,
        store_id: str,
    ) -> dict:
        """
        完整同步流程：拉取 → 映射 → UPSERT 写入数据库。

        每次 DB 操作前设置 set_config 保证 RLS 生效。

        Args:
            db: 异步数据库会话
            tenant_id: 屯象租户ID（UUID 字符串）
            store_uuid: 屯象门店UUID（与 tables.store_id 外键对应）
            store_id: 品智门店 ognid

        Returns:
            同步统计 {"total": int, "upserted": int, "failed": int}
        """
        raw_tables = await self.fetch_tables(store_id)

        mapped: list[dict] = []
        failed = 0
        for raw in raw_tables:
            try:
                mapped.append(self.map_to_tunxiang_table(raw, tenant_id, store_uuid))
            except (KeyError, ValueError, TypeError) as exc:
                logger.warning(
                    "table_mapping_failed",
                    table_id=raw.get("tableId"),
                    error=str(exc),
                )
                failed += 1

        if not mapped:
            logger.info("table_sync_nothing_to_upsert", store_id=store_id)
            return {"total": len(raw_tables), "upserted": 0, "failed": failed}

        # 设置 RLS 租户上下文
        await db.execute(text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": tenant_id})

        upserted = 0
        for row in mapped:
            try:
                await db.execute(
                    text("""
                        INSERT INTO tables (
                            id, tenant_id, store_id, table_no, area, floor, seats,
                            min_consume_fen, status, sort_order, is_active, config,
                            created_at, updated_at, is_deleted
                        ) VALUES (
                            :id::uuid, :tenant_id::uuid, :store_id::uuid,
                            :table_no, :area, :floor, :seats,
                            :min_consume_fen, :status, :sort_order, :is_active,
                            :config::jsonb,
                            NOW(), NOW(), false
                        )
                        ON CONFLICT (id) DO UPDATE SET
                            table_no       = EXCLUDED.table_no,
                            area           = EXCLUDED.area,
                            floor          = EXCLUDED.floor,
                            seats          = EXCLUDED.seats,
                            min_consume_fen = EXCLUDED.min_consume_fen,
                            status         = EXCLUDED.status,
                            sort_order     = EXCLUDED.sort_order,
                            is_active      = EXCLUDED.is_active,
                            config         = EXCLUDED.config,
                            updated_at     = NOW()
                    """),
                    {**row, "config": __import__("json").dumps(row["config"])},
                )
                upserted += 1
            except Exception as exc:  # noqa: BLE001 — 单行失败不阻断整批
                logger.error(
                    "table_upsert_failed",
                    table_no=row.get("table_no"),
                    error=str(exc),
                    exc_info=True,
                )
                failed += 1

        await db.commit()

        logger.info(
            "pinzhi_tables_synced",
            tenant_id=tenant_id,
            store_id=store_id,
            total=len(raw_tables),
            upserted=upserted,
            failed=failed,
        )
        return {"total": len(raw_tables), "upserted": upserted, "failed": failed}
