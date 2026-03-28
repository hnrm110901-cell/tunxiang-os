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

from vision_service import router as vision_router
from voice_service import router as voice_router
from federated_client import router as federated_router

logger = structlog.get_logger()

COREML_URL = os.getenv("COREML_BRIDGE_URL", "http://localhost:8100")

app = FastAPI(
    title="TunxiangOS Mac Station",
    version="4.1.0",
    description="门店本地智能后台 — Mac mini M4 (Voice + Vision + KDS)",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── Vision Service 路由 ───
app.include_router(vision_router)

# ─── Voice Service 路由 ───
app.include_router(voice_router)

# ─── Federated Learning 路由 ───
app.include_router(federated_router)

# ─── 健康检查 ───

@app.get("/health")
async def health() -> dict:
    return {"ok": True, "data": {"service": "mac-station", "version": "3.0.0"}}


# ─── 离线查询 API ───

@app.get("/api/v1/offline/revenue")
async def query_revenue_offline(store_id: str, date: str = "today") -> dict:
    """离线查询营业额（从本地 PG 读取）"""
    # TODO: 接入本地 PG
    return {"ok": True, "data": {"store_id": store_id, "date": date, "revenue_fen": 0, "source": "local_cache"}}


@app.get("/api/v1/offline/inventory")
async def query_inventory_offline(store_id: str) -> dict:
    """离线查询库存（从本地 PG 读取）"""
    return {"ok": True, "data": {"store_id": store_id, "items": [], "source": "local_cache"}}


@app.get("/api/v1/offline/orders")
async def query_orders_offline(store_id: str, status: str = "pending") -> dict:
    """离线查询订单"""
    return {"ok": True, "data": {"store_id": store_id, "orders": [], "source": "local_cache"}}


# ─── Core ML 代理 ───

@app.post("/api/v1/predict/{model_name}")
async def predict(model_name: str, data: dict) -> dict:
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
async def agent_push_ws(websocket: WebSocket) -> None:
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
async def kds_ws(websocket: WebSocket, station_id: str) -> None:
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
                await kds_pusher.push_rush_order(msg.get("ticket_id", ""), extra=msg)

            elif msg_type == "remake_order":
                await kds_pusher.push_remake_order(
                    station_id=msg.get("station_id", station_id),
                    task_id=msg.get("task_id", ""),
                    dish_name=msg.get("dish_name", ""),
                    reason=msg.get("reason", ""),
                    table_number=msg.get("table_number", ""),
                    remake_count=msg.get("remake_count", 1),
                )

            elif msg_type == "timeout_alert":
                await kds_pusher.push_timeout_alert(
                    station_id=msg.get("station_id", station_id),
                    payload=msg.get("payload", {}),
                )

    except WebSocketDisconnect:
        await kds_pusher.unregister(station_id, websocket)
        logger.info("kds_ws_disconnected", station_id=station_id)


# ─── KDS HTTP Push 接口（供 tx-trade 服务端调用） ───


@app.post("/api/v1/kds/push")
async def kds_push_via_http(data: dict) -> dict:
    """HTTP -> WebSocket 桥接：tx-trade 服务通过此接口推送消息到 KDS 终端。

    请求体:
        station_id: str — 目标档口ID
        message: dict — 推送消息体（含 type 字段）
    """
    station_id = data.get("station_id", "")
    message = data.get("message", {})
    msg_type = message.get("type", "")

    if not station_id or not msg_type:
        return {"ok": False, "error": {"code": "INVALID_PARAMS", "message": "station_id and message.type required"}}

    if msg_type == "rush_order":
        await kds_pusher.push_rush_order(
            message.get("ticket_id", message.get("order_id", "")),
            extra={**message, "station_id": station_id},
        )
    elif msg_type == "remake_order":
        await kds_pusher.push_remake_order(
            station_id=station_id,
            task_id=message.get("task_id", ""),
            dish_name=message.get("dish_name", ""),
            reason=message.get("reason", ""),
            table_number=message.get("table_number", ""),
            remake_count=message.get("remake_count", 1),
        )
    elif msg_type == "timeout_alert":
        await kds_pusher.push_timeout_alert(
            station_id=station_id,
            payload=message.get("payload", message),
        )
    elif msg_type == "new_ticket":
        await kds_pusher.push_new_ticket(station_id, message.get("payload", message))
    elif msg_type == "status_change":
        await kds_pusher.push_status_change(
            message.get("ticket_id", ""),
            message.get("new_status", ""),
        )
    else:
        # 通用推送
        await kds_pusher._send_to_station(station_id, message)

    return {"ok": True, "data": {"station_id": station_id, "type": msg_type}}


# ─── 管理员告警推送 ───


@app.post("/api/v1/admin/alert")
async def admin_alert(data: dict) -> dict:
    """接收管理员告警并广播到所有连接的终端。

    后续扩展：转发到企微/钉钉/短信等渠道。
    """
    alert_type = data.get("type", "unknown")
    logger.warning("admin_alert_received", alert_type=alert_type, severity=data.get("severity"))

    # 广播到所有 Agent 推送连接（管理员终端）
    await broadcast_agent_decision({
        "type": "admin_alert",
        "payload": data,
    })

    # TODO: 转发到企微/钉钉/短信
    return {"ok": True, "data": {"forwarded": True, "channels": ["websocket"]}}


async def broadcast_agent_decision(decision: dict) -> None:
    """广播 Agent 决策到所有连接的 POS 终端"""
    for ws in connected_clients:
        try:
            await ws.send_json(decision)
        except (WebSocketDisconnect, RuntimeError, OSError):
            pass


# ─── 打印机管理 ───

import asyncio
import base64

# 门店打印机注册表（启动时从配置或 API 加载）
# 格式: { "printer_id": { "name": "前台打印机", "type": "network|sunmi", "address": "192.168.1.100:9100", "paper_width": 80 } }
_printers: dict[str, dict] = {}


def _load_printers_from_env() -> None:
    """从环境变量加载打印机配置（轻量方案，不依赖数据库）"""
    # PRINTERS=receipt:network:192.168.1.100:9100,kitchen:network:192.168.1.101:9100
    raw = os.getenv("PRINTERS", "")
    for entry in raw.split(","):
        entry = entry.strip()
        if not entry:
            continue
        parts = entry.split(":")
        if len(parts) >= 3:
            name = parts[0]
            ptype = parts[1]
            address = ":".join(parts[2:])
            _printers[name] = {"name": name, "type": ptype, "address": address, "paper_width": 80}
            logger.info("printer_registered", name=name, type=ptype, address=address)


_load_printers_from_env()


async def _send_to_network_printer(address: str, esc_pos_bytes: bytes) -> bool:
    """通过 TCP 发送 ESC/POS 数据到网络打印机（如佳博、芯烨等）"""
    try:
        host, port = address.rsplit(":", 1)
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, int(port)),
            timeout=5,
        )
        writer.write(esc_pos_bytes)
        await writer.drain()
        writer.close()
        await writer.wait_closed()
        logger.info("network_print_ok", address=address, bytes=len(esc_pos_bytes))
        return True
    except TimeoutError:
        logger.error("network_print_timeout", address=address)
        return False
    except OSError as e:
        logger.error("network_print_error", address=address, error=str(e))
        return False


@app.get("/api/printers")
async def list_printers() -> dict:
    """列出已注册的打印机"""
    return {"ok": True, "data": {"printers": _printers}}


@app.post("/api/printers/{printer_id}/test")
async def test_printer(printer_id: str) -> dict:
    """测试打印机连通性"""
    printer = _printers.get(printer_id)
    if not printer:
        return {"ok": False, "error": {"code": "PRINTER_NOT_FOUND", "message": f"打印机 {printer_id} 未注册"}}

    if printer["type"] == "network":
        # 发送一行测试文本 + 切纸
        test_data = b'\x1b\x40'  # ESC @ 初始化
        test_data += "---- 打印机测试 ----\n".encode("gbk", errors="replace")
        test_data += f"打印机: {printer['name']}\n".encode("gbk", errors="replace")
        test_data += f"地址: {printer['address']}\n".encode("gbk", errors="replace")
        test_data += b'\x1d\x56\x00'  # GS V 0 切纸
        ok = await _send_to_network_printer(printer["address"], test_data)
        return {"ok": ok, "data": {"message": "测试打印已发送" if ok else "打印机连接失败"}}

    return {"ok": False, "error": {"code": "UNSUPPORTED", "message": f"打印机类型 {printer['type']} 不支持测试"}}


@app.post("/api/print")
async def print_receipt(data: dict) -> dict:
    """打印小票 — 自动选择打印通道

    请求体:
        content_base64: str — ESC/POS 字节流的 base64 编码
        content: str — 旧格式兼容（hex 字符串）
        printer_id: str — 指定打印机（可选，默认用第一台网络打印机）
    """
    # 解析打印内容
    esc_pos_bytes = None
    if "content_base64" in data:
        esc_pos_bytes = base64.b64decode(data["content_base64"])
    elif "content" in data:
        try:
            esc_pos_bytes = bytes.fromhex(data["content"])
        except ValueError:
            esc_pos_bytes = data["content"].encode("gbk", errors="replace")

    if not esc_pos_bytes:
        return {"ok": False, "error": {"code": "NO_CONTENT", "message": "缺少打印内容"}}

    # 选择打印机
    printer_id = data.get("printer_id", "")
    printer = _printers.get(printer_id) if printer_id else None

    # 没指定就用第一台网络打印机
    if not printer:
        for p in _printers.values():
            if p["type"] == "network":
                printer = p
                break

    # 有网络打印机 → 直接 TCP 发送
    if printer and printer["type"] == "network":
        ok = await _send_to_network_printer(printer["address"], esc_pos_bytes)
        return {"ok": ok, "data": {"printer": printer["name"], "channel": "network_tcp"}}

    # 没有网络打印机 → 转发到安卓 POS（旧路径兜底）
    await broadcast_agent_decision({"type": "print", "payload": data})
    return {"ok": True, "data": {"channel": "android_pos_forward"}}


@app.post("/api/cash-box")
async def open_cash_box() -> dict:
    """接收钱箱开启请求"""
    await broadcast_agent_decision({"type": "open_cash_box"})
    return {"ok": True, "data": {"message": "Cash box command forwarded"}}
