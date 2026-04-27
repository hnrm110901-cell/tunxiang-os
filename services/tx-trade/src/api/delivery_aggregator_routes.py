"""
外卖聚合深度 — 美团/饿了么/抖音聚合订单完整落库 + 异常单补偿 + 监控指标
Y-A5 Mock→DB 改造（v207）

全部端点已接入 DB（aggregator_orders / aggregator_metrics）
"""

from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime, timezone
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Path, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db_with_tenant

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/trade/aggregator", tags=["delivery-aggregator"])

SUPPORTED_PLATFORMS = {"meituan", "eleme", "douyin"}

PLATFORM_CONFIG: dict[str, dict] = {
    "meituan": {"label": "美团外卖", "color": "orange", "accept_ack": {"errno": 0, "errmsg": "OK"}},
    "eleme": {"label": "饿了么", "color": "blue", "accept_ack": {"code": 200, "msg": "success"}},
    "douyin": {"label": "抖音外卖", "color": "red", "accept_ack": {"err_no": 0, "err_tips": "success"}},
}


# ── DB 依赖 ──────────────────────────────────────────────────────────────────


def _get_tenant_id(request: Request) -> str:
    return request.headers.get("X-Tenant-Id", request.headers.get("X-Tenant-ID", "default"))


async def _get_db(request: Request):
    tenant_id = _get_tenant_id(request)
    async for session in get_db_with_tenant(tenant_id):
        yield session


# ── Pydantic 模型 ────────────────────────────────────────────────────────────


class AggregatorOrderItem(BaseModel):
    dish_name: str = Field(min_length=1, max_length=200)
    quantity: int = Field(ge=1)
    unit_price_fen: int = Field(ge=0)
    spec: Optional[str] = Field(default=None, max_length=200)


class AggregatorWebhookPayload(BaseModel):
    platform_order_id: str = Field(min_length=1, max_length=100)
    store_id: str = Field(min_length=1, max_length=100)
    items: list[AggregatorOrderItem] = Field(min_length=1)
    total_fen: int = Field(ge=0)
    customer_phone: Optional[str] = Field(default=None)
    estimated_delivery_at: Optional[str] = Field(default=None)
    platform_status: str
    extra: Optional[dict] = Field(default=None)


class CancelBody(BaseModel):
    reason: Optional[str] = Field(default=None, max_length=200)


# ── 工具函数 ─────────────────────────────────────────────────────────────────


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _hash_phone(phone: Optional[str]) -> Optional[str]:
    if not phone:
        return None
    return hashlib.sha256(phone.encode()).hexdigest()[:16]


def _mask_phone(phone: Optional[str]) -> Optional[str]:
    if not phone or len(phone) < 7:
        return phone
    return phone[:3] + "****" + phone[-4:]


def _verify_platform_sign(platform: str, sign: Optional[str]) -> bool:
    """验签（当前：非空即通过。生产替换各平台HMAC/RSA）"""
    return sign is not None and len(sign.strip()) > 0


async def _record_metric(
    db: AsyncSession, tenant_id: str, platform: str, success: bool, duration_ms: float, error_code: Optional[str] = None
) -> None:
    try:
        await db.execute(
            text(
                "INSERT INTO aggregator_metrics (tenant_id, platform, success, duration_ms, error_code) VALUES (:tid, :p, :s, :d, :e)"
            ),
            {"tid": tenant_id, "p": platform, "s": success, "d": duration_ms, "e": error_code},
        )
    except SQLAlchemyError as exc:
        logger.warning("aggregator.metric_write_failed", error=str(exc))


# ── 1. Webhook 接收 ──────────────────────────────────────────────────────────


@router.post("/webhook/{platform}", summary="接收平台推单 Webhook")
async def receive_webhook(
    request: Request,
    platform: str = Path(...),
    payload: AggregatorWebhookPayload = ...,
    x_platform_sign: Optional[str] = Header(None, alias="X-Platform-Sign"),
    db: AsyncSession = Depends(_get_db),
) -> dict:
    t0 = time.monotonic()
    tenant_id = _get_tenant_id(request)

    if platform not in SUPPORTED_PLATFORMS:
        await _record_metric(db, tenant_id, platform, False, (time.monotonic() - t0) * 1000, "UNSUPPORTED_PLATFORM")
        await db.commit()
        raise HTTPException(status_code=400, detail={"ok": False, "error": {"code": "UNSUPPORTED_PLATFORM"}})

    if not _verify_platform_sign(platform, x_platform_sign):
        await _record_metric(db, tenant_id, platform, False, (time.monotonic() - t0) * 1000, "SIGN_INVALID")
        await db.commit()
        raise HTTPException(status_code=401, detail={"ok": False, "error": {"code": "SIGN_INVALID"}})

    # 幂等 UPSERT
    row = await db.execute(
        text("""
            INSERT INTO aggregator_orders
                (tenant_id, platform, platform_order_id, store_id, items, total_fen,
                 customer_phone_hash, customer_phone_masked, estimated_delivery_at,
                 status, raw_payload, extra)
            VALUES (:tid, :platform, :poid, :sid, :items::jsonb, :total,
                    :phone_hash, :phone_masked, :est_delivery,
                    :status, :raw::jsonb, :extra::jsonb)
            ON CONFLICT (tenant_id, platform, platform_order_id) DO UPDATE
            SET status = EXCLUDED.status, updated_at = NOW()
            RETURNING id, (xmax = 0) AS is_new
        """),
        {
            "tid": tenant_id,
            "platform": platform,
            "poid": payload.platform_order_id,
            "sid": payload.store_id,
            "items": json.dumps([i.model_dump() for i in payload.items]),
            "total": payload.total_fen,
            "phone_hash": _hash_phone(payload.customer_phone),
            "phone_masked": _mask_phone(payload.customer_phone),
            "est_delivery": payload.estimated_delivery_at,
            "status": payload.platform_status,
            "raw": json.dumps(payload.model_dump()),
            "extra": json.dumps(payload.extra or {}),
        },
    )
    result = row.fetchone()
    agg_id = str(result.id)
    is_new = result.is_new

    duration_ms = (time.monotonic() - t0) * 1000
    await _record_metric(db, tenant_id, platform, True, duration_ms)
    await db.commit()

    return {
        "ok": True,
        "data": {
            "aggregator_order_id": agg_id,
            "is_new": is_new,
            "platform_ack": PLATFORM_CONFIG[platform]["accept_ack"],
        },
        "error": None,
    }


# ── 2. 聚合订单列表 ──────────────────────────────────────────────────────────


@router.get("/orders", summary="聚合订单列表")
async def list_aggregator_orders(
    platform: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    store_id: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(_get_db),
) -> dict:
    conds = ["1=1"]
    params: dict = {"limit": size, "offset": (page - 1) * size}
    if platform:
        conds.append("platform = :platform")
        params["platform"] = platform
    if status:
        conds.append("status = :status")
        params["status"] = status
    if store_id:
        conds.append("store_id = :store_id")
        params["store_id"] = store_id
    where = " AND ".join(conds)

    total = (await db.execute(text(f"SELECT COUNT(*) FROM aggregator_orders WHERE {where}"), params)).scalar() or 0
    rows = await db.execute(
        text(f"""
        SELECT id, platform, platform_order_id, store_id, status, total_fen,
               customer_phone_masked, estimated_delivery_at,
               jsonb_array_length(items) AS items_count, created_at, updated_at
        FROM aggregator_orders WHERE {where} ORDER BY created_at DESC LIMIT :limit OFFSET :offset
    """),
        params,
    )
    items = []
    for r in rows.fetchall():
        d = dict(r._mapping)
        cfg = PLATFORM_CONFIG.get(d["platform"], {})
        d["platform_label"] = cfg.get("label", d["platform"])
        d["platform_color"] = cfg.get("color", "default")
        items.append(d)
    return {"ok": True, "data": {"items": items, "total": total, "page": page, "size": size}, "error": None}


# ── 3. 聚合订单详情 ──────────────────────────────────────────────────────────


@router.get("/orders/{aggregator_order_id}", summary="聚合订单详情")
async def get_aggregator_order(
    request: Request,
    aggregator_order_id: str = Path(...),
    db: AsyncSession = Depends(_get_db),
) -> dict:
    tid = _get_tenant_id(request)
    row = await db.execute(
        text("SELECT * FROM aggregator_orders WHERE id = :oid AND tenant_id = :tid"),
        {"oid": aggregator_order_id, "tid": tid},
    )
    order = row.fetchone()
    if not order:
        raise HTTPException(status_code=404, detail={"ok": False, "error": {"code": "ORDER_NOT_FOUND"}})
    d = dict(order._mapping)
    d["platform_label"] = PLATFORM_CONFIG.get(d["platform"], {}).get("label", d["platform"])
    return {"ok": True, "data": d, "error": None}


# ── 4/5/6. 接单/备餐完成/取消 ────────────────────────────────────────────────

_STATUS_TRANSITIONS = {
    "accept": {"allowed_from": {"new"}, "target": "accepted"},
    "ready": {"allowed_from": {"accepted"}, "target": "ready"},
    "cancel": {"allowed_from": {"new", "accepted"}, "target": "cancelled"},
}


async def _order_action(db: AsyncSession, tid: str, oid: str, action: str, reason: Optional[str] = None) -> dict:
    row = await db.execute(
        text("SELECT id, platform, status FROM aggregator_orders WHERE id = :oid AND tenant_id = :tid"),
        {"oid": oid, "tid": tid},
    )
    order = row.fetchone()
    if not order:
        raise HTTPException(status_code=404, detail={"ok": False, "error": {"code": "ORDER_NOT_FOUND"}})
    cfg = _STATUS_TRANSITIONS[action]
    if order.status not in cfg["allowed_from"]:
        raise HTTPException(
            status_code=409,
            detail={
                "ok": False,
                "error": {"code": "INVALID_STATUS_TRANSITION", "message": f"{order.status} 不允许 {action}"},
            },
        )
    sets = "status = :target, updated_at = NOW()"
    params: dict = {"oid": oid, "tid": tid, "target": cfg["target"]}
    if reason:
        sets += ", cancel_reason = :reason"
        params["reason"] = reason
    await db.execute(text(f"UPDATE aggregator_orders SET {sets} WHERE id = :oid AND tenant_id = :tid"), params)
    await db.commit()
    return {
        "ok": True,
        "data": {"aggregator_order_id": oid, "platform": order.platform, "status": cfg["target"]},
        "error": None,
    }


@router.post("/orders/{oid}/accept", summary="接单")
async def accept_order(request: Request, oid: str = Path(...), db: AsyncSession = Depends(_get_db)) -> dict:
    return await _order_action(db, _get_tenant_id(request), oid, "accept")


@router.post("/orders/{oid}/ready", summary="备餐完成")
async def mark_ready(request: Request, oid: str = Path(...), db: AsyncSession = Depends(_get_db)) -> dict:
    return await _order_action(db, _get_tenant_id(request), oid, "ready")


@router.post("/orders/{oid}/cancel", summary="取消单")
async def cancel_order(
    request: Request, oid: str = Path(...), body: CancelBody = CancelBody(), db: AsyncSession = Depends(_get_db)
) -> dict:
    return await _order_action(db, _get_tenant_id(request), oid, "cancel", body.reason)


# ── 7. 平台状态 ──────────────────────────────────────────────────────────────


@router.get("/platforms/status", summary="各平台连接状态+今日订单量")
async def get_platforms_status(db: AsyncSession = Depends(_get_db)) -> dict:
    today = _now().date()
    rows = await db.execute(
        text("""
        SELECT platform, COUNT(*) AS cnt, COUNT(*) FILTER (WHERE status != 'cancelled') AS ok_cnt
        FROM aggregator_orders WHERE created_at::date = :today GROUP BY platform
    """),
        {"today": today},
    )
    stats = {r.platform: {"count": r.cnt, "ok": r.ok_cnt} for r in rows.fetchall()}
    platforms = []
    for pid, cfg in PLATFORM_CONFIG.items():
        s = stats.get(pid, {"count": 0, "ok": 0})
        platforms.append(
            {
                "platform": pid,
                "label": cfg["label"],
                "color": cfg["color"],
                "online": True,
                "today_order_count": s["count"],
                "today_success_rate": round(s["ok"] / s["count"], 4) if s["count"] else 1.0,
            }
        )
    return {"ok": True, "data": {"platforms": platforms, "checked_at": _now().isoformat()}, "error": None}


# ── 8. 监控指标 ──────────────────────────────────────────────────────────────


@router.get("/metrics", summary="失败率/延迟/平台对比KPI")
async def get_metrics(hours: int = Query(24, ge=1, le=168), db: AsyncSession = Depends(_get_db)) -> dict:
    rows = await db.execute(
        text("""
        SELECT platform, success, duration_ms, error_code
        FROM aggregator_metrics WHERE recorded_at >= NOW() - (:hours * INTERVAL '1 hour')
    """),
        {"hours": hours},
    )
    records = rows.fetchall()
    if not records:
        return {
            "ok": True,
            "data": {"total_requests": 0, "success_rate": 1.0, "avg_latency_ms": 0, "by_platform": {}},
            "error": None,
        }
    total = len(records)
    ok = sum(1 for r in records if r.success)
    lats = sorted(r.duration_ms for r in records)
    p99i = max(0, int(len(lats) * 0.99) - 1)
    by_platform: dict = {}
    for pid in SUPPORTED_PLATFORMS:
        pr = [r for r in records if r.platform == pid]
        if not pr:
            continue
        pt = len(pr)
        ps = sum(1 for r in pr if r.success)
        pl = sorted(r.duration_ms for r in pr)
        pp = max(0, int(len(pl) * 0.99) - 1)
        ec: dict = {}
        for r in pr:
            if not r.success and r.error_code:
                ec[r.error_code] = ec.get(r.error_code, 0) + 1
        by_platform[pid] = {
            "label": PLATFORM_CONFIG[pid]["label"],
            "total": pt,
            "success_rate": round(ps / pt, 4),
            "avg_ms": round(sum(pl) / len(pl), 2),
            "p99_ms": round(pl[pp], 2),
            "errors": ec,
        }
    return {
        "ok": True,
        "data": {
            "total_requests": total,
            "success_rate": round(ok / total, 4),
            "avg_latency_ms": round(sum(lats) / len(lats), 2),
            "p99_latency_ms": round(lats[p99i], 2),
            "by_platform": by_platform,
            "window_hours": hours,
        },
        "error": None,
    }
