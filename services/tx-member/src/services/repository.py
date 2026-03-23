"""会员 Repository — 真实 DB 查询层

封装 Customer 的 CRUD + RFM 分析查询。
"""
import uuid
from typing import Optional

from sqlalchemy import select, func, case, text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.entities import Customer, Order


class CustomerRepository:
    """会员 Repository — 封装真实 DB 查询"""

    def __init__(self, db: AsyncSession, tenant_id: str):
        self.db = db
        self.tenant_id = tenant_id
        self._tenant_uuid = uuid.UUID(tenant_id)

    async def _set_tenant(self) -> None:
        await self.db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": self.tenant_id},
        )

    # ─── 会员 CRUD ───

    async def list_customers(
        self,
        store_id: str,
        rfm_level: Optional[str] = None,
        page: int = 1,
        size: int = 20,
    ) -> dict:
        """分页查询会员列表，可按 RFM 等级筛选"""
        await self._set_tenant()

        base = (
            select(Customer)
            .where(Customer.tenant_id == self._tenant_uuid)
            .where(Customer.is_deleted == False)  # noqa: E712
            .where(Customer.is_merged == False)  # noqa: E712
        )
        count_base = (
            select(func.count(Customer.id))
            .where(Customer.tenant_id == self._tenant_uuid)
            .where(Customer.is_deleted == False)  # noqa: E712
            .where(Customer.is_merged == False)  # noqa: E712
        )

        if rfm_level:
            base = base.where(Customer.rfm_level == rfm_level)
            count_base = count_base.where(Customer.rfm_level == rfm_level)

        total_result = await self.db.execute(count_base)
        total = total_result.scalar() or 0

        offset = (page - 1) * size
        query = base.order_by(Customer.last_order_at.desc().nullslast()).offset(offset).limit(size)
        result = await self.db.execute(query)
        rows = result.scalars().all()

        items = [self._customer_to_dict(c) for c in rows]
        return {"items": items, "total": total, "page": page, "size": size}

    async def get_customer(self, customer_id: str) -> Optional[dict]:
        """查询单个会员 360 度画像"""
        await self._set_tenant()

        result = await self.db.execute(
            select(Customer)
            .where(Customer.id == uuid.UUID(customer_id))
            .where(Customer.tenant_id == self._tenant_uuid)
            .where(Customer.is_deleted == False)  # noqa: E712
        )
        customer = result.scalar_one_or_none()
        if not customer:
            return None
        return self._customer_to_dict(customer)

    async def create_customer(self, data: dict) -> dict:
        """创建会员"""
        await self._set_tenant()

        customer = Customer(
            id=uuid.uuid4(),
            tenant_id=self._tenant_uuid,
            primary_phone=data["phone"],
            display_name=data.get("display_name"),
            gender=data.get("gender"),
            source=data.get("source", "manual"),
            tags=data.get("tags", []),
            rfm_level="S3",  # 新会员默认 S3
        )
        self.db.add(customer)
        await self.db.flush()
        return self._customer_to_dict(customer)

    # ─── RFM 分析 ───

    async def get_rfm_segments(self, store_id: str) -> dict:
        """获取 RFM 分层分布统计"""
        await self._set_tenant()

        result = await self.db.execute(
            select(
                Customer.rfm_level,
                func.count(Customer.id).label("count"),
            )
            .where(Customer.tenant_id == self._tenant_uuid)
            .where(Customer.is_deleted == False)  # noqa: E712
            .where(Customer.is_merged == False)  # noqa: E712
            .group_by(Customer.rfm_level)
        )
        rows = result.all()

        segments = {}
        total = 0
        for row in rows:
            level = row[0] or "S3"
            count = row[1]
            segments[level] = count
            total += count

        return {
            "segments": segments,
            "total": total,
        }

    async def get_at_risk(self, store_id: str, threshold: float = 0.5) -> list:
        """获取流失风险客户列表

        筛选条件：RFM level >= S4（低活跃），且最近消费距今天数超过 threshold 对应的天数。
        threshold=0.5 对应 rfm_recency_days >= 60。
        """
        await self._set_tenant()

        recency_threshold = int(threshold * 120)  # 0.5 -> 60 天

        result = await self.db.execute(
            select(Customer)
            .where(Customer.tenant_id == self._tenant_uuid)
            .where(Customer.is_deleted == False)  # noqa: E712
            .where(Customer.is_merged == False)  # noqa: E712
            .where(Customer.rfm_recency_days >= recency_threshold)
            .order_by(Customer.rfm_recency_days.desc())
            .limit(50)
        )
        rows = result.scalars().all()

        return [
            {
                "id": str(c.id),
                "display_name": c.display_name,
                "primary_phone": c.primary_phone,
                "rfm_level": c.rfm_level,
                "rfm_recency_days": c.rfm_recency_days,
                "last_order_at": c.last_order_at.isoformat() if c.last_order_at else None,
                "total_order_count": c.total_order_count,
                "total_order_amount_fen": c.total_order_amount_fen,
            }
            for c in rows
        ]

    # ─── 内部工具 ───

    @staticmethod
    def _customer_to_dict(c: Customer) -> dict:
        return {
            "id": str(c.id),
            "primary_phone": c.primary_phone,
            "display_name": c.display_name,
            "gender": c.gender,
            "source": c.source,
            "rfm_level": c.rfm_level,
            "rfm_recency_days": c.rfm_recency_days,
            "rfm_frequency": c.rfm_frequency,
            "rfm_monetary_fen": c.rfm_monetary_fen,
            "total_order_count": c.total_order_count,
            "total_order_amount_fen": c.total_order_amount_fen,
            "first_order_at": c.first_order_at.isoformat() if c.first_order_at else None,
            "last_order_at": c.last_order_at.isoformat() if c.last_order_at else None,
            "tags": c.tags,
            "wechat_nickname": c.wechat_nickname,
            "created_at": c.created_at.isoformat() if c.created_at else None,
        }
