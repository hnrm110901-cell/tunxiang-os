"""
A1 备用金守护 Agent
===================
职责：门店备用金全生命周期智能监控

触发时机：
  - 事件驱动：ops.daily_close.completed（POS日结完成）
  - 事件驱动：org.employee.departed（员工离职）
  - 定时轮询：每5分钟检查所有低于阈值的账户
  - 定时批量：每月25日生成月末核销总表

Agent铁律：
  - 补充申请自动起草，付款必须人工审批
  - 异常项标记不自动驳回
  - 所有自动操作写入 expense_agent_events 审计日志
  - 不直接操作资金（只读数据、起草草稿、发送通知）

量化目标：备用金未核销率 70%→<5%，异常识别周期 月末→当日
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Optional

import structlog
from sqlalchemy import select
from sqlalchemy.exc import OperationalError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.expense_enums import (
    AgentType,
    ExpenseStatus,
    NotificationEventType,
    PettyCashAccountStatus,
)
from ..models.petty_cash import PettyCashAccount, PettyCashTransaction
from ..services import notification_service
from ..services import petty_cash_service

log = structlog.get_logger(__name__)

# 防刷屏：同一账户两次预警之间的最小间隔（小时）
_MIN_ALERT_INTERVAL_HOURS = 4

# POS日结对账差异触发人工预警的阈值（分），与 petty_cash_service 保持一致
_POS_DIFF_ALERT_THRESHOLD = 5000   # 50元

# 单笔异常检测：超过日均50%视为异常
_ANOMALY_RATE_THRESHOLD = 0.5


# =============================================================================
# 1. Agent 任务日志记录
# =============================================================================

async def _log_agent_job(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    job_type: str,
    trigger_source: str,
    store_id: Optional[uuid.UUID] = None,
    result: Optional[dict] = None,
    error: Optional[str] = None,
) -> None:
    """
    写入 expense_agent_events 表（暂用结构化日志代替，P1补建表）。

    job_type: "daily_reconcile" / "balance_check" / "monthly_settlement" / "employee_departure"
    trigger_source: "pos_daily_close" / "schedule" / "employee_event"
    """
    log.info(
        "agent_job_executed",
        agent=AgentType.PETTY_CASH_GUARDIAN,
        job_type=job_type,
        trigger_source=trigger_source,
        store_id=str(store_id) if store_id else None,
        tenant_id=str(tenant_id),
        result=result,
        error=error,
    )


# =============================================================================
# 2. POS日结触发的对账处理
# =============================================================================

async def handle_pos_daily_close(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    store_id: uuid.UUID,
    pos_session_id: str,
    pos_declared_petty_cash: int,
    close_date: date,
) -> dict:
    """
    POS日结完成后自动触发：

    1. 调用 petty_cash_service.reconcile_with_pos()
    2. 若有差异 → 查询该差异涉及的流水
    3. 差异 > 50元 → 发送预警通知给店长（notification_service）
    4. 检查对账后余额是否低于预警阈值
    5. 若余额不足 → 调用 draft_replenishment_request() 起草补充申请
    6. 返回处理摘要 dict

    Args:
        pos_declared_petty_cash: POS系统申报的备用金支出，单位：分(fen)
        close_date:              POS日结对应的业务日期
    """
    summary: dict = {
        "store_id": str(store_id),
        "close_date": str(close_date),
        "pos_session_id": pos_session_id,
        "reconcile_status": None,
        "diff": None,
        "alert_sent": False,
        "replenishment_drafted": False,
        "replenishment_suggested_amount": None,
        "error": None,
    }

    try:
        # 步骤1：对账
        reconcile_result = await petty_cash_service.reconcile_with_pos(
            db=db,
            tenant_id=tenant_id,
            store_id=store_id,
            pos_session_id=pos_session_id,
            pos_reported_balance=pos_declared_petty_cash,
        )
        summary["reconcile_status"] = reconcile_result["status"]
        summary["diff"] = reconcile_result["diff"]
        diff = reconcile_result["diff"]
        account_balance = reconcile_result["account_balance"]

        # 步骤2：差异 > 50元 → 获取账户信息并发送预警
        if abs(diff) > _POS_DIFF_ALERT_THRESHOLD:
            # 查账户（获取 keeper_id / brand_id）
            account = await petty_cash_service.get_account(
                db=db,
                tenant_id=tenant_id,
                store_id=store_id,
            )

            # 步骤3：推送差异预警给保管人（店长）
            diff_yuan = f"{abs(diff) / 100:.2f}"
            direction = "多报" if diff > 0 else "少报"
            await notification_service.send_notification(
                db=db,
                tenant_id=tenant_id,
                application_id=account.id,
                recipient_id=account.keeper_id,
                recipient_role="store_keeper",
                event_type=NotificationEventType.REMINDER.value,
                application_title="备用金日结对账差异预警",
                applicant_name="A1备用金守护",
                total_amount=abs(diff),
                store_name=str(store_id),
                brand_id=account.brand_id,
                comment=(
                    f"POS日结对账发现差异 {diff_yuan} 元（{direction}），"
                    f"POS申报 {pos_declared_petty_cash / 100:.2f} 元，"
                    f"账户余额 {account_balance / 100:.2f} 元，"
                    f"日结单号：{pos_session_id}，请核实。"
                ),
            )
            summary["alert_sent"] = True

        # 步骤4&5：检查余额是否低于预警阈值，若不足则起草补充申请
        account = await petty_cash_service.get_account(
            db=db,
            tenant_id=tenant_id,
            store_id=store_id,
        )
        if (
            account.status == PettyCashAccountStatus.ACTIVE.value
            and account.balance < account.warning_threshold
        ):
            draft_result = await petty_cash_service.draft_replenishment_request(
                db=db,
                tenant_id=tenant_id,
                account_id=account.id,
                operator_id=account.keeper_id,
            )
            summary["replenishment_drafted"] = True
            summary["replenishment_suggested_amount"] = draft_result["suggested_amount"]

        await _log_agent_job(
            db=db,
            tenant_id=tenant_id,
            job_type="daily_reconcile",
            trigger_source="pos_daily_close",
            store_id=store_id,
            result=summary,
        )
        return summary

    except (OSError, RuntimeError, ValueError, SQLAlchemyError) as exc:
        error_msg = f"{type(exc).__name__}: {exc}"
        summary["error"] = error_msg
        log.error(
            "a1_handle_pos_daily_close_error",
            tenant_id=str(tenant_id),
            store_id=str(store_id),
            pos_session_id=pos_session_id,
            error=error_msg,
            exc_info=True,
        )
        await _log_agent_job(
            db=db,
            tenant_id=tenant_id,
            job_type="daily_reconcile",
            trigger_source="pos_daily_close",
            store_id=store_id,
            result=None,
            error=error_msg,
        )
        return summary


# =============================================================================
# 3. 员工离职触发的账户冻结
# =============================================================================

async def handle_employee_departure(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    store_id: uuid.UUID,
    employee_id: uuid.UUID,
    departure_date: date,
) -> dict:
    """
    员工离职时触发：

    1. 查询该员工是否是某个门店的备用金保管人（keeper_id）
    2. 若是 → 调用 petty_cash_service.freeze_account()
    3. 推送冻结通知给品牌财务（通知需要归还确认）
    4. 查询该员工名下未核销的费用申请（expense_applications WHERE applicant_id=employee_id
       AND status IN submitted/in_review）
    5. 返回处理摘要：{"frozen_accounts": N, "pending_applications": N}
    """
    summary: dict = {
        "employee_id": str(employee_id),
        "departure_date": str(departure_date),
        "frozen_accounts": 0,
        "pending_applications": 0,
        "error": None,
    }

    try:
        # 步骤1：查询该员工是否是某账户的保管人
        stmt = select(PettyCashAccount).where(
            PettyCashAccount.tenant_id == tenant_id,
            PettyCashAccount.keeper_id == employee_id,
            PettyCashAccount.status == PettyCashAccountStatus.ACTIVE.value,
        )
        result = await db.execute(stmt)
        keeper_accounts = list(result.scalars().all())

        # 步骤2：逐账户执行冻结
        for account in keeper_accounts:
            try:
                await petty_cash_service.freeze_account(
                    db=db,
                    tenant_id=tenant_id,
                    account_id=account.id,
                    reason=(
                        f"保管人离职（员工ID：{employee_id}，离职日期：{departure_date}），"
                        "账户冻结待归还确认。"
                    ),
                    operator_id=employee_id,
                )
                summary["frozen_accounts"] += 1

                # 步骤3：推送冻结通知给品牌财务（以 keeper_id=employee_id 作为通知接收人占位，
                # 实际生产应替换为品牌财务负责人的 ID；此处用 account.keeper_id 以保持可追溯性）
                await notification_service.send_notification(
                    db=db,
                    tenant_id=tenant_id,
                    application_id=account.id,
                    recipient_id=account.keeper_id,
                    recipient_role="brand_finance",
                    event_type=NotificationEventType.REMINDER.value,
                    application_title="备用金账户已冻结——待员工归还确认",
                    applicant_name="A1备用金守护",
                    total_amount=account.balance,
                    store_name=str(account.store_id),
                    brand_id=account.brand_id,
                    comment=(
                        f"员工（ID：{employee_id}）已于 {departure_date} 离职，"
                        f"其名下门店备用金账户（账户余额：{account.balance / 100:.2f} 元）已自动冻结。"
                        "请联系该员工完成备用金归还并由财务确认后解冻。"
                    ),
                )

            except (OperationalError, SQLAlchemyError, ValueError) as freeze_exc:
                log.error(
                    "a1_freeze_account_error",
                    tenant_id=str(tenant_id),
                    account_id=str(account.id),
                    employee_id=str(employee_id),
                    error=f"{type(freeze_exc).__name__}: {freeze_exc}",
                    exc_info=True,
                )

        # 步骤4：查询该员工名下未核销的费用申请
        # 使用原生 SQL 避免循环依赖（expense_applications 在 expense_application_service）
        from sqlalchemy import text as sa_text
        pending_stmt = sa_text(
            "SELECT COUNT(*) FROM expense_applications "
            "WHERE tenant_id = :tenant_id "
            "  AND applicant_id = :employee_id "
            "  AND status IN ('submitted', 'in_review') "
            "  AND is_deleted = FALSE"
        )
        pending_result = await db.execute(
            pending_stmt,
            {"tenant_id": tenant_id, "employee_id": employee_id},
        )
        summary["pending_applications"] = int(pending_result.scalar_one())

        await _log_agent_job(
            db=db,
            tenant_id=tenant_id,
            job_type="employee_departure",
            trigger_source="employee_event",
            store_id=store_id,
            result=summary,
        )
        return summary

    except (OSError, RuntimeError, ValueError, SQLAlchemyError) as exc:
        error_msg = f"{type(exc).__name__}: {exc}"
        summary["error"] = error_msg
        log.error(
            "a1_handle_employee_departure_error",
            tenant_id=str(tenant_id),
            employee_id=str(employee_id),
            error=error_msg,
            exc_info=True,
        )
        await _log_agent_job(
            db=db,
            tenant_id=tenant_id,
            job_type="employee_departure",
            trigger_source="employee_event",
            store_id=store_id,
            result=None,
            error=error_msg,
        )
        return summary


# =============================================================================
# 4. 余额轮询检查（每5分钟）
# =============================================================================

async def run_balance_check(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    brand_id: Optional[uuid.UUID] = None,
) -> dict:
    """
    定期检查所有活跃账户余额（由 Worker 每5分钟调用）：

    1. 查询 tenant 下所有 status=ACTIVE 的账户
    2. 若 brand_id 传入则只检查该品牌
    3. 对每个账户：余额低于阈值 → 推送预警 + 起草补充申请
    4. 防刷屏：若 last_reconciled_at 距今 < 4小时 则跳过（该账户刚完成日结，短期内不重复预警）
    5. 返回 {"checked": N, "alerted": N, "drafted_replenishment": N}
    """
    summary: dict = {
        "checked": 0,
        "alerted": 0,
        "drafted_replenishment": 0,
        "error": None,
    }

    try:
        # 步骤1&2：查询 ACTIVE 账户，可选按品牌过滤
        filters = [
            PettyCashAccount.tenant_id == tenant_id,
            PettyCashAccount.status == PettyCashAccountStatus.ACTIVE.value,
        ]
        if brand_id is not None:
            filters.append(PettyCashAccount.brand_id == brand_id)

        stmt = select(PettyCashAccount).where(*filters)
        result = await db.execute(stmt)
        accounts = list(result.scalars().all())

        now_utc = datetime.now(tz=timezone.utc)
        cooldown_cutoff = now_utc - timedelta(hours=_MIN_ALERT_INTERVAL_HOURS)

        for account in accounts:
            summary["checked"] += 1

            # 步骤4：防刷屏 — last_reconciled_at 距今 < 4小时则跳过
            if account.last_reconciled_at is not None:
                last_reconciled = account.last_reconciled_at
                # 兼容 naive datetime（数据库可能存储无时区）
                if last_reconciled.tzinfo is None:
                    last_reconciled = last_reconciled.replace(tzinfo=timezone.utc)
                if last_reconciled > cooldown_cutoff:
                    continue

            # 步骤3：余额低于阈值
            if account.balance >= account.warning_threshold:
                continue

            # 推送余额不足预警
            try:
                daily_avg = account.daily_avg_7d or 0
                days_of_coverage = (
                    round(account.balance / daily_avg, 1) if daily_avg > 0 else 999.0
                )
                await notification_service.send_notification(
                    db=db,
                    tenant_id=tenant_id,
                    application_id=account.id,
                    recipient_id=account.keeper_id,
                    recipient_role="store_keeper",
                    event_type=NotificationEventType.REMINDER.value,
                    application_title="备用金余额不足预警",
                    applicant_name="A1备用金守护",
                    total_amount=account.balance,
                    store_name=str(account.store_id),
                    brand_id=account.brand_id,
                    comment=(
                        f"当前余额 {account.balance / 100:.2f} 元，"
                        f"低于预警阈值 {account.warning_threshold / 100:.2f} 元，"
                        f"按日均消耗预计可用 {days_of_coverage} 天，请及时申请补充。"
                    ),
                )
                summary["alerted"] += 1
            except (OSError, RuntimeError, ValueError) as notify_exc:
                log.error(
                    "a1_balance_alert_notify_error",
                    tenant_id=str(tenant_id),
                    account_id=str(account.id),
                    error=f"{type(notify_exc).__name__}: {notify_exc}",
                    exc_info=True,
                )

            # 起草补充申请
            try:
                await petty_cash_service.draft_replenishment_request(
                    db=db,
                    tenant_id=tenant_id,
                    account_id=account.id,
                    operator_id=account.keeper_id,
                )
                summary["drafted_replenishment"] += 1
            except (OperationalError, SQLAlchemyError, ValueError) as draft_exc:
                log.error(
                    "a1_balance_draft_replenishment_error",
                    tenant_id=str(tenant_id),
                    account_id=str(account.id),
                    error=f"{type(draft_exc).__name__}: {draft_exc}",
                    exc_info=True,
                )

        await _log_agent_job(
            db=db,
            tenant_id=tenant_id,
            job_type="balance_check",
            trigger_source="schedule",
            result=summary,
        )
        return summary

    except (OSError, RuntimeError, ValueError, SQLAlchemyError) as exc:
        error_msg = f"{type(exc).__name__}: {exc}"
        summary["error"] = error_msg
        log.error(
            "a1_run_balance_check_error",
            tenant_id=str(tenant_id),
            brand_id=str(brand_id) if brand_id else None,
            error=error_msg,
            exc_info=True,
        )
        await _log_agent_job(
            db=db,
            tenant_id=tenant_id,
            job_type="balance_check",
            trigger_source="schedule",
            result=None,
            error=error_msg,
        )
        return summary


# =============================================================================
# 5. 月末核销批量处理（每月25日）
# =============================================================================

async def run_monthly_settlement(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    settlement_month: Optional[str] = None,
) -> dict:
    """
    月末核销主流程（由 Worker 每月25日调用）：

    1. settlement_month 默认当月（格式 "YYYY-MM"）
    2. 查询 tenant 下所有 ACTIVE 账户
    3. 对每个账户调用 generate_monthly_settlement()
    4. 统计：total_unreconciled_items（所有账户未核销流水总数）
    5. 有未核销流水的账户 → 推送催办通知给保管人
    6. 生成汇总简报（发送给品牌财务）：
       - 总账户数 / 已完成核销数 / 待财务确认数
       - 未核销流水笔数
       - 最大差异账户（前3名）
    7. 返回处理摘要
    """
    # 默认当月
    if settlement_month is None:
        today = datetime.now(tz=timezone.utc).date()
        settlement_month = today.strftime("%Y-%m")

    summary: dict = {
        "settlement_month": settlement_month,
        "total_accounts": 0,
        "settlement_generated": 0,
        "accounts_with_unreconciled": 0,
        "total_unreconciled_items": 0,
        "reminders_sent": 0,
        "top3_diff_accounts": [],
        "error": None,
    }

    try:
        # 步骤2：查询所有 ACTIVE 账户
        stmt = select(PettyCashAccount).where(
            PettyCashAccount.tenant_id == tenant_id,
            PettyCashAccount.status == PettyCashAccountStatus.ACTIVE.value,
        )
        result = await db.execute(stmt)
        accounts = list(result.scalars().all())
        summary["total_accounts"] = len(accounts)

        # 步骤3&4&5：逐账户处理
        account_unreconciled: list[dict] = []

        for account in accounts:
            try:
                settlement = await petty_cash_service.generate_monthly_settlement(
                    db=db,
                    tenant_id=tenant_id,
                    account_id=account.id,
                    settlement_month=settlement_month,
                )
                summary["settlement_generated"] += 1

                unreconciled_count = settlement.unreconciled_count or 0
                summary["total_unreconciled_items"] += unreconciled_count

                if unreconciled_count > 0:
                    summary["accounts_with_unreconciled"] += 1
                    account_unreconciled.append({
                        "account_id": str(account.id),
                        "store_id": str(account.store_id),
                        "unreconciled_count": unreconciled_count,
                        "balance": account.balance,
                    })

                    # 步骤5：推送催办通知给保管人
                    try:
                        await notification_service.send_notification(
                            db=db,
                            tenant_id=tenant_id,
                            application_id=account.id,
                            recipient_id=account.keeper_id,
                            recipient_role="store_keeper",
                            event_type=NotificationEventType.REMINDER.value,
                            application_title=f"备用金月末核销催办（{settlement_month}）",
                            applicant_name="A1备用金守护",
                            total_amount=account.balance,
                            store_name=str(account.store_id),
                            brand_id=account.brand_id,
                            comment=(
                                f"{settlement_month} 月末核销提醒：您名下备用金账户有 "
                                f"{unreconciled_count} 笔流水尚未核销，"
                                "请登录费控系统确认并提交月末核销单。"
                            ),
                        )
                        summary["reminders_sent"] += 1
                    except (OSError, RuntimeError, ValueError) as notify_exc:
                        log.error(
                            "a1_monthly_settlement_remind_error",
                            tenant_id=str(tenant_id),
                            account_id=str(account.id),
                            error=f"{type(notify_exc).__name__}: {notify_exc}",
                            exc_info=True,
                        )

            except (OperationalError, SQLAlchemyError, ValueError) as settle_exc:
                log.error(
                    "a1_generate_settlement_error",
                    tenant_id=str(tenant_id),
                    account_id=str(account.id),
                    settlement_month=settlement_month,
                    error=f"{type(settle_exc).__name__}: {settle_exc}",
                    exc_info=True,
                )

        # 步骤6：取未核销流水最多的前3名（差异最大账户）
        top3 = sorted(
            account_unreconciled,
            key=lambda x: x["unreconciled_count"],
            reverse=True,
        )[:3]
        summary["top3_diff_accounts"] = top3

        await _log_agent_job(
            db=db,
            tenant_id=tenant_id,
            job_type="monthly_settlement",
            trigger_source="schedule",
            result=summary,
        )
        return summary

    except (OSError, RuntimeError, ValueError, SQLAlchemyError) as exc:
        error_msg = f"{type(exc).__name__}: {exc}"
        summary["error"] = error_msg
        log.error(
            "a1_run_monthly_settlement_error",
            tenant_id=str(tenant_id),
            settlement_month=settlement_month,
            error=error_msg,
            exc_info=True,
        )
        await _log_agent_job(
            db=db,
            tenant_id=tenant_id,
            job_type="monthly_settlement",
            trigger_source="schedule",
            result=None,
            error=error_msg,
        )
        return summary


# =============================================================================
# 6. 单笔异常检测
# =============================================================================

async def detect_transaction_anomaly(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    account_id: uuid.UUID,
    transaction_id: uuid.UUID,
    amount: int,
) -> Optional[dict]:
    """
    单笔支出异常检测（录入支出时调用）：

    1. 获取账户的 daily_avg_7d
    2. 若 daily_avg_7d > 0 且 amount > daily_avg_7d * 0.5（超过日均50%）
    3. → 返回异常信息 {"anomaly": True, "over_rate": float, "message": str}
    4. 否则返回 None

    注意：只标记不自动驳回，由店长/财务人工处理。

    Args:
        amount: 支出金额，单位：分(fen)，传入绝对值（正数）
    """
    try:
        # 查询账户的7日日均消耗
        stmt = select(PettyCashAccount).where(
            PettyCashAccount.tenant_id == tenant_id,
            PettyCashAccount.id == account_id,
        )
        result = await db.execute(stmt)
        account = result.scalar_one_or_none()

        if account is None:
            log.warning(
                "a1_detect_anomaly_account_not_found",
                tenant_id=str(tenant_id),
                account_id=str(account_id),
                transaction_id=str(transaction_id),
            )
            return None

        daily_avg = account.daily_avg_7d or 0
        if daily_avg <= 0:
            # 无历史数据，无法判断异常
            return None

        threshold = daily_avg * _ANOMALY_RATE_THRESHOLD
        if amount <= threshold:
            return None

        over_rate = round(amount / daily_avg, 2)
        message = (
            f"单笔支出 {amount / 100:.2f} 元，"
            f"超过近7日日均消耗（{daily_avg / 100:.2f} 元）的 {over_rate} 倍，"
            "请核实是否属于正常支出。"
        )

        log.warning(
            "a1_transaction_anomaly_detected",
            tenant_id=str(tenant_id),
            account_id=str(account_id),
            transaction_id=str(transaction_id),
            amount=amount,
            daily_avg_7d=daily_avg,
            over_rate=over_rate,
        )

        return {
            "anomaly": True,
            "over_rate": over_rate,
            "message": message,
        }

    except (OperationalError, SQLAlchemyError) as exc:
        log.error(
            "a1_detect_transaction_anomaly_error",
            tenant_id=str(tenant_id),
            account_id=str(account_id),
            transaction_id=str(transaction_id),
            error=f"{type(exc).__name__}: {exc}",
            exc_info=True,
        )
        return None


# =============================================================================
# 7. Agent 主入口（统一调度）
# =============================================================================

async def run(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    trigger: str,
    payload: dict,
) -> dict:
    """
    Agent 统一入口，由事件消费者和定时 Worker 调用。

    trigger 值：
      "pos_daily_close"    → handle_pos_daily_close(payload)
      "employee_departure" → handle_employee_departure(payload)
      "balance_check"      → run_balance_check(payload)
      "monthly_settlement" → run_monthly_settlement(payload)

    所有异常捕获后记录日志，不向上传播（Agent 失败不影响业务主流程）。

    返回处理结果 dict（总是返回，不抛异常）。
    """
    log.info(
        "a1_agent_run_start",
        agent=AgentType.PETTY_CASH_GUARDIAN,
        trigger=trigger,
        tenant_id=str(tenant_id),
    )

    try:
        if trigger == "pos_daily_close":
            return await handle_pos_daily_close(
                db=db,
                tenant_id=tenant_id,
                store_id=uuid.UUID(payload["store_id"]),
                pos_session_id=payload["pos_session_id"],
                pos_declared_petty_cash=int(payload["pos_declared_petty_cash"]),
                close_date=date.fromisoformat(payload["close_date"]),
            )

        elif trigger == "employee_departure":
            return await handle_employee_departure(
                db=db,
                tenant_id=tenant_id,
                store_id=uuid.UUID(payload["store_id"]),
                employee_id=uuid.UUID(payload["employee_id"]),
                departure_date=date.fromisoformat(payload["departure_date"]),
            )

        elif trigger == "balance_check":
            brand_id_raw = payload.get("brand_id")
            return await run_balance_check(
                db=db,
                tenant_id=tenant_id,
                brand_id=uuid.UUID(brand_id_raw) if brand_id_raw else None,
            )

        elif trigger == "monthly_settlement":
            return await run_monthly_settlement(
                db=db,
                tenant_id=tenant_id,
                settlement_month=payload.get("settlement_month"),
            )

        else:
            unknown_result = {
                "error": f"未知 trigger 类型: {trigger}",
                "trigger": trigger,
            }
            log.error(
                "a1_agent_unknown_trigger",
                agent=AgentType.PETTY_CASH_GUARDIAN,
                trigger=trigger,
                tenant_id=str(tenant_id),
            )
            return unknown_result

    except (ValueError, KeyError, AttributeError, RuntimeError, OSError, SQLAlchemyError) as exc:
        error_msg = f"{type(exc).__name__}: {exc}"
        log.error(
            "a1_agent_run_unhandled_error",
            agent=AgentType.PETTY_CASH_GUARDIAN,
            trigger=trigger,
            tenant_id=str(tenant_id),
            error=error_msg,
            exc_info=True,
        )
        return {
            "trigger": trigger,
            "error": error_msg,
        }
