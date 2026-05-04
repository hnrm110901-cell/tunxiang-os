"""活码拉新引擎 API — 活码CRUD/扫码/统计/门店绑定

15个端点：
  CRUD (5):
    POST   /                        创建活码
    GET    /                        活码列表（分页+筛选）
    GET    /{id}                    活码详情
    PUT    /{id}                    更新活码
    DELETE /{id}                    删除活码

  Lifecycle (2):
    PUT    /{id}/pause              暂停活码
    PUT    /{id}/resume             恢复活码

  Scan (1):
    POST   /{id}/scan               扫码处理

  Stats (2):
    GET    /stats/overview          概览统计（多维）
    GET    /stats/channels          渠道统计（分页）

  Store Bindings (3):
    POST   /{id}/store-bindings     绑定门店
    DELETE /{id}/store-bindings/{store_id}  解绑门店
    GET    /{id}/store-bindings     门店绑定列表

  QR (1):
    GET    /{id}/qr-image           获取二维码图片URL
"""

import uuid
from datetime import date, datetime
from typing import Any, Optional

import structlog
from fastapi import APIRouter, Header
from pydantic import BaseModel
from services.live_code_service import LiveCodeError, LiveCodeService

from shared.ontology.src.database import async_session_factory

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/growth/live-codes", tags=["live-codes"])

_svc = LiveCodeService()


# ---------------------------------------------------------------------------
# 统一响应
# ---------------------------------------------------------------------------


def ok_response(data: Any) -> dict:
    return {"ok": True, "data": data}


def error_response(msg: str, code: str = "ERROR") -> dict:
    return {"ok": False, "error": {"code": code, "message": msg}}


# ---------------------------------------------------------------------------
# 请求模型
# ---------------------------------------------------------------------------


class CreateLiveCodeRequest(BaseModel):
    code_name: str
    code_type: str = "member"
    store_id: Optional[str] = None
    wecom_config_id: Optional[str] = None
    welcome_msg: Optional[str] = None
    welcome_media_url: Optional[str] = None
    target_group_ids: Optional[list] = None
    lbs_radius_meters: int = 3000
    daily_add_limit: int = 200
    total_add_limit: Optional[int] = None
    auto_tag_ids: Optional[list] = None
    channel_source: Optional[str] = None
    qr_image_url: Optional[str] = None
    expires_at: Optional[datetime] = None
    created_by: str


class UpdateLiveCodeRequest(BaseModel):
    code_name: Optional[str] = None
    welcome_msg: Optional[str] = None
    welcome_media_url: Optional[str] = None
    target_group_ids: Optional[list] = None
    lbs_radius_meters: Optional[int] = None
    daily_add_limit: Optional[int] = None
    total_add_limit: Optional[int] = None
    auto_tag_ids: Optional[list] = None
    channel_source: Optional[str] = None
    qr_image_url: Optional[str] = None
    expires_at: Optional[datetime] = None


class ScanRequest(BaseModel):
    customer_id: Optional[str] = None
    wecom_external_userid: Optional[str] = None
    scan_source: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    device_info: Optional[dict] = None


class BindStoreRequest(BaseModel):
    store_id: str
    group_chat_id: Optional[str] = None
    wecom_userid: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None


# ---------------------------------------------------------------------------
# CRUD 端点
# ---------------------------------------------------------------------------


@router.post("")
async def create_live_code(
    req: CreateLiveCodeRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """创建活码"""
    async with async_session_factory() as db:
        from sqlalchemy import text

        await db.execute(text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": x_tenant_id})
        try:
            result = await _svc.create_live_code(
                tenant_id=uuid.UUID(x_tenant_id),
                code_name=req.code_name,
                code_type=req.code_type,
                created_by=uuid.UUID(req.created_by),
                db=db,
                store_id=uuid.UUID(req.store_id) if req.store_id else None,
                wecom_config_id=uuid.UUID(req.wecom_config_id) if req.wecom_config_id else None,
                welcome_msg=req.welcome_msg,
                welcome_media_url=req.welcome_media_url,
                target_group_ids=req.target_group_ids,
                lbs_radius_meters=req.lbs_radius_meters,
                daily_add_limit=req.daily_add_limit,
                total_add_limit=req.total_add_limit,
                auto_tag_ids=req.auto_tag_ids,
                channel_source=req.channel_source,
                qr_image_url=req.qr_image_url,
                expires_at=req.expires_at,
            )
            await db.commit()
            return ok_response(result)
        except LiveCodeError as exc:
            return error_response(exc.message, exc.code)


@router.get("")
async def list_live_codes(
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    store_id: Optional[str] = None,
    code_type: Optional[str] = None,
    status: Optional[str] = None,
    channel_source: Optional[str] = None,
    page: int = 1,
    size: int = 20,
) -> dict:
    """活码列表"""
    async with async_session_factory() as db:
        from sqlalchemy import text

        await db.execute(text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": x_tenant_id})
        result = await _svc.list_live_codes(
            tenant_id=uuid.UUID(x_tenant_id),
            db=db,
            store_id=uuid.UUID(store_id) if store_id else None,
            code_type=code_type,
            status=status,
            channel_source=channel_source,
            page=page,
            size=size,
        )
        return ok_response(result)


@router.get("/{code_id}")
async def get_live_code(
    code_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """活码详情"""
    async with async_session_factory() as db:
        from sqlalchemy import text

        await db.execute(text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": x_tenant_id})
        try:
            result = await _svc.get_live_code(uuid.UUID(x_tenant_id), uuid.UUID(code_id), db)
            return ok_response(result)
        except LiveCodeError as exc:
            return error_response(exc.message, exc.code)


@router.put("/{code_id}")
async def update_live_code(
    code_id: str,
    req: UpdateLiveCodeRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """更新活码"""
    async with async_session_factory() as db:
        from sqlalchemy import text

        await db.execute(text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": x_tenant_id})
        try:
            updates = req.model_dump(exclude_none=True)
            result = await _svc.update_live_code(uuid.UUID(x_tenant_id), uuid.UUID(code_id), updates, db)
            await db.commit()
            return ok_response(result)
        except LiveCodeError as exc:
            return error_response(exc.message, exc.code)


@router.delete("/{code_id}")
async def delete_live_code(
    code_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """删除活码"""
    async with async_session_factory() as db:
        from sqlalchemy import text

        await db.execute(text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": x_tenant_id})
        try:
            result = await _svc.delete_live_code(uuid.UUID(x_tenant_id), uuid.UUID(code_id), db)
            await db.commit()
            return ok_response(result)
        except LiveCodeError as exc:
            return error_response(exc.message, exc.code)


# ---------------------------------------------------------------------------
# Lifecycle 端点
# ---------------------------------------------------------------------------


@router.put("/{code_id}/pause")
async def pause_live_code(
    code_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """暂停活码"""
    async with async_session_factory() as db:
        from sqlalchemy import text

        await db.execute(text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": x_tenant_id})
        try:
            result = await _svc.pause_live_code(uuid.UUID(x_tenant_id), uuid.UUID(code_id), db)
            await db.commit()
            return ok_response(result)
        except LiveCodeError as exc:
            return error_response(exc.message, exc.code)


@router.put("/{code_id}/resume")
async def resume_live_code(
    code_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """恢复活码"""
    async with async_session_factory() as db:
        from sqlalchemy import text

        await db.execute(text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": x_tenant_id})
        try:
            result = await _svc.resume_live_code(uuid.UUID(x_tenant_id), uuid.UUID(code_id), db)
            await db.commit()
            return ok_response(result)
        except LiveCodeError as exc:
            return error_response(exc.message, exc.code)


# ---------------------------------------------------------------------------
# Scan 端点
# ---------------------------------------------------------------------------


@router.post("/{code_id}/scan")
async def scan_live_code(
    code_id: str,
    req: ScanRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """处理扫码请求"""
    async with async_session_factory() as db:
        from sqlalchemy import text

        await db.execute(text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": x_tenant_id})
        try:
            result = await _svc.process_scan(
                tenant_id=uuid.UUID(x_tenant_id),
                code_id=uuid.UUID(code_id),
                db=db,
                customer_id=uuid.UUID(req.customer_id) if req.customer_id else None,
                wecom_external_userid=req.wecom_external_userid,
                scan_source=req.scan_source,
                latitude=req.latitude,
                longitude=req.longitude,
                device_info=req.device_info,
            )
            await db.commit()
            return ok_response(result)
        except LiveCodeError as exc:
            return error_response(exc.message, exc.code)


# ---------------------------------------------------------------------------
# Stats 端点
# ---------------------------------------------------------------------------


@router.get("/stats/overview")
async def get_overview_stats(
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    group_by: str = "date",
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    store_id: Optional[str] = None,
) -> dict:
    """概览统计"""
    async with async_session_factory() as db:
        from sqlalchemy import text

        await db.execute(text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": x_tenant_id})
        result = await _svc.get_overview_stats(
            tenant_id=uuid.UUID(x_tenant_id),
            db=db,
            group_by=group_by,
            date_from=date.fromisoformat(date_from) if date_from else None,
            date_to=date.fromisoformat(date_to) if date_to else None,
            store_id=uuid.UUID(store_id) if store_id else None,
        )
        return ok_response(result)


@router.get("/stats/channels")
async def get_channel_stats(
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    code_id: Optional[str] = None,
    store_id: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    page: int = 1,
    size: int = 20,
) -> dict:
    """渠道统计"""
    async with async_session_factory() as db:
        from sqlalchemy import text

        await db.execute(text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": x_tenant_id})
        result = await _svc.get_channel_stats(
            tenant_id=uuid.UUID(x_tenant_id),
            db=db,
            code_id=uuid.UUID(code_id) if code_id else None,
            store_id=uuid.UUID(store_id) if store_id else None,
            date_from=date.fromisoformat(date_from) if date_from else None,
            date_to=date.fromisoformat(date_to) if date_to else None,
            page=page,
            size=size,
        )
        return ok_response(result)


# ---------------------------------------------------------------------------
# Store Bindings 端点
# ---------------------------------------------------------------------------


@router.post("/{code_id}/store-bindings")
async def bind_store(
    code_id: str,
    req: BindStoreRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """绑定门店"""
    async with async_session_factory() as db:
        from sqlalchemy import text

        await db.execute(text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": x_tenant_id})
        try:
            result = await _svc.bind_store(
                tenant_id=uuid.UUID(x_tenant_id),
                code_id=uuid.UUID(code_id),
                store_id=uuid.UUID(req.store_id),
                db=db,
                group_chat_id=req.group_chat_id,
                wecom_userid=req.wecom_userid,
                latitude=req.latitude,
                longitude=req.longitude,
            )
            await db.commit()
            return ok_response(result)
        except LiveCodeError as exc:
            return error_response(exc.message, exc.code)


@router.delete("/{code_id}/store-bindings/{store_id}")
async def unbind_store(
    code_id: str,
    store_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """解绑门店"""
    async with async_session_factory() as db:
        from sqlalchemy import text

        await db.execute(text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": x_tenant_id})
        try:
            result = await _svc.unbind_store(
                uuid.UUID(x_tenant_id),
                uuid.UUID(code_id),
                uuid.UUID(store_id),
                db,
            )
            await db.commit()
            return ok_response(result)
        except LiveCodeError as exc:
            return error_response(exc.message, exc.code)


@router.get("/{code_id}/store-bindings")
async def list_store_bindings(
    code_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """门店绑定列表"""
    async with async_session_factory() as db:
        from sqlalchemy import text

        await db.execute(text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": x_tenant_id})
        result = await _svc.list_store_bindings(
            uuid.UUID(x_tenant_id),
            uuid.UUID(code_id),
            db,
        )
        return ok_response(result)


# ---------------------------------------------------------------------------
# QR Image 端点
# ---------------------------------------------------------------------------


@router.get("/{code_id}/qr-image")
async def get_qr_image(
    code_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """获取二维码图片URL"""
    async with async_session_factory() as db:
        from sqlalchemy import text

        await db.execute(text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": x_tenant_id})
        try:
            code = await _svc.get_live_code(uuid.UUID(x_tenant_id), uuid.UUID(code_id), db)
            return ok_response({"qr_image_url": code.get("qr_image_url")})
        except LiveCodeError as exc:
            return error_response(exc.message, exc.code)
