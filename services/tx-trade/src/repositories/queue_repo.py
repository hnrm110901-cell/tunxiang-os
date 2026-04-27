"""排队 Repository — 封装所有DB操作

修复:
  - [RACE CONDITION] increment_counter 改用 UPDATE ... SET last_number = last_number + 1
    RETURNING last_number，避免并发取号时的竞态条件
  - [PAGINATION] list_by_store_date 增加 LIMIT 保护（看板场景仍需当日全量，但加上限）
  - [STATS] 新增 get_stats_by_store_date 用 SQL 聚合替代内存统计
"""

import uuid
from typing import Optional

from sqlalchemy import and_, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.queue import QueueCounter, QueueEntry


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
        """按门店+日期查询所有排队记录

        注意: 看板场景需要当日全量数据，但加 LIMIT 2000 防止极端情况。
        单店单日排队量超 2000 已属异常。
        """
        store_uuid = uuid.UUID(store_id)
        stmt = (
            select(QueueEntry)
            .where(
                and_(
                    QueueEntry.tenant_id == self.tenant_id,
                    QueueEntry.store_id == store_uuid,
                    QueueEntry.date == date,
                    QueueEntry.is_deleted.is_(False),
                )
            )
            .limit(2000)
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
        stmt = (
            select(func.count())
            .select_from(QueueEntry)
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
        )
        result = await self.db.execute(stmt)
        return result.scalar_one()

    async def get_earliest_waiting_ts(
        self,
        store_id: str,
        date: str,
        prefix: str,
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
        self,
        store_id: str,
        phone: str,
        date: str,
    ) -> Optional[QueueEntry]:
        """查找已同步的美团排队记录"""
        store_uuid = uuid.UUID(store_id)
        stmt = (
            select(QueueEntry)
            .where(
                and_(
                    QueueEntry.tenant_id == self.tenant_id,
                    QueueEntry.store_id == store_uuid,
                    QueueEntry.phone == phone,
                    QueueEntry.date == date,
                    QueueEntry.source == "meituan",
                    QueueEntry.is_deleted.is_(False),
                )
            )
            .limit(1)
        )
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
            select(QueueEntry).where(and_(*base_conditions)).order_by(QueueEntry.taken_at).offset(offset).limit(limit)
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all()), total

    async def get_stats_by_store_date(
        self,
        store_id: str,
        date: str,
    ) -> dict:
        """用 SQL 聚合获取统计信息，避免拉取全量记录到内存

        修复说明: 原 get_queue_history 在分页查询之后又做了一次全表查询用于统计，
        现在用 SQL 聚合一次完成。

        Returns:
            {total, seated, skipped, cancelled, avg_wait_min}
        """
        store_uuid = uuid.UUID(store_id)
        base_conditions = and_(
            QueueEntry.tenant_id == self.tenant_id,
            QueueEntry.store_id == store_uuid,
            QueueEntry.date == date,
            QueueEntry.is_deleted.is_(False),
        )

        # 按状态分组计数
        status_stmt = (
            select(QueueEntry.status, func.count().label("cnt")).where(base_conditions).group_by(QueueEntry.status)
        )
        status_result = await self.db.execute(status_stmt)
        status_counts: dict[str, int] = {}
        total = 0
        for row in status_result:
            status_counts[row.status] = row.cnt
            total += row.cnt

        return {
            "total": total,
            "seated": status_counts.get("seated", 0),
            "skipped": status_counts.get("skipped", 0),
            "cancelled": status_counts.get("cancelled", 0),
            "waiting": status_counts.get("waiting", 0),
            "called": status_counts.get("called", 0),
        }

    # ─── 计数器 ───

    async def get_or_create_counter(
        self,
        store_id: str,
        date: str,
        prefix: str,
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
        """原子递增计数器并返回新值

        修复说明: 原实现 counter.last_number += 1 + flush 存在并发竞态条件。
        两个并发取号可能读到同一个 last_number 值。
        改用 UPDATE ... SET last_number = last_number + 1 + RETURNING 保证原子性。
        """
        stmt = (
            update(QueueCounter)
            .where(QueueCounter.id == counter.id)
            .values(last_number=QueueCounter.last_number + 1)
            .returning(QueueCounter.last_number)
        )
        result = await self.db.execute(stmt)
        new_val = result.scalar_one()
        # 同步 ORM 对象的属性
        counter.last_number = new_val
        return new_val
