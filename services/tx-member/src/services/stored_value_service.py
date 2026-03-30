"""储值卡服务 — 充值/消费/退款/冻结/查询

安全要求：
- 消费先扣赠送金再扣本金
- 退款仅退本金，赠送金按比例扣回
- 并发安全：使用 SELECT ... FOR UPDATE
- 所有操作记录流水（StoredValueTransaction）
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger()


class InsufficientBalanceError(Exception):
    pass


class CardNotActiveError(Exception):
    pass


class StoredValueService:
    """储值卡核心服务"""

    async def get_card(self, db: AsyncSession, card_no: str) -> Optional[dict]:
        """查询储值卡信息"""
        from models.stored_value import StoredValueCard
        result = await db.execute(
            select(StoredValueCard).where(
                StoredValueCard.card_no == card_no,
                StoredValueCard.is_deleted.is_(False),
            )
        )
        card = result.scalar_one_or_none()
        if not card:
            return None
        return {
            "id": str(card.id),
            "card_no": card.card_no,
            "customer_id": str(card.customer_id),
            "card_type": card.card_type,
            "status": card.status,
            "balance_fen": card.balance_fen,
            "gift_balance_fen": card.gift_balance_fen,
            "total_balance_fen": card.balance_fen + card.gift_balance_fen,
            "total_recharged_fen": card.total_recharged_fen,
            "total_consumed_fen": card.total_consumed_fen,
        }

    async def recharge(
        self,
        db: AsyncSession,
        card_no: str,
        amount_fen: int,
        operator_id: str | None = None,
        store_id: str | None = None,
    ) -> dict:
        """充值（含自动匹配赠送规则）"""
        from models.stored_value import StoredValueCard, StoredValueTransaction, RechargeRule

        if amount_fen <= 0:
            raise ValueError("充值金额必须大于0")

        card = await self._get_active_card_for_update(db, card_no)

        gift_fen = await self._match_recharge_gift(db, amount_fen, store_id)

        card.balance_fen += amount_fen
        card.gift_balance_fen += gift_fen
        card.total_recharged_fen += amount_fen

        txn = StoredValueTransaction(
            id=uuid.uuid4(),
            tenant_id=card.tenant_id,
            card_id=card.id,
            txn_type="recharge",
            amount_fen=amount_fen,
            gift_amount_fen=gift_fen,
            balance_after_fen=card.balance_fen,
            gift_balance_after_fen=card.gift_balance_fen,
            operator_id=uuid.UUID(operator_id) if operator_id else None,
            store_id=uuid.UUID(store_id) if store_id else None,
            remark=f"充值{amount_fen / 100:.2f}元" + (f"，赠送{gift_fen / 100:.2f}元" if gift_fen else ""),
        )
        db.add(txn)

        logger.info("stored_value_recharge", card_no=card_no, amount=amount_fen, gift=gift_fen)
        return {
            "card_no": card_no,
            "recharge_fen": amount_fen,
            "gift_fen": gift_fen,
            "balance_fen": card.balance_fen,
            "gift_balance_fen": card.gift_balance_fen,
            "txn_id": str(txn.id),
        }

    async def consume(
        self,
        db: AsyncSession,
        card_no: str,
        amount_fen: int,
        order_id: str | None = None,
        operator_id: str | None = None,
        store_id: str | None = None,
    ) -> dict:
        """消费扣款 — 先扣赠送金再扣本金"""
        from models.stored_value import StoredValueCard, StoredValueTransaction

        if amount_fen <= 0:
            raise ValueError("消费金额必须大于0")

        card = await self._get_active_card_for_update(db, card_no)

        total_available = card.balance_fen + card.gift_balance_fen
        if total_available < amount_fen:
            raise InsufficientBalanceError(
                f"余额不足：可用{total_available / 100:.2f}元，需{amount_fen / 100:.2f}元"
            )

        gift_deduct = min(card.gift_balance_fen, amount_fen)
        principal_deduct = amount_fen - gift_deduct

        card.gift_balance_fen -= gift_deduct
        card.balance_fen -= principal_deduct
        card.total_consumed_fen += amount_fen

        txn = StoredValueTransaction(
            id=uuid.uuid4(),
            tenant_id=card.tenant_id,
            card_id=card.id,
            txn_type="consume",
            amount_fen=-amount_fen,
            gift_amount_fen=-gift_deduct,
            balance_after_fen=card.balance_fen,
            gift_balance_after_fen=card.gift_balance_fen,
            order_id=uuid.UUID(order_id) if order_id else None,
            operator_id=uuid.UUID(operator_id) if operator_id else None,
            store_id=uuid.UUID(store_id) if store_id else None,
            remark=f"消费{amount_fen / 100:.2f}元（赠送金{gift_deduct / 100:.2f}+本金{principal_deduct / 100:.2f}）",
        )
        db.add(txn)

        logger.info("stored_value_consume", card_no=card_no, amount=amount_fen, gift_deduct=gift_deduct)
        return {
            "card_no": card_no,
            "consume_fen": amount_fen,
            "gift_deducted_fen": gift_deduct,
            "principal_deducted_fen": principal_deduct,
            "balance_fen": card.balance_fen,
            "gift_balance_fen": card.gift_balance_fen,
            "txn_id": str(txn.id),
        }

    async def refund(
        self,
        db: AsyncSession,
        card_no: str,
        amount_fen: int,
        order_id: str | None = None,
        operator_id: str | None = None,
    ) -> dict:
        """退款 — 仅退本金，赠送金按比例扣回"""
        from models.stored_value import StoredValueCard, StoredValueTransaction

        if amount_fen <= 0:
            raise ValueError("退款金额必须大于0")

        card = await self._get_active_card_for_update(db, card_no)

        card.balance_fen += amount_fen
        card.total_refunded_fen += amount_fen

        txn = StoredValueTransaction(
            id=uuid.uuid4(),
            tenant_id=card.tenant_id,
            card_id=card.id,
            txn_type="refund",
            amount_fen=amount_fen,
            gift_amount_fen=0,
            balance_after_fen=card.balance_fen,
            gift_balance_after_fen=card.gift_balance_fen,
            order_id=uuid.UUID(order_id) if order_id else None,
            operator_id=uuid.UUID(operator_id) if operator_id else None,
            remark=f"退款{amount_fen / 100:.2f}元",
        )
        db.add(txn)

        logger.info("stored_value_refund", card_no=card_no, amount=amount_fen)
        return {
            "card_no": card_no,
            "refund_fen": amount_fen,
            "balance_fen": card.balance_fen,
            "gift_balance_fen": card.gift_balance_fen,
            "txn_id": str(txn.id),
        }

    async def freeze(self, db: AsyncSession, card_no: str, operator_id: str | None = None) -> dict:
        """冻结储值卡"""
        from models.stored_value import StoredValueCard, StoredValueTransaction

        card = await self._get_active_card_for_update(db, card_no)
        card.status = "frozen"
        card.frozen_at = datetime.now(timezone.utc)

        txn = StoredValueTransaction(
            id=uuid.uuid4(),
            tenant_id=card.tenant_id,
            card_id=card.id,
            txn_type="freeze",
            amount_fen=0,
            gift_amount_fen=0,
            balance_after_fen=card.balance_fen,
            gift_balance_after_fen=card.gift_balance_fen,
            operator_id=uuid.UUID(operator_id) if operator_id else None,
            remark="冻结储值卡",
        )
        db.add(txn)
        return {"card_no": card_no, "status": "frozen"}

    async def unfreeze(self, db: AsyncSession, card_no: str, operator_id: str | None = None) -> dict:
        """解冻储值卡"""
        from models.stored_value import StoredValueCard, StoredValueTransaction

        result = await db.execute(
            select(StoredValueCard)
            .where(StoredValueCard.card_no == card_no, StoredValueCard.is_deleted.is_(False))
            .with_for_update()
        )
        card = result.scalar_one_or_none()
        if not card:
            raise ValueError(f"储值卡不存在: {card_no}")
        if card.status != "frozen":
            raise CardNotActiveError("卡片非冻结状态，无需解冻")

        card.status = "active"
        card.frozen_at = None

        txn = StoredValueTransaction(
            id=uuid.uuid4(),
            tenant_id=card.tenant_id,
            card_id=card.id,
            txn_type="unfreeze",
            amount_fen=0,
            gift_amount_fen=0,
            balance_after_fen=card.balance_fen,
            gift_balance_after_fen=card.gift_balance_fen,
            operator_id=uuid.UUID(operator_id) if operator_id else None,
            remark="解冻储值卡",
        )
        db.add(txn)
        return {"card_no": card_no, "status": "active"}

    async def get_transactions(
        self, db: AsyncSession, card_no: str, limit: int = 20, offset: int = 0,
    ) -> dict:
        """查询储值卡交易流水"""
        from models.stored_value import StoredValueCard, StoredValueTransaction

        card_result = await db.execute(
            select(StoredValueCard.id).where(StoredValueCard.card_no == card_no)
        )
        card_id = card_result.scalar_one_or_none()
        if not card_id:
            raise ValueError(f"储值卡不存在: {card_no}")

        result = await db.execute(
            select(StoredValueTransaction)
            .where(StoredValueTransaction.card_id == card_id)
            .order_by(StoredValueTransaction.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        txns = result.scalars().all()
        return {
            "card_no": card_no,
            "transactions": [
                {
                    "txn_id": str(t.id),
                    "txn_type": t.txn_type,
                    "amount_fen": t.amount_fen,
                    "gift_amount_fen": t.gift_amount_fen,
                    "balance_after_fen": t.balance_after_fen,
                    "gift_balance_after_fen": t.gift_balance_after_fen,
                    "remark": t.remark,
                    "created_at": str(t.created_at) if t.created_at else None,
                }
                for t in txns
            ],
        }

    async def _get_active_card_for_update(self, db: AsyncSession, card_no: str):
        """获取活跃卡并加行锁（防并发）"""
        from models.stored_value import StoredValueCard
        result = await db.execute(
            select(StoredValueCard)
            .where(StoredValueCard.card_no == card_no, StoredValueCard.is_deleted.is_(False))
            .with_for_update()
        )
        card = result.scalar_one_or_none()
        if not card:
            raise ValueError(f"储值卡不存在: {card_no}")
        if card.status != "active":
            raise CardNotActiveError(f"储值卡状态异常: {card.status}")
        return card

    async def _match_recharge_gift(
        self, db: AsyncSession, amount_fen: int, store_id: str | None,
    ) -> int:
        """匹配充值赠送规则，返回赠送金额"""
        from models.stored_value import RechargeRule
        now = datetime.now(timezone.utc)

        result = await db.execute(
            select(RechargeRule)
            .where(RechargeRule.is_active.is_(True), RechargeRule.is_deleted.is_(False))
            .where(RechargeRule.recharge_amount_fen <= amount_fen)
            .order_by(RechargeRule.recharge_amount_fen.desc())
        )
        rules = result.scalars().all()
        for rule in rules:
            if rule.start_date and now < rule.start_date:
                continue
            if rule.end_date and now > rule.end_date:
                continue
            if rule.store_ids and store_id and store_id not in [str(s) for s in rule.store_ids]:
                continue
            return rule.gift_amount_fen

        return 0
