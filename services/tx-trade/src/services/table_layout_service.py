"""桌位图形化布局服务 — 布局管理 + 实时状态 + 换台 + WebSocket广播"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

import structlog
from fastapi import WebSocket
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.websockets import WebSocketState

logger = structlog.get_logger()


# ─── Pydantic 模型 ───


class TableNode(BaseModel):
    """layout_json 中的单个桌子节点"""

    id: str
    table_db_id: Optional[UUID] = None
    x: float
    y: float
    width: float
    height: float
    shape: str  # rect / circle / oval
    seats: int
    label: str
    rotation: float = 0.0


class LayoutJson(BaseModel):
    tables: list[TableNode]
    walls: list[dict]   # [{x1, y1, x2, y2}]
    areas: list[dict]   # [{x, y, width, height, label, color}]


class TableLayout(BaseModel):
    id: UUID
    store_id: UUID
    floor_no: int
    floor_name: str
    canvas_width: int
    canvas_height: int
    layout_json: LayoutJson
    version: int
    published_at: Optional[datetime]


class TableLayoutSummary(BaseModel):
    floor_no: int
    floor_name: str
    table_count: int
    version: int


class TableStatus(BaseModel):
    table_db_id: UUID
    table_number: str
    status: str  # available / occupied / reserved / cleaning / disabled
    order_id: Optional[UUID] = None
    order_no: Optional[str] = None
    seated_at: Optional[datetime] = None
    seated_duration_min: Optional[int] = None
    guest_count: Optional[int] = None
    current_amount_fen: Optional[int] = None


class TransferResult(BaseModel):
    order_id: UUID
    from_table_id: UUID
    to_table_id: UUID
    success: bool


# ─── 全局 WebSocket 连接池 ───

layout_connections: dict[str, set[WebSocket]] = {}  # store_id → WebSocket 集合


# ─── 服务类 ───


class TableLayoutService:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    # ── 1. 获取楼层布局 ──

    async def get_layout(
        self,
        store_id: UUID,
        tenant_id: UUID,
        floor_no: int = 1,
    ) -> Optional[TableLayout]:
        """获取指定楼层布局"""
        row = await self._db.execute(
            text("""
                SELECT id, store_id, floor_no, floor_name,
                       canvas_width, canvas_height, layout_json,
                       version, published_at
                FROM table_layouts
                WHERE store_id = :store_id
                  AND tenant_id = :tenant_id
                  AND floor_no  = :floor_no
                LIMIT 1
            """),
            {"store_id": str(store_id), "tenant_id": str(tenant_id), "floor_no": floor_no},
        )
        record = row.mappings().first()
        if record is None:
            return None
        return self._row_to_layout(record)

    # ── 2. 创建或更新布局 ──

    async def upsert_layout(
        self,
        store_id: UUID,
        tenant_id: UUID,
        floor_no: int,
        floor_name: str,
        layout_json: dict,
        published_by: UUID,
    ) -> TableLayout:
        """创建或更新布局（自动递增版本号）"""
        now = datetime.now(timezone.utc)
        row = await self._db.execute(
            text("""
                INSERT INTO table_layouts
                    (tenant_id, store_id, floor_no, floor_name,
                     layout_json, version, published_at, published_by,
                     created_at, updated_at)
                VALUES
                    (:tenant_id, :store_id, :floor_no, :floor_name,
                     :layout_json::jsonb, 1, :now, :published_by,
                     :now, :now)
                ON CONFLICT (tenant_id, store_id, floor_no)
                DO UPDATE SET
                    floor_name   = EXCLUDED.floor_name,
                    layout_json  = EXCLUDED.layout_json,
                    version      = table_layouts.version + 1,
                    published_at = EXCLUDED.published_at,
                    published_by = EXCLUDED.published_by,
                    updated_at   = EXCLUDED.updated_at
                RETURNING id, store_id, floor_no, floor_name,
                          canvas_width, canvas_height, layout_json,
                          version, published_at
            """),
            {
                "tenant_id": str(tenant_id),
                "store_id": str(store_id),
                "floor_no": floor_no,
                "floor_name": floor_name,
                "layout_json": __import__("json").dumps(layout_json),
                "now": now,
                "published_by": str(published_by),
            },
        )
        await self._db.commit()
        record = row.mappings().first()
        return self._row_to_layout(record)

    # ── 3. 获取所有楼层列表 ──

    async def get_all_floors(
        self,
        store_id: UUID,
        tenant_id: UUID,
    ) -> list[TableLayoutSummary]:
        """获取门店所有楼层列表（不含完整 layout_json）"""
        rows = await self._db.execute(
            text("""
                SELECT floor_no,
                       COALESCE(floor_name, '') AS floor_name,
                       jsonb_array_length(layout_json->'tables') AS table_count,
                       version
                FROM table_layouts
                WHERE store_id  = :store_id
                  AND tenant_id = :tenant_id
                ORDER BY floor_no
            """),
            {"store_id": str(store_id), "tenant_id": str(tenant_id)},
        )
        return [
            TableLayoutSummary(
                floor_no=r["floor_no"],
                floor_name=r["floor_name"] or "",
                table_count=r["table_count"] or 0,
                version=r["version"],
            )
            for r in rows.mappings()
        ]

    # ── 4. 获取所有桌台实时状态 ──

    async def get_realtime_status(
        self,
        store_id: UUID,
        tenant_id: UUID,
    ) -> list[TableStatus]:
        """获取所有桌台实时状态（用于图形化着色）"""
        rows = await self._db.execute(
            text("""
                SELECT
                    t.id            AS table_db_id,
                    t.table_number,
                    t.status,
                    o.id            AS order_id,
                    o.order_no,
                    o.created_at    AS seated_at,
                    o.guest_count,
                    o.total_amount_fen AS current_amount_fen,
                    EXTRACT(EPOCH FROM (NOW() - o.created_at)) / 60 AS seated_duration_min
                FROM tables t
                LEFT JOIN orders o
                    ON o.table_number = t.table_number
                    AND o.store_id    = t.store_id
                    AND o.tenant_id   = t.tenant_id
                    AND o.status IN ('pending', 'confirmed', 'preparing', 'ready')
                WHERE t.store_id  = :store_id
                  AND t.tenant_id = :tenant_id
                ORDER BY t.table_number
            """),
            {"store_id": str(store_id), "tenant_id": str(tenant_id)},
        )
        result: list[TableStatus] = []
        for r in rows.mappings():
            duration = r["seated_duration_min"]
            result.append(
                TableStatus(
                    table_db_id=UUID(str(r["table_db_id"])),
                    table_number=r["table_number"],
                    status=r["status"] or "available",
                    order_id=UUID(str(r["order_id"])) if r["order_id"] else None,
                    order_no=r["order_no"],
                    seated_at=r["seated_at"],
                    seated_duration_min=int(duration) if duration is not None else None,
                    guest_count=r["guest_count"],
                    current_amount_fen=r["current_amount_fen"],
                )
            )
        return result

    # ── 5. 换台 ──

    async def transfer_table(
        self,
        from_table_id: UUID,
        to_table_id: UUID,
        order_id: UUID,
        tenant_id: UUID,
        operator_id: UUID,
    ) -> TransferResult:
        """换台：将订单从一张桌转移到另一张桌"""
        # 查询目标桌台状态
        to_row = await self._db.execute(
            text("""
                SELECT id, table_number, status
                FROM tables
                WHERE id = :table_id AND tenant_id = :tenant_id
            """),
            {"table_id": str(to_table_id), "tenant_id": str(tenant_id)},
        )
        to_table = to_row.mappings().first()
        if to_table is None:
            raise ValueError(f"目标桌台 {to_table_id} 不存在")
        if to_table["status"] != "available":
            raise ValueError(f"目标桌台 {to_table['table_number']} 状态非空闲，无法换台")

        # 查询来源桌台
        from_row = await self._db.execute(
            text("""
                SELECT id, table_number, store_id
                FROM tables
                WHERE id = :table_id AND tenant_id = :tenant_id
            """),
            {"table_id": str(from_table_id), "tenant_id": str(tenant_id)},
        )
        from_table = from_row.mappings().first()
        if from_table is None:
            raise ValueError(f"来源桌台 {from_table_id} 不存在")

        store_id_str = str(from_table["store_id"])

        # 更新订单桌号
        await self._db.execute(
            text("""
                UPDATE orders
                SET table_number = :to_table_number,
                    updated_at   = NOW()
                WHERE id        = :order_id
                  AND tenant_id = :tenant_id
            """),
            {
                "to_table_number": to_table["table_number"],
                "order_id": str(order_id),
                "tenant_id": str(tenant_id),
            },
        )

        # 更新目标桌台状态为 occupied
        await self._db.execute(
            text("""
                UPDATE tables
                SET status     = 'occupied',
                    updated_at = NOW()
                WHERE id        = :table_id
                  AND tenant_id = :tenant_id
            """),
            {"table_id": str(to_table_id), "tenant_id": str(tenant_id)},
        )

        # 释放来源桌台
        await self._db.execute(
            text("""
                UPDATE tables
                SET status     = 'available',
                    updated_at = NOW()
                WHERE id        = :table_id
                  AND tenant_id = :tenant_id
            """),
            {"table_id": str(from_table_id), "tenant_id": str(tenant_id)},
        )

        await self._db.commit()

        # 广播两张桌台的状态变更
        await self.broadcast_table_update(
            store_id=store_id_str,
            table_id=from_table_id,
            new_status="available",
        )
        await self.broadcast_table_update(
            store_id=store_id_str,
            table_id=to_table_id,
            new_status="occupied",
            order_info={"order_id": str(order_id)},
        )

        logger.info(
            "table_transfer_done",
            from_table=str(from_table_id),
            to_table=str(to_table_id),
            order_id=str(order_id),
            operator=str(operator_id),
        )

        return TransferResult(
            order_id=order_id,
            from_table_id=from_table_id,
            to_table_id=to_table_id,
            success=True,
        )

    # ── 6. 广播桌台状态变更 ──

    async def broadcast_table_update(
        self,
        store_id: str,
        table_id: UUID,
        new_status: str,
        order_info: Optional[dict] = None,
    ) -> None:
        """广播桌台状态变更到所有订阅的 POS 终端"""
        conns = layout_connections.get(store_id, set())
        if not conns:
            return

        message = {
            "type": "table_status_update",
            "table_id": str(table_id),
            "new_status": new_status,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        if order_info:
            message.update(order_info)

        dead: list[WebSocket] = []

        async def _send(ws: WebSocket) -> None:
            try:
                if ws.client_state != WebSocketState.CONNECTED:
                    dead.append(ws)
                    return
                await ws.send_json(message)
            except (RuntimeError, OSError, ConnectionError) as exc:
                logger.warning("table_ws_send_failed", error=str(exc))
                dead.append(ws)

        await asyncio.gather(*[_send(ws) for ws in list(conns)], return_exceptions=True)

        for ws in dead:
            conns.discard(ws)

        logger.info(
            "table_status_broadcast",
            store_id=store_id,
            table_id=str(table_id),
            new_status=new_status,
            sent=len(conns) - len(dead),
        )

    # ── 内部辅助 ──

    @staticmethod
    def _row_to_layout(record: dict) -> TableLayout:
        raw_json = record["layout_json"]
        if isinstance(raw_json, str):
            import json
            raw_json = json.loads(raw_json)
        return TableLayout(
            id=UUID(str(record["id"])),
            store_id=UUID(str(record["store_id"])),
            floor_no=record["floor_no"],
            floor_name=record["floor_name"] or "",
            canvas_width=record["canvas_width"],
            canvas_height=record["canvas_height"],
            layout_json=LayoutJson(**raw_json),
            version=record["version"],
            published_at=record["published_at"],
        )
