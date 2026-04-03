"""小红书平台对接 API — 5个端点

1. POST   /api/v1/xhs/verify                    团购券核销
2. GET    /api/v1/xhs/verifications             核销记录列表
3. POST   /api/v1/xhs/poi/bind                  绑定门店与小红书POI
4. GET    /api/v1/xhs/poi/{store_id}            查询POI绑定
5. POST   /webhook/xhs                          小红书回调（订单/退款通知）
"""
from __future__ import annotations

import uuid
from typing import Any

import structlog
from fastapi import APIRouter, Depends, Header, Query, Request
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger(__name__)

router = APIRouter(tags=["xiaohongshu"])


async def get_db() -> AsyncSession:  # type: ignore[override]
    raise NotImplementedError("DB session dependency not configured")


def ok_response(data: Any) -> dict:
    return {"ok": True, "data": data}


def error_response(msg: str) -> dict:
    return {"ok": False, "error": {"message": msg}}


# ── 请求模型 ──────────────────────────────────────────────────

class VerifyCouponReq(BaseModel):
    coupon_code: str
    store_id: str
    order_id: str = ""
    verified_by: str = ""


class BindPOIReq(BaseModel):
    store_id: str
    xhs_poi_id: str
    xhs_shop_name: str = ""


# ── 1. 团购券核销 ────────────────────────────────────────────

@router.post("/api/v1/xhs/verify")
async def verify_coupon(
    body: VerifyCouponReq,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """扫码核销小红书团购券"""
    from shared.adapters.xiaohongshu.src.xhs_coupon_adapter import XHSCouponAdapter

    # TODO: 从配置或 DB 读取 app_id/app_secret
    adapter = XHSCouponAdapter(app_id="", app_secret="")
    try:
        result = await adapter.verify_and_record(
            coupon_code=body.coupon_code,
            store_id=body.store_id,
            order_id=body.order_id,
            verified_by=body.verified_by,
            tenant_id=x_tenant_id,
            db=db,
        )
        if result.get("verified"):
            await db.commit()
        return ok_response(result)
    except (ValueError, OSError, RuntimeError) as exc:
        return error_response(str(exc))


# ── 2. 核销记录列表 ─────────────────────────────────────────

@router.get("/api/v1/xhs/verifications")
async def list_verifications(
    store_id: str = Query(...),
    status: str = Query("verified"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    from shared.adapters.xiaohongshu.src.xhs_coupon_adapter import XHSCouponAdapter

    adapter = XHSCouponAdapter(app_id="", app_secret="")
    result = await adapter.list_verifications(
        store_id=store_id, tenant_id=x_tenant_id, db=db,
        status=status, page=page, size=size,
    )
    return ok_response(result)


# ── 3. 绑定门店 POI ─────────────────────────────────────────

@router.post("/api/v1/xhs/poi/bind")
async def bind_poi(
    body: BindPOIReq,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    tid = uuid.UUID(x_tenant_id)
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": x_tenant_id},
    )

    # UPSERT — 一店一POI
    await db.execute(
        text("""
            INSERT INTO xhs_poi_mappings
                (id, tenant_id, store_id, xhs_poi_id, xhs_shop_name,
                 sync_status, created_at, updated_at)
            VALUES
                (:id, :tid, :sid, :poi, :sname, 'pending', NOW(), NOW())
            ON CONFLICT (tenant_id, store_id)
            DO UPDATE SET
                xhs_poi_id = EXCLUDED.xhs_poi_id,
                xhs_shop_name = EXCLUDED.xhs_shop_name,
                sync_status = 'pending',
                updated_at = NOW()
        """),
        {
            "id": uuid.uuid4(), "tid": tid,
            "sid": uuid.UUID(body.store_id),
            "poi": body.xhs_poi_id,
            "sname": body.xhs_shop_name,
        },
    )
    await db.commit()
    return ok_response({
        "store_id": body.store_id,
        "xhs_poi_id": body.xhs_poi_id,
        "status": "bound",
    })


# ── 4. 查询POI绑定 ──────────────────────────────────────────

@router.get("/api/v1/xhs/poi/{store_id}")
async def get_poi_binding(
    store_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": x_tenant_id},
    )
    row = await db.execute(
        text("""
            SELECT xhs_poi_id, xhs_shop_name, sync_status, last_synced_at
            FROM xhs_poi_mappings
            WHERE tenant_id = :tid AND store_id = :sid AND is_deleted = false
        """),
        {"tid": uuid.UUID(x_tenant_id), "sid": uuid.UUID(store_id)},
    )
    mapping = row.fetchone()
    if not mapping:
        return error_response("poi_not_bound")
    return ok_response({
        "store_id": store_id,
        "xhs_poi_id": mapping.xhs_poi_id,
        "xhs_shop_name": mapping.xhs_shop_name,
        "sync_status": mapping.sync_status,
        "last_synced_at": mapping.last_synced_at.isoformat() if mapping.last_synced_at else None,
    })


# ── 5. 小红书 Webhook ────────────────────────────────────────

@router.post("/webhook/xhs")
async def xhs_webhook(request: Request) -> dict:
    """接收小红书回调：订单状态变更、退款通知"""
    payload = await request.json()
    event_type = payload.get("event_type", "unknown")

    logger.info("xhs.webhook_received", event_type=event_type)

    # TODO: 实现各事件类型的处理逻辑
    # - order_verified: 核销确认
    # - order_refunded: 退款通知 → 更新 xhs_coupon_verifications.status
    # - poi_updated: POI 信息变更

    return {"code": 0, "msg": "ok"}
