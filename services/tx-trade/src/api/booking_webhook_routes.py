"""预订渠道 Webhook 接收 + Mock 生成 + WebSocket 实时推送

支持平台：
  - 美团（meituan）
  - 大众点评（dianping）
  - 微信小程序（wechat）

统一内部格式: source_channel + platform_order_id 用于去重。
验签: HMAC-SHA256（美团/大众点评）/ SHA256（微信）。
WS推送: 内存级连接管理（生产环境用 Redis Pub/Sub 替代）。

Revision: 2026-04-02
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import logging
import os
import random
import time
import uuid
from datetime import datetime, timedelta
from typing import AsyncGenerator, Dict, Optional, Set

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db_with_tenant

from ..services.reservation_service import ReservationService

logger = logging.getLogger(__name__)
_structlog = structlog.get_logger()

# ─── Webhook 签名验证 ─────────────────────────────────────────────────────────

_REPLAY_WINDOW_SECONDS = 300  # 防重放：5 分钟


def _get_client_ip(request: Request) -> str:
    forwarded = request.headers.get("X-Forwarded-For", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _check_timestamp(timestamp_str: str) -> bool:
    """检查 timestamp（Unix 秒）是否在 5 分钟窗口内，防重放攻击。"""
    try:
        ts = int(timestamp_str)
    except ValueError:
        return False
    now = int(time.time())
    return abs(now - ts) <= _REPLAY_WINDOW_SECONDS


def verify_meituan_signature(body: bytes, signature: str, secret: str) -> bool:
    """美团/大众点评 Webhook 签名验证（HMAC-SHA256）。"""
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


def verify_wechat_signature(body: bytes, signature: str, timestamp: str, secret: str) -> bool:
    """微信 Webhook 签名验证：SHA256(token + timestamp + body)。"""
    content = secret + timestamp + body.decode("utf-8")
    expected = hashlib.sha256(content.encode()).hexdigest()
    return hmac.compare_digest(expected, signature)


async def _verify_webhook_signature(
    request: Request,
    platform: str,
    signature_header: str,
) -> None:
    """通用签名验证流程，验证失败抛出 HTTP 403。

    - WEBHOOK_SECRET 未设置（空字符串）时 → 跳过（开发环境）
    - 签名缺失或验证失败 → 403
    - timestamp 超出 5 分钟窗口 → 403
    """
    secret = os.getenv("WEBHOOK_SECRET", "")
    if not secret:
        _structlog.warning(
            "webhook_signature_skipped",
            platform=platform,
            reason="WEBHOOK_SECRET not set, dev/test env assumed",
        )
        return

    body = await request.body()
    signature = request.headers.get(signature_header, "")
    timestamp_str = request.headers.get("X-Timestamp", "")
    client_ip = _get_client_ip(request)
    store_id = request.headers.get("X-Tenant-ID", "unknown")

    # 防重放：先检查 timestamp
    if not timestamp_str or not _check_timestamp(timestamp_str):
        _structlog.warning(
            "webhook_replay_rejected",
            platform=platform,
            store_id=store_id,
            ip=client_ip,
            timestamp=timestamp_str,
        )
        raise HTTPException(
            status_code=403,
            detail={"ok": False, "data": None, "error": {"code": "INVALID_SIGNATURE"}},
        )

    # 签名校验
    if platform == "wechat":
        valid = bool(signature) and verify_wechat_signature(body, signature, timestamp_str, secret)
    else:
        valid = bool(signature) and verify_meituan_signature(body, signature, secret)

    if not valid:
        _structlog.warning(
            "webhook_signature_invalid",
            platform=platform,
            store_id=store_id,
            ip=client_ip,
        )
        raise HTTPException(
            status_code=403,
            detail={"ok": False, "data": None, "error": {"code": "INVALID_SIGNATURE"}},
        )

router = APIRouter(prefix="/api/v1/booking", tags=["booking-webhook"])


# ─── WebSocket 连接管理器 ─────────────────────────────────────────────────────

class ReservationWSManager:
    """内存级 WebSocket 连接管理器。

    store_id → Set[WebSocket]
    生产环境建议替换为 Redis Pub/Sub 以支持多实例水平扩展。
    """

    def __init__(self) -> None:
        self.connections: Dict[str, Set[WebSocket]] = {}

    async def connect(self, store_id: str, ws: WebSocket) -> None:
        await ws.accept()
        if store_id not in self.connections:
            self.connections[store_id] = set()
        self.connections[store_id].add(ws)
        logger.info(
            "ws_reservation_connected",
            extra={"store_id": store_id, "total": len(self.connections[store_id])},
        )

    def disconnect(self, store_id: str, ws: WebSocket) -> None:
        if store_id in self.connections:
            self.connections[store_id].discard(ws)
            if not self.connections[store_id]:
                del self.connections[store_id]
        logger.info("ws_reservation_disconnected", extra={"store_id": store_id})

    async def broadcast_to_store(self, store_id: str, message: dict) -> None:
        """向某门店所有已连接前端广播 JSON 消息，自动清除失效连接。"""
        if store_id not in self.connections:
            return
        dead: Set[WebSocket] = set()
        for ws in list(self.connections[store_id]):
            try:
                await ws.send_json(message)
            except Exception:  # noqa: BLE001 — 逐个连接容错，不能用具体类型
                dead.add(ws)
        if dead:
            self.connections[store_id] -= dead
            if not self.connections[store_id]:
                del self.connections[store_id]


reservation_ws_manager = ReservationWSManager()


# ─── WebSocket 端点 ───────────────────────────────────────────────────────────

@router.websocket("/ws/{store_id}")
async def reservation_ws(store_id: str, websocket: WebSocket) -> None:
    """预订实时推送 WebSocket 端点。

    连接路径: /api/v1/booking/ws/{store_id}
    心跳: 客户端每 25 秒发送 "ping"，服务端回应 "pong"。
    断线: 30 秒未收到心跳则主动断开，客户端负责 5 秒后重连。
    """
    await reservation_ws_manager.connect(store_id, websocket)
    try:
        while True:
            try:
                data = await asyncio.wait_for(websocket.receive_text(), timeout=30.0)
                if data == "ping":
                    await websocket.send_text("pong")
            except asyncio.TimeoutError:
                # 超时主动断开，让客户端重连
                break
    except WebSocketDisconnect:
        pass
    finally:
        reservation_ws_manager.disconnect(store_id, websocket)


# ─── DB 会话辅助 ──────────────────────────────────────────────────────────────

def _get_tenant_id(request: Request) -> str:
    tid = getattr(request.state, "tenant_id", None) or request.headers.get("X-Tenant-ID", "")
    if not tid:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header required")
    return tid


async def _get_db_session(request: Request) -> AsyncGenerator[AsyncSession, None]:
    tenant_id = _get_tenant_id(request)
    async for session in get_db_with_tenant(tenant_id):
        yield session


def _ok(data: object) -> dict:
    return {"ok": True, "data": data, "error": None}


def _err(msg: str, code: int = 400) -> None:
    raise HTTPException(
        status_code=code,
        detail={"ok": False, "data": None, "error": {"message": msg}},
    )


# ─── 平台 Payload 模型 ────────────────────────────────────────────────────────

class MeituanBookingPayload(BaseModel):
    """美团预订平台推送格式（Mock 对接，真实需对接美团开放平台）"""
    order_id: str                          # 美团订单号
    shop_id: str                           # 美团门店ID
    customer_name: str
    customer_phone: str
    party_size: int
    arrive_time: str                       # ISO 格式，如 2026-04-02T18:30:00
    table_type: str = "大厅"               # 大厅 / 包厢
    special_request: str = ""
    status: str = "confirmed"              # confirmed / cancelled
    created_at: str


class DianpingBookingPayload(BaseModel):
    """大众点评预订平台推送格式"""
    deal_id: str                           # 大众点评订单号
    poi_id: str                            # POI 门店 ID
    user_name: str
    user_phone: str
    guest_num: int
    visit_time: str                        # ISO 格式
    room_type: str = "大厅"               # 大厅 / 包厢 / 靠窗
    remark: str = ""
    order_status: str = "CONFIRMED"        # CONFIRMED / CANCELLED / COMPLETED
    create_time: str


class WechatBookingPayload(BaseModel):
    """微信小程序预订推送格式（来自 miniapp-customer）"""
    booking_id: str                        # 小程序端生成的预订ID
    openid: str                            # 用户 openid
    customer_name: str
    customer_phone: str
    party_size: int
    arrive_time: str                       # ISO 格式
    table_preference: str = "大厅"        # 大厅 / 包厢 / 靠窗
    notes: str = ""
    store_id: str                          # 内部门店 ID（小程序已绑定）
    status: str = "confirmed"


# ─── 内部归一化 ───────────────────────────────────────────────────────────────

def _normalize_meituan(payload: MeituanBookingPayload) -> dict:
    """将美团格式映射到内部 reservation 字段"""
    # 解析到到店时间中的 date / time
    arrive_dt = datetime.fromisoformat(payload.arrive_time)
    return {
        "source_channel": "meituan",
        "platform_order_id": payload.order_id,
        "shop_platform_id": payload.shop_id,
        "customer_name": payload.customer_name,
        "phone": payload.customer_phone,
        "party_size": payload.party_size,
        "date": arrive_dt.strftime("%Y-%m-%d"),
        "time": arrive_dt.strftime("%H:%M"),
        "room_name": payload.table_type if payload.table_type != "大厅" else None,
        "special_requests": payload.special_request or None,
        "status_raw": payload.status,
    }


def _normalize_dianping(payload: DianpingBookingPayload) -> dict:
    """将大众点评格式映射到内部 reservation 字段"""
    arrive_dt = datetime.fromisoformat(payload.visit_time)
    return {
        "source_channel": "dianping",
        "platform_order_id": payload.deal_id,
        "shop_platform_id": payload.poi_id,
        "customer_name": payload.user_name,
        "phone": payload.user_phone,
        "party_size": payload.guest_num,
        "date": arrive_dt.strftime("%Y-%m-%d"),
        "time": arrive_dt.strftime("%H:%M"),
        "room_name": payload.room_type if payload.room_type != "大厅" else None,
        "special_requests": payload.remark or None,
        "status_raw": "confirmed" if payload.order_status == "CONFIRMED" else "cancelled",
    }


def _normalize_wechat(payload: WechatBookingPayload) -> dict:
    """将微信小程序格式映射到内部 reservation 字段"""
    arrive_dt = datetime.fromisoformat(payload.arrive_time)
    return {
        "source_channel": "wechat",
        "platform_order_id": payload.booking_id,
        "shop_platform_id": None,          # 小程序直接传 store_id
        "store_id_direct": payload.store_id,
        "customer_name": payload.customer_name,
        "phone": payload.customer_phone,
        "party_size": payload.party_size,
        "date": arrive_dt.strftime("%Y-%m-%d"),
        "time": arrive_dt.strftime("%H:%M"),
        "room_name": payload.table_preference if payload.table_preference != "大厅" else None,
        "special_requests": payload.notes or None,
        "status_raw": payload.status,
    }


async def _upsert_reservation(
    normalized: dict,
    store_id: str,
    db: AsyncSession,
    tenant_id: str,
) -> dict:
    """将归一化后的预订数据写入数据库（新建或幂等更新）"""
    svc = ReservationService(db=db, tenant_id=tenant_id, store_id=store_id)

    is_cancel = normalized.get("status_raw") == "cancelled"

    try:
        # 先尝试通过 platform_order_id 查找已有记录
        existing = await svc.find_by_platform_order_id(
            source_channel=normalized["source_channel"],
            platform_order_id=normalized["platform_order_id"],
        )

        if existing:
            # 已存在：仅更新状态
            if is_cancel:
                result = await svc.cancel_reservation(existing["id"], reason="platform_cancelled")
            else:
                result = existing
            logger.info(
                "webhook_upsert_existing",
                extra={
                    "source": normalized["source_channel"],
                    "platform_order_id": normalized["platform_order_id"],
                    "action": "cancel" if is_cancel else "noop",
                },
            )
            return result
        elif is_cancel:
            # 不存在 + 已取消：忽略
            logger.info(
                "webhook_skip_cancelled_unknown",
                extra={"platform_order_id": normalized["platform_order_id"]},
            )
            return {"action": "skipped", "reason": "already_cancelled_before_creation"}
        else:
            # 新建预订
            result = await svc.create_reservation(
                store_id=store_id,
                customer_name=normalized["customer_name"],
                phone=normalized["phone"],
                type="regular",
                date=normalized["date"],
                time=normalized["time"],
                party_size=int(normalized["party_size"]),
                room_name=normalized.get("room_name"),
                special_requests=normalized.get("special_requests"),
                deposit_required=False,
                deposit_amount_fen=0,
                consumer_id=None,
                source_channel=str(normalized["source_channel"]),
                platform_order_id=str(normalized["platform_order_id"]),
            )
            logger.info(
                "webhook_created",
                extra={
                    "source": normalized["source_channel"],
                    "platform_order_id": normalized["platform_order_id"],
                    "reservation_id": result.get("id"),
                },
            )
            # 实时推送：新预订广播给该门店所有已连接前端
            await reservation_ws_manager.broadcast_to_store(store_id, {
                "type": "new_reservation",
                "reservation": result,
                "source": str(normalized["source_channel"]),
                "timestamp": datetime.utcnow().isoformat(),
            })
            return result
    except ValueError as e:
        _err(str(e))
        return {}  # unreachable, _err always raises


def _resolve_store_id(shop_platform_id: Optional[str], tenant_id: str) -> str:
    """通过平台门店 ID 映射到内部 store_id。
    TODO: 从 store_platform_bindings 配置表查询真实映射。
    当前 Mock：直接返回占位值，实际部署时替换。
    """
    _ = shop_platform_id  # 参数预留，查询时使用
    _ = tenant_id
    # TODO: SELECT store_id FROM store_platform_bindings
    #       WHERE platform_shop_id = shop_platform_id
    #       AND   tenant_id = tenant_id
    #       LIMIT 1
    return "store_001"


# ─── Webhook 端点 ─────────────────────────────────────────────────────────────

@router.post("/webhook/meituan")
async def webhook_meituan(
    payload: MeituanBookingPayload,
    request: Request,
    db: AsyncSession = Depends(_get_db_session),
):
    """接收美团预订 Webhook 推送

    验签：HMAC-SHA256(WEBHOOK_SECRET, body)，签名来自 X-Meituan-Signature header。
    防重放：X-Timestamp 需在 5 分钟窗口内。
    WEBHOOK_SECRET 未设置时跳过验证（dev/test 环境）。
    """
    await _verify_webhook_signature(request, platform="meituan", signature_header="X-Meituan-Signature")

    logger.info(
        "webhook_meituan_received",
        extra={
            "order_id": payload.order_id,
            "sign_verified": True,
        },
    )

    tenant_id = _get_tenant_id(request)
    normalized = _normalize_meituan(payload)
    store_id = _resolve_store_id(payload.shop_id, tenant_id)
    result = await _upsert_reservation(normalized, store_id, db, tenant_id)

    # 美团要求固定响应格式
    return {"code": 0, "message": "ok", "data": result}


@router.post("/webhook/dianping")
async def webhook_dianping(
    payload: DianpingBookingPayload,
    request: Request,
    db: AsyncSession = Depends(_get_db_session),
):
    """接收大众点评预订 Webhook 推送

    验签：HMAC-SHA256(WEBHOOK_SECRET, body)，签名来自 X-Meituan-Signature header（美团/点评共享体系）。
    防重放：X-Timestamp 需在 5 分钟窗口内。
    WEBHOOK_SECRET 未设置时跳过验证（dev/test 环境）。
    """
    await _verify_webhook_signature(request, platform="dianping", signature_header="X-Meituan-Signature")

    logger.info(
        "webhook_dianping_received",
        extra={
            "deal_id": payload.deal_id,
            "sign_verified": True,
        },
    )

    tenant_id = _get_tenant_id(request)
    normalized = _normalize_dianping(payload)
    store_id = _resolve_store_id(payload.poi_id, tenant_id)
    result = await _upsert_reservation(normalized, store_id, db, tenant_id)

    # 大众点评要求固定响应格式
    return {"code": 0, "message": "success", "data": result}


@router.post("/webhook/wechat")
async def webhook_wechat(
    payload: WechatBookingPayload,
    request: Request,
    db: AsyncSession = Depends(_get_db_session),
):
    """接收微信小程序预订推送（来自 miniapp-customer）

    验签：SHA256(WEBHOOK_SECRET + X-Timestamp + body)，签名来自 X-Wechat-Signature header。
    防重放：X-Timestamp 需在 5 分钟窗口内。
    WEBHOOK_SECRET 未设置时跳过验证（dev/test 环境）。
    """
    await _verify_webhook_signature(request, platform="wechat", signature_header="X-Wechat-Signature")

    logger.info(
        "webhook_wechat_received",
        extra={
            "booking_id": payload.booking_id,
            "openid_prefix": payload.openid[:8] if payload.openid else "",
            "sign_verified": True,
        },
    )

    tenant_id = _get_tenant_id(request)
    normalized = _normalize_wechat(payload)
    # 微信小程序直接传 store_id，无需映射
    store_id = payload.store_id
    result = await _upsert_reservation(normalized, store_id, db, tenant_id)

    return _ok(result)


# ─── Mock 生成端点 ────────────────────────────────────────────────────────────

_MOCK_CHANNELS = ["meituan", "dianping"]
_VALID_TABLE_TYPES = ["大厅", "包厢", "靠窗"]
_SPECIAL_REQUESTS_POOL = [
    "忌辣，庆生，需要蛋糕",
    "对海鲜过敏",
    "需要婴儿椅",
    "靠窗座位",
    "",
    "不吃香菜",
    "安静包厢",
]


async def _sample_customer_from_reservations(
    store_id: str,
    tenant_id: str,
    db: AsyncSession,
) -> tuple[str, str]:
    """从 reservations 历史中随机取一条预订的客户名/手机。
    若无历史数据，使用匿名占位符。
    """
    from sqlalchemy import text as _text  # noqa: PLC0415

    try:
        sql = _text("""
            SELECT customer_name, phone
            FROM reservations
            WHERE store_id = :store_id
              AND tenant_id = :tenant_id
              AND customer_name IS NOT NULL
              AND phone IS NOT NULL
            ORDER BY RANDOM()
            LIMIT 1
        """)
        result = await db.execute(sql, {"store_id": store_id, "tenant_id": tenant_id})
        row = result.fetchone()
        if row:
            return row.customer_name, row.phone
    except Exception as exc:  # noqa: BLE001 — 查询失败时使用占位符
        _structlog.warning("booking_mock.customer_fetch_failed", error=str(exc))

    return "测试客户", "138****" + str(random.randint(1000, 9999))  # noqa: S311


@router.post("/mock/new-reservation")
async def mock_new_reservation(
    request: Request,
    db: AsyncSession = Depends(_get_db_session),
    store_id: str = Query("store_001", description="内部门店 ID"),
):
    """生成一条 Mock 预订（美团/大众点评随机），供开发测试用

    不需要签名，不会触发真实外部请求。
    客户名/手机从该门店历史预订中随机取样（无历史时使用匿名占位符）。
    直接写入数据库并返回创建结果。
    """
    tenant_id = _get_tenant_id(request)
    channel = random.choice(_MOCK_CHANNELS)  # noqa: S311 — mock data generator

    # 随机到店时间：今天或明天的 11:00-21:00
    days_offset = random.choice([0, 1])  # noqa: S311 — mock data generator
    base_date = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    arrive_date = base_date + timedelta(days=days_offset)
    hour = random.choice([11, 12, 13, 17, 18, 19, 20])  # noqa: S311 — mock data generator
    minute = random.choice([0, 15, 30, 45])  # noqa: S311 — mock data generator
    arrive_dt = arrive_date.replace(hour=hour, minute=minute)

    # 客户信息从 DB 历史取样
    name, phone = await _sample_customer_from_reservations(store_id, tenant_id, db)
    party_size = random.randint(2, 8)  # noqa: S311 — mock data generator
    table_type = random.choice(_VALID_TABLE_TYPES)  # noqa: S311 — mock data generator
    special_req = random.choice(_SPECIAL_REQUESTS_POOL)  # noqa: S311 — mock data generator
    mock_order_id = f"mock_{channel}_{uuid.uuid4().hex[:12]}"

    normalized: dict = {
        "source_channel": channel,
        "platform_order_id": mock_order_id,
        "customer_name": name,
        "phone": phone,
        "party_size": party_size,
        "date": arrive_dt.strftime("%Y-%m-%d"),
        "time": arrive_dt.strftime("%H:%M"),
        "room_name": table_type if table_type != "大厅" else None,
        "special_requests": special_req or None,
        "status_raw": "confirmed",
    }

    result = await _upsert_reservation(normalized, store_id, db, tenant_id)

    return _ok({
        "mock_channel": channel,
        "mock_order_id": mock_order_id,
        "reservation": result,
    })
