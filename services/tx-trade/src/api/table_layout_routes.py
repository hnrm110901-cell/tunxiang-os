"""桌位图形化布局 + 实时状态广播 API

端点清单：
  GET  /api/v1/tables/layout/{store_id}/floors           — 获取所有楼层列表
  GET  /api/v1/tables/layout/{store_id}/floor/{floor_no} — 获取指定楼层布局
  PUT  /api/v1/tables/layout/{store_id}/floor/{floor_no} — 保存布局
  GET  /api/v1/tables/status/{store_id}                  — 获取所有桌台实时状态
  POST /api/v1/tables/{table_id}/transfer                — 换台
  WS   /api/v1/tables/ws/layout/{store_id}               — POS/KDS 订阅桌台状态变更

统一响应格式: {"ok": bool, "data": {}, "error": {}}
所有 HTTP 接口需 X-Tenant-ID header。
"""
from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, WebSocket, WebSocketDisconnect
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db
from ..services.table_layout_service import (
    TableLayoutService,
    layout_connections,
)

import uuid

logger = structlog.get_logger()

router = APIRouter(prefix="/api/v1/tables", tags=["table-layout"])


# ─── 工具函数 ───


def _get_tenant_id(request: Request) -> uuid.UUID:
    tid = getattr(request.state, "tenant_id", None) or request.headers.get("X-Tenant-ID", "")
    if not tid:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header required")
    return uuid.UUID(str(tid))


def _ok(data: dict | list) -> dict:
    return {"ok": True, "data": data, "error": None}


def _err(msg: str, code: int = 400) -> None:
    raise HTTPException(
        status_code=code,
        detail={"ok": False, "data": None, "error": {"message": msg}},
    )


# ─── 请求模型 ───


class UpsertLayoutReq(BaseModel):
    floor_name: str
    layout_json: dict
    published_by: uuid.UUID


class TransferTableReq(BaseModel):
    to_table_id: uuid.UUID
    order_id: uuid.UUID
    operator_id: uuid.UUID


# ─── 布局管理 ───


@router.get("/layout/{store_id}/floors")
async def api_get_floors(
    store_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """获取门店所有楼层列表（不含完整 layout_json）"""
    tenant_id = _get_tenant_id(request)
    svc = TableLayoutService(db)
    floors = await svc.get_all_floors(store_id=store_id, tenant_id=tenant_id)
    return _ok([f.model_dump() for f in floors])


@router.get("/layout/{store_id}/floor/{floor_no}")
async def api_get_floor_layout(
    store_id: uuid.UUID,
    floor_no: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """获取指定楼层布局"""
    tenant_id = _get_tenant_id(request)
    svc = TableLayoutService(db)
    layout = await svc.get_layout(
        store_id=store_id, tenant_id=tenant_id, floor_no=floor_no
    )
    if layout is None:
        _err(f"楼层 {floor_no} 布局不存在", 404)
    return _ok(layout.model_dump())


@router.put("/layout/{store_id}/floor/{floor_no}")
async def api_upsert_floor_layout(
    store_id: uuid.UUID,
    floor_no: int,
    req: UpsertLayoutReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """保存布局（总部后台编辑器用），自动递增版本号"""
    tenant_id = _get_tenant_id(request)
    svc = TableLayoutService(db)
    try:
        layout = await svc.upsert_layout(
            store_id=store_id,
            tenant_id=tenant_id,
            floor_no=floor_no,
            floor_name=req.floor_name,
            layout_json=req.layout_json,
            published_by=req.published_by,
        )
    except ValueError as exc:
        _err(str(exc))
        return
    return _ok(layout.model_dump())


# ─── 实时状态 ───


@router.get("/status/{store_id}")
async def api_get_realtime_status(
    store_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """获取门店所有桌台实时状态（用于图形化着色）"""
    tenant_id = _get_tenant_id(request)
    svc = TableLayoutService(db)
    statuses = await svc.get_realtime_status(store_id=store_id, tenant_id=tenant_id)
    return _ok([s.model_dump() for s in statuses])


@router.post("/{table_id}/transfer")
async def api_transfer_table(
    table_id: uuid.UUID,
    req: TransferTableReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """换台 — 将订单从一张桌转移到另一张桌"""
    tenant_id = _get_tenant_id(request)
    svc = TableLayoutService(db)
    try:
        result = await svc.transfer_table(
            from_table_id=table_id,
            to_table_id=req.to_table_id,
            order_id=req.order_id,
            tenant_id=tenant_id,
            operator_id=req.operator_id,
        )
    except ValueError as exc:
        _err(str(exc))
        return
    return _ok(result.model_dump())


# ─── WebSocket 实时广播 ───


@router.websocket("/ws/layout/{store_id}")
async def ws_layout(store_id: str, websocket: WebSocket):
    """POS/KDS 订阅桌台状态变更

    连接后立即进入监听状态，服务端通过 broadcast_table_update() 推送消息。
    消息格式：
    {
      "type": "table_status_update",
      "table_id": "uuid",
      "table_number": "A01",
      "new_status": "occupied",
      "order_no": "TX20260331001",
      "guest_count": 4,
      "timestamp": "2026-03-31T10:00:00Z"
    }
    """
    await websocket.accept()

    if store_id not in layout_connections:
        layout_connections[store_id] = set()
    layout_connections[store_id].add(websocket)

    logger.info("table_ws_connected", store_id=store_id, total=len(layout_connections[store_id]))

    try:
        while True:
            # 保持连接，接收心跳 ping
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        pass
    finally:
        if store_id in layout_connections:
            layout_connections[store_id].discard(websocket)
            if not layout_connections[store_id]:
                del layout_connections[store_id]
        logger.info("table_ws_disconnected", store_id=store_id)
