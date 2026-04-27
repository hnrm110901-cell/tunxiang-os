"""
A4 预算预警 Agent
每日监控各类费用执行率，阈值触发推送预警。

触发场景：
1. Cron 调用（每日 09:00）: run_daily_check()
2. 事件触发（申请审批通过）: handle_expense_approved()

预警规则：
- 月度费用执行率 >80%: 向费控管理员推送"预算预警"
- 月度费用执行率 >100%: 向财务负责人推送"预算超支"（紧急）
- 合同到期 ≤30天: 推送合同到期预警
- 付款逾期: 推送逾期付款提醒

预算数据来自 BudgetService（v242 budget_system 表）。
未配置预算时降级返回 is_placeholder: True，不触发预警。
预警通知通过 notification_service 推送。
"""

from __future__ import annotations

import os
import uuid
from datetime import date, datetime, timezone
from typing import Any

import httpx
import structlog
from sqlalchemy import func, select
from sqlalchemy.exc import OperationalError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.expense_application import ExpenseApplication, ExpenseItem
from ..models.expense_enums import ExpenseStatus

logger = structlog.get_logger(__name__)

# 预警阈值
_ALERT_WARN_RATE = 0.80  # 80%：预算预警
_ALERT_OVERSPEND_RATE = 1.00  # 100%：预算超支（紧急）

# 通知 webhook（从环境变量读取，不硬编码）
_NOTIFY_URL = os.environ.get("EXPENSE_WECOM_WEBHOOK_URL", "")
_HTTP_TIMEOUT = 5.0


# ─────────────────────────────────────────────────────────────────────────────
# 内部工具
# ─────────────────────────────────────────────────────────────────────────────


def _now_utc() -> datetime:
    return datetime.now(tz=timezone.utc)


def _today() -> date:
    return date.today()


async def _push_webhook(message: str, urgent: bool = False) -> bool:
    """通过企业微信 Webhook 推送预警消息。

    Returns:
        True 推送成功，False 跳过（无配置）或失败（已记录日志）。
    """
    webhook_url = os.environ.get("EXPENSE_WECOM_WEBHOOK_URL", "")
    if not webhook_url:
        logger.warning("a4_alert_no_webhook_configured")
        return False

    prefix = "【紧急】" if urgent else "【预警】"
    payload = {
        "msgtype": "markdown",
        "markdown": {
            "content": f"{prefix}屯象费控\n{message}",
        },
    }
    try:
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
            resp = await client.post(webhook_url, json=payload)
            resp.raise_for_status()
            return True
    except httpx.HTTPStatusError as exc:
        logger.error(
            "a4_alert_push_http_error",
            status_code=exc.response.status_code,
            message=message[:100],
        )
        return False
    except httpx.RequestError as exc:
        logger.error(
            "a4_alert_push_request_error",
            error=str(exc),
            message=message[:100],
        )
        return False


# ─────────────────────────────────────────────────────────────────────────────
# A4BudgetAlertAgent
# ─────────────────────────────────────────────────────────────────────────────


class A4BudgetAlertAgent:
    """
    A4 预算预警 Agent

    职责：
    1. 每日跑批：check_expense_rates + check_contract_alerts
    2. 事件触发：申请审批通过后实时检查该类型费用执行率
    3. 所有推送调用 notification_service / webhook，不阻塞主业务
    """

    async def calculate_expense_rate(
        self,
        db: AsyncSession,
        tenant_id: uuid.UUID,
        year: int,
        month: int,
    ) -> list[dict]:
        """按费用科目类型统计当月已审批金额 vs 预算，返回执行率列表。

        Returns::
            [
                {
                    "category_code": str,
                    "category_name": str,
                    "budget_fen": int,      # 来自 BudgetService，未配置时为 0
                    "actual_fen": int,       # 本月已审批通过的费用金额（分）
                    "rate": float,           # actual / budget，budget=0 时返回 -1
                }
            ]

        Note:
            budget_fen 来自 BudgetService.get_current_budget()，未配置预算时降级返回 is_placeholder: True。
        """
        # ── 查询当月已审批通过的费用，按科目汇总 ──────────────────────────────
        from ..models.expense_application import ExpenseCategory

        approved_statuses = [ExpenseStatus.APPROVED.value, ExpenseStatus.PAID.value]

        stmt = (
            select(
                ExpenseCategory.code.label("category_code"),
                ExpenseCategory.name.label("category_name"),
                func.coalesce(func.sum(ExpenseItem.amount), 0).label("actual_fen"),
            )
            .join(ExpenseItem, ExpenseItem.category_id == ExpenseCategory.id)
            .join(
                ExpenseApplication,
                ExpenseApplication.id == ExpenseItem.application_id,
            )
            .where(
                ExpenseItem.tenant_id == tenant_id,
                ExpenseApplication.tenant_id == tenant_id,
                ExpenseApplication.is_deleted == False,  # noqa: E712
                ExpenseApplication.status.in_(approved_statuses),
                func.extract("year", ExpenseApplication.created_at) == year,
                func.extract("month", ExpenseApplication.created_at) == month,
            )
            .group_by(ExpenseCategory.id, ExpenseCategory.code, ExpenseCategory.name)
            .order_by(func.sum(ExpenseItem.amount).desc())
        )
        result = await db.execute(stmt)
        rows = result.mappings().all()

        # ── P2：从预算管理系统查询真实月度/年度预算 ───────────────────────────
        from ..services.budget_service import BudgetService

        _budget_svc = BudgetService()

        # 查找当前周期的 active 预算（优先月度，无月度则取年度）
        current_budget = None
        try:
            current_budget = await _budget_svc.get_current_budget(
                db=db,
                tenant_id=tenant_id,
                budget_type="expense",
                store_id=None,  # 集团级预算
            )
        except (OperationalError, SQLAlchemyError, ValueError) as exc:
            logger.error(
                "a4_budget_lookup_failed",
                tenant_id=str(tenant_id),
                year=year,
                month=month,
                error=str(exc),
                exc_info=True,
            )

        output = []
        for row in rows:
            actual = int(row["actual_fen"])

            if current_budget is None:
                # 降级：未找到预算配置，返回 placeholder 标志
                output.append(
                    {
                        "category_code": row["category_code"],
                        "category_name": row["category_name"],
                        "budget_fen": 0,
                        "actual_fen": actual,
                        "rate": -1.0,
                        "is_placeholder": True,
                    }
                )
                continue

            # 优先使用科目分配额度，无分配则使用预算总额
            alloc_fen: int = 0
            if current_budget.allocations:
                for alloc in current_budget.allocations:
                    if alloc.category_code == row["category_code"]:
                        alloc_fen = alloc.allocated_amount
                        break

            budget_fen = alloc_fen if alloc_fen > 0 else current_budget.total_amount
            rate = actual / budget_fen if budget_fen > 0 else -1.0

            output.append(
                {
                    "category_code": row["category_code"],
                    "category_name": row["category_name"],
                    "budget_fen": budget_fen,
                    "actual_fen": actual,
                    "rate": round(rate, 4),
                    "is_placeholder": False,
                    "budget_id": str(current_budget.id),
                }
            )

        logger.info(
            "a4_expense_rate_calculated",
            tenant_id=str(tenant_id),
            year=year,
            month=month,
            category_count=len(output),
        )
        return output

    async def run_daily_check(
        self,
        db: AsyncSession,
        tenant_id: uuid.UUID,
    ) -> dict[str, Any]:
        """每日批次检查入口（Cron 09:00 调用）。

        Returns::
            {
                "check_date": str,
                "alerts_sent": int,
                "expense_rate_alerts": int,
                "contract_alerts": int,
            }
        """
        today = _today()
        log = logger.bind(tenant_id=str(tenant_id), check_date=today.isoformat())
        log.info("a4_daily_check_start")

        alerts_sent = 0
        expense_rate_alerts = 0
        contract_alerts_count = 0

        # ── 1. 费用执行率检查 ───────────────────────────────────────────────
        try:
            rates = await self.calculate_expense_rate(db=db, tenant_id=tenant_id, year=today.year, month=today.month)
            for item in rates:
                rate = item["rate"]
                if rate < 0:
                    continue  # budget=0，跳过

                if rate > _ALERT_OVERSPEND_RATE:
                    msg = (
                        f"**预算超支警告** 科目【{item['category_name']}】"
                        f"{today.year}年{today.month}月执行率 **{rate * 100:.1f}%**，"
                        f"已超出预算 {(rate - 1) * 100:.1f}%，"
                        f"实际 {item['actual_fen'] / 100:.0f}元 / 预算 {item['budget_fen'] / 100:.0f}元"
                    )
                    sent = await _push_webhook(msg, urgent=True)
                    if sent:
                        alerts_sent += 1
                    expense_rate_alerts += 1
                    log.warning(
                        "a4_budget_overspend",
                        category=item["category_code"],
                        rate=rate,
                    )

                elif rate > _ALERT_WARN_RATE:
                    msg = (
                        f"**预算预警** 科目【{item['category_name']}】"
                        f"{today.year}年{today.month}月执行率 {rate * 100:.1f}%，"
                        f"已超80%预算阈值，"
                        f"实际 {item['actual_fen'] / 100:.0f}元 / 预算 {item['budget_fen'] / 100:.0f}元"
                    )
                    sent = await _push_webhook(msg, urgent=False)
                    if sent:
                        alerts_sent += 1
                    expense_rate_alerts += 1
                    log.info(
                        "a4_budget_warn",
                        category=item["category_code"],
                        rate=rate,
                    )

        except (OperationalError, SQLAlchemyError, ValueError) as exc:
            log.error("a4_expense_rate_check_failed", error=str(exc), exc_info=True)

        # ── 2. 合同预警检查 ─────────────────────────────────────────────────
        try:
            contract_alerts = await self.check_contract_alerts(db=db, tenant_id=tenant_id)
            contract_alerts_count = len(contract_alerts)
        except (OperationalError, SQLAlchemyError, ValueError) as exc:
            log.error("a4_contract_check_failed", error=str(exc), exc_info=True)

        result = {
            "check_date": today.isoformat(),
            "alerts_sent": alerts_sent,
            "expense_rate_alerts": expense_rate_alerts,
            "contract_alerts": contract_alerts_count,
        }

        log.info("a4_daily_check_complete", **result)
        return result

    async def handle_expense_approved(
        self,
        event_data: dict,
        db: AsyncSession,
        tenant_id: uuid.UUID,
    ) -> None:
        """处理费用申请审批通过事件，实时检查该科目执行率。

        event_data 格式（来自事件总线）：
            {
                "application_id": str,
                "tenant_id": str,
                "total_amount": int,      # 分
                "scenario_code": str,
                "approved_at": str,
            }
        """
        log = logger.bind(
            tenant_id=str(tenant_id),
            application_id=event_data.get("application_id"),
        )
        log.info("a4_handle_expense_approved")

        today = _today()
        try:
            rates = await self.calculate_expense_rate(db=db, tenant_id=tenant_id, year=today.year, month=today.month)
            for item in rates:
                rate = item["rate"]
                if rate < 0:
                    continue

                if rate > _ALERT_OVERSPEND_RATE:
                    msg = (
                        f"**实时预算超支** 审批通过后，科目【{item['category_name']}】"
                        f"执行率已达 **{rate * 100:.1f}%**，请财务负责人关注。"
                    )
                    await _push_webhook(msg, urgent=True)
                    log.warning(
                        "a4_realtime_overspend",
                        category=item["category_code"],
                        rate=rate,
                        application_id=event_data.get("application_id"),
                    )

                elif rate > _ALERT_WARN_RATE:
                    msg = f"**实时预算预警** 审批通过后，科目【{item['category_name']}】执行率已达 {rate * 100:.1f}%。"
                    await _push_webhook(msg, urgent=False)
                    log.info(
                        "a4_realtime_warn",
                        category=item["category_code"],
                        rate=rate,
                    )

        except (OperationalError, SQLAlchemyError, ValueError) as exc:
            log.error("a4_handle_expense_approved_failed", error=str(exc), exc_info=True)

    async def check_contract_alerts(
        self,
        db: AsyncSession,
        tenant_id: uuid.UUID,
    ) -> list:
        """检查合同到期和逾期付款，生成并推送预警。

        调用 ContractLedgerService.generate_alerts()，
        对未推送的预警逐条发送 webhook 通知。
        """
        from ..services.contract_ledger_service import ContractLedgerService

        svc = ContractLedgerService()
        log = logger.bind(tenant_id=str(tenant_id))

        try:
            new_alerts = await svc.generate_alerts(db=db, tenant_id=tenant_id)

            for alert in new_alerts:
                if alert.is_sent:
                    continue

                urgent = alert.alert_type in ("overdue",)
                sent = await _push_webhook(alert.message or "", urgent=urgent)

                if sent:
                    alert.is_sent = True
                    alert.sent_at = _now_utc()
                    log.info(
                        "a4_contract_alert_sent",
                        alert_id=str(alert.id),
                        alert_type=alert.alert_type,
                        contract_id=str(alert.contract_id),
                    )

            # flush 更新 is_sent 状态
            if any(a.is_sent for a in new_alerts):
                await db.flush()

            return new_alerts

        except Exception as exc:
            log.error("a4_contract_alerts_failed", error=str(exc), exc_info=True)
            return []

    async def run(
        self,
        event_type: str,
        event_data: dict,
        db: AsyncSession,
        tenant_id: uuid.UUID,
    ) -> dict[str, Any]:
        """统一入口：根据 event_type 分发到对应处理方法。

        event_type 取值：
            "daily_check"       — 每日跑批（Cron 触发）
            "expense_approved"  — 费用申请审批通过（事件总线触发）

        Returns:
            处理结果字典。
        """
        log = logger.bind(tenant_id=str(tenant_id), event_type=event_type)
        log.info("a4_agent_run")

        if event_type == "daily_check":
            return await self.run_daily_check(db=db, tenant_id=tenant_id)

        elif event_type == "expense_approved":
            await self.handle_expense_approved(event_data=event_data, db=db, tenant_id=tenant_id)
            return {"event_type": event_type, "status": "handled"}

        else:
            log.warning("a4_unknown_event_type", event_type=event_type)
            return {"event_type": event_type, "status": "skipped", "reason": "unknown_event_type"}
