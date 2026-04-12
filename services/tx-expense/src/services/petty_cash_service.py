"""
备用金管理服务
核心是一个严格的状态机：账户余额必须与流水合计始终一致。

状态机转换：
  账户 active → frozen（员工离职）→ active（归还确认后）
  账户 active → closed（门店关店）

余额一致性保证：
  每次写 transaction 时，在同一事务内更新 account.balance = balance_after
  balance_after = 上次流水的 balance_after + 本次 amount

金额约定：所有金额参数和存储均为分(fen)。
"""
from __future__ import annotations

import asyncio
import uuid
from calendar import monthrange
from datetime import date, datetime, timezone
from typing import Optional

import structlog
from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
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


# ─────────────────────────────────────────────────────────────────────────────
# 1. open_account
# ─────────────────────────────────────────────────────────────────────────────

async def open_account(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    store_id: uuid.UUID,
    brand_id: uuid.UUID,
    keeper_id: uuid.UUID,
    approved_limit: int,
    warning_threshold: int,
    opening_balance: int = 0,
) -> PettyCashAccount:
    """开设备用金账户。

    每个门店只允许一个账户（tenant_id + store_id 唯一）。
    若 opening_balance > 0，自动生成一条 OPENING_BALANCE 流水。

    Args:
        approved_limit: 审批额度上限，单位：分(fen)
        warning_threshold: 预警阈值，单位：分(fen)
        opening_balance: 期初余额，单位：分(fen)，默认0

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
        "petty_cash_account_opened",
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
    """按门店查询备用金账户。

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
# 3. get_balance
# ─────────────────────────────────────────────────────────────────────────────

async def get_balance(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    store_id: uuid.UUID,
) -> dict:
    """查询门店备用金余额及运营指标。

    Returns:
        {
            "store_id": str,
            "balance": int,              # 当前余额（分）
            "balance_yuan": float,       # 元，/100
            "approved_limit": int,       # 审批额度（分）
            "warning_threshold": int,    # 预警阈值（分）
            "daily_avg_7d": int,         # 近7日日均消耗（分）
            "days_of_coverage": float,   # 可用天数（balance/daily_avg_7d，daily_avg=0时返回999）
            "status": str,
            "last_reconciled_at": str,   # ISO8601 或 None
            "is_warning": bool,          # balance < warning_threshold
        }
    """
    account = await get_account(db, tenant_id, store_id)

    daily_avg = account.daily_avg_7d or 0
    if daily_avg > 0:
        days_of_coverage = round(account.balance / daily_avg, 1)
    else:
        days_of_coverage = 999.0

    return {
        "store_id": str(store_id),
        "balance": account.balance,
        "balance_yuan": round(account.balance / 100, 2),
        "approved_limit": account.approved_limit,
        "warning_threshold": account.warning_threshold,
        "daily_avg_7d": daily_avg,
        "days_of_coverage": days_of_coverage,
        "status": account.status,
        "last_reconciled_at": (
            account.last_reconciled_at.isoformat()
            if account.last_reconciled_at
            else None
        ),
        "is_warning": account.balance < account.warning_threshold,
    }


# ─────────────────────────────────────────────────────────────────────────────
# 4. record_expense
# ─────────────────────────────────────────────────────────────────────────────

async def record_expense(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    store_id: uuid.UUID,
    amount: int,
    description: str,
    operator_id: uuid.UUID,
    expense_date: date,
    reference_id: Optional[uuid.UUID] = None,
) -> PettyCashTransaction:
    """录入日常支出流水。

    Args:
        amount: 支出金额，单位：分(fen)，必须 > 0（服务内部转为负数存入流水）

    Raises:
        HTTPException 400: 账户冻结/已关闭、金额非正、余额不足
    """
    if amount <= 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="支出金额必须大于0",
        )

    account = await get_account(db, tenant_id, store_id)

    if account.status == PettyCashAccountStatus.FROZEN.value:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="备用金账户已冻结，无法录入支出。请联系管理员处理",
        )
    if account.status == PettyCashAccountStatus.CLOSED.value:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="备用金账户已关闭，无法录入支出",
        )

    if account.balance - amount < 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"余额不足：当前余额 {account.balance} 分，"
                f"本次支出 {amount} 分，差额 {amount - account.balance} 分"
            ),
        )

    # 在同一事务内：计算余额 → 创建流水 → 更新账户
    balance_after = account.balance - amount

    txn = PettyCashTransaction(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        account_id=account.id,
        transaction_type=PettyCashTransactionType.DAILY_USE.value,
        amount=-amount,            # 支出存为负数
        balance_after=balance_after,
        description=description,
        reference_id=reference_id,
        operator_id=operator_id,
        is_reconciled=False,
        expense_date=expense_date,
    )
    db.add(txn)

    account.balance = balance_after
    account.updated_at = _now_utc()

    await db.flush()

    logger.info(
        "petty_cash_expense_recorded",
        tenant_id=str(tenant_id),
        store_id=str(store_id),
        account_id=str(account.id),
        amount=amount,
        balance_after=balance_after,
        operator_id=str(operator_id),
    )

    # 余额预警检查（旁路，不阻塞主业务）
    if balance_after < account.warning_threshold:
        logger.warning(
            "petty_cash_balance_warning",
            tenant_id=str(tenant_id),
            store_id=str(store_id),
            balance_after=balance_after,
            warning_threshold=account.warning_threshold,
        )
        # TODO P1: 换用专用 petty_cash_warning 通知事件类型
        asyncio.create_task(
            notification_service.send_notification(
                db=db,
                tenant_id=tenant_id,
                application_id=account.id,          # 占位：用 account.id 作为关联ID
                recipient_id=account.keeper_id,
                recipient_role="store_keeper",
                event_type=NotificationEventType.REMINDER.value,
                application_title="备用金余额预警",
                applicant_name="系统",
                total_amount=balance_after,
                store_name=str(store_id),
                brand_id=account.brand_id,
                comment=(
                    f"当前余额 {balance_after} 分（{round(balance_after/100,2)} 元），"
                    f"已低于预警阈值 {account.warning_threshold} 分，请及时申请补充"
                ),
            )
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
    pos_reported_expenses: int,
    reconcile_date: date,
) -> dict:
    """与POS日结数据对账。

    Args:
        pos_reported_expenses: POS日结推送的备用金支出金额，单位：分(fen)
        reconcile_date: 对账业务日期

    差异处理策略：
        |diff| <= 5000（50元）：自动创建 POS_RECONCILE_ADJUST 流水
        5000 < |diff| <= 30000（300元）：标记需人工确认
        |diff| > 30000：标记异常，TODO 写入 expense_agent_events

    Returns:
        {"status": "matched"|"adjusted"|"needs_review"|"anomaly", "diff": int, "pos_session_id": str}
    """
    account = await get_account(db, tenant_id, store_id)

    # 统计当日所有 DAILY_USE 流水金额合计（amount 为负数，取绝对值）
    daily_stmt = select(
        func.coalesce(func.sum(PettyCashTransaction.amount), 0).label("total")
    ).where(
        PettyCashTransaction.tenant_id == tenant_id,
        PettyCashTransaction.account_id == account.id,
        PettyCashTransaction.transaction_type == PettyCashTransactionType.DAILY_USE.value,
        PettyCashTransaction.expense_date == reconcile_date,
    )
    daily_result = await db.execute(daily_stmt)
    daily_total_signed = int(daily_result.scalar_one())
    # daily_total_signed 为负数或0，取绝对值得到系统侧支出合计
    system_expenses = abs(daily_total_signed)

    diff = pos_reported_expenses - system_expenses  # 正：POS多，负：系统多

    # 更新对账信息
    account.last_reconciled_at = _now_utc()
    account.pos_session_ref = pos_session_id
    account.updated_at = _now_utc()

    if diff == 0:
        await db.flush()
        logger.info(
            "petty_cash_pos_reconcile_matched",
            tenant_id=str(tenant_id),
            store_id=str(store_id),
            pos_session_id=pos_session_id,
            system_expenses=system_expenses,
            pos_reported_expenses=pos_reported_expenses,
        )
        return {"status": "matched", "diff": 0, "pos_session_id": pos_session_id}

    abs_diff = abs(diff)

    if abs_diff <= 5000:
        # 自动调整：创建 POS_RECONCILE_ADJUST 流水（正负视差异方向）
        balance_after = account.balance + diff

        adjust_txn = PettyCashTransaction(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            account_id=account.id,
            transaction_type=PettyCashTransactionType.POS_RECONCILE_ADJUST.value,
            amount=diff,
            balance_after=balance_after,
            description=(
                f"POS日结对账自动调整，差额 {diff} 分，POS日结ID: {pos_session_id}"
            ),
            reference_type="pos_session",
            operator_id=account.keeper_id,
            is_reconciled=True,
            reconciled_at=_now_utc(),
            expense_date=reconcile_date,
        )
        db.add(adjust_txn)
        account.balance = balance_after
        account.updated_at = _now_utc()

        await db.flush()

        logger.info(
            "petty_cash_pos_reconcile_adjusted",
            tenant_id=str(tenant_id),
            store_id=str(store_id),
            pos_session_id=pos_session_id,
            diff=diff,
            balance_after=balance_after,
        )
        return {"status": "adjusted", "diff": diff, "pos_session_id": pos_session_id}

    elif abs_diff <= 30000:
        # 需人工确认
        await db.flush()
        logger.warning(
            "petty_cash_pos_reconcile_needs_review",
            tenant_id=str(tenant_id),
            store_id=str(store_id),
            pos_session_id=pos_session_id,
            diff=diff,
            abs_diff=abs_diff,
        )
        return {
            "status": "needs_review",
            "diff": diff,
            "pos_session_id": pos_session_id,
        }

    else:
        # 异常：差异超过300元
        # TODO: 写入 expense_agent_events 创建差异说明任务
        await db.flush()
        logger.error(
            "petty_cash_pos_reconcile_anomaly",
            tenant_id=str(tenant_id),
            store_id=str(store_id),
            pos_session_id=pos_session_id,
            diff=diff,
            abs_diff=abs_diff,
        )
        return {"status": "anomaly", "diff": diff, "pos_session_id": pos_session_id}


# ─────────────────────────────────────────────────────────────────────────────
# 6. replenish
# ─────────────────────────────────────────────────────────────────────────────

async def replenish(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    store_id: uuid.UUID,
    amount: int,
    operator_id: uuid.UUID,
    reference_id: Optional[uuid.UUID] = None,
    notes: Optional[str] = None,
) -> PettyCashTransaction:
    """补充备用金入账（审批通过后由财务调用）。

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

    account = await get_account(db, tenant_id, store_id)

    if account.status == PettyCashAccountStatus.CLOSED.value:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="备用金账户已关闭，无法补充入账",
        )

    balance_after = account.balance + amount

    txn = PettyCashTransaction(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        account_id=account.id,
        transaction_type=PettyCashTransactionType.REPLENISHMENT.value,
        amount=amount,              # 收入为正数
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

    account.balance = balance_after
    account.updated_at = _now_utc()

    await db.flush()

    # 重新计算近7日日均消耗
    new_daily_avg = await update_daily_avg(db, tenant_id, account.id)

    logger.info(
        "petty_cash_replenished",
        tenant_id=str(tenant_id),
        store_id=str(store_id),
        account_id=str(account.id),
        amount=amount,
        balance_after=balance_after,
        new_daily_avg=new_daily_avg,
        operator_id=str(operator_id),
    )

    return txn


# ─────────────────────────────────────────────────────────────────────────────
# 7. draft_replenishment_request
# ─────────────────────────────────────────────────────────────────────────────

async def draft_replenishment_request(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    store_id: uuid.UUID,
    operator_id: uuid.UUID,
) -> dict:
    """A1 Agent 调用：余额不足时自动起草补充建议。

    建议金额 = max(approved_limit * 0.3, daily_avg_7d * 30)
    不超过 approved_limit - balance（不超过审批额度上限）。

    注意：只是"起草建议"，不创建申请单（由前端确认后提交）。

    Returns:
        {"suggested_amount": int, "reason": str, "store_id": str, "current_balance": int}
    """
    account = await get_account(db, tenant_id, store_id)

    # 计算建议补充金额
    amount_by_limit = int(account.approved_limit * 0.3)
    amount_by_days = account.daily_avg_7d * 30  # 月均消耗

    suggested_amount = max(amount_by_limit, amount_by_days)

    # 不超过审批额度上限与当前余额的差额
    max_replenish = account.approved_limit - account.balance
    if max_replenish <= 0:
        # 余额已达上限，无需补充
        suggested_amount = 0
        reason = (
            f"当前余额 {account.balance} 分已达审批额度上限 {account.approved_limit} 分，无需补充"
        )
    else:
        suggested_amount = min(suggested_amount, max_replenish)
        daily_avg = account.daily_avg_7d or 0
        days_left = (
            round(account.balance / daily_avg, 1) if daily_avg > 0 else 999
        )
        reason = (
            f"当前余额 {account.balance} 分（{round(account.balance/100,2)} 元），"
            f"预计可用 {days_left} 天；"
            f"建议补充 {suggested_amount} 分（{round(suggested_amount/100,2)} 元），"
            f"按月均消耗 {daily_avg*30} 分计算"
        )

    logger.info(
        "petty_cash_replenishment_draft",
        tenant_id=str(tenant_id),
        store_id=str(store_id),
        current_balance=account.balance,
        suggested_amount=suggested_amount,
        operator_id=str(operator_id),
    )

    return {
        "suggested_amount": suggested_amount,
        "reason": reason,
        "store_id": str(store_id),
        "current_balance": account.balance,
    }


# ─────────────────────────────────────────────────────────────────────────────
# 8. freeze_account
# ─────────────────────────────────────────────────────────────────────────────

async def freeze_account(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    store_id: uuid.UUID,
    reason: str,
    operator_id: uuid.UUID,
) -> PettyCashAccount:
    """冻结备用金账户（员工离职等场景）。

    创建一条 FREEZE_RESERVE 流水记录冻结事件（amount=0）。
    触发通知推送给 keeper_id 和管理层。

    Raises:
        HTTPException 400: 账户已冻结或已关闭
    """
    account = await get_account(db, tenant_id, store_id)

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
        account_id=account.id,
        transaction_type=PettyCashTransactionType.FREEZE_RESERVE.value,
        amount=0,
        balance_after=account.balance,
        description=f"账户冻结：{reason}",
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
        store_id=str(store_id),
        account_id=str(account.id),
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
            store_name=str(store_id),
            brand_id=account.brand_id,
            comment=f"账户已冻结，原因：{reason}。当前余额 {account.balance} 分待归还确认。",
        )
    )

    return account


# ─────────────────────────────────────────────────────────────────────────────
# 9. process_return
# ─────────────────────────────────────────────────────────────────────────────

async def process_return(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    store_id: uuid.UUID,
    amount: int,
    returning_employee_id: uuid.UUID,
    operator_id: uuid.UUID,
    notes: Optional[str] = None,
) -> PettyCashTransaction:
    """处理员工归还备用金（离职交接场景）。

    创建 RETURN_FROM_KEEPER 流水（amount=+amount）。
    归还后若余额合理（>=0），自动解冻账户（status=ACTIVE）。

    Args:
        amount: 归还金额，单位：分(fen)，必须 > 0
        returning_employee_id: 归还资金的员工ID

    Raises:
        HTTPException 400: 金额非正
    """
    if amount <= 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="归还金额必须大于0",
        )

    account = await get_account(db, tenant_id, store_id)

    balance_after = account.balance + amount

    txn = PettyCashTransaction(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        account_id=account.id,
        transaction_type=PettyCashTransactionType.RETURN_FROM_KEEPER.value,
        amount=amount,
        balance_after=balance_after,
        description=f"员工归还备用金，归还人ID: {returning_employee_id}",
        operator_id=operator_id,
        is_reconciled=False,
        expense_date=_today(),
        notes=notes,
    )
    db.add(txn)

    account.balance = balance_after
    account.updated_at = _now_utc()

    # 若归还后余额合理（>=0），自动解冻账户
    if balance_after >= 0 and account.status == PettyCashAccountStatus.FROZEN.value:
        account.status = PettyCashAccountStatus.ACTIVE.value
        account.frozen_reason = None
        account.frozen_at = None

        logger.info(
            "petty_cash_account_unfrozen_after_return",
            tenant_id=str(tenant_id),
            store_id=str(store_id),
            account_id=str(account.id),
            balance_after=balance_after,
        )

    await db.flush()

    logger.info(
        "petty_cash_return_processed",
        tenant_id=str(tenant_id),
        store_id=str(store_id),
        account_id=str(account.id),
        amount=amount,
        balance_after=balance_after,
        returning_employee_id=str(returning_employee_id),
        operator_id=str(operator_id),
    )

    return txn


# ─────────────────────────────────────────────────────────────────────────────
# 10. generate_monthly_settlement
# ─────────────────────────────────────────────────────────────────────────────

async def generate_monthly_settlement(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    store_id: uuid.UUID,
    settlement_month: str,
) -> PettyCashSettlement:
    """生成月末核销单（幂等操作）。

    Args:
        settlement_month: 格式 "YYYY-MM"，如 "2026-04"

    幂等：若该月核销单已存在，直接返回现有核销单（不重复生成）。

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

    account = await get_account(db, tenant_id, store_id)

    # 幂等检查：是否已有该月核销单
    existing_stmt = select(PettyCashSettlement).where(
        PettyCashSettlement.tenant_id == tenant_id,
        PettyCashSettlement.account_id == account.id,
        PettyCashSettlement.settlement_month == settlement_month,
    )
    existing_result = await db.execute(existing_stmt)
    existing_settlement = existing_result.scalar_one_or_none()
    if existing_settlement is not None:
        logger.info(
            "petty_cash_settlement_already_exists",
            tenant_id=str(tenant_id),
            store_id=str(store_id),
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
        PettyCashTransaction.account_id == account.id,
        PettyCashTransaction.expense_date >= period_start,
        PettyCashTransaction.expense_date <= period_end,
    )
    txn_result = await db.execute(txn_stmt)
    transactions = list(txn_result.scalars().all())

    total_income = sum(t.amount for t in transactions if t.amount > 0)
    total_expense = sum(abs(t.amount) for t in transactions if t.amount < 0)
    reconciled_count = sum(1 for t in transactions if t.is_reconciled)
    unreconciled_count = sum(1 for t in transactions if not t.is_reconciled)

    # 期初余额：当月第一笔流水之前的余额
    # 从期初录入或前月核销单推算：取本月最早流水的 balance_after - amount
    # 简化实现：opening = closing - income + expense
    # closing_balance 取当前账户余额（若统计月为当月）
    # 若为历史月：取本月最后一笔流水的 balance_after
    if transactions:
        # 按 expense_date 和 id 排序，取最后一笔的 balance_after 作为期末余额
        sorted_by_date = sorted(
            transactions,
            key=lambda t: (t.expense_date, t.created_at if t.created_at else date.min),
        )
        closing_balance = sorted_by_date[-1].balance_after
        opening_balance = closing_balance - total_income + total_expense
    else:
        # 本月无流水：期初=期末=当前余额
        closing_balance = account.balance
        opening_balance = account.balance

    settlement = PettyCashSettlement(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        account_id=account.id,
        store_id=store_id,
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
        store_id=str(store_id),
        account_id=str(account.id),
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
# 11. update_daily_avg
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
    account_stmt = select(PettyCashAccount).where(
        PettyCashAccount.tenant_id == tenant_id,
        PettyCashAccount.id == account_id,
    )
    account_result = await db.execute(account_stmt)
    account = account_result.scalar_one_or_none()

    if account is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="备用金账户不存在",
        )

    today = _today()
    # 近7天：包含今天在内往前数7天
    from datetime import timedelta
    seven_days_ago = today - timedelta(days=6)

    # 统计近7天 DAILY_USE 流水合计（amount 为负数，取绝对值）
    sum_stmt = select(
        func.coalesce(func.sum(PettyCashTransaction.amount), 0).label("total_expense")
    ).where(
        PettyCashTransaction.tenant_id == tenant_id,
        PettyCashTransaction.account_id == account_id,
        PettyCashTransaction.transaction_type == PettyCashTransactionType.DAILY_USE.value,
        PettyCashTransaction.expense_date >= seven_days_ago,
        PettyCashTransaction.expense_date <= today,
    )
    sum_result = await db.execute(sum_stmt)
    total_expense_signed = int(sum_result.scalar_one())

    # 7天内实际有流水的天数（避免新账户用固定7除）
    days_stmt = select(
        func.count(PettyCashTransaction.expense_date.distinct()).label("days_count")
    ).where(
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
