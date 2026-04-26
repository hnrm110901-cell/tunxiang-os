"""KDS Delta 增量同步 + 设备心跳 API

为 web-kds IndexedDB 本地缓存提供增量同步端点，
避免每次全量拉取。设备心跳用于 KDS 设备管理。

注册方式：
  app.include_router(kds_delta_router)
"""

from datetime import datetime, timezone
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import and_, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from shared.ontology.src.database import get_db
from shared.ontology.src.entities import Order, OrderItem

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/kds", tags=["kds-delta"])


def _get_tenant_id(request: Request) -> str:
    tid = getattr(request.state, "tenant_id", None) or request.headers.get("X-Tenant-ID", "")
    if not tid:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header required")
    return tid


# ─── 请求/响应模型 ───


class HeartbeatReq(BaseModel):
    device_id: str = Field(..., max_length=64, description="KDS设备唯一标识")
    store_id: str = Field(..., description="门店ID")
    device_kind: str = Field(default="kds", max_length=20, description="设备类型: kds/expo/caller")
    station_id: Optional[str] = Field(default=None, max_length=64, description="归属档口ID")
    software_version: Optional[str] = Field(default=None, max_length=20, description="客户端版本号")
    last_sync_at: Optional[str] = Field(default=None, description="上次同步时间戳 ISO 8601")


class DeltaOrderItemOut(BaseModel):
    item_id: str
    dish_name: str
    quantity: int
    status: str
    station_id: Optional[str] = None
    notes: Optional[str] = None
    unit_price_fen: int = 0


class DeltaOrderOut(BaseModel):
    order_id: str
    order_no: str
    table_no: Optional[str] = None
    items: list[DeltaOrderItemOut]
    status: str
    priority: str = "normal"
    order_type: str = "dine_in"
    created_at: str
    updated_at: str


# ─── Delta 增量同步 ───


@router.get("/orders/delta")
async def api_kds_orders_delta(
    request: Request,
    store_id: str = Query(..., description="门店ID"),
    since_at: str = Query(..., description="上次同步时间戳 ISO 8601，如 2026-04-26T10:00:00Z"),
    device_id: Optional[str] = Query(default=None, description="设备ID（用于过滤归属档口）"),
    limit: int = Query(default=100, ge=1, le=500, description="单次拉取上限"),
    db: AsyncSession = Depends(get_db),
):
    """KDS Delta 增量同步 — 返回自 since_at 后有变化的订单

    前端 IndexedDB 缓存定期轮询此接口，仅拉取增量数据。
    返回 has_more=true 时，前端应使用最后一条的 updated_at 继续拉取。

    示例：GET /api/v1/kds/orders/delta?store_id=xxx&since_at=2026-04-26T10:00:00Z&limit=100
    """
    tenant_id = _get_tenant_id(request)

    # 解析 since_at
    try:
        since_dt = datetime.fromisoformat(since_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=f"since_at 格式错误，需 ISO 8601: {exc}",
        ) from exc

    logger.info(
        "kds_delta_sync",
        tenant_id=tenant_id,
        store_id=store_id,
        since_at=since_at,
        device_id=device_id,
        limit=limit,
    )

    # 构造查询：updated_at > since_at 的活跃订单
    import uuid as _uuid

    try:
        store_uuid = _uuid.UUID(store_id)
        tenant_uuid = _uuid.UUID(tenant_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"无效的 UUID: {exc}") from exc

    # 基础条件
    conditions = [
        Order.tenant_id == tenant_uuid,
        Order.store_id == store_uuid,
        Order.updated_at > since_dt,
        Order.order_type.in_(["dine_in", "takeaway"]),
        ~Order.status.in_(["cancelled", "voided"]),
        Order.is_deleted == False,  # noqa: E712
    ]

    stmt = (
        select(Order)
        .options(selectinload(Order.items))
        .where(and_(*conditions))
        .order_by(Order.updated_at.asc())
        .limit(limit + 1)  # 多取一条判断 has_more
    )

    result = await db.execute(stmt)
    orders = list(result.scalars().unique())

    # 判断是否还有更多数据
    has_more = len(orders) > limit
    if has_more:
        orders = orders[:limit]

    # 如果指定了 device_id，后续可用于按 station_id 过滤
    # 当前实现返回所有档口的订单，前端按 station_id 自行过滤
    # TODO: 查询设备绑定的 station_id，在 SQL 层过滤 order_items

    # 序列化
    server_time = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    delta_orders: list[dict] = []

    for order in orders:
        items_out: list[dict] = []
        for item in order.items:
            if item.is_deleted:
                continue
            items_out.append(
                DeltaOrderItemOut(
                    item_id=str(item.id),
                    dish_name=item.item_name,
                    quantity=item.quantity,
                    status=item.kds_station or "pending",  # 复用 kds_station 标记状态
                    station_id=item.kds_station,
                    notes=item.notes,
                    unit_price_fen=item.unit_price_fen,
                ).model_dump()
            )

        delta_orders.append(
            DeltaOrderOut(
                order_id=str(order.id),
                order_no=order.order_no,
                table_no=order.table_number,
                items=items_out,
                status=order.status,
                priority="rush" if order.abnormal_type == "timeout" else "normal",
                order_type=order.order_type,
                created_at=order.created_at.isoformat().replace("+00:00", "Z") if order.created_at else "",
                updated_at=order.updated_at.isoformat().replace("+00:00", "Z") if order.updated_at else "",
            ).model_dump()
        )

    logger.info(
        "kds_delta_sync_result",
        tenant_id=tenant_id,
        store_id=store_id,
        count=len(delta_orders),
        has_more=has_more,
    )

    return {
        "ok": True,
        "data": {
            "orders": delta_orders,
            "server_time": server_time,
            "has_more": has_more,
        },
    }


# ─── 设备心跳 ───


@router.post("/heartbeat")
async def api_kds_heartbeat(
    body: HeartbeatReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """KDS 设备心跳注册 — 用于设备在线状态管理

    KDS 客户端每 30-60 秒调用一次，上报设备状态。
    后端 upsert 到 kds_device_heartbeats 表（如存在），
    否则仅在内存/日志中记录。

    可用于：
    - 监控哪些 KDS 设备在线
    - 检测设备离线告警
    - 统计设备软件版本分布
    """
    tenant_id = _get_tenant_id(request)

    logger.info(
        "kds_heartbeat",
        tenant_id=tenant_id,
        device_id=body.device_id,
        store_id=body.store_id,
        device_kind=body.device_kind,
        station_id=body.station_id,
        software_version=body.software_version,
        last_sync_at=body.last_sync_at,
    )

    now = datetime.now(timezone.utc)

    # 尝试写入 kds_device_heartbeats 表（如果表已存在）
    # 如果表不存在，仅记录日志，不报错（渐进式部署）
    device_registered = False
    try:
        upsert_sql = text("""
            INSERT INTO kds_device_heartbeats (
                id, tenant_id, device_id, store_id, device_kind,
                station_id, software_version, last_sync_at,
                last_heartbeat_at, created_at, updated_at, is_deleted
            ) VALUES (
                gen_random_uuid(), :tenant_id, :device_id, :store_id, :device_kind,
                :station_id, :software_version, :last_sync_at,
                :now, :now, :now, false
            )
            ON CONFLICT (tenant_id, device_id)
            DO UPDATE SET
                store_id = EXCLUDED.store_id,
                device_kind = EXCLUDED.device_kind,
                station_id = EXCLUDED.station_id,
                software_version = EXCLUDED.software_version,
                last_sync_at = EXCLUDED.last_sync_at,
                last_heartbeat_at = EXCLUDED.last_heartbeat_at,
                updated_at = EXCLUDED.updated_at
        """)

        import uuid as _uuid

        await db.execute(
            upsert_sql,
            {
                "tenant_id": _uuid.UUID(tenant_id),
                "device_id": body.device_id,
                "store_id": _uuid.UUID(body.store_id),
                "device_kind": body.device_kind,
                "station_id": body.station_id,
                "software_version": body.software_version,
                "last_sync_at": body.last_sync_at,
                "now": now,
            },
        )
        await db.commit()
        device_registered = True
    except Exception:
        # 表可能不存在（迁移未执行），仅记录日志不阻塞
        await db.rollback()
        logger.warning(
            "kds_heartbeat_table_missing",
            tenant_id=tenant_id,
            device_id=body.device_id,
            msg="kds_device_heartbeats 表不存在或写入失败，心跳仅记录日志",
        )

    return {
        "ok": True,
        "data": {
            "device_id": body.device_id,
            "server_time": now.isoformat().replace("+00:00", "Z"),
            "registered": device_registered,
        },
    }
