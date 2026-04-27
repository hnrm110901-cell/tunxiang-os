"""储值卡服务 — 充值/消费/退款/冻结/查询

安全要求：
- 消费先扣赠送金再扣本金
- 退款仅退本金，不退赠送余额
- 并发安全：使用 SELECT ... FOR UPDATE
- 所有操作记录流水（StoredValueTransaction）

v2 新增：
- create_card：开卡
- recharge_by_plan：按套餐充值（替代按金额+规则匹配）
- get_balance：按 card_id 查询余额
- get_transactions_by_id：按 card_id 分页查询流水
- list_recharge_plans：查询有效套餐列表
- create_recharge_plan：新建套餐
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from typing import Optional

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger()


class InsufficientBalanceError(Exception):
    pass


class CardNotActiveError(Exception):
    pass


class PlanNotFoundError(Exception):
    pass


class TransferNotAllowedError(Exception):
    pass


class CardNotFoundError(ValueError):
    """储值卡不存在（ValueError 子类，兼容现有 except ValueError 捕获）"""

    pass


class StoredValueService:
    """储值卡核心服务"""

    # ──────────────────────────────────────────────────────────────
    # 开卡
    # ──────────────────────────────────────────────────────────────

    async def create_card(
        self,
        db: AsyncSession,
        customer_id: uuid.UUID,
        tenant_id: uuid.UUID,
        store_id: uuid.UUID | None = None,
        scope_type: str = "brand",
        operator_id: uuid.UUID | None = None,
        remark: str | None = None,
    ) -> dict:
        """开卡 — 生成唯一卡号，插入 StoredValueCard"""
        from models.stored_value import StoredValueCard

        card_no = f"SV-{datetime.now(timezone.utc).strftime('%Y%m%d')}-{str(uuid.uuid4())[:6].upper()}"

        card = StoredValueCard(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            card_no=card_no,
            customer_id=customer_id,
            store_id=store_id,
            scope_type=scope_type,
            operator_id=operator_id,
            remark=remark,
        )
        db.add(card)
        await db.flush()

        logger.info("stored_value_create_card", card_no=card_no, customer_id=str(customer_id))
        return _card_to_dict(card)

    # ──────────────────────────────────────────────────────────────
    # 查询（按 card_no）
    # ──────────────────────────────────────────────────────────────

    async def get_card(self, db: AsyncSession, card_no: str) -> Optional[dict]:
        """查询储值卡信息（按卡号）"""
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
        return _card_to_dict(card)

    # ──────────────────────────────────────────────────────────────
    # 查询（按 card_id）
    # ──────────────────────────────────────────────────────────────

    async def get_balance(
        self,
        db: AsyncSession,
        card_id: uuid.UUID,
        tenant_id: uuid.UUID,
    ) -> dict:
        """查询储值卡余额（按 card_id）"""
        from models.stored_value import StoredValueCard

        result = await db.execute(
            select(StoredValueCard).where(
                StoredValueCard.id == card_id,
                StoredValueCard.tenant_id == tenant_id,
                StoredValueCard.is_deleted.is_(False),
            )
        )
        card = result.scalar_one_or_none()
        if not card:
            raise ValueError(f"储值卡不存在: {card_id}")
        return {
            "card_no": card.card_no,
            "balance_fen": card.balance_fen,
            "main_balance_fen": card.main_balance_fen,
            "gift_balance_fen": card.gift_balance_fen,
            "status": card.status,
            "expiry_date": str(card.expiry_date) if card.expiry_date else None,
        }

    async def get_card_by_id(
        self,
        db: AsyncSession,
        card_id: uuid.UUID,
        tenant_id: uuid.UUID,
    ) -> Optional[dict]:
        """查询储值卡详情（按 card_id）"""
        from models.stored_value import StoredValueCard

        result = await db.execute(
            select(StoredValueCard).where(
                StoredValueCard.id == card_id,
                StoredValueCard.tenant_id == tenant_id,
                StoredValueCard.is_deleted.is_(False),
            )
        )
        card = result.scalar_one_or_none()
        if not card:
            return None
        return _card_to_dict(card)

    # ──────────────────────────────────────────────────────────────
    # 充值 — 按 plan_id（v2 新逻辑）
    # ──────────────────────────────────────────────────────────────

    async def recharge_by_plan(
        self,
        db: AsyncSession,
        card_id: uuid.UUID,
        plan_id: uuid.UUID,
        tenant_id: uuid.UUID,
        operator_id: uuid.UUID | None = None,
        store_id: uuid.UUID | None = None,
    ) -> dict:
        """按套餐充值 — 验证套餐有效性，同一事务内更新卡余额并记录流水"""
        from models.stored_value import StoredValueRechargePlan, StoredValueTransaction

        # 查套餐（带 tenant_id 隔离）
        plan_result = await db.execute(
            select(StoredValueRechargePlan).where(
                StoredValueRechargePlan.id == plan_id,
                StoredValueRechargePlan.tenant_id == tenant_id,
                StoredValueRechargePlan.is_deleted.is_(False),
            )
        )
        plan = plan_result.scalar_one_or_none()
        if not plan:
            raise PlanNotFoundError(f"充值套餐不存在: {plan_id}")
        if not plan.is_active:
            raise PlanNotFoundError("充值套餐已下架")

        now = datetime.now(timezone.utc)
        if plan.valid_from and now < plan.valid_from:
            raise PlanNotFoundError("充值套餐尚未开始")
        if plan.valid_until and now > plan.valid_until:
            raise PlanNotFoundError("充值套餐已过期")

        # 查卡（加行锁）
        card = await self._get_card_by_id_for_update(db, card_id, tenant_id)
        _check_card_active_and_not_expired(card)

        card.main_balance_fen += plan.recharge_amount_fen
        card.gift_balance_fen += plan.gift_amount_fen
        card.balance_fen = card.main_balance_fen + card.gift_balance_fen
        card.total_recharged_fen += plan.recharge_amount_fen

        total_amount = plan.recharge_amount_fen + plan.gift_amount_fen
        txn = StoredValueTransaction(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            card_id=card.id,
            customer_id=card.customer_id,
            txn_type="recharge",
            amount_fen=total_amount,
            main_amount_fen=plan.recharge_amount_fen,
            gift_amount_fen=plan.gift_amount_fen,
            balance_after_fen=card.balance_fen,
            gift_balance_after_fen=card.gift_balance_fen,
            recharge_plan_id=str(plan.id),
            operator_id=operator_id,
            store_id=store_id,
            remark=(
                f"充值套餐[{plan.name}] "
                f"充{plan.recharge_amount_fen / 100:.2f}元"
                + (f"赠{plan.gift_amount_fen / 100:.2f}元" if plan.gift_amount_fen else "")
            ),
        )
        db.add(txn)

        logger.info(
            "stored_value_recharge_by_plan",
            card_id=str(card_id),
            plan_id=str(plan_id),
            recharge=plan.recharge_amount_fen,
            gift=plan.gift_amount_fen,
        )

        # 发布储值充值事件（不阻塞主流程）
        import asyncio

        from shared.events.event_publisher import MemberEventPublisher
        from shared.events.member_events import MemberEventType

        asyncio.create_task(
            MemberEventPublisher.publish(
                MemberEventType.STORED_VALUE_RECHARGED,
                tenant_id=tenant_id,
                customer_id=card.customer_id,
                event_data={
                    "amount_fen": plan.recharge_amount_fen,
                    "gift_fen": plan.gift_amount_fen,
                    "card_id": str(card.id),
                    "plan_id": str(plan_id),
                },
                source_service="tx-member",
            )
        )

        return _txn_to_dict(txn)

    # ──────────────────────────────────────────────────────────────
    # 充值 — 按金额（v1 兼容保留）
    # ──────────────────────────────────────────────────────────────

    async def recharge(
        self,
        db: AsyncSession,
        card_no: str,
        amount_fen: int,
        operator_id: str | None = None,
        store_id: str | None = None,
    ) -> dict:
        """充值（按金额，含自动匹配赠送规则）— 兼容 v1 路由"""
        from models.stored_value import StoredValueTransaction

        if amount_fen <= 0:
            raise ValueError("充值金额必须大于0")

        card = await self._get_active_card_for_update(db, card_no)

        gift_fen = await self._match_recharge_gift(db, amount_fen, store_id)

        card.main_balance_fen += amount_fen
        card.gift_balance_fen += gift_fen
        card.balance_fen = card.main_balance_fen + card.gift_balance_fen
        card.total_recharged_fen += amount_fen

        txn = StoredValueTransaction(
            id=uuid.uuid4(),
            tenant_id=card.tenant_id,
            card_id=card.id,
            customer_id=card.customer_id,
            txn_type="recharge",
            amount_fen=amount_fen + gift_fen,
            main_amount_fen=amount_fen,
            gift_amount_fen=gift_fen,
            balance_after_fen=card.balance_fen,
            gift_balance_after_fen=card.gift_balance_fen,
            operator_id=uuid.UUID(operator_id) if operator_id else None,
            store_id=uuid.UUID(store_id) if store_id else None,
            remark=f"充值{amount_fen / 100:.2f}元" + (f"，赠送{gift_fen / 100:.2f}元" if gift_fen else ""),
        )
        db.add(txn)

        logger.info("stored_value_recharge", card_no=card_no, amount=amount_fen, gift=gift_fen)

        # 发布储值充值事件（不阻塞主流程）
        import asyncio

        from shared.events.event_publisher import MemberEventPublisher
        from shared.events.member_events import MemberEventType

        asyncio.create_task(
            MemberEventPublisher.publish(
                MemberEventType.STORED_VALUE_RECHARGED,
                tenant_id=card.tenant_id,
                customer_id=card.customer_id,
                event_data={
                    "amount_fen": amount_fen,
                    "gift_fen": gift_fen,
                    "card_id": str(card.id),
                    "card_no": card_no,
                },
                source_service="tx-member",
            )
        )

        return {
            "card_no": card_no,
            "recharge_fen": amount_fen,
            "gift_fen": gift_fen,
            "balance_fen": card.balance_fen,
            "gift_balance_fen": card.gift_balance_fen,
            "txn_id": str(txn.id),
        }

    # ──────────────────────────────────────────────────────────────
    # 消费
    # ──────────────────────────────────────────────────────────────

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
        from models.stored_value import StoredValueTransaction

        if amount_fen <= 0:
            raise ValueError("消费金额必须大于0")

        card = await self._get_active_card_for_update(db, card_no)
        _check_card_active_and_not_expired(card)

        if card.balance_fen < amount_fen:
            raise InsufficientBalanceError(f"余额不足：可用{card.balance_fen / 100:.2f}元，需{amount_fen / 100:.2f}元")

        gift_deduct = min(card.gift_balance_fen, amount_fen)
        principal_deduct = amount_fen - gift_deduct

        card.gift_balance_fen -= gift_deduct
        card.main_balance_fen -= principal_deduct
        card.balance_fen = card.main_balance_fen + card.gift_balance_fen
        card.total_consumed_fen += amount_fen

        txn = StoredValueTransaction(
            id=uuid.uuid4(),
            tenant_id=card.tenant_id,
            card_id=card.id,
            customer_id=card.customer_id,
            txn_type="consume",
            amount_fen=-amount_fen,
            main_amount_fen=-principal_deduct,
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

        # ─── 跨店分账：消费店 != 充值店时自动触发 ───
        split_result = None
        consume_store_uuid = uuid.UUID(store_id) if store_id else None
        if consume_store_uuid and card.store_id and consume_store_uuid != card.store_id:
            split_result = await self._trigger_cross_store_split(
                db=db,
                tenant_id=card.tenant_id,
                transaction_id=txn.id,
                recharge_store_id=card.store_id,
                consume_store_id=consume_store_uuid,
                amount_fen=amount_fen,
            )

        result = {
            "card_no": card_no,
            "consume_fen": amount_fen,
            "gift_deducted_fen": gift_deduct,
            "principal_deducted_fen": principal_deduct,
            "balance_fen": card.balance_fen,
            "gift_balance_fen": card.gift_balance_fen,
            "txn_id": str(txn.id),
        }
        if split_result:
            result["split"] = split_result
        return result

    async def consume_by_id(
        self,
        db: AsyncSession,
        card_id: uuid.UUID,
        amount_fen: int,
        tenant_id: uuid.UUID,
        order_id: uuid.UUID | None = None,
        store_id: uuid.UUID | None = None,
    ) -> dict:
        """消费扣款（按 card_id，v2 路由用）"""
        from models.stored_value import StoredValueTransaction

        if amount_fen <= 0:
            raise ValueError("消费金额必须大于0")

        card = await self._get_card_by_id_for_update(db, card_id, tenant_id)
        _check_card_active_and_not_expired(card)

        if card.balance_fen < amount_fen:
            raise InsufficientBalanceError(f"余额不足：可用{card.balance_fen / 100:.2f}元，需{amount_fen / 100:.2f}元")

        gift_deduct = min(card.gift_balance_fen, amount_fen)
        principal_deduct = amount_fen - gift_deduct

        card.gift_balance_fen -= gift_deduct
        card.main_balance_fen -= principal_deduct
        card.balance_fen = card.main_balance_fen + card.gift_balance_fen
        card.total_consumed_fen += amount_fen

        txn = StoredValueTransaction(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            card_id=card.id,
            customer_id=card.customer_id,
            txn_type="consume",
            amount_fen=-amount_fen,
            main_amount_fen=-principal_deduct,
            gift_amount_fen=-gift_deduct,
            balance_after_fen=card.balance_fen,
            gift_balance_after_fen=card.gift_balance_fen,
            order_id=order_id,
            store_id=store_id,
            remark=f"消费{amount_fen / 100:.2f}元（赠送金{gift_deduct / 100:.2f}+本金{principal_deduct / 100:.2f}）",
        )
        db.add(txn)

        logger.info("stored_value_consume_by_id", card_id=str(card_id), amount=amount_fen)

        # ─── 跨店分账：消费店 != 充值店时自动触发 ───
        split_result = None
        if store_id and card.store_id and store_id != card.store_id:
            split_result = await self._trigger_cross_store_split(
                db=db,
                tenant_id=tenant_id,
                transaction_id=txn.id,
                recharge_store_id=card.store_id,
                consume_store_id=store_id,
                amount_fen=amount_fen,
            )

        result = _txn_to_dict(txn)
        if split_result:
            result["split"] = split_result
        return result

    # ──────────────────────────────────────────────────────────────
    # 退款
    # ──────────────────────────────────────────────────────────────

    async def refund(
        self,
        db: AsyncSession,
        card_no: str,
        amount_fen: int,
        order_id: str | None = None,
        operator_id: str | None = None,
    ) -> dict:
        """退款 — 仅退本金（兼容 v1 路由）"""
        from models.stored_value import StoredValueTransaction

        if amount_fen <= 0:
            raise ValueError("退款金额必须大于0")

        card = await self._get_active_card_for_update(db, card_no)

        card.main_balance_fen += amount_fen
        card.balance_fen = card.main_balance_fen + card.gift_balance_fen
        card.total_refunded_fen += amount_fen

        txn = StoredValueTransaction(
            id=uuid.uuid4(),
            tenant_id=card.tenant_id,
            card_id=card.id,
            customer_id=card.customer_id,
            txn_type="refund",
            amount_fen=amount_fen,
            main_amount_fen=amount_fen,
            gift_amount_fen=0,
            balance_after_fen=card.balance_fen,
            gift_balance_after_fen=card.gift_balance_fen,
            order_id=uuid.UUID(order_id) if order_id else None,
            operator_id=uuid.UUID(operator_id) if operator_id else None,
            remark=f"退款{amount_fen / 100:.2f}元（仅退本金）",
        )
        db.add(txn)

        logger.info("stored_value_refund", card_no=card_no, amount=amount_fen)

        # ─── 退款分账冲正：如关联订单有分账记录则反向冲正 ───
        reversal_result = None
        if order_id:
            reversal_result = await self._trigger_split_reversal(
                db=db,
                tenant_id=card.tenant_id,
                original_order_id=order_id,
                refund_transaction_id=str(txn.id),
                refund_amount_fen=amount_fen,
            )

        result = {
            "card_no": card_no,
            "refund_fen": amount_fen,
            "balance_fen": card.balance_fen,
            "gift_balance_fen": card.gift_balance_fen,
            "txn_id": str(txn.id),
        }
        if reversal_result:
            result["split_reversal"] = reversal_result
        return result

    async def refund_by_transaction(
        self,
        db: AsyncSession,
        transaction_id: uuid.UUID,
        refund_amount_fen: int,
        tenant_id: uuid.UUID,
        operator_id: uuid.UUID | None = None,
    ) -> dict:
        """按原始流水退款 — 退款不超过原始消费额，仅退本金（v2 路由用）"""
        from models.stored_value import StoredValueTransaction

        if refund_amount_fen <= 0:
            raise ValueError("退款金额必须大于0")

        # 查原始 consume 流水
        txn_result = await db.execute(
            select(StoredValueTransaction).where(
                StoredValueTransaction.id == transaction_id,
                StoredValueTransaction.tenant_id == tenant_id,
                StoredValueTransaction.is_deleted.is_(False),
            )
        )
        orig_txn = txn_result.scalar_one_or_none()
        if not orig_txn:
            raise ValueError(f"原始流水不存在: {transaction_id}")
        if orig_txn.txn_type != "consume":
            raise ValueError(f"只能对消费流水发起退款，当前流水类型: {orig_txn.txn_type}")

        orig_amount = abs(orig_txn.amount_fen)
        if refund_amount_fen > orig_amount:
            raise ValueError(f"退款金额({refund_amount_fen / 100:.2f}元)超过原始消费额({orig_amount / 100:.2f}元)")

        # 加锁查卡
        card = await self._get_card_by_id_for_update(db, orig_txn.card_id, tenant_id)

        # 仅退本金（不退赠送余额）
        card.main_balance_fen += refund_amount_fen
        card.balance_fen = card.main_balance_fen + card.gift_balance_fen
        card.total_refunded_fen += refund_amount_fen

        refund_txn = StoredValueTransaction(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            card_id=card.id,
            customer_id=card.customer_id,
            txn_type="refund",
            amount_fen=refund_amount_fen,
            main_amount_fen=refund_amount_fen,
            gift_amount_fen=0,
            balance_after_fen=card.balance_fen,
            gift_balance_after_fen=card.gift_balance_fen,
            order_id=orig_txn.order_id,
            operator_id=operator_id,
            remark=f"退款{refund_amount_fen / 100:.2f}元（原流水 {transaction_id}，仅退本金）",
        )
        db.add(refund_txn)

        logger.info(
            "stored_value_refund_by_txn",
            orig_txn_id=str(transaction_id),
            refund_amount=refund_amount_fen,
        )

        # ─── 退款分账冲正：如原始消费有分账记录则反向冲正 ───
        reversal_result = None
        if orig_txn.order_id:
            reversal_result = await self._trigger_split_reversal(
                db=db,
                tenant_id=tenant_id,
                original_order_id=str(orig_txn.order_id),
                refund_transaction_id=str(refund_txn.id),
                refund_amount_fen=refund_amount_fen,
            )

        result = _txn_to_dict(refund_txn)
        if reversal_result:
            result["split_reversal"] = reversal_result
        return result

    # ──────────────────────────────────────────────────────────────
    # 流水查询
    # ──────────────────────────────────────────────────────────────

    async def get_transactions(
        self,
        db: AsyncSession,
        card_no: str,
        limit: int = 20,
        offset: int = 0,
    ) -> dict:
        """查询储值卡流水（按卡号，v1 兼容）"""
        from models.stored_value import StoredValueCard, StoredValueTransaction

        card_result = await db.execute(select(StoredValueCard.id).where(StoredValueCard.card_no == card_no))
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

    async def get_transactions_by_id(
        self,
        db: AsyncSession,
        card_id: uuid.UUID,
        tenant_id: uuid.UUID,
        page: int = 1,
        size: int = 20,
    ) -> dict:
        """按 card_id 分页查询流水（v2 路由用）"""
        from models.stored_value import StoredValueTransaction

        offset = (page - 1) * size

        count_result = await db.execute(
            select(func.count()).where(
                StoredValueTransaction.card_id == card_id,
                StoredValueTransaction.tenant_id == tenant_id,
                StoredValueTransaction.is_deleted.is_(False),
            )
        )
        total: int = count_result.scalar_one()

        result = await db.execute(
            select(StoredValueTransaction)
            .where(
                StoredValueTransaction.card_id == card_id,
                StoredValueTransaction.tenant_id == tenant_id,
                StoredValueTransaction.is_deleted.is_(False),
            )
            .order_by(StoredValueTransaction.created_at.desc())
            .offset(offset)
            .limit(size)
        )
        txns = result.scalars().all()
        return {
            "items": [_txn_to_dict(t) for t in txns],
            "total": total,
            "page": page,
            "size": size,
        }

    # ──────────────────────────────────────────────────────────────
    # 套餐管理
    # ──────────────────────────────────────────────────────────────

    async def list_recharge_plans(
        self,
        db: AsyncSession,
        tenant_id: uuid.UUID,
    ) -> list[dict]:
        """查询有效套餐列表（is_active=True，在有效期内）"""
        from models.stored_value import StoredValueRechargePlan

        now = datetime.now(timezone.utc)

        result = await db.execute(
            select(StoredValueRechargePlan)
            .where(
                StoredValueRechargePlan.tenant_id == tenant_id,
                StoredValueRechargePlan.is_active.is_(True),
                StoredValueRechargePlan.is_deleted.is_(False),
            )
            .order_by(StoredValueRechargePlan.sort_order.asc())
        )
        plans = result.scalars().all()

        # 在 Python 层过滤时间范围（兼顾 nullable valid_from/until）
        return [
            _plan_to_dict(p)
            for p in plans
            if (p.valid_from is None or p.valid_from <= now) and (p.valid_until is None or p.valid_until >= now)
        ]

    async def create_recharge_plan(
        self,
        db: AsyncSession,
        tenant_id: uuid.UUID,
        name: str,
        recharge_amount_fen: int,
        gift_amount_fen: int = 0,
        scope_type: str = "brand",
        sort_order: int = 0,
        valid_from: datetime | None = None,
        valid_until: datetime | None = None,
        remark: str | None = None,
    ) -> dict:
        """新建充值套餐"""
        from models.stored_value import StoredValueRechargePlan

        if recharge_amount_fen <= 0:
            raise ValueError("充值金额必须大于0")
        if gift_amount_fen < 0:
            raise ValueError("赠送金额不能为负")

        plan = StoredValueRechargePlan(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            name=name,
            recharge_amount_fen=recharge_amount_fen,
            gift_amount_fen=gift_amount_fen,
            scope_type=scope_type,
            sort_order=sort_order,
            valid_from=valid_from,
            valid_until=valid_until,
            remark=remark,
        )
        db.add(plan)
        await db.flush()

        logger.info("stored_value_create_plan", plan_id=str(plan.id), name=name)
        return _plan_to_dict(plan)

    # ──────────────────────────────────────────────────────────────
    # 直接充值（按 card_id + 金额，不走套餐）
    # ──────────────────────────────────────────────────────────────

    async def recharge_direct(
        self,
        db: AsyncSession,
        card_id: uuid.UUID,
        amount_fen: int,
        tenant_id: uuid.UUID,
        gift_amount_fen: int = 0,
        operator_id: uuid.UUID | None = None,
        store_id: uuid.UUID | None = None,
        remark: str | None = None,
    ) -> dict:
        """直接充值（按 card_id + 金额）— 支持满赠逻辑，不走套餐匹配。

        满赠逻辑由调用方计算并通过 gift_amount_fen 传入。
        """
        from models.stored_value import StoredValueTransaction

        if amount_fen <= 0:
            raise ValueError("充值金额必须大于0")
        if gift_amount_fen < 0:
            raise ValueError("赠送金额不能为负")

        card = await self._get_card_by_id_for_update(db, card_id, tenant_id)
        _check_card_active_and_not_expired(card)

        card.main_balance_fen += amount_fen
        card.gift_balance_fen += gift_amount_fen
        card.balance_fen = card.main_balance_fen + card.gift_balance_fen
        card.total_recharged_fen += amount_fen

        total_fen = amount_fen + gift_amount_fen
        auto_remark = remark or (
            f"充值{amount_fen / 100:.2f}元" + (f"，赠送{gift_amount_fen / 100:.2f}元" if gift_amount_fen else "")
        )

        txn = StoredValueTransaction(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            card_id=card.id,
            customer_id=card.customer_id,
            txn_type="recharge",
            amount_fen=total_fen,
            main_amount_fen=amount_fen,
            gift_amount_fen=gift_amount_fen,
            balance_after_fen=card.balance_fen,
            gift_balance_after_fen=card.gift_balance_fen,
            operator_id=operator_id,
            store_id=store_id,
            remark=auto_remark,
        )
        db.add(txn)

        logger.info(
            "stored_value_recharge_direct",
            card_id=str(card_id),
            amount=amount_fen,
            gift=gift_amount_fen,
        )
        return _txn_to_dict(txn)

    # ──────────────────────────────────────────────────────────────
    # 直接退款（按 card_id + 金额）
    # ──────────────────────────────────────────────────────────────

    async def refund_direct(
        self,
        db: AsyncSession,
        card_id: uuid.UUID,
        amount_fen: int,
        tenant_id: uuid.UUID,
        order_id: uuid.UUID | None = None,
        operator_id: uuid.UUID | None = None,
        remark: str | None = None,
    ) -> dict:
        """直接退款（仅退本金）— 按 card_id，不验证原始流水。"""
        from models.stored_value import StoredValueTransaction

        if amount_fen <= 0:
            raise ValueError("退款金额必须大于0")

        card = await self._get_card_by_id_for_update(db, card_id, tenant_id)

        card.main_balance_fen += amount_fen
        card.balance_fen = card.main_balance_fen + card.gift_balance_fen
        card.total_refunded_fen += amount_fen

        txn = StoredValueTransaction(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            card_id=card.id,
            customer_id=card.customer_id,
            txn_type="refund",
            amount_fen=amount_fen,
            main_amount_fen=amount_fen,
            gift_amount_fen=0,
            balance_after_fen=card.balance_fen,
            gift_balance_after_fen=card.gift_balance_fen,
            order_id=order_id,
            operator_id=operator_id,
            remark=remark or f"退款{amount_fen / 100:.2f}元（仅退本金）",
        )
        db.add(txn)

        logger.info("stored_value_refund_direct", card_id=str(card_id), amount=amount_fen)
        return _txn_to_dict(txn)

    # ──────────────────────────────────────────────────────────────
    # 余额转赠
    # ──────────────────────────────────────────────────────────────

    async def transfer(
        self,
        db: AsyncSession,
        from_card_id: uuid.UUID,
        to_card_id: uuid.UUID,
        amount_fen: int,
        tenant_id: uuid.UUID,
        operator_id: uuid.UUID | None = None,
        remark: str | None = None,
    ) -> dict:
        """余额转赠 — 从 from_card 转入 to_card（同一租户内，仅转本金）

        并发安全：对两张卡同时加行锁（按 UUID 排序防死锁）。
        仅转本金余额，不转赠送余额。
        """
        from models.stored_value import StoredValueCard, StoredValueTransaction

        if amount_fen <= 0:
            raise ValueError("转赠金额必须大于0")
        if from_card_id == to_card_id:
            raise ValueError("不能向自己转赠")

        # 按 UUID 固定加锁顺序防死锁
        id_a, id_b = sorted([from_card_id, to_card_id])

        result_a = await db.execute(
            select(StoredValueCard)
            .where(
                StoredValueCard.id == id_a,
                StoredValueCard.tenant_id == tenant_id,
                StoredValueCard.is_deleted.is_(False),
            )
            .with_for_update()
        )
        card_a = result_a.scalar_one_or_none()
        if not card_a:
            raise ValueError(f"储值卡不存在: {id_a}")

        result_b = await db.execute(
            select(StoredValueCard)
            .where(
                StoredValueCard.id == id_b,
                StoredValueCard.tenant_id == tenant_id,
                StoredValueCard.is_deleted.is_(False),
            )
            .with_for_update()
        )
        card_b = result_b.scalar_one_or_none()
        if not card_b:
            raise ValueError(f"储值卡不存在: {id_b}")

        # 根据排序结果确定哪张是 from / to
        from_card = card_a if card_a.id == from_card_id else card_b
        to_card = card_b if card_b.id == to_card_id else card_a

        _check_card_active_and_not_expired(from_card)
        _check_card_active_and_not_expired(to_card)

        if from_card.main_balance_fen < amount_fen:
            raise InsufficientBalanceError(
                f"本金余额不足以转赠：可用{from_card.main_balance_fen / 100:.2f}元，需{amount_fen / 100:.2f}元"
            )

        # 扣出
        from_card.main_balance_fen -= amount_fen
        from_card.balance_fen = from_card.main_balance_fen + from_card.gift_balance_fen

        # 转入
        to_card.main_balance_fen += amount_fen
        to_card.balance_fen = to_card.main_balance_fen + to_card.gift_balance_fen

        transfer_remark = remark or f"余额转赠 {amount_fen / 100:.2f}元"

        out_txn = StoredValueTransaction(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            card_id=from_card.id,
            customer_id=from_card.customer_id,
            txn_type="transfer_out",
            amount_fen=-amount_fen,
            main_amount_fen=-amount_fen,
            gift_amount_fen=0,
            balance_after_fen=from_card.balance_fen,
            gift_balance_after_fen=from_card.gift_balance_fen,
            operator_id=operator_id,
            remark=f"{transfer_remark} → 卡{to_card_id}",
        )
        in_txn = StoredValueTransaction(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            card_id=to_card.id,
            customer_id=to_card.customer_id,
            txn_type="transfer_in",
            amount_fen=amount_fen,
            main_amount_fen=amount_fen,
            gift_amount_fen=0,
            balance_after_fen=to_card.balance_fen,
            gift_balance_after_fen=to_card.gift_balance_fen,
            operator_id=operator_id,
            remark=f"{transfer_remark} ← 卡{from_card_id}",
        )
        db.add(out_txn)
        db.add(in_txn)

        logger.info(
            "stored_value_transfer",
            from_card_id=str(from_card_id),
            to_card_id=str(to_card_id),
            amount=amount_fen,
        )
        return {
            "from_card_id": str(from_card_id),
            "to_card_id": str(to_card_id),
            "amount_fen": amount_fen,
            "from_balance_fen": from_card.balance_fen,
            "to_balance_fen": to_card.balance_fen,
            "out_txn_id": str(out_txn.id),
            "in_txn_id": str(in_txn.id),
        }

    # ──────────────────────────────────────────────────────────────
    # 批量过期处理
    # ──────────────────────────────────────────────────────────────

    async def process_expiry_batch(
        self,
        db: AsyncSession,
        tenant_id: uuid.UUID,
    ) -> dict:
        """批量处理到期账户（夜批调用）

        逻辑：
        1. 查找 expiry_date <= 今天 且 status=active 的卡 → 冻结
        2. 返回处理汇总（冻结数量）

        通知（发 NOTIFY 事件到 pg_notify）由调用方或 worker 负责发送。
        """
        from models.stored_value import StoredValueCard, StoredValueTransaction

        today = datetime.now(timezone.utc).date()

        expired_result = await db.execute(
            select(StoredValueCard)
            .where(
                StoredValueCard.tenant_id == tenant_id,
                StoredValueCard.status == "active",
                StoredValueCard.expiry_date.isnot(None),
                StoredValueCard.expiry_date <= today,
                StoredValueCard.is_deleted.is_(False),
            )
            .with_for_update(skip_locked=True)
        )
        expired_cards = expired_result.scalars().all()

        frozen_count = 0
        for card in expired_cards:
            card.status = "expired"
            txn = StoredValueTransaction(
                id=uuid.uuid4(),
                tenant_id=tenant_id,
                card_id=card.id,
                customer_id=card.customer_id,
                txn_type="freeze",
                amount_fen=0,
                main_amount_fen=0,
                gift_amount_fen=0,
                balance_after_fen=card.balance_fen,
                gift_balance_after_fen=card.gift_balance_fen,
                remark=f"到期自动冻结（expiry_date={card.expiry_date}）",
            )
            db.add(txn)
            frozen_count += 1

        logger.info(
            "stored_value_expiry_batch",
            tenant_id=str(tenant_id),
            frozen_count=frozen_count,
        )
        return {
            "tenant_id": str(tenant_id),
            "frozen_count": frozen_count,
            "processed_at": datetime.now(timezone.utc).isoformat(),
        }

    # ──────────────────────────────────────────────────────────────
    # 冻结 / 解冻
    # ──────────────────────────────────────────────────────────────

    async def freeze(self, db: AsyncSession, card_no: str, operator_id: str | None = None) -> dict:
        """冻结储值卡"""
        from models.stored_value import StoredValueTransaction

        card = await self._get_active_card_for_update(db, card_no)
        card.status = "frozen"
        card.frozen_at = datetime.now(timezone.utc)

        txn = StoredValueTransaction(
            id=uuid.uuid4(),
            tenant_id=card.tenant_id,
            card_id=card.id,
            customer_id=card.customer_id,
            txn_type="freeze",
            amount_fen=0,
            main_amount_fen=0,
            gift_amount_fen=0,
            balance_after_fen=card.balance_fen,
            gift_balance_after_fen=card.gift_balance_fen,
            operator_id=uuid.UUID(operator_id) if operator_id else None,
            remark="冻结储值卡",
        )
        db.add(txn)
        return {"card_no": card_no, "status": "frozen"}

    async def freeze_by_id(
        self,
        db: AsyncSession,
        card_id: uuid.UUID,
        tenant_id: uuid.UUID,
        operator_id: uuid.UUID | None = None,
        remark: str | None = None,
    ) -> dict:
        """冻结储值卡（按 card_id）"""
        from models.stored_value import StoredValueTransaction

        card = await self._get_card_by_id_for_update(db, card_id, tenant_id)
        if card.status != "active":
            raise CardNotActiveError(f"只能冻结 active 状态的卡，当前状态: {card.status}")

        card.status = "frozen"
        card.frozen_at = datetime.now(timezone.utc)

        txn = StoredValueTransaction(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            card_id=card.id,
            customer_id=card.customer_id,
            txn_type="freeze",
            amount_fen=0,
            main_amount_fen=0,
            gift_amount_fen=0,
            balance_after_fen=card.balance_fen,
            gift_balance_after_fen=card.gift_balance_fen,
            operator_id=operator_id,
            remark=remark or "冻结储值卡",
        )
        db.add(txn)

        logger.info("stored_value_freeze_by_id", card_id=str(card_id))
        return {"card_id": str(card_id), "card_no": card.card_no, "status": "frozen"}

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
            customer_id=card.customer_id,
            txn_type="unfreeze",
            amount_fen=0,
            main_amount_fen=0,
            gift_amount_fen=0,
            balance_after_fen=card.balance_fen,
            gift_balance_after_fen=card.gift_balance_fen,
            operator_id=uuid.UUID(operator_id) if operator_id else None,
            remark="解冻储值卡",
        )
        db.add(txn)
        return {"card_no": card_no, "status": "active"}

    async def unfreeze_by_id(
        self,
        db: AsyncSession,
        card_id: uuid.UUID,
        tenant_id: uuid.UUID,
        operator_id: uuid.UUID | None = None,
        remark: str | None = None,
    ) -> dict:
        """解冻储值卡（按 card_id）"""
        from models.stored_value import StoredValueTransaction

        card = await self._get_card_by_id_for_update(db, card_id, tenant_id)
        if card.status != "frozen":
            raise CardNotActiveError("卡片非冻结状态，无需解冻")

        card.status = "active"
        card.frozen_at = None

        txn = StoredValueTransaction(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            card_id=card.id,
            customer_id=card.customer_id,
            txn_type="unfreeze",
            amount_fen=0,
            main_amount_fen=0,
            gift_amount_fen=0,
            balance_after_fen=card.balance_fen,
            gift_balance_after_fen=card.gift_balance_fen,
            operator_id=operator_id,
            remark=remark or "解冻储值卡",
        )
        db.add(txn)

        logger.info("stored_value_unfreeze_by_id", card_id=str(card_id))
        return {"card_id": str(card_id), "card_no": card.card_no, "status": "active"}

    async def list_cards_by_customer(
        self,
        db: AsyncSession,
        customer_id: uuid.UUID,
        tenant_id: uuid.UUID,
        include_inactive: bool = False,
    ) -> list[dict]:
        """查询会员名下所有储值卡（按 customer_id）

        参数：
            include_inactive: True 时返回所有卡（含冻结/过期），
                              False 时只返回 active 卡（默认）。
        """
        from models.stored_value import StoredValueCard

        stmt = (
            select(StoredValueCard)
            .where(
                StoredValueCard.customer_id == customer_id,
                StoredValueCard.tenant_id == tenant_id,
                StoredValueCard.is_deleted.is_(False),
            )
            .order_by(StoredValueCard.created_at.asc())
        )
        if not include_inactive:
            stmt = stmt.where(StoredValueCard.status == "active")

        result = await db.execute(stmt)
        cards = result.scalars().all()
        return [_card_to_dict(c) for c in cards]

    # ──────────────────────────────────────────────────────────────
    # 积分兑换余额
    # ──────────────────────────────────────────────────────────────

    async def exchange_points_for_balance(
        self,
        db: AsyncSession,
        tenant_id: uuid.UUID,
        member_id: uuid.UUID,
        points: int,
        points_to_fen_ratio: int = 100,
    ) -> dict:
        """积分兑换储值余额

        流程：
        1. 查找会员储值卡（按 customer_id，取第一张 active 卡）
        2. 从 member_cards 扣除积分（乐观检查余额）
        3. 将兑换金额充入储值卡余额（作为本金）
        4. 记录 sv_transactions 流水（type='exchange'）
        5. 返回交易记录

        参数：
            points: 要兑换的积分数（> 0）
            points_to_fen_ratio: 每多少积分兑换 1 分（默认 100 积分 = 1 分钱）

        异常：
            ValueError: points <= 0
            CardNotFoundError: 该会员没有 active 储值卡
            InsufficientBalanceError: 积分余额不足
        """
        from models.stored_value import StoredValueCard, StoredValueTransaction
        from sqlalchemy import text

        if points <= 0:
            raise ValueError("兑换积分必须大于0")

        amount_fen = points // points_to_fen_ratio
        if amount_fen <= 0:
            raise ValueError(f"积分不足以兑换（需至少 {points_to_fen_ratio} 积分兑换 1 分钱，当前 {points} 积分）")

        # 1. 查找会员 active 储值卡（customer_id = member_id）
        card_result = await db.execute(
            select(StoredValueCard)
            .where(
                StoredValueCard.customer_id == member_id,
                StoredValueCard.tenant_id == tenant_id,
                StoredValueCard.status == "active",
                StoredValueCard.is_deleted.is_(False),
            )
            .order_by(StoredValueCard.created_at.asc())
            .limit(1)
            .with_for_update()
        )
        card = card_result.scalar_one_or_none()
        if not card:
            raise CardNotFoundError(f"会员 {member_id} 没有有效的储值卡，请先开卡")

        # 2. 从 member_cards 扣积分（raw SQL，兼容现有积分体系）
        deduct_result = await db.execute(
            text(
                "UPDATE member_cards "
                "SET points = points - :pts, updated_at = :now "
                "WHERE customer_id = :mid AND tenant_id = :tid "
                "AND is_deleted = false AND points >= :pts "
                "RETURNING id, points"
            ),
            {
                "pts": points,
                "mid": member_id,
                "tid": tenant_id,
                "now": datetime.now(timezone.utc),
            },
        )
        row = deduct_result.fetchone()
        if not row:
            raise InsufficientBalanceError(f"积分余额不足（需 {points} 积分）或会员卡不存在")

        # 3. 充入储值卡（仅充本金）
        balance_before = card.balance_fen
        card.main_balance_fen += amount_fen
        card.balance_fen = card.main_balance_fen + card.gift_balance_fen
        card.total_recharged_fen += amount_fen

        # 4. 记录流水
        txn = StoredValueTransaction(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            card_id=card.id,
            customer_id=member_id,
            txn_type="exchange",
            amount_fen=amount_fen,
            main_amount_fen=amount_fen,
            gift_amount_fen=0,
            balance_after_fen=card.balance_fen,
            gift_balance_after_fen=card.gift_balance_fen,
            remark=f"积分兑换余额：{points} 积分 → {amount_fen / 100:.2f} 元",
        )
        db.add(txn)

        logger.info(
            "stored_value_exchange_points",
            member_id=str(member_id),
            points=points,
            amount_fen=amount_fen,
            card_id=str(card.id),
        )

        return {
            **_txn_to_dict(txn),
            "points_deducted": points,
            "balance_before_fen": balance_before,
        }

    # ──────────────────────────────────────────────────────────────
    # 跨店分账辅助方法
    # ──────────────────────────────────────────────────────────────

    async def _trigger_cross_store_split(
        self,
        db: AsyncSession,
        tenant_id: uuid.UUID,
        transaction_id: uuid.UUID,
        recharge_store_id: uuid.UUID,
        consume_store_id: uuid.UUID,
        amount_fen: int,
    ) -> dict | None:
        """跨店消费时触发分账（异常不阻塞主流程）"""
        try:
            from services.tx_finance_client import get_split_service

            split_svc = get_split_service(db, str(tenant_id))
            return await split_svc.trigger_split_on_consume(
                transaction_id=str(transaction_id),
                recharge_store_id=str(recharge_store_id),
                consume_store_id=str(consume_store_id),
                amount_fen=amount_fen,
            )
        except ImportError:
            # tx-finance 客户端未配置，降级跳过
            logger.warning(
                "sv_split.client_unavailable",
                transaction_id=str(transaction_id),
            )
            return None
        except Exception:
            # 分账失败不阻塞消费主流程，记录日志后续人工处理
            logger.exception(
                "sv_split.trigger_failed",
                transaction_id=str(transaction_id),
            )
            return None

    async def _trigger_split_reversal(
        self,
        db: AsyncSession,
        tenant_id: uuid.UUID,
        original_order_id: str,
        refund_transaction_id: str,
        refund_amount_fen: int,
    ) -> dict | None:
        """退款时触发分账冲正（异常不阻塞主流程）"""
        try:
            from services.tx_finance_client import get_split_service

            split_svc = get_split_service(db, str(tenant_id))
            return await split_svc.create_reversal_record(
                original_transaction_id=original_order_id,
                refund_transaction_id=refund_transaction_id,
                refund_amount_fen=refund_amount_fen,
            )
        except ImportError:
            logger.warning(
                "sv_split_reversal.client_unavailable",
                original_order_id=original_order_id,
            )
            return None
        except Exception:
            logger.exception(
                "sv_split_reversal.trigger_failed",
                original_order_id=original_order_id,
            )
            return None

    # ──────────────────────────────────────────────────────────────
    # 内部辅助方法
    # ──────────────────────────────────────────────────────────────

    async def _get_active_card_for_update(self, db: AsyncSession, card_no: str):
        """获取活跃卡并加行锁（防并发）— 按卡号"""
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

    async def _get_card_by_id_for_update(
        self,
        db: AsyncSession,
        card_id: uuid.UUID,
        tenant_id: uuid.UUID,
    ):
        """获取卡并加行锁（防并发）— 按 card_id，带 tenant_id 校验"""
        from models.stored_value import StoredValueCard

        result = await db.execute(
            select(StoredValueCard)
            .where(
                StoredValueCard.id == card_id,
                StoredValueCard.tenant_id == tenant_id,
                StoredValueCard.is_deleted.is_(False),
            )
            .with_for_update()
        )
        card = result.scalar_one_or_none()
        if not card:
            raise ValueError(f"储值卡不存在: {card_id}")
        return card

    async def _match_recharge_gift(
        self,
        db: AsyncSession,
        amount_fen: int,
        store_id: str | None,
    ) -> int:
        """匹配充值赠送规则，返回赠送金额（v1 兼容）"""
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


# ──────────────────────────────────────────────────────────────────
# 序列化辅助函数
# ──────────────────────────────────────────────────────────────────


def _card_to_dict(card) -> dict:
    return {
        "id": str(card.id),
        "card_no": card.card_no,
        "customer_id": str(card.customer_id),
        "store_id": str(card.store_id) if card.store_id else None,
        "balance_fen": card.balance_fen,
        "main_balance_fen": card.main_balance_fen,
        "gift_balance_fen": card.gift_balance_fen,
        "total_recharged_fen": card.total_recharged_fen,
        "total_consumed_fen": card.total_consumed_fen,
        "total_refunded_fen": card.total_refunded_fen,
        "scope_type": card.scope_type,
        "scope_id": str(card.scope_id) if getattr(card, "scope_id", None) else None,
        "status": card.status,
        "expiry_date": str(card.expiry_date) if getattr(card, "expiry_date", None) else None,
        "remark": card.remark,
        "created_at": str(card.created_at) if card.created_at else None,
    }


def _txn_to_dict(txn) -> dict:
    return {
        "id": str(txn.id),
        "card_id": str(txn.card_id),
        "customer_id": str(txn.customer_id) if txn.customer_id else None,
        "store_id": str(txn.store_id) if txn.store_id else None,
        "txn_type": txn.txn_type,
        "amount_fen": txn.amount_fen,
        "main_amount_fen": txn.main_amount_fen,
        "gift_amount_fen": txn.gift_amount_fen,
        "balance_after_fen": txn.balance_after_fen,
        "order_id": str(txn.order_id) if txn.order_id else None,
        "recharge_plan_id": txn.recharge_plan_id,
        "operator_id": str(txn.operator_id) if txn.operator_id else None,
        "remark": txn.remark,
        "created_at": str(txn.created_at) if txn.created_at else None,
    }


def _plan_to_dict(plan) -> dict:
    return {
        "id": str(plan.id),
        "name": plan.name,
        "recharge_amount_fen": plan.recharge_amount_fen,
        "gift_amount_fen": plan.gift_amount_fen,
        "scope_type": plan.scope_type,
        "is_active": plan.is_active,
        "sort_order": plan.sort_order,
        "valid_from": str(plan.valid_from) if plan.valid_from else None,
        "valid_until": str(plan.valid_until) if plan.valid_until else None,
        "remark": getattr(plan, "remark", None),
        "created_at": str(plan.created_at) if plan.created_at else None,
    }


def _check_card_active_and_not_expired(card) -> None:
    """检查卡状态为 active 且未过期"""
    if card.status != "active":
        raise CardNotActiveError(f"储值卡状态异常: {card.status}")
    expiry: date | None = getattr(card, "expiry_date", None)
    if expiry and expiry < datetime.now(timezone.utc).date():
        raise CardNotActiveError("储值卡已过期")
