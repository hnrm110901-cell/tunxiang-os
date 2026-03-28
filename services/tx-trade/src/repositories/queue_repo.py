"""排队 Repository — 封装所有DB操作"""
import uuid
from typing import Optional

from sqlalchemy import select, and_, func, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.queue import QueueEntry, QueueCounter


class QueueRepository:
    """排队数据访问层"""

    def __init__(self, db: AsyncSession, tenant_id: str):
        self.db = db
        self.tenant_id = uuid.UUID(tenant_id)

    async def create(self, **kwargs: object) -> QueueEntry:
        """创建排队记录"""
        record = QueueEntry(tenant_id=self.tenant_id, **kwargs)
        self.db.add(record)
        await self.db.flush()
        return record

    async def get_by_queue_id(self, queue_id: str) -> Optional[QueueEntry]:
        """根据业务ID查询"""
        stmt = select(QueueEntry).where(
            and_(
                QueueEntry.tenant_id == self.tenant_id,
                QueueEntry.queue_id == queue_id,
                QueueEntry.is_deleted.is_(False),
            )
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def list_by_store_date(
        self,
        store_id: str,
        date: str,
    ) -> list[QueueEntry]:
        """按门店+日期查询所有排队记录"""
        store_uuid = uuid.UUID(store_id)
        stmt = select(QueueEntry).where(
            and_(
                QueueEntry.tenant_id == self.tenant_id,
                QueueEntry.store_id == store_uuid,
                QueueEntry.date == date,
                QueueEntry.is_deleted.is_(False),
            )
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def list_waiting_by_prefix(
        self,
        store_id: str,
        date: str,
        prefix: str,
    ) -> list[QueueEntry]:
        """查询某桌型等待中的排队记录"""
        store_uuid = uuid.UUID(store_id)
        stmt = (
            select(QueueEntry)
            .where(
                and_(
                    QueueEntry.tenant_id == self.tenant_id,
                    QueueEntry.store_id == store_uuid,
                    QueueEntry.date == date,
                    QueueEntry.prefix == prefix,
                    QueueEntry.status == "waiting",
                    QueueEntry.is_deleted.is_(False),
                )
            )
            .order_by(QueueEntry.priority_ts)
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def count_waiting(self, store_id: str, date: str, prefix: str) -> int:
        """统计某桌型等待人数"""
        store_uuid = uuid.UUID(store_id)
        stmt = select(func.count()).select_from(QueueEntry).where(
            and_(
                QueueEntry.tenant_id == self.tenant_id,
                QueueEntry.store_id == store_uuid,
                QueueEntry.date == date,
                QueueEntry.prefix == prefix,
                QueueEntry.status == "waiting",
                QueueEntry.is_deleted.is_(False),
            )
        )
        result = await self.db.execute(stmt)
        return result.scalar_one()

    async def get_earliest_waiting_ts(
        self, store_id: str, date: str, prefix: str,
    ) -> Optional[str]:
        """获取某桌型最早等待者的priority_ts"""
        store_uuid = uuid.UUID(store_id)
        stmt = (
            select(QueueEntry.priority_ts)
            .where(
                and_(
                    QueueEntry.tenant_id == self.tenant_id,
                    QueueEntry.store_id == store_uuid,
                    QueueEntry.date == date,
                    QueueEntry.prefix == prefix,
                    QueueEntry.status == "waiting",
                    QueueEntry.is_deleted.is_(False),
                )
            )
            .order_by(QueueEntry.priority_ts)
            .limit(1)
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def find_existing_meituan(
        self, store_id: str, phone: str, date: str,
    ) -> Optional[QueueEntry]:
        """查找已同步的美团排队记录"""
        store_uuid = uuid.UUID(store_id)
        stmt = select(QueueEntry).where(
            and_(
                QueueEntry.tenant_id == self.tenant_id,
                QueueEntry.store_id == store_uuid,
                QueueEntry.phone == phone,
                QueueEntry.date == date,
                QueueEntry.source == "meituan",
                QueueEntry.is_deleted.is_(False),
            )
        ).limit(1)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def list_by_store_date_paged(
        self,
        store_id: str,
        date: str,
        offset: int,
        limit: int,
    ) -> tuple[list[QueueEntry], int]:
        """分页查询排队历史"""
        store_uuid = uuid.UUID(store_id)
        base_conditions = [
            QueueEntry.tenant_id == self.tenant_id,
            QueueEntry.store_id == store_uuid,
            QueueEntry.date == date,
            QueueEntry.is_deleted.is_(False),
        ]
        # 总数
        count_stmt = select(func.count()).select_from(QueueEntry).where(and_(*base_conditions))
        total = (await self.db.execute(count_stmt)).scalar_one()

        # 分页数据
        stmt = (
            select(QueueEntry)
            .where(and_(*base_conditions))
            .order_by(QueueEntry.taken_at)
            .offset(offset)
            .limit(limit)
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all()), total

    # ─── 计数器 ───

    async def get_or_create_counter(
        self, store_id: str, date: str, prefix: str,
    ) -> QueueCounter:
        """获取或创建当日计数器"""
        store_uuid = uuid.UUID(store_id)
        stmt = select(QueueCounter).where(
            and_(
                QueueCounter.tenant_id == self.tenant_id,
                QueueCounter.store_id == store_uuid,
                QueueCounter.date == date,
                QueueCounter.prefix == prefix,
            )
        )
        result = await self.db.execute(stmt)
        counter = result.scalar_one_or_none()
        if counter is None:
            counter = QueueCounter(
                tenant_id=self.tenant_id,
                store_id=store_uuid,
                date=date,
                prefix=prefix,
                last_number=0,
            )
            self.db.add(counter)
            await self.db.flush()
        return counter

    async def increment_counter(self, counter: QueueCounter) -> int:
        """递增计数器并返回新值"""
        counter.last_number += 1
        await self.db.flush()
        return counter.last_number
