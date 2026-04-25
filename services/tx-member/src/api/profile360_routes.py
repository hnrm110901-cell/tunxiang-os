"""360° 会员画像 API — 企微侧边栏一站式数据入口

前缀: /api/v1/member/profile360

端点:
  GET  /by-wecom/{external_userid}     通过企微ID查360画像(侧边栏主入口)
  GET  /by-phone/{phone}               通过手机号查(到店识别)
  GET  /by-card/{card_no}              通过卡号查(扫码)
  GET  /{customer_id}                  通过customer_id查
  GET  /{customer_id}/consumption      消费明细(分页)
  GET  /{customer_id}/dish-preferences 菜品偏好详情
  GET  /{customer_id}/coupons          可用券列表
  POST /{customer_id}/send-coupon      1v1发券
  GET  /{customer_id}/coupon-sends     发券历史
  GET  /stats/employee/{employee_id}   员工发券统计
  GET  /stats/store/{store_id}         门店发券统计
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from services.profile360_service import Profile360Service
from shared.ontology.src.database import get_db

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/member/profile360", tags=["profile360"])

_service = Profile360Service()


# ─── 请求模型 ────────────────────────────────────────────────


class SendCouponRequest(BaseModel):
    employee_id: str = Field(..., description="发券员工ID")
    store_id: Optional[str] = Field(None, description="门店ID")
    coupon_batch_id: Optional[str] = Field(None, description="优惠券批次ID")
    coupon_instance_id: Optional[str] = Field(None, description="优惠券实例ID")
    coupon_name: str = Field("", max_length=200, description="优惠券名称")
    discount_desc: str = Field("", max_length=200, description="折扣描述(如满100减20)")
    channel: str = Field("wecom_sidebar", description="发放渠道")


# ─── 辅助函数 ────────────────────────────────────────────────


def _require_tenant(x_tenant_id: Optional[str]) -> str:
    if not x_tenant_id:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header is required")
    try:
        uuid.UUID(x_tenant_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="X-Tenant-ID must be a valid UUID")
    return x_tenant_id


async def _set_rls(db: AsyncSession, tenant_id: str) -> None:
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": tenant_id},
    )


# ─── 画像查询端点 ────────────────────────────────────────────


@router.get("/by-wecom/{external_userid}")
async def get_profile_by_wecom(
    external_userid: str,
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """通过企微 external_userid 查询360画像(侧边栏主入口)"""
    tenant_id = _require_tenant(x_tenant_id)
    log = logger.bind(tenant_id=tenant_id, external_userid=external_userid)
    log.info("profile360_by_wecom")

    await _set_rls(db, tenant_id)
    try:
        profile = await _service.get_profile_by_wecom(tenant_id, external_userid, db)
    except SQLAlchemyError as exc:
        log.error("profile360_by_wecom_error", error=str(exc))
        raise HTTPException(status_code=500, detail="db_error")

    if profile is None:
        raise HTTPException(status_code=404, detail="customer_not_found")

    return {"ok": True, "data": profile}


@router.get("/by-phone/{phone}")
async def get_profile_by_phone(
    phone: str,
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """通过手机号查询360画像(到店识别)"""
    tenant_id = _require_tenant(x_tenant_id)
    log = logger.bind(tenant_id=tenant_id)
    log.info("profile360_by_phone")

    await _set_rls(db, tenant_id)
    try:
        profile = await _service.get_profile_by_phone(tenant_id, phone, db)
    except SQLAlchemyError as exc:
        log.error("profile360_by_phone_error", error=str(exc))
        raise HTTPException(status_code=500, detail="db_error")

    if profile is None:
        raise HTTPException(status_code=404, detail="customer_not_found")

    return {"ok": True, "data": profile}


@router.get("/by-card/{card_no}")
async def get_profile_by_card(
    card_no: str,
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """通过会员卡号查询360画像(扫码场景)"""
    tenant_id = _require_tenant(x_tenant_id)
    log = logger.bind(tenant_id=tenant_id)
    log.info("profile360_by_card")

    await _set_rls(db, tenant_id)
    try:
        profile = await _service.get_profile_by_card(tenant_id, card_no, db)
    except SQLAlchemyError as exc:
        log.error("profile360_by_card_error", error=str(exc))
        raise HTTPException(status_code=500, detail="db_error")

    if profile is None:
        raise HTTPException(status_code=404, detail="customer_not_found")

    return {"ok": True, "data": profile}


@router.get("/{customer_id}")
async def get_profile_by_id(
    customer_id: str,
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """通过 customer_id 查询360画像"""
    tenant_id = _require_tenant(x_tenant_id)
    log = logger.bind(tenant_id=tenant_id, customer_id=customer_id)
    log.info("profile360_by_id")

    await _set_rls(db, tenant_id)
    try:
        profile = await _service.get_full_profile(tenant_id, customer_id, db)
    except SQLAlchemyError as exc:
        log.error("profile360_by_id_error", error=str(exc))
        raise HTTPException(status_code=500, detail="db_error")

    if profile is None:
        raise HTTPException(status_code=404, detail="customer_not_found")

    return {"ok": True, "data": profile}


# ─── 消费明细 ────────────────────────────────────────────────


@router.get("/{customer_id}/consumption")
async def get_consumption_detail(
    customer_id: str,
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """消费明细(分页, 最近N笔订单详情)"""
    tenant_id = _require_tenant(x_tenant_id)

    await _set_rls(db, tenant_id)
    try:
        data = await _service.get_consumption_detail(tenant_id, customer_id, page, size, db)
    except SQLAlchemyError as exc:
        logger.error("profile360_consumption_error", error=str(exc), customer_id=customer_id)
        return {"ok": True, "data": {"items": [], "total": 0, "page": page, "size": size}}

    return {"ok": True, "data": data}


# ─── 菜品偏好 ────────────────────────────────────────────────


@router.get("/{customer_id}/dish-preferences")
async def get_dish_preferences(
    customer_id: str,
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """菜品偏好详情(全量)"""
    tenant_id = _require_tenant(x_tenant_id)

    await _set_rls(db, tenant_id)
    try:
        items = await _service.get_dish_preferences_full(tenant_id, customer_id, db)
    except SQLAlchemyError as exc:
        logger.error("profile360_dish_prefs_error", error=str(exc), customer_id=customer_id)
        return {"ok": True, "data": {"items": []}}

    return {"ok": True, "data": {"items": items}}


# ─── 可用券 ────────────────────────────────────────────────


@router.get("/{customer_id}/coupons")
async def get_customer_coupons(
    customer_id: str,
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """客户可用券列表"""
    tenant_id = _require_tenant(x_tenant_id)

    await _set_rls(db, tenant_id)
    try:
        items = await _service.get_customer_coupons(tenant_id, customer_id, db)
    except SQLAlchemyError as exc:
        logger.error("profile360_coupons_error", error=str(exc), customer_id=customer_id)
        return {"ok": True, "data": {"items": [], "total": 0}}

    return {"ok": True, "data": {"items": items, "total": len(items)}}


# ─── 1v1 发券 ────────────────────────────────────────────────


@router.post("/{customer_id}/send-coupon")
async def send_coupon(
    customer_id: str,
    body: SendCouponRequest,
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """1v1发券(记录日志到 coupon_send_logs)"""
    tenant_id = _require_tenant(x_tenant_id)
    log = logger.bind(tenant_id=tenant_id, customer_id=customer_id, employee_id=body.employee_id)
    log.info("profile360_send_coupon")

    await _set_rls(db, tenant_id)
    send_data = {
        "customer_id": customer_id,
        "employee_id": body.employee_id,
        "store_id": body.store_id,
        "coupon_batch_id": body.coupon_batch_id,
        "coupon_instance_id": body.coupon_instance_id,
        "coupon_name": body.coupon_name,
        "discount_desc": body.discount_desc,
        "channel": body.channel,
    }

    try:
        result = await _service.record_coupon_send(tenant_id, send_data, db)
    except SQLAlchemyError as exc:
        log.error("profile360_send_coupon_error", error=str(exc))
        raise HTTPException(status_code=500, detail="db_error")

    log.info("profile360_send_coupon_ok", send_id=result["send_id"])
    return {"ok": True, "data": result}


# ─── 发券历史 ────────────────────────────────────────────────


@router.get("/{customer_id}/coupon-sends")
async def get_coupon_sends(
    customer_id: str,
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """客户发券历史"""
    tenant_id = _require_tenant(x_tenant_id)

    await _set_rls(db, tenant_id)
    try:
        data = await _service.get_coupon_send_history(tenant_id, customer_id, page, size, db)
    except SQLAlchemyError as exc:
        logger.error("profile360_coupon_sends_error", error=str(exc), customer_id=customer_id)
        return {"ok": True, "data": {"items": [], "total": 0, "page": page, "size": size}}

    return {"ok": True, "data": data}


# ─── 员工发券统计 ────────────────────────────────────────────


@router.get("/stats/employee/{employee_id}")
async def get_employee_send_stats(
    employee_id: str,
    start_date: str = Query(..., description="开始日期 YYYY-MM-DD"),
    end_date: str = Query(..., description="结束日期 YYYY-MM-DD"),
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """员工发券统计(发放数/核销数/核销率/GMV)"""
    tenant_id = _require_tenant(x_tenant_id)

    await _set_rls(db, tenant_id)
    try:
        data = await _service.get_employee_send_stats(tenant_id, employee_id, start_date, end_date, db)
    except SQLAlchemyError as exc:
        logger.error("profile360_employee_stats_error", error=str(exc), employee_id=employee_id)
        return {"ok": True, "data": {"employee_id": employee_id, "total_sent": 0, "total_used": 0, "use_rate": 0.0, "total_revenue_fen": 0}}

    return {"ok": True, "data": data}


# ─── 门店发券统计 ────────────────────────────────────────────


@router.get("/stats/store/{store_id}")
async def get_store_send_stats(
    store_id: str,
    start_date: str = Query(..., description="开始日期 YYYY-MM-DD"),
    end_date: str = Query(..., description="结束日期 YYYY-MM-DD"),
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """门店发券统计"""
    tenant_id = _require_tenant(x_tenant_id)

    await _set_rls(db, tenant_id)
    try:
        data = await _service.get_store_send_stats(tenant_id, store_id, start_date, end_date, db)
    except SQLAlchemyError as exc:
        logger.error("profile360_store_stats_error", error=str(exc), store_id=store_id)
        return {"ok": True, "data": {"store_id": store_id, "total_sent": 0, "total_used": 0, "use_rate": 0.0, "total_revenue_fen": 0}}

    return {"ok": True, "data": data}
