"""预订 Repository — 封装所有DB操作

修复:
  - [PAGINATION] list_by_store 增加分页支持，防止全表扫描
  - [PAGINATION] list_by_date_range 增加 LIMIT 上限保护
"""
import uuid
from typing import Optional

from sqlalchemy import select, and_, func
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.reservation import Reservation, NoShowRecord


class ReservationRepository:
    """预订数据访问层"""

    def __init__(self, db: AsyncSession, tenant_id: str):
        self.db = db
        self.tenant_id = uuid.UUID(tenant_id)

    async def create(self, **kwargs: object) -> Reservation:
        """创建预订记录"""
        record = Reservation(tenant_id=self.tenant_id, **kwargs)
        self.db.add(record)
        await self.db.flush()
        return record

    async def get_by_reservation_id(self, reservation_id: str) -> Optional[Reservation]:
        """根据业务ID查询"""
        stmt = select(Reservation).where(
            and_(
                Reservation.tenant_id == self.tenant_id,
                Reservation.reservation_id == reservation_id,
                Reservation.is_deleted.is_(False),
            )
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def list_by_store_paged(
        self,
        store_id: str,
        date: Optional[str] = None,
        status: Optional[str] = None,
        type: Optional[str] = None,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[list[Reservation], int]:
        """按门店查询预订列表（分页）

        修复说明: 原 list_by_store 无分页，当预订量大时会全表扫描。
        返回 (records, total_count)。
        """
        store_uuid = uuid.UUID(store_id)
        conditions = [
            Reservation.tenant_id == self.tenant_id,
            Reservation.store_id == store_uuid,
            Reservation.is_deleted.is_(False),
        ]
        if date:
            conditions.append(Reservation.date == date)
        if status:
            conditions.append(Reservation.status == status)
        if type:
            conditions.append(Reservation.type == type)

        # 总数
        count_stmt = select(func.count()).select_from(Reservation).where(and_(*conditions))
        total = (await self.db.execute(count_stmt)).scalar_one()

        # 分页数据
        stmt = (
            select(Reservation)
            .where(and_(*conditions))
            .order_by(Reservation.date, Reservation.time)
            .offset(offset)
            .limit(limit)
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all()), total

    async def list_by_store_date_active(
        self,
        store_id: str,
        date: str,
    ) -> list[Reservation]:
        """查询某天有效预订（排除已取消/爽约/已完成）"""
        store_uuid = uuid.UUID(store_id)
        stmt = select(Reservation).where(
            and_(
                Reservation.tenant_id == self.tenant_id,
                Reservation.store_id == store_uuid,
                Reservation.date == date,
                Reservation.status.notin_(["cancelled", "no_show", "completed"]),
                Reservation.is_deleted.is_(False),
            )
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def list_by_date_range(
        self,
        store_id: str,
        start_date: str,
        end_date: str,
    ) -> list[Reservation]:
        """按日期范围查询

        注意: 统计场景使用，已加 LIMIT 1000 防止极端情况下拉取过多记录。
        如需更大范围，应使用 SQL 聚合而非内存统计。
        """
        store_uuid = uuid.UUID(store_id)
        stmt = (
            select(Reservation)
            .where(
                and_(
                    Reservation.tenant_id == self.tenant_id,
                    Reservation.store_id == store_uuid,
                    Reservation.date >= start_date,
                    Reservation.date <= end_date,
                    Reservation.is_deleted.is_(False),
                )
            )
            .limit(1000)
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def add_no_show_record(self, phone: str, reservation_id: str) -> None:
        """添加爽约记录"""
        record = NoShowRecord(
            tenant_id=self.tenant_id,
            phone=phone,
            reservation_id=reservation_id,
        )
        self.db.add(record)
        await self.db.flush()

    async def count_no_shows(self, phone: str) -> int:
        """统计某手机号爽约次数"""
        stmt = select(func.count()).select_from(NoShowRecord).where(
            and_(
                NoShowRecord.tenant_id == self.tenant_id,
                NoShowRecord.phone == phone,
                NoShowRecord.is_deleted.is_(False),
            )
        )
        result = await self.db.execute(stmt)
        return result.scalar_one()
