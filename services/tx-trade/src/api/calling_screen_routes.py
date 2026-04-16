"""叫号屏 API — 快餐顾客展示屏 + 收银台叫号操作

端点清单：
  GET       /api/v1/calling-screen/{store_id}/current  — 当前正在叫的号
  GET       /api/v1/calling-screen/{store_id}/recent   — 最近叫过的 N 个号
  WebSocket /ws/calling-screen/{store_id}              — 实时推送叫号事件

WebSocket 消息格式（服务端 → 客户端）：
  {"event": "call_number",  "data": {"call_number": "A023", "quick_order_id": "...", "called_at": "..."}}
  {"event": "complete",     "data": {"call_number": "A023", "quick_order_id": "..."}}
  {"event": "recent_list",  "data": [{"call_number": "A023", ...}, ...]}
  {"event": "ping",         "data": {}}

WebSocket 消息格式（客户端 → 服务端）：
  {"action": "ping"}
  {"action": "subscribe"}   — 订阅门店叫号推送
"""
import asyncio
import json
from datetime import datetime, timezone
from typing import Optional

import structlog
from fastapi import APIRouter, Query, Request, WebSocket, WebSocketDisconnect
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db
from fastapi import Depends

logger = structlog.get_logger(__name__)

router = APIRouter(tags=["calling-screen"])

# ─── 连接管理器（内存级，单实例部署） ───────────────────────────────────────

class CallingScreenManager:
    """管理门店叫号屏的 WebSocket 连接。

    key: store_id → set[WebSocket]
    """

    def __init__(self) -> None:
        self._connections: dict[str, set[WebSocket]] = {}

    async def connect(self, store_id: str, ws: WebSocket) -> None:
        await ws.accept()
        if store_id not in self._connections:
            self._connections[store_id] = set()
        self._connections[store_id].add(ws)
        logger.info("calling_screen_ws_connected", store_id=store_id)

    def disconnect(self, store_id: str, ws: WebSocket) -> None:
        if store_id in self._connections:
            self._connections[store_id].discard(ws)
            if not self._connections[store_id]:
                del self._connections[store_id]
        logger.info("calling_screen_ws_disconnected", store_id=store_id)

    async def broadcast(self, store_id: str, payload: dict) -> None:
        """向该门店所有连接的叫号屏广播消息。"""
        connections = list(self._connections.get(store_id, set()))
        if not connections:
            return

        message = json.dumps(payload, ensure_ascii=False)
        dead: list[WebSocket] = []
        for ws in connections:
            try:
                await ws.send_text(message)
            except Exception as exc:  # noqa: BLE001 — WebSocket断连，标记清理
                logger.debug("calling_screen.ws_send_failed", error=str(exc))
                dead.append(ws)

        for ws in dead:
            self.disconnect(store_id, ws)

    def connection_count(self, store_id: str) -> int:
        return len(self._connections.get(store_id, set()))


_manager = CallingScreenManager()


def get_calling_manager() -> CallingScreenManager:
    """依赖注入入口，供其他模块调用 broadcast。"""
    return _manager


# ─── 工具函数 ────────────────────────────────────────────────────────────────


def _get_tenant_id(request: Request) -> str:
    from fastapi import HTTPException

    tid = getattr(request.state, "tenant_id", None) or request.headers.get("X-Tenant-ID", "")
    if not tid:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header required")
    return tid


def _ok(data: dict | list) -> dict:
    return {"ok": True, "data": data, "error": None}


# ─── REST 端点 ───────────────────────────────────────────────────────────────


@router.get("/api/v1/calling-screen/{store_id}/current")
async def get_current_calling(
    store_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """获取当前正在叫号的快餐订单（status=calling，最新一条）。"""
    tenant_id = _get_tenant_id(request)

    row = await db.execute(
        text(
            """
            SELECT id, call_number, order_type, status, called_at, created_at
            FROM quick_orders
            WHERE tenant_id = :tenant_id
              AND store_id = :store_id
              AND status = 'calling'
            ORDER BY called_at DESC
            LIMIT 1
            """
        ),
        {"tenant_id": tenant_id, "store_id": store_id},
    )
    current = row.mappings().first()

    return _ok(dict(current) if current else None)


@router.get("/api/v1/calling-screen/{store_id}/recent")
async def get_recent_called(
    store_id: str,
    n: int = Query(default=10, ge=1, le=50, description="返回最近 N 条"),
    request: Request = None,  # type: ignore[assignment]
    db: AsyncSession = Depends(get_db),
) -> dict:
    """获取最近叫过的 N 个号（status=calling 或 completed，按叫号时间倒序）。"""
    tenant_id = _get_tenant_id(request)  # type: ignore[arg-type]

    rows = await db.execute(
        text(
            """
            SELECT id, call_number, order_type, status, called_at, completed_at, created_at
            FROM quick_orders
            WHERE tenant_id = :tenant_id
              AND store_id = :store_id
              AND status IN ('calling', 'completed')
              AND called_at IS NOT NULL
            ORDER BY called_at DESC
            LIMIT :n
            """
        ),
        {"tenant_id": tenant_id, "store_id": store_id, "n": n},
    )
    items = [dict(row) for row in rows.mappings()]

    return _ok({"items": items, "total": len(items)})


# ─── WebSocket 端点 ──────────────────────────────────────────────────────────


@router.websocket("/ws/calling-screen/{store_id}")
async def calling_screen_ws(
    store_id: str,
    ws: WebSocket,
    tenant_id: Optional[str] = Query(default=None, alias="tenantId"),
) -> None:
    """实时推送叫号事件到顾客叫号屏。

    连接建立后：
      1. 发送当前叫号中的号（如有）
      2. 发送 ping，保持连接活跃
      3. 监听客户端消息（ping / subscribe）

    叫号操作通过 POST /quick-cashier/{id}/call 触发，
    该接口调用 broadcast() 推送 call_number 事件到所有已连接屏幕。
    """
    await _manager.connect(store_id, ws)

    # 发送欢迎消息：当前叫号数量
    await ws.send_text(json.dumps({
        "event": "connected",
        "data": {
            "store_id": store_id,
            "connections": _manager.connection_count(store_id),
        },
    }, ensure_ascii=False))

    # 保活 ping 任务
    async def _ping_loop() -> None:
        while True:
            try:
                await asyncio.sleep(30)
                await ws.send_text(json.dumps({"event": "ping", "data": {}}))
            except Exception:  # noqa: BLE001 — WebSocket已断开，退出保活循环
                break

    ping_task = asyncio.create_task(_ping_loop())

    try:
        while True:
            raw = await ws.receive_text()
            try:
                msg = json.loads(raw)
                if msg.get("action") == "ping":
                    await ws.send_text(json.dumps({"event": "pong", "data": {}}))
                elif msg.get("action") == "subscribe":
                    # 客户端重新订阅（重连后发送）
                    await ws.send_text(json.dumps({
                        "event": "subscribed",
                        "data": {"store_id": store_id},
                    }))
            except (json.JSONDecodeError, KeyError):
                pass  # 忽略非法消息，不断开连接

    except WebSocketDisconnect:
        pass
    except Exception as exc:  # noqa: BLE001  # outermost WebSocket handler
        logger.warning("calling_screen_ws_error", store_id=store_id, error=str(exc), exc_info=True)
    finally:
        ping_task.cancel()
        _manager.disconnect(store_id, ws)


# ─── 内部广播接口（供 quick_cashier_routes 调用） ────────────────────────────


async def broadcast_call_number(
    store_id: str,
    quick_order_id: str,
    call_number: str,
    called_at: datetime,
) -> None:
    """叫号时广播到所有叫号屏 WebSocket 连接。"""
    await _manager.broadcast(
        store_id,
        {
            "event": "call_number",
            "data": {
                "quick_order_id": quick_order_id,
                "call_number": call_number,
                "called_at": called_at.isoformat(),
            },
        },
    )


async def broadcast_complete(
    store_id: str,
    quick_order_id: str,
    call_number: str,
) -> None:
    """取餐完成时广播到所有叫号屏。"""
    await _manager.broadcast(
        store_id,
        {
            "event": "complete",
            "data": {
                "quick_order_id": quick_order_id,
                "call_number": call_number,
            },
        },
    )
