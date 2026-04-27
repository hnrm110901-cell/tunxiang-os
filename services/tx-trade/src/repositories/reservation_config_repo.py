"""预订配置 Repository — 包间/区域配置 + 时段配置 DB 操作"""

import uuid
from typing import Optional

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.reservation_config import ReservationConfig, ReservationTimeSlot


class ReservationConfigRepository:
    """预订配置数据访问层"""

    def __init__(self, db: AsyncSession, tenant_id: str):
        self.db = db
        self.tenant_id = uuid.UUID(tenant_id)

    # ─── 包间配置 ───

    async def list_rooms(
        self,
        store_id: str,
        active_only: bool = True,
    ) -> list[ReservationConfig]:
        """查询门店所有包间配置"""
        store_uuid = uuid.UUID(store_id)
        conditions = [
            ReservationConfig.tenant_id == self.tenant_id,
            ReservationConfig.store_id == store_uuid,
            ReservationConfig.is_deleted.is_(False),
        ]
        if active_only:
            conditions.append(ReservationConfig.is_active.is_(True))

        stmt = (
            select(ReservationConfig)
            .where(and_(*conditions))
            .order_by(ReservationConfig.sort_order, ReservationConfig.room_code)
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def get_room_by_id(self, room_id: str) -> Optional[ReservationConfig]:
        """根据ID查询包间配置"""
        stmt = select(ReservationConfig).where(
            and_(
                ReservationConfig.tenant_id == self.tenant_id,
                ReservationConfig.id == uuid.UUID(room_id),
                ReservationConfig.is_deleted.is_(False),
            )
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_room_by_code(self, store_id: str, room_code: str) -> Optional[ReservationConfig]:
        """根据编码查询包间配置"""
        store_uuid = uuid.UUID(store_id)
        stmt = select(ReservationConfig).where(
            and_(
                ReservationConfig.tenant_id == self.tenant_id,
                ReservationConfig.store_id == store_uuid,
                ReservationConfig.room_code == room_code,
                ReservationConfig.is_deleted.is_(False),
            )
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def create_room(self, **kwargs: object) -> ReservationConfig:
        """创建包间配置"""
        record = ReservationConfig(tenant_id=self.tenant_id, **kwargs)
        self.db.add(record)
        await self.db.flush()
        return record

    async def update_room(self, room_id: str, **kwargs: object) -> Optional[ReservationConfig]:
        """更新包间配置"""
        record = await self.get_room_by_id(room_id)
        if not record:
            return None
        for key, value in kwargs.items():
            if hasattr(record, key) and value is not None:
                setattr(record, key, value)
        await self.db.flush()
        return record

    async def soft_delete_room(self, room_id: str) -> bool:
        """软删除包间配置"""
        record = await self.get_room_by_id(room_id)
        if not record:
            return False
        record.is_deleted = True
        await self.db.flush()
        return True

    async def list_rooms_for_guests(
        self,
        store_id: str,
        guest_count: int,
    ) -> list[ReservationConfig]:
        """查询容纳指定人数的可用包间"""
        store_uuid = uuid.UUID(store_id)
        stmt = (
            select(ReservationConfig)
            .where(
                and_(
                    ReservationConfig.tenant_id == self.tenant_id,
                    ReservationConfig.store_id == store_uuid,
                    ReservationConfig.is_active.is_(True),
                    ReservationConfig.is_deleted.is_(False),
                    ReservationConfig.min_guests <= guest_count,
                    ReservationConfig.max_guests >= guest_count,
                )
            )
            .order_by(ReservationConfig.max_guests)
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    # ─── 时段配置 ───

    async def list_time_slots(
        self,
        store_id: str,
        active_only: bool = True,
    ) -> list[ReservationTimeSlot]:
        """查询门店所有时段配置"""
        store_uuid = uuid.UUID(store_id)
        conditions = [
            ReservationTimeSlot.tenant_id == self.tenant_id,
            ReservationTimeSlot.store_id == store_uuid,
            ReservationTimeSlot.is_deleted.is_(False),
        ]
        if active_only:
            conditions.append(ReservationTimeSlot.is_active.is_(True))

        stmt = (
            select(ReservationTimeSlot)
            .where(and_(*conditions))
            .order_by(ReservationTimeSlot.sort_order, ReservationTimeSlot.start_time)
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def get_time_slot_by_id(self, slot_id: str) -> Optional[ReservationTimeSlot]:
        """根据ID查询时段配置"""
        stmt = select(ReservationTimeSlot).where(
            and_(
                ReservationTimeSlot.tenant_id == self.tenant_id,
                ReservationTimeSlot.id == uuid.UUID(slot_id),
                ReservationTimeSlot.is_deleted.is_(False),
            )
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def create_time_slot(self, **kwargs: object) -> ReservationTimeSlot:
        """创建时段配置"""
        record = ReservationTimeSlot(tenant_id=self.tenant_id, **kwargs)
        self.db.add(record)
        await self.db.flush()
        return record

    async def update_time_slot(self, slot_id: str, **kwargs: object) -> Optional[ReservationTimeSlot]:
        """更新时段配置"""
        record = await self.get_time_slot_by_id(slot_id)
        if not record:
            return None
        for key, value in kwargs.items():
            if hasattr(record, key) and value is not None:
                setattr(record, key, value)
        await self.db.flush()
        return record

    async def count_reservations_in_slot(
        self,
        store_id: str,
        date: str,
        start_time_str: str,
        end_time_str: str,
    ) -> int:
        """统计某时段内的活跃预订数量（用于 max_reservations 检查）"""
        from ..models.reservation import Reservation

        store_uuid = uuid.UUID(store_id)
        stmt = (
            select(func.count())
            .select_from(Reservation)
            .where(
                and_(
                    Reservation.tenant_id == self.tenant_id,
                    Reservation.store_id == store_uuid,
                    Reservation.date == date,
                    Reservation.time >= start_time_str,
                    Reservation.time < end_time_str,
                    Reservation.status.notin_(["cancelled", "no_show", "completed"]),
                    Reservation.is_deleted.is_(False),
                )
            )
        )
        result = await self.db.execute(stmt)
        return result.scalar_one()
