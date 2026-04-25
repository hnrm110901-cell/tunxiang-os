"""预订配置管理 API — 包间/区域 + 时段配置（DB驱动，v345）

路由注册（在 main.py 中添加）:
    from .api.reservation_config_routes import router as reservation_config_router
    app.include_router(reservation_config_router, prefix="/api/v1/reservation")

所有接口需 X-Tenant-ID + X-Store-ID header。
统一响应格式: {"ok": bool, "data": {}, "error": {}}
"""

from __future__ import annotations

import logging
import uuid
from datetime import time as dt_time
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

from ..repositories.reservation_config_repo import ReservationConfigRepository
from ..services.reservation_service import ReservationService

logger = logging.getLogger(__name__)

router = APIRouter(tags=["reservation-config"])


# ─── 辅助函数 ────────────────────────────────────────────────────────────────


def _get_tenant_id(request: Request) -> str:
    return request.headers.get("X-Tenant-ID", "")


def _get_store_id(request: Request) -> str:
    return request.headers.get("X-Store-ID", "")


def _ok(data: object) -> dict:
    return {"ok": True, "data": data}


def _err(msg: str, code: int = 400) -> None:
    raise HTTPException(status_code=code, detail={"ok": False, "error": {"message": msg}})


async def _set_tenant(db: AsyncSession, tenant_id: str) -> None:
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": str(tenant_id)},
    )


def _parse_time(time_str: str) -> dt_time:
    """解析 HH:MM 格式的时间字符串"""
    parts = time_str.split(":")
    if len(parts) != 2:
        raise ValueError(f"Invalid time format: {time_str}, expected HH:MM")
    return dt_time(int(parts[0]), int(parts[1]))


# ─── Request Models ──────────────────────────────────────────────────────────


class RoomCreateBody(BaseModel):
    store_id: str
    room_code: str = Field(..., max_length=50)
    room_name: str = Field(..., max_length=100)
    room_type: str = Field(default="private", pattern=r"^(private|hall|outdoor)$")
    min_guests: int = Field(default=2, ge=1)
    max_guests: int = Field(default=12, ge=1)
    deposit_fen: int = Field(default=0, ge=0)
    is_active: bool = True
    sort_order: int = 0

    @field_validator("max_guests")
    @classmethod
    def max_gte_min(cls, v: int, info) -> int:
        min_val = info.data.get("min_guests", 1)
        if v < min_val:
            raise ValueError("max_guests must be >= min_guests")
        return v


class RoomUpdateBody(BaseModel):
    room_name: Optional[str] = Field(default=None, max_length=100)
    room_type: Optional[str] = Field(default=None, pattern=r"^(private|hall|outdoor)$")
    min_guests: Optional[int] = Field(default=None, ge=1)
    max_guests: Optional[int] = Field(default=None, ge=1)
    deposit_fen: Optional[int] = Field(default=None, ge=0)
    is_active: Optional[bool] = None
    sort_order: Optional[int] = None


class TimeSlotCreateBody(BaseModel):
    store_id: str
    slot_name: str = Field(..., max_length=50)
    start_time: str = Field(..., pattern=r"^\d{2}:\d{2}$")
    end_time: str = Field(..., pattern=r"^\d{2}:\d{2}$")
    dining_duration_min: int = Field(default=120, ge=30, le=480)
    max_reservations: int = Field(default=0, ge=0)
    is_active: bool = True
    sort_order: int = 0


class TimeSlotUpdateBody(BaseModel):
    slot_name: Optional[str] = Field(default=None, max_length=50)
    start_time: Optional[str] = Field(default=None, pattern=r"^\d{2}:\d{2}$")
    end_time: Optional[str] = Field(default=None, pattern=r"^\d{2}:\d{2}$")
    dining_duration_min: Optional[int] = Field(default=None, ge=30, le=480)
    max_reservations: Optional[int] = Field(default=None, ge=0)
    is_active: Optional[bool] = None
    sort_order: Optional[int] = None


# ─── 包间配置端点 ─────────────────────────────────────────────────────────────


@router.get("/configs")
async def get_store_configs(
    request: Request,
    store_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """GET /api/v1/reservation/configs — 门店预订配置（包间 + 时段）"""
    tenant_id = _get_tenant_id(request)
    if not tenant_id:
        _err("缺少 X-Tenant-ID", 401)

    try:
        await _set_tenant(db, tenant_id)

        repo = ReservationConfigRepository(db, tenant_id)
        rooms = await repo.list_rooms(store_id, active_only=False)
        time_slots = await repo.list_time_slots(store_id, active_only=False)

        return _ok({
            "store_id": store_id,
            "rooms": [r.to_dict() for r in rooms],
            "time_slots": [s.to_dict() for s in time_slots],
        })
    except SQLAlchemyError as exc:
        logger.error("reservation_config_list_error", exc_info=True)
        _err("查询预订配置失败", 500)


@router.post("/configs/rooms")
async def create_room(
    body: RoomCreateBody,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """POST /api/v1/reservation/configs/rooms — 新增包间"""
    tenant_id = _get_tenant_id(request)
    if not tenant_id:
        _err("缺少 X-Tenant-ID", 401)

    try:
        await _set_tenant(db, tenant_id)

        repo = ReservationConfigRepository(db, tenant_id)

        # 检查 room_code 是否已存在
        existing = await repo.get_room_by_code(body.store_id, body.room_code)
        if existing:
            _err(f"包间编码 {body.room_code} 已存在")

        store_uuid = uuid.UUID(body.store_id)
        record = await repo.create_room(
            store_id=store_uuid,
            room_code=body.room_code,
            room_name=body.room_name,
            room_type=body.room_type,
            min_guests=body.min_guests,
            max_guests=body.max_guests,
            deposit_fen=body.deposit_fen,
            is_active=body.is_active,
            sort_order=body.sort_order,
        )
        await db.commit()

        logger.info(
            "reservation_room_created",
            room_code=body.room_code,
            store_id=body.store_id,
        )

        return _ok(record.to_dict())
    except HTTPException:
        raise
    except SQLAlchemyError as exc:
        await db.rollback()
        logger.error("reservation_room_create_error", exc_info=True)
        _err("创建包间配置失败", 500)


@router.put("/configs/rooms/{room_id}")
async def update_room(
    room_id: str,
    body: RoomUpdateBody,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """PUT /api/v1/reservation/configs/rooms/{id} — 更新包间"""
    tenant_id = _get_tenant_id(request)
    if not tenant_id:
        _err("缺少 X-Tenant-ID", 401)

    try:
        await _set_tenant(db, tenant_id)

        repo = ReservationConfigRepository(db, tenant_id)

        update_data = body.model_dump(exclude_none=True)
        if not update_data:
            _err("没有需要更新的字段")

        record = await repo.update_room(room_id, **update_data)
        if not record:
            _err("包间配置不存在", 404)

        await db.commit()

        logger.info(
            "reservation_room_updated",
            room_id=room_id,
            fields=list(update_data.keys()),
        )

        return _ok(record.to_dict())
    except HTTPException:
        raise
    except SQLAlchemyError as exc:
        await db.rollback()
        logger.error("reservation_room_update_error", exc_info=True)
        _err("更新包间配置失败", 500)


@router.delete("/configs/rooms/{room_id}")
async def delete_room(
    room_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """DELETE /api/v1/reservation/configs/rooms/{id} — 删除包间"""
    tenant_id = _get_tenant_id(request)
    if not tenant_id:
        _err("缺少 X-Tenant-ID", 401)

    try:
        await _set_tenant(db, tenant_id)

        repo = ReservationConfigRepository(db, tenant_id)

        deleted = await repo.soft_delete_room(room_id)
        if not deleted:
            _err("包间配置不存在", 404)

        await db.commit()

        logger.info("reservation_room_deleted", room_id=room_id)

        return _ok({"id": room_id, "deleted": True})
    except HTTPException:
        raise
    except SQLAlchemyError as exc:
        await db.rollback()
        logger.error("reservation_room_delete_error", exc_info=True)
        _err("删除包间配置失败", 500)


# ─── 时段配置端点 ─────────────────────────────────────────────────────────────


@router.get("/configs/time-slots")
async def list_time_slots(
    request: Request,
    store_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """GET /api/v1/reservation/configs/time-slots — 时段列表"""
    tenant_id = _get_tenant_id(request)
    if not tenant_id:
        _err("缺少 X-Tenant-ID", 401)

    try:
        await _set_tenant(db, tenant_id)

        repo = ReservationConfigRepository(db, tenant_id)
        slots = await repo.list_time_slots(store_id, active_only=False)

        return _ok({
            "store_id": store_id,
            "time_slots": [s.to_dict() for s in slots],
        })
    except SQLAlchemyError as exc:
        logger.error("reservation_time_slots_list_error", exc_info=True)
        _err("查询时段配置失败", 500)


@router.post("/configs/time-slots")
async def create_time_slot(
    body: TimeSlotCreateBody,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """POST /api/v1/reservation/configs/time-slots — 新增时段"""
    tenant_id = _get_tenant_id(request)
    if not tenant_id:
        _err("缺少 X-Tenant-ID", 401)

    try:
        await _set_tenant(db, tenant_id)

        start_t = _parse_time(body.start_time)
        end_t = _parse_time(body.end_time)

        if end_t <= start_t:
            _err("end_time 必须大于 start_time")

        repo = ReservationConfigRepository(db, tenant_id)

        store_uuid = uuid.UUID(body.store_id)
        record = await repo.create_time_slot(
            store_id=store_uuid,
            slot_name=body.slot_name,
            start_time=start_t,
            end_time=end_t,
            dining_duration_min=body.dining_duration_min,
            max_reservations=body.max_reservations,
            is_active=body.is_active,
            sort_order=body.sort_order,
        )
        await db.commit()

        logger.info(
            "reservation_time_slot_created",
            slot_name=body.slot_name,
            store_id=body.store_id,
        )

        return _ok(record.to_dict())
    except HTTPException:
        raise
    except SQLAlchemyError as exc:
        await db.rollback()
        logger.error("reservation_time_slot_create_error", exc_info=True)
        _err("创建时段配置失败", 500)


@router.put("/configs/time-slots/{slot_id}")
async def update_time_slot(
    slot_id: str,
    body: TimeSlotUpdateBody,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """PUT /api/v1/reservation/configs/time-slots/{id} — 更新时段"""
    tenant_id = _get_tenant_id(request)
    if not tenant_id:
        _err("缺少 X-Tenant-ID", 401)

    try:
        await _set_tenant(db, tenant_id)

        repo = ReservationConfigRepository(db, tenant_id)

        update_data = body.model_dump(exclude_none=True)
        if not update_data:
            _err("没有需要更新的字段")

        # 转换时间字符串为 time 对象
        if "start_time" in update_data:
            update_data["start_time"] = _parse_time(update_data["start_time"])
        if "end_time" in update_data:
            update_data["end_time"] = _parse_time(update_data["end_time"])

        record = await repo.update_time_slot(slot_id, **update_data)
        if not record:
            _err("时段配置不存在", 404)

        await db.commit()

        logger.info(
            "reservation_time_slot_updated",
            slot_id=slot_id,
            fields=list(update_data.keys()),
        )

        return _ok(record.to_dict())
    except HTTPException:
        raise
    except SQLAlchemyError as exc:
        await db.rollback()
        logger.error("reservation_time_slot_update_error", exc_info=True)
        _err("更新时段配置失败", 500)


# ─── 顾客查询可预订信息 ──────────────────────────────────────────────────────


@router.get("/available")
async def get_available(
    request: Request,
    store_id: str = Query(...),
    date: str = Query(..., pattern=r"^\d{4}-\d{2}-\d{2}$"),
    guest_count: int = Query(default=2, ge=1),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """GET /api/v1/reservation/available — 顾客查询可预订时段+包间

    返回指定门店、日期、人数下的可用包间和时段信息。
    """
    tenant_id = _get_tenant_id(request)
    if not tenant_id:
        _err("缺少 X-Tenant-ID", 401)

    try:
        await _set_tenant(db, tenant_id)

        svc = ReservationService(db=db, tenant_id=tenant_id, store_id=store_id)

        rooms = await svc.get_available_rooms(store_id, date, guest_count)
        time_slots = await svc.get_available_time_slots(store_id, date)

        return _ok({
            "store_id": store_id,
            "date": date,
            "guest_count": guest_count,
            "rooms": rooms,
            "time_slots": time_slots,
        })
    except ValueError as exc:
        _err(str(exc))
    except SQLAlchemyError as exc:
        logger.error("reservation_available_query_error", exc_info=True)
        _err("查询可预订信息失败", 500)
