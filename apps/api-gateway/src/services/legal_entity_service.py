"""
法人主体服务（Task 1）

职责：
  - 法人主体 CRUD
  - 门店-法人绑定（支持历史）
  - 查询门店在某一时点的生效主体（签合同/发薪/开票关键前置）
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import Any, Dict, List, Optional

import structlog
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.legal_entity import (
    LegalEntity,
    LegalEntityStatus,
    LegalEntityType,
    StoreLegalEntity,
)

logger = structlog.get_logger()


def _money_fen_to_yuan(fen: Optional[int]) -> Optional[float]:
    """分→元（保留 2 位）"""
    if fen is None:
        return None
    return round(fen / 100, 2)


class LegalEntityService:
    """法人主体服务"""

    @staticmethod
    async def create_entity(
        session: AsyncSession,
        *,
        code: str,
        name: str,
        entity_type: str = LegalEntityType.DIRECT_OPERATED.value,
        brand_id: Optional[str] = None,
        unified_social_credit: Optional[str] = None,
        legal_representative: Optional[str] = None,
        registered_address: Optional[str] = None,
        registered_capital_fen: Optional[int] = None,
        establish_date: Optional[date] = None,
        tax_number: Optional[str] = None,
        bank_name: Optional[str] = None,
        bank_account: Optional[str] = None,
        contact_phone: Optional[str] = None,
        remark: Optional[str] = None,
    ) -> LegalEntity:
        """新建法人主体"""
        entity = LegalEntity(
            id=uuid.uuid4(),
            code=code,
            name=name,
            entity_type=LegalEntityType(entity_type),
            brand_id=brand_id,
            unified_social_credit=unified_social_credit,
            legal_representative=legal_representative,
            registered_address=registered_address,
            registered_capital_fen=registered_capital_fen,
            establish_date=establish_date,
            tax_number=tax_number,
            bank_name=bank_name,
            bank_account=bank_account,
            contact_phone=contact_phone,
            remark=remark,
        )
        session.add(entity)
        await session.flush()
        logger.info("legal_entity.created", code=code, entity_id=str(entity.id))
        return entity

    @staticmethod
    async def bind_to_store(
        session: AsyncSession,
        *,
        entity_id: uuid.UUID,
        store_id: str,
        start_date: date,
        end_date: Optional[date] = None,
        is_primary: bool = True,
        remark: Optional[str] = None,
    ) -> StoreLegalEntity:
        """绑定门店到法人主体。

        如果 is_primary=True 且门店已有未结束的主绑定，先把旧绑定 end_date 置为 start_date-1。
        """
        if is_primary:
            existing = await session.execute(
                select(StoreLegalEntity).where(
                    and_(
                        StoreLegalEntity.store_id == store_id,
                        StoreLegalEntity.is_primary.is_(True),
                        StoreLegalEntity.end_date.is_(None),
                    )
                )
            )
            for old in existing.scalars().all():
                # 新绑定起日的前一天作为旧绑定结束日
                from datetime import timedelta

                old.end_date = start_date - timedelta(days=1)

        link = StoreLegalEntity(
            id=uuid.uuid4(),
            store_id=store_id,
            legal_entity_id=entity_id,
            start_date=start_date,
            end_date=end_date,
            is_primary=is_primary,
            remark=remark,
        )
        session.add(link)
        await session.flush()
        logger.info(
            "legal_entity.bound_to_store",
            entity_id=str(entity_id),
            store_id=store_id,
            start_date=str(start_date),
        )
        return link

    @staticmethod
    async def get_active_entity_for_store(
        session: AsyncSession,
        store_id: str,
        as_of_date: Optional[date] = None,
    ) -> Optional[Dict[str, Any]]:
        """查询门店在指定日期生效的主签约法人。"""
        as_of_date = as_of_date or date.today()
        q = select(StoreLegalEntity, LegalEntity).join(
            LegalEntity, LegalEntity.id == StoreLegalEntity.legal_entity_id
        ).where(
            and_(
                StoreLegalEntity.store_id == store_id,
                StoreLegalEntity.start_date <= as_of_date,
                or_(
                    StoreLegalEntity.end_date.is_(None),
                    StoreLegalEntity.end_date >= as_of_date,
                ),
                StoreLegalEntity.is_primary.is_(True),
            )
        ).order_by(StoreLegalEntity.start_date.desc())

        res = await session.execute(q)
        row = res.first()
        if not row:
            return None
        link, entity = row
        return LegalEntityService._entity_to_dict(entity, link=link)

    @staticmethod
    async def list_by_brand(
        session: AsyncSession,
        brand_id: Optional[str] = None,
        status: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """按品牌列举法人主体"""
        conds = []
        if brand_id:
            conds.append(LegalEntity.brand_id == brand_id)
        if status:
            conds.append(LegalEntity.status == LegalEntityStatus(status))
        q = select(LegalEntity)
        if conds:
            q = q.where(and_(*conds))
        q = q.order_by(LegalEntity.created_at.desc())
        res = await session.execute(q)
        return [LegalEntityService._entity_to_dict(e) for e in res.scalars().all()]

    @staticmethod
    def _entity_to_dict(entity: LegalEntity, link: Optional[StoreLegalEntity] = None) -> Dict[str, Any]:
        data = {
            "id": str(entity.id),
            "code": entity.code,
            "name": entity.name,
            "entity_type": entity.entity_type.value if entity.entity_type else None,
            "brand_id": entity.brand_id,
            "unified_social_credit": entity.unified_social_credit,
            "legal_representative": entity.legal_representative,
            "registered_address": entity.registered_address,
            "registered_capital_fen": entity.registered_capital_fen,
            "registered_capital_yuan": _money_fen_to_yuan(entity.registered_capital_fen),
            "establish_date": str(entity.establish_date) if entity.establish_date else None,
            "status": entity.status.value if entity.status else None,
            "tax_number": entity.tax_number,
            "bank_name": entity.bank_name,
            "bank_account": entity.bank_account,
            "contact_phone": entity.contact_phone,
        }
        if link is not None:
            data["bind_start_date"] = str(link.start_date) if link.start_date else None
            data["bind_end_date"] = str(link.end_date) if link.end_date else None
            data["bind_is_primary"] = bool(link.is_primary)
        return data
