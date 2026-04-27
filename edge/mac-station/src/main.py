"""Mac Station — 门店本地 FastAPI 服务

职责：只做智能，不碰外设。
1. 本地 PostgreSQL 副本的 API 接口
2. 离线查询（断网时收银/KDS/Agent 不停摆）
3. WebSocket 推送 Agent 决策到安卓 POS
4. 代理 Core ML 桥接请求
5. ForgeNode 离线感知决策引擎（读取 SKILL.yaml degradation.offline 配置）
"""

import asyncio
import base64
import json
import os
from contextlib import asynccontextmanager

import httpx
import structlog
from api.forge_routes import router as forge_router
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from federated_client import router as federated_router
from forge_node import ForgeNode
from heartbeat_routes import router as heartbeat_router
from offline_cashier import router as offline_cashier_router
from offline_routes import router as offline_router
from ota_routes import router as ota_router
from vision_service import router as vision_router
from voice_service import router as voice_router

logger = structlog.get_logger()

COREML_URL = os.getenv("COREML_BRIDGE_URL", "http://localhost:8100")


# ─── ForgeNode 生命周期 ───────────────────────────────────────────────────────


@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI 应用生命周期：启动时初始化 ForgeNode，关闭时取消后台任务"""
    # 初始化 ForgeNode（加载所有 SKILL.yaml + 初始化 SQLite 缓冲）
    forge = ForgeNode()
    await forge.initialize()
    app.state.forge_node = forge

    # 启动后台连接状态检测（30秒间隔，非阻塞）
    connectivity_task = asyncio.create_task(
        forge.start_connectivity_check(),
        name="forge_connectivity_check",
    )
    logger.info("forge_node_background_task_started")

    yield  # 应用运行期间

    # 关闭时取消后台任务
    connectivity_task.cancel()
    try:
        await connectivity_task
    except asyncio.CancelledError:
        pass
    logger.info("forge_node_background_task_stopped")


app = FastAPI(
    title="TunxiangOS Mac Station",
    version="4.2.0",
    description="门店本地智能后台 — Mac mini M4 (Voice + Vision + KDS + ForgeNode)",
    lifespan=lifespan,
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

# ─── 设备心跳注册表路由 ───
app.include_router(heartbeat_router)

# ─── OTA 版本检查路由（带1小时本地缓存）───
app.include_router(ota_router)

# ─── 离线查询路由（本地 PG）───
app.include_router(offline_router)

# ─── 离线收银路由（Y-K1 断网优先写入）───
app.include_router(offline_cashier_router)

# ─── ForgeNode 离线感知决策路由 ───
app.include_router(forge_router)

# ─── 健康检查 ───


@app.get("/health")
async def health() -> dict:
    return {"ok": True, "data": {"service": "mac-station", "version": "4.2.0"}}


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
        return {
            "ok": False,
            "data": None,
            "error": {"code": "COREML_UNAVAILABLE", "message": "Core ML bridge not running"},
        }


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
    except (WebSocketDisconnect, RuntimeError, OSError, ConnectionError):
        pass
    finally:
        try:
            connected_clients.remove(websocket)
        except ValueError:
            pass
        logger.info("ws_client_disconnected", total=len(connected_clients))


# ─── KDS WebSocket 推送 ───

from kds_pusher import KDSPusher
from pos_pusher import DiscountAlert, POSPusher

kds_pusher = KDSPusher()
pos_pusher = POSPusher()


# ─── POS WebSocket 推送 ───


@app.websocket("/ws/pos/{store_id}/{terminal_id}")
async def pos_ws_endpoint(websocket: WebSocket, store_id: str, terminal_id: str) -> None:
    """POS 收银终端 WebSocket 连接端点。

    收银端连接后可接收：
    - discount_alert: 折扣守护预警
    - operation_alert: 运营通知（库存低/临期/班次提醒/销售里程碑）
    支持心跳：客户端发 "ping"，服务端回 "pong"
    """
    await websocket.accept()
    await pos_pusher.connect(store_id, terminal_id, websocket)

    try:
        while True:
            data = await asyncio.wait_for(websocket.receive_text(), timeout=30)
            if data == "ping":
                await websocket.send_text("pong")
    except asyncio.TimeoutError:
        # 30秒无心跳 → 断开，等待客户端重连
        logger.info(
            "pos_ws_heartbeat_timeout",
            store_id=store_id,
            terminal_id=terminal_id,
        )
    except WebSocketDisconnect:
        pass
    finally:
        pos_pusher.disconnect(store_id, terminal_id)


# ─── POS HTTP Push 接口（供 tx-agent 调用） ───


@app.post("/api/v1/pos/push-discount-alert")
async def pos_push_discount_alert(data: dict) -> dict:
    """HTTP → WebSocket 桥接：tx-agent 通过此接口触发折扣预警推送。

    请求体:
        store_id: str — 目标门店 ID
        alert: dict  — DiscountAlert 字段（见 pos_pusher.DiscountAlert）

    响应:
        { "ok": true, "data": { "store_id": str, "sent_count": int } }
    """
    store_id = data.get("store_id", "")
    alert_data = data.get("alert", {})

    if not store_id:
        return {
            "ok": False,
            "error": {"code": "INVALID_PARAMS", "message": "store_id required"},
        }

    alert = DiscountAlert(
        alert_id=alert_data.get("alert_id", ""),
        store_id=store_id,
        order_id=alert_data.get("order_id", ""),
        employee_id=alert_data.get("employee_id", alert_data.get("operator_id", "")),
        employee_name=alert_data.get("employee_name", alert_data.get("operator_id", "")),
        discount_rate=float(alert_data.get("discount_rate", 0)),
        threshold=float(alert_data.get("threshold", 0.5)),
        amount_fen=int(alert_data.get("amount_fen", alert_data.get("discount_amount_fen", 0))),
        risk_level=alert_data.get("risk_level", alert_data.get("severity", "medium")),
        message=alert_data.get("message", alert_data.get("violation_type", "")),
        timestamp=alert_data.get("timestamp", alert_data.get("logged_at", "")),
    )

    sent = await pos_pusher.push_discount_alert(store_id, alert)
    terminals = pos_pusher.get_connected_terminals(store_id)

    return {
        "ok": True,
        "data": {
            "store_id": store_id,
            "sent_count": sent,
            "terminals_online": terminals,
        },
    }


@app.get("/api/v1/pos/terminals/{store_id}")
async def pos_get_terminals(store_id: str) -> dict:
    """查询门店当前在线的 POS 终端列表。"""
    terminals = pos_pusher.get_connected_terminals(store_id)
    return {
        "ok": True,
        "data": {"store_id": store_id, "terminals": terminals, "count": len(terminals)},
    }


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
    await broadcast_agent_decision(
        {
            "type": "admin_alert",
            "payload": data,
        }
    )

    # TODO: 转发到企微/钉钉/短信
    return {"ok": True, "data": {"forwarded": True, "channels": ["websocket"]}}


async def broadcast_agent_decision(decision: dict) -> None:
    """广播 Agent 决策到所有连接的 POS 终端"""
    dead: list[WebSocket] = []
    for ws in connected_clients:
        try:
            await ws.send_json(decision)
        except (WebSocketDisconnect, RuntimeError, OSError, ConnectionError):
            dead.append(ws)
    for ws in dead:
        try:
            connected_clients.remove(ws)
        except ValueError:
            pass


# ─── 打印机管理 ───

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
        test_data = b"\x1b\x40"  # ESC @ 初始化
        test_data += "---- 打印机测试 ----\n".encode("gbk", errors="replace")
        test_data += f"打印机: {printer['name']}\n".encode("gbk", errors="replace")
        test_data += f"地址: {printer['address']}\n".encode("gbk", errors="replace")
        test_data += b"\x1d\x56\x00"  # GS V 0 切纸
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
    printer_address = data.get("printer_address", "")
    printer = _printers.get(printer_id) if printer_id else None

    # 如果指定了 printer_address（如档口打印机地址 host:port），直接 TCP 发送
    if printer_address and ":" in printer_address:
        ok = await _send_to_network_printer(printer_address, esc_pos_bytes)
        return {"ok": ok, "data": {"printer_address": printer_address, "channel": "network_tcp_direct"}}

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


# ─── 数字菜单展示屏 WebSocket（Redis Pub/Sub → 前端） ───

menu_board_clients: dict[str, list[WebSocket]] = {}


@app.websocket("/ws/menu-board-updates")
async def menu_board_ws(
    websocket: WebSocket,
    store_id: str = "",
    tenant_id: str = "",
) -> None:
    """数字菜单展示屏 WebSocket 端点。

    前端连接后，监听来自 tx-trade 通过 Redis Pub/Sub 广播的菜单更新事件。
    支持的事件：dish_soldout / dish_available / price_update / announcement_update
    """
    await websocket.accept()
    channel = f"menu_board:{tenant_id}:{store_id}" if tenant_id and store_id else "menu_board:*"
    menu_board_clients.setdefault(channel, []).append(websocket)
    logger.info("menu_board_ws_connected", channel=channel, total=len(menu_board_clients.get(channel, [])))

    # 启动 Redis 订阅（每条连接独立订阅，适合低并发场景）
    redis_task = asyncio.create_task(_subscribe_menu_board_redis(channel, websocket))

    try:
        while True:
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text("pong")
    except (WebSocketDisconnect, RuntimeError, OSError, ConnectionError):
        pass
    finally:
        redis_task.cancel()
        clients = menu_board_clients.get(channel, [])
        try:
            clients.remove(websocket)
        except ValueError:
            pass
        logger.info("menu_board_ws_disconnected", channel=channel)


async def _subscribe_menu_board_redis(channel: str, websocket: WebSocket) -> None:
    """订阅 Redis Pub/Sub 频道，将消息转发给对应 WebSocket 客户端。

    Redis 不可用时静默退出（前端 mock 数据兜底）。
    """
    try:
        import redis.asyncio as aioredis  # type: ignore

        redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
        async with aioredis.from_url(redis_url, decode_responses=True) as client, client.pubsub() as pubsub:
            await pubsub.subscribe(channel)
            async for message in pubsub.listen():
                if message["type"] != "message":
                    continue
                try:
                    await websocket.send_text(message["data"])
                except (RuntimeError, OSError, ConnectionError):
                    break
    except ImportError:
        logger.warning("redis_not_installed_menu_board")
    except (ConnectionError, OSError) as e:
        logger.warning("redis_subscribe_failed_menu_board", channel=channel, error=str(e))
    except asyncio.CancelledError:
        pass


@app.post("/api/cash-box")
async def open_cash_box() -> dict:
    """接收钱箱开启请求"""
    await broadcast_agent_decision({"type": "open_cash_box"})
    return {"ok": True, "data": {"message": "Cash box command forwarded"}}
