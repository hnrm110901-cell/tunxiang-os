"""
备用金服务（状态机核心）
负责备用金账户全生命周期管理。

核心设计原则：
  1. 每笔 Transaction 写入时同步更新 Account.balance（强一致性）
  2. 所有补充申请由 Agent 起草，付款必须人工审批（安全红线）
  3. 异常标记不自动驳回，由人工核实（可解释性原则）
  4. 日结对账是自动化流程，差异>50元才触发人工介入

金额约定：所有入参和存储均为分(fen)。
"""

from __future__ import annotations

import asyncio
import uuid
from calendar import monthrange
from datetime import date, datetime, timedelta, timezone
from typing import Optional

import structlog
from fastapi import HTTPException, status
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.expense_enums import (
    NotificationEventType,
    PettyCashAccountStatus,
    PettyCashSettlementStatus,
    PettyCashTransactionType,
)
from ..models.petty_cash import (
    PettyCashAccount,
    PettyCashSettlement,
    PettyCashTransaction,
)
from . import notification_service

logger = structlog.get_logger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# 内部工具
# ─────────────────────────────────────────────────────────────────────────────


def _now_utc() -> datetime:
    return datetime.now(tz=timezone.utc)


def _today() -> date:
    return datetime.now(tz=timezone.utc).date()


async def _get_account_by_id(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    account_id: uuid.UUID,
) -> PettyCashAccount:
    """按 account_id 查询账户（防跨租户）。内部工具。"""
    stmt = select(PettyCashAccount).where(
        PettyCashAccount.tenant_id == tenant_id,
        PettyCashAccount.id == account_id,
    )
    result = await db.execute(stmt)
    account = result.scalar_one_or_none()
    if account is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"备用金账户不存在或无权限访问（account_id={account_id}）",
        )
    return account


# ─────────────────────────────────────────────────────────────────────────────
# 1. create_account
# ─────────────────────────────────────────────────────────────────────────────


async def create_account(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    store_id: uuid.UUID,
    brand_id: uuid.UUID,
    keeper_id: uuid.UUID,
    approved_limit: int,
    warning_threshold: int,
    opening_balance: int = 0,
) -> PettyCashAccount:
    """开设备用金账户（每门店唯一）。

    检查 store_id 是否已有账户（UNIQUE 约束，提前检查给友好报错）。
    若 opening_balance > 0，同时写一条 OPENING_BALANCE 流水。

    Args:
        approved_limit:      审批额度上限，单位：分(fen)
        warning_threshold:   预警阈值，单位：分(fen)
        opening_balance:     期初余额，单位：分(fen)，默认 0

    Raises:
        HTTPException 409: 该门店已有备用金账户
        HTTPException 400: 参数校验失败
    """
    if approved_limit <= 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="审批额度上限必须大于0",
        )
    if warning_threshold < 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="预警阈值不能为负数",
        )
    if opening_balance < 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="期初余额不能为负数",
        )

    # 软检查：先查询是否已有账户，给出清晰错误信息
    existing_stmt = select(PettyCashAccount).where(
        PettyCashAccount.tenant_id == tenant_id,
        PettyCashAccount.store_id == store_id,
    )
    existing_result = await db.execute(existing_stmt)
    existing = existing_result.scalar_one_or_none()
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="该门店已开设备用金账户，不可重复开设",
        )

    account = PettyCashAccount(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        store_id=store_id,
        brand_id=brand_id,
        keeper_id=keeper_id,
        balance=opening_balance,
        approved_limit=approved_limit,
        warning_threshold=warning_threshold,
        daily_avg_7d=0,
        status=PettyCashAccountStatus.ACTIVE.value,
    )
    db.add(account)

    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="该门店已开设备用金账户，不可重复开设",
        )

    # 若期初余额 > 0，自动创建 OPENING_BALANCE 流水
    if opening_balance > 0:
        opening_txn = PettyCashTransaction(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            account_id=account.id,
            transaction_type=PettyCashTransactionType.OPENING_BALANCE.value,
            amount=opening_balance,
            balance_after=opening_balance,
            description="期初备用金录入",
            operator_id=keeper_id,
            is_reconciled=False,
            expense_date=_today(),
        )
        db.add(opening_txn)
        await db.flush()

    logger.info(
        "petty_cash_account_created",
        tenant_id=str(tenant_id),
        store_id=str(store_id),
        account_id=str(account.id),
        opening_balance=opening_balance,
        approved_limit=approved_limit,
    )

    return account


# ─────────────────────────────────────────────────────────────────────────────
# 2. get_account
# ─────────────────────────────────────────────────────────────────────────────


async def get_account(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    store_id: uuid.UUID,
) -> PettyCashAccount:
    """按门店查询备用金账户（防跨租户）。

    Raises:
        HTTPException 404: 该门店尚未开设备用金账户
    """
    stmt = select(PettyCashAccount).where(
        PettyCashAccount.tenant_id == tenant_id,
        PettyCashAccount.store_id == store_id,
    )
    result = await db.execute(stmt)
    account = result.scalar_one_or_none()

    if account is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="该门店尚未开设备用金账户",
        )

    return account


# ─────────────────────────────────────────────────────────────────────────────
# 3. record_expense
# ─────────────────────────────────────────────────────────────────────────────


async def record_expense(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    account_id: uuid.UUID,
    amount: int,
    description: str,
    operator_id: uuid.UUID,
    expense_date: date,
    reference_id: Optional[uuid.UUID] = None,
    reference_type: Optional[str] = None,
    notes: Optional[str] = None,
) -> PettyCashTransaction:
    """录入日常支出流水（DAILY_USE）。

    Args:
        amount:       支出金额，单位：分(fen)，必须 > 0（服务层内部转为负数存储）
        description:  流水描述
        expense_date: 费用发生日期（业务日期）

    余额不足时仍允许记录，但在 notes 中追加余额不足警告。
    录入后若余额低于 warning_threshold，异步推送预警（旁路不阻塞）。

    Raises:
        HTTPException 400: amount <= 0
    """
    if amount <= 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="支出金额必须大于0",
        )

    account = await _get_account_by_id(db, tenant_id, account_id)

    balance_after = account.balance - amount

    # 余额不足时追加警告到 notes，但仍允许记录（不拦截）
    warning_note: Optional[str] = None
    if balance_after < 0:
        warning_note = (
            f"【余额不足警告】本次支出后余额为 {balance_after} 分，已透支 {abs(balance_after)} 分，请尽快申请补充"
        )
        combined_notes = "\n".join(filter(None, [notes, warning_note]))
    else:
        combined_notes = notes

    txn = PettyCashTransaction(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        account_id=account_id,
        transaction_type=PettyCashTransactionType.DAILY_USE.value,
        amount=-amount,  # 支出存为负数
        balance_after=balance_after,
        description=description,
        reference_id=reference_id,
        reference_type=reference_type,
        operator_id=operator_id,
        is_reconciled=False,
        expense_date=expense_date,
        notes=combined_notes,
    )
    db.add(txn)

    # 同步更新账户余额（同一事务，保证原子性）
    account.balance = balance_after
    account.updated_at = _now_utc()

    await db.flush()

    logger.info(
        "petty_cash_expense_recorded",
        tenant_id=str(tenant_id),
        account_id=str(account_id),
        amount=amount,
        balance_after=balance_after,
        operator_id=str(operator_id),
    )

    # 余额预警检查（旁路，不阻塞主业务）
    if balance_after < account.warning_threshold:
        logger.warning(
            "petty_cash_balance_warning",
            tenant_id=str(tenant_id),
            account_id=str(account_id),
            balance_after=balance_after,
            warning_threshold=account.warning_threshold,
        )
        asyncio.create_task(
            notification_service.send_notification(
                db=db,
                tenant_id=tenant_id,
                application_id=account.id,  # 以 account.id 作为关联ID
                recipient_id=account.keeper_id,
                recipient_role="store_keeper",
                event_type=NotificationEventType.REMINDER.value,
                application_title="备用金余额预警",
                applicant_name="系统",
                total_amount=balance_after,
                store_name=str(account.store_id),
                brand_id=account.brand_id,
                comment=(
                    f"当前余额 {balance_after} 分（{round(balance_after / 100, 2)} 元），"
                    f"已低于预警阈值 {account.warning_threshold} 分，请及时申请补充"
                ),
            )
        )

    return txn


# ─────────────────────────────────────────────────────────────────────────────
# 4. record_replenishment
# ─────────────────────────────────────────────────────────────────────────────


async def record_replenishment(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    account_id: uuid.UUID,
    amount: int,
    operator_id: uuid.UUID,
    reference_id: Optional[uuid.UUID] = None,
    notes: Optional[str] = None,
) -> PettyCashTransaction:
    """补充备用金入账（审批通过后由财务/系统调用）。

    创建 REPLENISHMENT 流水（amount 正数），同步更新 Account.balance += amount。

    Args:
        amount: 补充金额，单位：分(fen)，必须 > 0

    Raises:
        HTTPException 400: 金额非正或账户已关闭
    """
    if amount <= 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="补充金额必须大于0",
        )

    account = await _get_account_by_id(db, tenant_id, account_id)

    if account.status == PettyCashAccountStatus.CLOSED.value:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="备用金账户已关闭，无法补充入账",
        )

    balance_after = account.balance + amount

    txn = PettyCashTransaction(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        account_id=account_id,
        transaction_type=PettyCashTransactionType.REPLENISHMENT.value,
        amount=amount,  # 收入为正数
        balance_after=balance_after,
        description=f"备用金补充拨付，金额 {amount} 分",
        reference_id=reference_id,
        reference_type="expense_application" if reference_id else None,
        operator_id=operator_id,
        is_reconciled=False,
        expense_date=_today(),
        notes=notes,
    )
    db.add(txn)

    # 同步更新账户余额（同一事务，保证原子性）
    account.balance = balance_after
    account.updated_at = _now_utc()

    await db.flush()

    logger.info(
        "petty_cash_replenished",
        tenant_id=str(tenant_id),
        account_id=str(account_id),
        amount=amount,
        balance_after=balance_after,
        operator_id=str(operator_id),
    )

    return txn


# ─────────────────────────────────────────────────────────────────────────────
# 5. reconcile_with_pos
# ─────────────────────────────────────────────────────────────────────────────


async def reconcile_with_pos(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    store_id: uuid.UUID,
    pos_session_id: str,
    pos_reported_balance: int,
) -> dict:
    """与 POS 日结数据对账（比较账户余额快照 vs POS 上报余额）。

    差异处理策略：
        |diff| <= 5000（50元）：自动调平，写 POS_RECONCILE_ADJUST 流水，更新余额，标记 last_reconciled_at
        |diff| >  5000：不自动调平，返回差异信息，更新 last_reconciled_at 但不改 balance

    Args:
        pos_reported_balance: POS 日结上报的备用金余额，单位：分(fen)

    Returns:
        {
            "status": "ok" | "diff_detected",
            "diff": int,                    # pos_reported_balance - account.balance
            "account_balance": int,         # 当前账户余额（分）
            "pos_balance": int,             # POS 上报余额（分）
            "requires_explanation": bool,   # diff_detected 时为 True
        }
    """
    account = await get_account(db, tenant_id, store_id)

    diff = pos_reported_balance - account.balance
    abs_diff = abs(diff)

    now = _now_utc()
    account.last_reconciled_at = now
    account.pos_session_ref = pos_session_id
    account.updated_at = now

    if abs_diff <= 5000:
        # 自动调平：差异 <= 50元
        if diff != 0:
            balance_after = account.balance + diff
            adjust_txn = PettyCashTransaction(
                id=uuid.uuid4(),
                tenant_id=tenant_id,
                account_id=account.id,
                transaction_type=PettyCashTransactionType.POS_RECONCILE_ADJUST.value,
                amount=diff,
                balance_after=balance_after,
                description=(f"POS日结对账自动调平，差额 {diff} 分，POS日结ID: {pos_session_id}"),
                reference_type="pos_session",
                operator_id=account.keeper_id,
                is_reconciled=True,
                reconciled_at=now,
                expense_date=_today(),
            )
            db.add(adjust_txn)
            account.balance = balance_after
            account.updated_at = now

        await db.flush()

        logger.info(
            "petty_cash_pos_reconcile_ok",
            tenant_id=str(tenant_id),
            store_id=str(store_id),
            pos_session_id=pos_session_id,
            diff=diff,
            account_balance=account.balance,
        )

        return {
            "status": "ok",
            "diff": diff,
            "account_balance": account.balance,
            "pos_balance": pos_reported_balance,
            "requires_explanation": False,
        }

    else:
        # 差异 > 50元：不自动调平，标记需人工介入
        await db.flush()

        logger.warning(
            "petty_cash_pos_reconcile_diff_detected",
            tenant_id=str(tenant_id),
            store_id=str(store_id),
            pos_session_id=pos_session_id,
            diff=diff,
            abs_diff=abs_diff,
            account_balance=account.balance,
            pos_reported_balance=pos_reported_balance,
        )

        return {
            "status": "diff_detected",
            "diff": diff,
            "account_balance": account.balance,
            "pos_balance": pos_reported_balance,
            "requires_explanation": True,
        }


# ─────────────────────────────────────────────────────────────────────────────
# 6. freeze_account
# ─────────────────────────────────────────────────────────────────────────────


async def freeze_account(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    account_id: uuid.UUID,
    reason: str,
    operator_id: uuid.UUID,
) -> PettyCashAccount:
    """冻结备用金账户（员工离职、异常等场景）。

    状态改为 FROZEN，记录 frozen_reason + frozen_at。
    写一条 FREEZE_RESERVE 流水（amount=0，description=reason）。

    Raises:
        HTTPException 400: 账户已冻结或已关闭
    """
    account = await _get_account_by_id(db, tenant_id, account_id)

    if account.status == PettyCashAccountStatus.FROZEN.value:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="备用金账户已处于冻结状态",
        )
    if account.status == PettyCashAccountStatus.CLOSED.value:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="备用金账户已关闭，无法冻结",
        )

    now = _now_utc()
    account.status = PettyCashAccountStatus.FROZEN.value
    account.frozen_reason = reason
    account.frozen_at = now
    account.updated_at = now

    # 创建 FREEZE_RESERVE 流水（amount=0，仅记录冻结事件）
    freeze_txn = PettyCashTransaction(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        account_id=account_id,
        transaction_type=PettyCashTransactionType.FREEZE_RESERVE.value,
        amount=0,
        balance_after=account.balance,
        description=reason,
        operator_id=operator_id,
        is_reconciled=True,
        reconciled_at=now,
        expense_date=_today(),
    )
    db.add(freeze_txn)

    await db.flush()

    logger.info(
        "petty_cash_account_frozen",
        tenant_id=str(tenant_id),
        account_id=str(account_id),
        store_id=str(account.store_id),
        reason=reason,
        operator_id=str(operator_id),
    )

    # 旁路通知（推送给 keeper_id）
    asyncio.create_task(
        notification_service.send_notification(
            db=db,
            tenant_id=tenant_id,
            application_id=account.id,
            recipient_id=account.keeper_id,
            recipient_role="store_keeper",
            event_type=NotificationEventType.REMINDER.value,
            application_title="备用金账户冻结通知",
            applicant_name="系统",
            total_amount=account.balance,
            store_name=str(account.store_id),
            brand_id=account.brand_id,
            comment=f"账户已冻结，原因：{reason}。当前余额 {account.balance} 分待归还确认。",
        )
    )

    return account


# ─────────────────────────────────────────────────────────────────────────────
# 7. unfreeze_account
# ─────────────────────────────────────────────────────────────────────────────


async def unfreeze_account(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    account_id: uuid.UUID,
    operator_id: uuid.UUID,
    returned_amount: int = 0,
) -> PettyCashAccount:
    """解冻备用金账户（状态 FROZEN → ACTIVE，清空 frozen_reason/frozen_at）。

    若 returned_amount > 0，先创建 RETURN_FROM_KEEPER 流水（归还确认入账）。

    Args:
        returned_amount: 员工归还金额，单位：分(fen)，默认 0（不归还直接解冻）

    Raises:
        HTTPException 400: 账户不处于冻结状态
    """
    account = await _get_account_by_id(db, tenant_id, account_id)

    if account.status != PettyCashAccountStatus.FROZEN.value:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"账户当前状态为 '{account.status}'，只有冻结状态的账户才可解冻",
        )

    now = _now_utc()

    # 若有归还金额，先写归还流水
    if returned_amount > 0:
        balance_after = account.balance + returned_amount
        return_txn = PettyCashTransaction(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            account_id=account_id,
            transaction_type=PettyCashTransactionType.RETURN_FROM_KEEPER.value,
            amount=returned_amount,
            balance_after=balance_after,
            description=f"员工归还备用金，归还金额 {returned_amount} 分",
            operator_id=operator_id,
            is_reconciled=False,
            expense_date=_today(),
        )
        db.add(return_txn)
        account.balance = balance_after

    account.status = PettyCashAccountStatus.ACTIVE.value
    account.frozen_reason = None
    account.frozen_at = None
    account.updated_at = now

    await db.flush()

    logger.info(
        "petty_cash_account_unfrozen",
        tenant_id=str(tenant_id),
        account_id=str(account_id),
        store_id=str(account.store_id),
        operator_id=str(operator_id),
        returned_amount=returned_amount,
    )

    return account


# ─────────────────────────────────────────────────────────────────────────────
# 8. draft_replenishment_request
# ─────────────────────────────────────────────────────────────────────────────


async def draft_replenishment_request(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    account_id: uuid.UUID,
    operator_id: uuid.UUID,
) -> dict:
    """A1 Agent 触发：余额低于阈值时自动起草补充申请草稿。

    !! 安全红线 !!
    此方法只起草草稿，不触发付款，不提交申请。
    资金流出必须经人工审批（店长确认后手动提交 expense_application）。

    建议补充金额 = max(daily_avg_7d * 30, warning_threshold)
    不超过 approved_limit（不超上限）。

    Returns:
        {
            "application_id": None,          # 草稿尚未创建申请单，由前端触发后创建
            "suggested_amount": int,         # 分(fen)
            "reason": str,
        }
    """
    account = await _get_account_by_id(db, tenant_id, account_id)

    daily_avg = account.daily_avg_7d or 0
    # 建议金额：月均消耗 or 预警阈值，取较大值
    monthly_avg = daily_avg * 30
    suggested_amount = max(monthly_avg, account.warning_threshold)

    # 不超过审批额度上限
    suggested_amount = min(suggested_amount, account.approved_limit)

    days_left = round(account.balance / daily_avg, 1) if daily_avg > 0 else 999.0

    reason = (
        f"余额低于阈值自动起草：当前余额 {account.balance} 分"
        f"（{round(account.balance / 100, 2)} 元），"
        f"预警阈值 {account.warning_threshold} 分，"
        f"预计可用 {days_left} 天；"
        f"建议补充 {suggested_amount} 分（{round(suggested_amount / 100, 2)} 元）"
    )

    logger.info(
        "petty_cash_replenishment_draft_created",
        tenant_id=str(tenant_id),
        account_id=str(account_id),
        store_id=str(account.store_id),
        current_balance=account.balance,
        suggested_amount=suggested_amount,
        operator_id=str(operator_id),
    )

    # application_id 为 None：只返回建议，前端确认后调用 expense_application_service.create_application()
    store_name = str(account.store_id)  # 暂用 store_id 字符串，路由层可按需替换为真实门店名
    prefill_title = f"【{store_name}】备用金补充申请"
    prefill_notes = (
        f"当前余额 {account.balance} 分（{round(account.balance / 100, 2)} 元），"
        f"预计可用 {days_left} 天。"
        f"建议补充金额 {suggested_amount} 分（{round(suggested_amount / 100, 2)} 元），"
        f"基于近7日日均消耗 {account.daily_avg_7d} 分 × 30天 × 30%。"
    )

    return {
        "application_id": None,
        "suggested_amount": suggested_amount,
        "reason": reason,
        "scenario_code": "PETTY_CASH_REQUEST",
        "prefill_title": prefill_title,
        "prefill_notes": prefill_notes,
    }


# ─────────────────────────────────────────────────────────────────────────────
# 9. update_daily_avg
# ─────────────────────────────────────────────────────────────────────────────


async def update_daily_avg(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    account_id: uuid.UUID,
) -> int:
    """计算并更新近7天 DAILY_USE 流水日均消耗。

    Args:
        account_id: 备用金账户ID

    Returns:
        新的日均消耗值，单位：分(fen)
    """
    account = await _get_account_by_id(db, tenant_id, account_id)

    today = _today()
    seven_days_ago = today - timedelta(days=6)

    # 统计近7天 DAILY_USE 流水合计（amount 为负数，取绝对值）
    sum_stmt = select(func.coalesce(func.sum(PettyCashTransaction.amount), 0).label("total_expense")).where(
        PettyCashTransaction.tenant_id == tenant_id,
        PettyCashTransaction.account_id == account_id,
        PettyCashTransaction.transaction_type == PettyCashTransactionType.DAILY_USE.value,
        PettyCashTransaction.expense_date >= seven_days_ago,
        PettyCashTransaction.expense_date <= today,
    )
    sum_result = await db.execute(sum_stmt)
    total_expense_signed = int(sum_result.scalar_one())

    # 7天内实际有流水的天数（避免新账户用固定7除）
    days_stmt = select(func.count(PettyCashTransaction.expense_date.distinct()).label("days_count")).where(
        PettyCashTransaction.tenant_id == tenant_id,
        PettyCashTransaction.account_id == account_id,
        PettyCashTransaction.transaction_type == PettyCashTransactionType.DAILY_USE.value,
        PettyCashTransaction.expense_date >= seven_days_ago,
        PettyCashTransaction.expense_date <= today,
    )
    days_result = await db.execute(days_stmt)
    days_with_expense = int(days_result.scalar_one())

    if days_with_expense > 0:
        new_daily_avg = abs(total_expense_signed) // days_with_expense
    else:
        new_daily_avg = 0

    account.daily_avg_7d = new_daily_avg
    account.updated_at = _now_utc()

    await db.flush()

    logger.info(
        "petty_cash_daily_avg_updated",
        tenant_id=str(tenant_id),
        account_id=str(account_id),
        new_daily_avg=new_daily_avg,
        days_with_expense=days_with_expense,
        seven_day_total=abs(total_expense_signed),
    )

    return new_daily_avg


# ─────────────────────────────────────────────────────────────────────────────
# 10. generate_monthly_settlement
# ─────────────────────────────────────────────────────────────────────────────


async def generate_monthly_settlement(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    account_id: uuid.UUID,
    settlement_month: str,
) -> PettyCashSettlement:
    """生成月末核销单（幂等操作）。

    Args:
        settlement_month: 格式 "YYYY-MM"，如 "2026-04"

    幂等：若该月核销单已存在，直接返回现有核销单（不重复生成）。
    汇总该月所有流水：total_income（正数流水之和）、total_expense（负数流水绝对值之和）。
    统计 reconciled_count 和 unreconciled_count。
    创建 DRAFT 状态核销单。

    Raises:
        HTTPException 400: settlement_month 格式错误
    """
    # 解析月份
    try:
        year_str, month_str = settlement_month.split("-")
        year = int(year_str)
        month = int(month_str)
        if not (1 <= month <= 12):
            raise ValueError("月份范围错误")
    except (ValueError, AttributeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"settlement_month 格式错误，应为 YYYY-MM：{exc}",
        )

    account = await _get_account_by_id(db, tenant_id, account_id)

    # 幂等检查：是否已有该月核销单
    existing_stmt = select(PettyCashSettlement).where(
        PettyCashSettlement.tenant_id == tenant_id,
        PettyCashSettlement.account_id == account_id,
        PettyCashSettlement.settlement_month == settlement_month,
    )
    existing_result = await db.execute(existing_stmt)
    existing_settlement = existing_result.scalar_one_or_none()
    if existing_settlement is not None:
        logger.info(
            "petty_cash_settlement_already_exists",
            tenant_id=str(tenant_id),
            account_id=str(account_id),
            settlement_month=settlement_month,
            settlement_id=str(existing_settlement.id),
        )
        return existing_settlement

    # 统计期间
    _, last_day = monthrange(year, month)
    period_start = date(year, month, 1)
    period_end = date(year, month, last_day)

    # 统计本月流水
    txn_stmt = select(PettyCashTransaction).where(
        PettyCashTransaction.tenant_id == tenant_id,
        PettyCashTransaction.account_id == account_id,
        PettyCashTransaction.expense_date >= period_start,
        PettyCashTransaction.expense_date <= period_end,
    )
    txn_result = await db.execute(txn_stmt)
    transactions = list(txn_result.scalars().all())

    total_income = sum(t.amount for t in transactions if t.amount > 0)
    total_expense = sum(abs(t.amount) for t in transactions if t.amount < 0)
    reconciled_count = sum(1 for t in transactions if t.is_reconciled)
    unreconciled_count = sum(1 for t in transactions if not t.is_reconciled)

    # 期初余额：由流水反推（closing - income + expense）
    if transactions:
        sorted_by_date = sorted(
            transactions,
            key=lambda t: (t.expense_date, t.created_at if t.created_at else date.min),
        )
        closing_balance = sorted_by_date[-1].balance_after
        opening_balance = closing_balance - total_income + total_expense
    else:
        # 本月无流水：期初=期末=当前账户余额
        closing_balance = account.balance
        opening_balance = account.balance

    settlement = PettyCashSettlement(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        account_id=account_id,
        store_id=account.store_id,
        settlement_month=settlement_month,
        period_start=period_start,
        period_end=period_end,
        opening_balance=opening_balance,
        total_income=total_income,
        total_expense=total_expense,
        closing_balance=closing_balance,
        reconciled_count=reconciled_count,
        unreconciled_count=unreconciled_count,
        status=PettyCashSettlementStatus.DRAFT.value,
        generated_by="a1_agent",
    )
    db.add(settlement)

    await db.flush()

    logger.info(
        "petty_cash_settlement_generated",
        tenant_id=str(tenant_id),
        account_id=str(account_id),
        settlement_id=str(settlement.id),
        settlement_month=settlement_month,
        opening_balance=opening_balance,
        total_income=total_income,
        total_expense=total_expense,
        closing_balance=closing_balance,
        reconciled_count=reconciled_count,
        unreconciled_count=unreconciled_count,
    )

    return settlement


# ─────────────────────────────────────────────────────────────────────────────
# 11. confirm_settlement
# ─────────────────────────────────────────────────────────────────────────────


async def confirm_settlement(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    settlement_id: uuid.UUID,
    confirmed_by: uuid.UUID,
) -> PettyCashSettlement:
    """财务确认月末核销单（DRAFT/SUBMITTED → CONFIRMED）。

    - 记录 confirmed_by + confirmed_at
    - 将该月所有未核销流水标记为 is_reconciled=True

    Raises:
        HTTPException 404: 核销单不存在
        HTTPException 400: 核销单状态不允许确认（已是 CONFIRMED/CLOSED）
    """
    settlement_stmt = select(PettyCashSettlement).where(
        PettyCashSettlement.tenant_id == tenant_id,
        PettyCashSettlement.id == settlement_id,
    )
    settlement_result = await db.execute(settlement_stmt)
    settlement = settlement_result.scalar_one_or_none()

    if settlement is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"月末核销单不存在（settlement_id={settlement_id}）",
        )

    allowed_statuses = {
        PettyCashSettlementStatus.DRAFT.value,
        PettyCashSettlementStatus.SUBMITTED.value,
    }
    if settlement.status not in allowed_statuses:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(f"核销单当前状态为 '{settlement.status}'，只有 DRAFT 或 SUBMITTED 状态的核销单才可确认"),
        )

    now = _now_utc()
    settlement.status = PettyCashSettlementStatus.CONFIRMED.value
    settlement.confirmed_by = confirmed_by
    settlement.confirmed_at = now
    settlement.updated_at = now

    # 将该月期间内所有未核销流水标记为已核销
    reconcile_stmt = (
        update(PettyCashTransaction)
        .where(
            PettyCashTransaction.tenant_id == tenant_id,
            PettyCashTransaction.account_id == settlement.account_id,
            PettyCashTransaction.expense_date >= settlement.period_start,
            PettyCashTransaction.expense_date <= settlement.period_end,
            PettyCashTransaction.is_reconciled == False,  # noqa: E712
        )
        .values(
            is_reconciled=True,
            reconciled_at=now,
        )
    )
    await db.execute(reconcile_stmt)

    await db.flush()

    logger.info(
        "petty_cash_settlement_confirmed",
        tenant_id=str(tenant_id),
        settlement_id=str(settlement_id),
        account_id=str(settlement.account_id),
        settlement_month=settlement.settlement_month,
        confirmed_by=str(confirmed_by),
    )

    return settlement


# ─────────────────────────────────────────────────────────────────────────────
# 12. get_balance_summary
# ─────────────────────────────────────────────────────────────────────────────


async def get_balance_summary(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    brand_id: Optional[uuid.UUID] = None,
    store_ids: Optional[list[uuid.UUID]] = None,
) -> list[dict]:
    """查询多门店备用金余额汇总（用于总部/财务看板）。

    Args:
        brand_id:   可选，按品牌过滤
        store_ids:  可选，按门店列表过滤

    Returns:
        [
            {
                "store_id": str,
                "account_id": str,
                "balance": int,             # 分(fen)
                "warning_threshold": int,   # 分(fen)
                "status": str,
                "is_below_threshold": bool,
            },
            ...
        ]
    """
    conditions = [
        PettyCashAccount.tenant_id == tenant_id,
    ]
    if brand_id is not None:
        conditions.append(PettyCashAccount.brand_id == brand_id)
    if store_ids is not None:
        conditions.append(PettyCashAccount.store_id.in_(store_ids))

    stmt = select(PettyCashAccount).where(*conditions).order_by(PettyCashAccount.store_id)
    result = await db.execute(stmt)
    accounts = list(result.scalars().all())

    summary = [
        {
            "store_id": str(acc.store_id),
            "account_id": str(acc.id),
            "balance": acc.balance,
            "warning_threshold": acc.warning_threshold,
            "status": acc.status,
            "is_below_threshold": acc.balance < acc.warning_threshold,
        }
        for acc in accounts
    ]

    logger.info(
        "petty_cash_balance_summary_queried",
        tenant_id=str(tenant_id),
        brand_id=str(brand_id) if brand_id else None,
        store_count=len(summary),
        below_threshold_count=sum(1 for s in summary if s["is_below_threshold"]),
    )

    return summary


# ─────────────────────────────────────────────────────────────────────────────
# 13. get_account_by_store  （与 get_account 相同职责，预加载最近10条流水）
# ─────────────────────────────────────────────────────────────────────────────


async def get_account_by_store(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    store_id: uuid.UUID,
) -> PettyCashAccount:
    """按门店查询备用金账户，并预加载最近10条流水记录。

    Raises:
        HTTPException 404: 该门店尚未开设备用金账户
    """
    from sqlalchemy.orm import selectinload

    stmt = (
        select(PettyCashAccount)
        .where(
            PettyCashAccount.tenant_id == tenant_id,
            PettyCashAccount.store_id == store_id,
        )
        .options(selectinload(PettyCashAccount.transactions))
    )
    result = await db.execute(stmt)
    account = result.scalar_one_or_none()

    if account is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="该门店尚未开设备用金账户",
        )

    # 从已加载的 transactions 中保留最新10条（按 created_at DESC）
    if account.transactions:
        account.transactions.sort(
            key=lambda t: t.created_at or datetime.min.replace(tzinfo=timezone.utc),
            reverse=True,
        )
        # 截取前10条（SQLAlchemy relationship 返回完整列表，这里仅做展示截断）
        # 注意：此操作不修改数据库，仅影响当前对象的内存列表
        account.transactions[:] = account.transactions[:10]

    return account


# ─────────────────────────────────────────────────────────────────────────────
# 14. check_balance_alert
# ─────────────────────────────────────────────────────────────────────────────


async def check_balance_alert(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    account_id: uuid.UUID,
) -> Optional[dict]:
    """检查账户余额是否低于预警阈值，并计算可用天数覆盖率。

    用于 A1 Agent 定时巡检场景。

    Returns:
        若余额低于阈值，返回预警信息 dict；否则返回 None。

        预警 dict 格式::

            {
                "account_id": str,
                "store_id": str,
                "current_balance": int,      # 分(fen)
                "warning_threshold": int,    # 分(fen)
                "days_of_coverage": float,   # 按近7日均值，余额可维持天数
                "daily_avg_7d": int,         # 分(fen)
                "alert_level": "warning",    # 固定值，未来可扩展为 critical
            }
    """
    account = await _get_account_by_id(db, tenant_id, account_id)

    # daily_avg_7d = 0 时无法计算，返回 None
    if account.daily_avg_7d <= 0:
        return None

    days_of_coverage = account.balance / account.daily_avg_7d

    if account.balance < account.warning_threshold:
        alert = {
            "account_id": str(account.id),
            "store_id": str(account.store_id),
            "current_balance": account.balance,
            "warning_threshold": account.warning_threshold,
            "days_of_coverage": round(days_of_coverage, 1),
            "daily_avg_7d": account.daily_avg_7d,
            "alert_level": "warning",
        }
        logger.warning(
            "petty_cash_balance_alert_triggered",
            tenant_id=str(tenant_id),
            account_id=str(account_id),
            store_id=str(account.store_id),
            current_balance=account.balance,
            warning_threshold=account.warning_threshold,
            days_of_coverage=round(days_of_coverage, 1),
        )
        return alert

    return None


# ─────────────────────────────────────────────────────────────────────────────
# 15. get_account_stats  （看板统计视图）
# ─────────────────────────────────────────────────────────────────────────────


async def get_account_stats(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    store_id: Optional[uuid.UUID] = None,
    brand_id: Optional[uuid.UUID] = None,
) -> dict:
    """备用金账户统计看板（总部/财务视图）。

    Args:
        store_id:  可选，限定单门店
        brand_id:  可选，按品牌过滤

    Returns::

        {
            "total_accounts": int,
            "active_count": int,
            "frozen_count": int,
            "total_balance": int,           # 所有账户余额合计（分）
            "below_threshold_count": int,   # 低于预警阈值的账户数
            "unreconciled_this_month": int, # 本月未核销流水数
        }
    """
    from sqlalchemy import case

    # 账户级别统计条件
    account_conditions = [PettyCashAccount.tenant_id == tenant_id]
    if store_id is not None:
        account_conditions.append(PettyCashAccount.store_id == store_id)
    if brand_id is not None:
        account_conditions.append(PettyCashAccount.brand_id == brand_id)

    # 汇总：总数、各状态数、总余额、低于阈值数
    stats_stmt = select(
        func.count().label("total_accounts"),
        func.coalesce(
            func.sum(
                case(
                    (PettyCashAccount.status == PettyCashAccountStatus.ACTIVE.value, 1),
                    else_=0,
                )
            ),
            0,
        ).label("active_count"),
        func.coalesce(
            func.sum(
                case(
                    (PettyCashAccount.status == PettyCashAccountStatus.FROZEN.value, 1),
                    else_=0,
                )
            ),
            0,
        ).label("frozen_count"),
        func.coalesce(func.sum(PettyCashAccount.balance), 0).label("total_balance"),
        func.coalesce(
            func.sum(
                case(
                    (PettyCashAccount.balance < PettyCashAccount.warning_threshold, 1),
                    else_=0,
                )
            ),
            0,
        ).label("below_threshold_count"),
    ).where(*account_conditions)

    stats_result = await db.execute(stats_stmt)
    row = stats_result.mappings().one()

    total_accounts = int(row["total_accounts"])
    active_count = int(row["active_count"])
    frozen_count = int(row["frozen_count"])
    total_balance = int(row["total_balance"])
    below_threshold_count = int(row["below_threshold_count"])

    # 本月未核销流水数
    today = _today()
    month_start = date(today.year, today.month, 1)

    txn_conditions = [
        PettyCashTransaction.tenant_id == tenant_id,
        PettyCashTransaction.expense_date >= month_start,
        PettyCashTransaction.is_reconciled == False,  # noqa: E712
    ]
    if store_id is not None or brand_id is not None:
        # 需要 JOIN petty_cash_accounts 来过滤 store_id / brand_id
        unreconciled_stmt = (
            select(func.count())
            .select_from(PettyCashTransaction)
            .join(
                PettyCashAccount,
                PettyCashAccount.id == PettyCashTransaction.account_id,
            )
            .where(
                *txn_conditions,
                *([PettyCashAccount.store_id == store_id] if store_id else []),
                *([PettyCashAccount.brand_id == brand_id] if brand_id else []),
            )
        )
    else:
        unreconciled_stmt = select(func.count()).where(*txn_conditions)

    unreconciled_result = await db.execute(unreconciled_stmt)
    unreconciled_this_month = int(unreconciled_result.scalar_one())

    stats = {
        "total_accounts": total_accounts,
        "active_count": active_count,
        "frozen_count": frozen_count,
        "total_balance": total_balance,
        "below_threshold_count": below_threshold_count,
        "unreconciled_this_month": unreconciled_this_month,
    }

    logger.info(
        "petty_cash_stats_queried",
        tenant_id=str(tenant_id),
        store_id=str(store_id) if store_id else None,
        brand_id=str(brand_id) if brand_id else None,
        **stats,
    )

    return stats
