"""多人协同扫码点餐 + 呼叫服务员 API

HTTP REST 端点 + WebSocket 实时推送

顾客端：
  POST   /api/v1/collab-order/sessions                        — 创建会话
  POST   /api/v1/collab-order/sessions/{token}/join           — 加入会话
  GET    /api/v1/collab-order/sessions/{token}                — 获取会话状态
  POST   /api/v1/collab-order/sessions/{token}/cart           — 加菜
  DELETE /api/v1/collab-order/sessions/{token}/cart/{dish_id} — 移除菜品
  POST   /api/v1/collab-order/sessions/{token}/submit         — 提交厨房
  POST   /api/v1/collab-order/sessions/{token}/call-waiter    — 呼叫服务员

服务员端：
  GET    /api/v1/collab-order/waiter-calls/{store_id}         — 待处理呼叫列表
  POST   /api/v1/collab-order/waiter-calls/{call_id}/ack      — 确认响应

WebSocket：
  WS     /api/v1/collab-order/ws/session/{session_token}      — 顾客端订阅
  WS     /api/v1/collab-order/ws/waiter/{store_id}            — 服务员端订阅
"""
import asyncio
import uuid

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

from ..services.table_session_service import TableSessionService

logger = structlog.get_logger()

router = APIRouter(prefix="/api/v1/collab-order", tags=["collab-order"])

# ─── WebSocket 连接管理 ───

# session_token → 顾客端 WebSocket 连接集合
sessions_connections: dict[str, set[WebSocket]] = {}
# store_id → 服务员端 WebSocket 连接集合
waiter_connections: dict[str, set[WebSocket]] = {}


async def _broadcast_session(session_token: str, payload: dict) -> None:
    """向指定会话的所有顾客端广播消息"""
    connections = sessions_connections.get(session_token, set())
    dead: set[WebSocket] = set()
    for ws in list(connections):
        try:
            await ws.send_json(payload)
        except Exception:  # noqa: BLE001 — MLPS3-P0: WebSocket断开时异常类型不固定，收窄后兜底
            dead.add(ws)
    for ws in dead:
        connections.discard(ws)


async def _broadcast_waiter(store_id: str, payload: dict) -> None:
    """向指定门店的所有服务员端广播消息"""
    connections = waiter_connections.get(store_id, set())
    dead: set[WebSocket] = set()
    for ws in list(connections):
        try:
            await ws.send_json(payload)
        except Exception:  # noqa: BLE001 — MLPS3-P0: WebSocket断开时异常类型不固定，收窄后兜底
            dead.add(ws)
    for ws in dead:
        connections.discard(ws)


# ─── 通用工具 ───


def _get_tenant_id(request: Request) -> str:
    tid = getattr(request.state, "tenant_id", None) or request.headers.get("X-Tenant-ID", "")
    if not tid:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header required")
    return tid


def _ok(data: dict | list) -> dict:
    return {"ok": True, "data": data, "error": None}


def _err(msg: str, code: int = 400) -> None:
    raise HTTPException(
        status_code=code,
        detail={"ok": False, "data": None, "error": {"message": msg}},
    )


def _session_payload(session) -> dict:
    """将 TableSession 转换为可广播的字典"""
    return {
        "id": str(session.id),
        "session_token": session.session_token,
        "table_id": str(session.table_id),
        "order_id": str(session.order_id) if session.order_id else None,
        "status": session.status,
        "participants": [
            {
                "openid": p.openid,
                "nickname": p.nickname,
                "joined_at": p.joined_at.isoformat(),
                "item_count": p.item_count,
            }
            for p in session.participants
        ],
        "cart_items": [
            {
                "dish_id": str(c.dish_id),
                "dish_name": c.dish_name,
                "quantity": c.quantity,
                "price_fen": c.price_fen,
                "subtotal_fen": c.subtotal_fen,
                "added_by_openid": c.added_by_openid,
                "added_at": c.added_at.isoformat(),
            }
            for c in session.cart_items
        ],
        "expires_at": session.expires_at.isoformat(),
        "submitted_at": session.submitted_at.isoformat() if session.submitted_at else None,
    }


# ─── 请求模型 ───


class CreateSessionReq(BaseModel):
    store_id: uuid.UUID
    table_id: uuid.UUID
    openid: str


class JoinSessionReq(BaseModel):
    openid: str
    nickname: str = ""


class AddCartItemReq(BaseModel):
    dish_id: uuid.UUID
    dish_name: str
    quantity: int
    price_fen: int
    openid: str


class CallWaiterReq(BaseModel):
    call_type: str = "general"
    note: str = ""


class AckCallReq(BaseModel):
    waiter_id: uuid.UUID


# ─── 1. 创建会话 ───


@router.post("/sessions")
async def create_session(
    req: CreateSessionReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """第一个顾客扫码 → 创建协同会话"""
    tenant_id = _get_tenant_id(request)
    svc = TableSessionService(db, uuid.UUID(tenant_id))

    try:
        session = await svc.create_session(
            store_id=req.store_id,
            table_id=req.table_id,
            openid=req.openid,
        )
    except ValueError as e:
        _err(str(e))
        return

    await db.commit()
    return _ok(_session_payload(session))


# ─── 2. 加入会话 ───


@router.post("/sessions/{token}/join")
async def join_session(
    token: str,
    req: JoinSessionReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """第2-N个顾客扫码 → 加入已有会话"""
    tenant_id = _get_tenant_id(request)
    svc = TableSessionService(db, uuid.UUID(tenant_id))

    try:
        session = await svc.join_session(
            session_token=token,
            openid=req.openid,
            nickname=req.nickname,
        )
    except ValueError as e:
        _err(str(e))
        return

    await db.commit()

    # 广播参与者变更
    asyncio.create_task(
        _broadcast_session(
            token,
            {"type": "participant_joined", **_session_payload(session)},
        )
    )

    return _ok(_session_payload(session))


# ─── 3. 获取会话状态 ───


@router.get("/sessions/{token}")
async def get_session(
    token: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    tenant_id = _get_tenant_id(request)
    svc = TableSessionService(db, uuid.UUID(tenant_id))

    session = await svc.get_session(token)
    if session is None:
        _err("会话不存在", 404)
        return

    return _ok(_session_payload(session))


# ─── 4. 加菜 ───


@router.post("/sessions/{token}/cart")
async def add_cart_item(
    token: str,
    req: AddCartItemReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """向共享购物车加菜"""
    tenant_id = _get_tenant_id(request)
    svc = TableSessionService(db, uuid.UUID(tenant_id))

    try:
        session = await svc.add_cart_item(
            session_token=token,
            openid=req.openid,
            dish_id=req.dish_id,
            dish_name=req.dish_name,
            quantity=req.quantity,
            price_fen=req.price_fen,
        )
    except ValueError as e:
        _err(str(e))
        return

    await db.commit()

    # 广播购物车变更
    asyncio.create_task(
        _broadcast_session(
            token,
            {"type": "cart_update", **_session_payload(session)},
        )
    )

    return _ok(_session_payload(session))


# ─── 5. 移除菜品 ───


@router.delete("/sessions/{token}/cart/{dish_id}")
async def remove_cart_item(
    token: str,
    dish_id: uuid.UUID,
    request: Request,
    openid: str = Query(...),
    db: AsyncSession = Depends(get_db),
):
    """从购物车移除菜品（仅限自己加的）"""
    tenant_id = _get_tenant_id(request)
    svc = TableSessionService(db, uuid.UUID(tenant_id))

    try:
        session = await svc.remove_cart_item(
            session_token=token,
            openid=openid,
            dish_id=dish_id,
        )
    except ValueError as e:
        _err(str(e))
        return

    await db.commit()

    # 广播购物车变更
    asyncio.create_task(
        _broadcast_session(
            token,
            {"type": "cart_update", **_session_payload(session)},
        )
    )

    return _ok(_session_payload(session))


# ─── 6. 提交厨房 ───


@router.post("/sessions/{token}/submit")
async def submit_session(
    token: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """提交购物车到厨房（任何人都能提交）"""
    tenant_id = _get_tenant_id(request)
    svc = TableSessionService(db, uuid.UUID(tenant_id))

    try:
        result = await svc.submit_session(session_token=token)
    except ValueError as e:
        _err(str(e))
        return

    await db.commit()

    # 广播提交完成
    asyncio.create_task(
        _broadcast_session(
            token,
            {
                "type": "session_submitted",
                "session_id": str(result.session_id),
                "order_id": str(result.order_id),
                "total_items": result.total_items,
                "total_fen": result.total_fen,
                "kds_sent": result.kds_sent,
            },
        )
    )

    return _ok(
        {
            "session_id": str(result.session_id),
            "order_id": str(result.order_id),
            "total_items": result.total_items,
            "total_fen": result.total_fen,
            "kds_sent": result.kds_sent,
        }
    )


# ─── 7. 呼叫服务员 ───


@router.post("/sessions/{token}/call-waiter")
async def call_waiter(
    token: str,
    req: CallWaiterReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """顾客呼叫服务员"""
    tenant_id = _get_tenant_id(request)
    svc = TableSessionService(db, uuid.UUID(tenant_id))

    # 先获取会话以获取 store_id 和 table_id
    session = await svc.get_session(token)
    if session is None:
        _err("会话不存在", 404)
        return

    try:
        call = await svc.call_waiter(
            session_token=token,
            store_id=uuid.UUID(str(session.table_id)),   # 实际使用 session 关联的 store_id
            table_id=session.table_id,
            call_type=req.call_type,
            note=req.note,
        )
    except ValueError as e:
        _err(str(e))
        return

    # 需要从数据库重新获取含 store_id 的会话行；直接从 session_payload 获取
    # 广播给服务员端
    session_row = await svc._fetch_session_row(token)
    store_id_str = str(session_row["store_id"])

    await db.commit()

    asyncio.create_task(
        _broadcast_waiter(
            store_id_str,
            {
                "type": "waiter_call",
                "call_id": str(call.id),
                "table_id": str(call.table_id),
                "call_type": call.call_type,
                "note": call.note,
                "created_at": call.created_at.isoformat(),
            },
        )
    )

    return _ok(
        {
            "call_id": str(call.id),
            "table_id": str(call.table_id),
            "call_type": call.call_type,
            "note": call.note,
            "status": call.status,
        }
    )


# ─── 8. 待处理呼叫列表（服务员端） ───


@router.get("/waiter-calls/{store_id}")
async def get_pending_calls(
    store_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """获取门店待处理呼叫列表"""
    tenant_id = _get_tenant_id(request)
    svc = TableSessionService(db, uuid.UUID(tenant_id))

    calls = await svc.get_pending_calls(store_id=store_id)

    return _ok(
        [
            {
                "call_id": str(c.id),
                "table_id": str(c.table_id),
                "call_type": c.call_type,
                "note": c.note,
                "status": c.status,
                "created_at": c.created_at.isoformat(),
            }
            for c in calls
        ]
    )


# ─── 9. 服务员确认响应 ───


@router.post("/waiter-calls/{call_id}/ack")
async def acknowledge_call(
    call_id: uuid.UUID,
    req: AckCallReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """服务员确认响应呼叫"""
    tenant_id = _get_tenant_id(request)
    svc = TableSessionService(db, uuid.UUID(tenant_id))

    try:
        call = await svc.acknowledge_call(call_id=call_id, waiter_id=req.waiter_id)
    except ValueError as e:
        _err(str(e))
        return

    await db.commit()

    return _ok(
        {
            "call_id": str(call.id),
            "status": call.status,
            "acknowledged_by": str(call.acknowledged_by) if call.acknowledged_by else None,
            "acknowledged_at": call.acknowledged_at.isoformat() if call.acknowledged_at else None,
        }
    )


# ─── WebSocket: 顾客端订阅 ───


@router.websocket("/ws/session/{session_token}")
async def ws_session(
    websocket: WebSocket,
    session_token: str,
):
    """顾客端 WebSocket — 订阅购物车实时变更"""
    await websocket.accept()

    if session_token not in sessions_connections:
        sessions_connections[session_token] = set()
    sessions_connections[session_token].add(websocket)

    logger.info(
        "ws_session_connected",
        session_token=session_token,
        total_connections=len(sessions_connections[session_token]),
    )

    try:
        while True:
            # 保持心跳：等待客户端消息（ping/pong 或断开）
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        pass
    finally:
        sessions_connections.get(session_token, set()).discard(websocket)
        logger.info("ws_session_disconnected", session_token=session_token)


# ─── WebSocket: 服务员端订阅 ───


@router.websocket("/ws/waiter/{store_id}")
async def ws_waiter(
    websocket: WebSocket,
    store_id: str,
):
    """服务员端 WebSocket — 订阅呼叫推送"""
    await websocket.accept()

    if store_id not in waiter_connections:
        waiter_connections[store_id] = set()
    waiter_connections[store_id].add(websocket)

    logger.info(
        "ws_waiter_connected",
        store_id=store_id,
        total_connections=len(waiter_connections[store_id]),
    )

    try:
        while True:
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        pass
    finally:
        waiter_connections.get(store_id, set()).discard(websocket)
        logger.info("ws_waiter_disconnected", store_id=store_id)
