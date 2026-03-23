"""Mac Station — 门店本地 FastAPI 服务

职责：只做智能，不碰外设。
1. 本地 PostgreSQL 副本的 API 接口
2. 离线查询（断网时收银/KDS/Agent 不停摆）
3. WebSocket 推送 Agent 决策到安卓 POS
4. 代理 Core ML 桥接请求
"""
import os

import httpx
import structlog
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

logger = structlog.get_logger()

COREML_URL = os.getenv("COREML_BRIDGE_URL", "http://localhost:8100")

app = FastAPI(
    title="TunxiangOS Mac Station",
    version="3.0.0",
    description="门店本地智能后台 — Mac mini M4",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── 健康检查 ───

@app.get("/health")
async def health():
    return {"ok": True, "data": {"service": "mac-station", "version": "3.0.0"}}


# ─── 离线查询 API ───

@app.get("/api/v1/offline/revenue")
async def query_revenue_offline(store_id: str, date: str = "today"):
    """离线查询营业额（从本地 PG 读取）"""
    # TODO: 接入本地 PG
    return {"ok": True, "data": {"store_id": store_id, "date": date, "revenue_fen": 0, "source": "local_cache"}}


@app.get("/api/v1/offline/inventory")
async def query_inventory_offline(store_id: str):
    """离线查询库存（从本地 PG 读取）"""
    return {"ok": True, "data": {"store_id": store_id, "items": [], "source": "local_cache"}}


@app.get("/api/v1/offline/orders")
async def query_orders_offline(store_id: str, status: str = "pending"):
    """离线查询订单"""
    return {"ok": True, "data": {"store_id": store_id, "orders": [], "source": "local_cache"}}


# ─── Core ML 代理 ───

@app.post("/api/v1/predict/{model_name}")
async def predict(model_name: str, data: dict):
    """代理 Core ML 桥接请求到 coreml-bridge (port 8100)"""
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.post(f"{COREML_URL}/predict/{model_name}", json=data)
            return resp.json()
    except httpx.ConnectError:
        logger.warning("coreml_bridge_unavailable", model=model_name)
        return {"ok": False, "data": None, "error": {"code": "COREML_UNAVAILABLE", "message": "Core ML bridge not running"}}


# ─── WebSocket 推送（Agent → 安卓 POS） ───

connected_clients: list[WebSocket] = []


@app.websocket("/ws/agent-push")
async def agent_push_ws(websocket: WebSocket):
    """WebSocket 端点 — Agent 决策实时推送到安卓 POS"""
    await websocket.accept()
    connected_clients.append(websocket)
    logger.info("ws_client_connected", total=len(connected_clients))

    try:
        while True:
            # 保持连接，接收心跳
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        connected_clients.remove(websocket)
        logger.info("ws_client_disconnected", total=len(connected_clients))


# ─── KDS WebSocket 推送 ───

from kds_pusher import KDSPusher
import json

kds_pusher = KDSPusher()


@app.websocket("/ws/kds/{station_id}")
async def kds_ws(websocket: WebSocket, station_id: str):
    """KDS 终端 WebSocket 连接端点"""
    await websocket.accept()
    await kds_pusher.register(station_id, websocket)
    logger.info("kds_ws_connected", station_id=station_id)

    try:
        while True:
            raw = await websocket.receive_text()
            if raw == "ping":
                await websocket.send_text("pong")
                continue

            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue

            msg_type = msg.get("type")

            if msg_type == "new_order":
                # 收到新订单 -> 按出品部门拆分推送到各档口
                await kds_pusher.dispatch_new_order(msg.get("order", {}))

            elif msg_type == "status_change":
                await kds_pusher.push_status_change(
                    msg.get("ticket_id", ""),
                    msg.get("new_status", ""),
                )

            elif msg_type == "rush_order":
                await kds_pusher.push_rush_order(msg.get("ticket_id", ""))

    except WebSocketDisconnect:
        await kds_pusher.unregister(station_id, websocket)
        logger.info("kds_ws_disconnected", station_id=station_id)


async def broadcast_agent_decision(decision: dict):
    """广播 Agent 决策到所有连接的 POS 终端"""
    for ws in connected_clients:
        try:
            await ws.send_json(decision)
        except Exception:
            pass


# ─── 安卓 POS 外设转发（iPad 用） ───

@app.post("/api/print")
async def print_receipt(data: dict):
    """接收 iPad/浏览器的打印请求，转发到安卓 POS（通过 WebSocket）"""
    await broadcast_agent_decision({"type": "print", "payload": data})
    return {"ok": True, "data": {"message": "Print command forwarded"}}


@app.post("/api/cash-box")
async def open_cash_box():
    """接收钱箱开启请求"""
    await broadcast_agent_decision({"type": "open_cash_box"})
    return {"ok": True, "data": {"message": "Cash box command forwarded"}}
