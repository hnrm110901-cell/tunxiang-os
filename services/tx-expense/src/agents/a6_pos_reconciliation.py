"""
A6 POS对账 Agent
================
职责：监听 ops.daily_close 事件，自动执行备用金核销 + 对账 + 成本数据更新。

触发时机：
  - 事件驱动：ops.daily_close.completed（POS日结完成）

Agent 铁律：
  - 差异 ≤50分：自动平账，仅记录日志
  - 差异 50-200分：通知店长确认
  - 差异 >200分：升级通知区域经理 + 费控管理员
  - 不直接操作资金（只调 petty_cash_service，由后者执行状态机）
  - 所有操作写入结构化日志（审计留痕）

量化目标：备用金核销误差率 <0.1%，对账自动化率 >95%
"""
from __future__ import annotations

import asyncio
from datetime import date, datetime, timezone
from typing import Any, Optional
from uuid import UUID

import structlog
from sqlalchemy import select, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

log = structlog.get_logger(__name__)

# 对账差异阈值（分）
_AUTO_RECONCILE_THRESHOLD = 50      # ≤50分：自动平账
_STORE_MANAGER_THRESHOLD = 200      # 50-200分：通知店长
# >200分：升级通知区域经理 + 费控管理员


class A6POSReconciliationAgent:
    """
    A6 POS对账 Agent。

    监听 ops.daily_close 事件，完成三项工作：
    1. 调用 petty_cash_service.reconcile_with_pos() 执行备用金核销
    2. 根据差异金额分级通知
    3. 更新 daily_cost_reports.pos_data_source 字段

    外部调用入口：
        agent = A6POSReconciliationAgent()
        result = await agent.handle_daily_close(event_data, db)
    """

    # ── 1. 核心对账处理 ────────────────────────────────────────────────────

    async def handle_daily_close(
        self, event_data: dict[str, Any], db: AsyncSession
    ) -> dict[str, Any]:
        """处理 ops.daily_close 事件，执行备用金核销 + 对账。

        Args:
            event_data: 事件 payload，必须包含：
                tenant_id           str UUID
                store_id            str UUID
                date                str ISO date（日结日期）
                pos_summary         dict（POS日结汇总，可选）
                  pos_petty_cash_balance  int 分（备用金余额）
                  pos_session_id          str
                  pos_source              str（数据来源）
                  total_revenue_fen       int 分
            db: AsyncSession

        Returns:
            对账结果 dict
        """
        tenant_id = UUID(event_data["tenant_id"])
        store_id = UUID(event_data["store_id"])
        close_date_str = event_data.get("date") or event_data.get("close_date")
        close_date = date.fromisoformat(close_date_str) if close_date_str else date.today()

        pos_summary = event_data.get("pos_summary") or {}
        pos_petty_cash_balance = int(pos_summary.get("pos_petty_cash_balance", 0))
        pos_session_id = str(pos_summary.get("pos_session_id", ""))
        pos_source = pos_summary.get("pos_source") or pos_summary.get("data_source", "")

        log.info(
            "a6_pos_reconciliation_start",
            tenant_id=str(tenant_id),
            store_id=str(store_id),
            close_date=close_date.isoformat(),
            pos_session_id=pos_session_id,
            pos_petty_cash_balance=pos_petty_cash_balance,
        )

        result: dict[str, Any] = {
            "agent": "A6",
            "tenant_id": str(tenant_id),
            "store_id": str(store_id),
            "close_date": close_date.isoformat(),
            "reconcile_status": None,
            "diff_fen": None,
            "notification_level": None,
            "cost_report_updated": False,
            "error": None,
        }

        # ── 步骤1：备用金核销 ───────────────────────────────────────────
        reconcile_result: Optional[dict[str, Any]] = None
        try:
            from ..services import petty_cash_service

            reconcile_result = await petty_cash_service.reconcile_with_pos(
                db=db,
                tenant_id=tenant_id,
                store_id=store_id,
                pos_session_id=pos_session_id,
                pos_reported_balance=pos_petty_cash_balance,
            )
            result["reconcile_status"] = reconcile_result["status"]
            result["diff_fen"] = reconcile_result["diff"]

            log.info(
                "a6_reconcile_completed",
                tenant_id=str(tenant_id),
                store_id=str(store_id),
                close_date=close_date.isoformat(),
                reconcile_status=reconcile_result["status"],
                diff_fen=reconcile_result["diff"],
            )

        except (SQLAlchemyError, ValueError, KeyError) as exc:  # 对账失败不阻断成本报告更新
            log.error(
                "a6_reconcile_failed",
                tenant_id=str(tenant_id),
                store_id=str(store_id),
                close_date=close_date.isoformat(),
                error=str(exc),
                exc_info=True,
            )
            result["error"] = str(exc)
            # 继续执行后续步骤

        # ── 步骤2：生成对账报告 + 分级通知 ────────────────────────────────
        if reconcile_result is not None:
            report = await self.generate_reconciliation_report(
                store_id=store_id,
                target_date=close_date,
                pos_data=pos_summary,
                reconcile_result=reconcile_result,
            )
            diff_fen = abs(reconcile_result.get("diff", 0))

            if diff_fen <= _AUTO_RECONCILE_THRESHOLD:
                # 自动平账，仅记录日志
                result["notification_level"] = "auto"
                log.info(
                    "a6_auto_reconciled",
                    tenant_id=str(tenant_id),
                    store_id=str(store_id),
                    close_date=close_date.isoformat(),
                    diff_fen=diff_fen,
                )

            elif diff_fen <= _STORE_MANAGER_THRESHOLD:
                # 通知店长确认
                result["notification_level"] = "store_manager"
                await self.escalate_discrepancy(
                    tenant_id=tenant_id,
                    store_id=store_id,
                    discrepancy_fen=diff_fen,
                    report=report,
                )

            else:
                # 升级通知区域经理 + 费控管理员
                result["notification_level"] = "escalated"
                await self.escalate_discrepancy(
                    tenant_id=tenant_id,
                    store_id=store_id,
                    discrepancy_fen=diff_fen,
                    report=report,
                )

        # ── 步骤3：更新 daily_cost_reports.pos_data_source ─────────────────
        if pos_source:
            try:
                updated = await self._update_cost_report_pos_source(
                    db=db,
                    tenant_id=tenant_id,
                    store_id=store_id,
                    report_date=close_date,
                    pos_source=pos_source,
                )
                result["cost_report_updated"] = updated
            except SQLAlchemyError as exc:
                log.error(
                    "a6_cost_report_update_failed",
                    tenant_id=str(tenant_id),
                    store_id=str(store_id),
                    close_date=close_date.isoformat(),
                    error=str(exc),
                    exc_info=True,
                )

        log.info(
            "a6_pos_reconciliation_complete",
            **{k: v for k, v in result.items() if v is not None},
        )
        return result

    # ── 2. 对账差异报告生成 ────────────────────────────────────────────────

    async def generate_reconciliation_report(
        self,
        store_id: UUID,
        target_date: date,
        pos_data: dict[str, Any],
        reconcile_result: dict[str, Any],
    ) -> dict[str, Any]:
        """生成对账差异报告。

        Args:
            store_id: 门店 UUID
            target_date: 对账日期
            pos_data: POS 日结汇总数据
            reconcile_result: petty_cash_service.reconcile_with_pos() 的返回值

        Returns:
            结构化对账报告 dict
        """
        diff = reconcile_result.get("diff", 0)
        abs_diff = abs(diff)
        account_balance = reconcile_result.get("account_balance", 0)
        pos_balance = reconcile_result.get("pos_balance", pos_data.get("pos_petty_cash_balance", 0))
        status = reconcile_result.get("status", "unknown")

        if abs_diff <= _AUTO_RECONCILE_THRESHOLD:
            conclusion = "自动平账，差异在允许范围内"
            action_required = False
        elif abs_diff <= _STORE_MANAGER_THRESHOLD:
            conclusion = f"差异 {abs_diff / 100:.2f}元，请店长确认备用金实物"
            action_required = True
        else:
            conclusion = f"差异 {abs_diff / 100:.2f}元，已升级通知区域经理"
            action_required = True

        report = {
            "store_id": str(store_id),
            "report_date": target_date.isoformat(),
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "reconcile_status": status,
            "account_balance_fen": account_balance,
            "pos_balance_fen": pos_balance,
            "diff_fen": diff,
            "abs_diff_fen": abs_diff,
            "diff_yuan": round(diff / 100, 2),
            "conclusion": conclusion,
            "action_required": action_required,
            "pos_revenue_fen": pos_data.get("total_revenue_fen", 0),
            "pos_source": pos_data.get("pos_source") or pos_data.get("data_source", ""),
        }

        log.info(
            "a6_reconciliation_report_generated",
            store_id=str(store_id),
            report_date=target_date.isoformat(),
            conclusion=conclusion,
            diff_fen=diff,
        )
        return report

    # ── 3. 分级通知升级 ────────────────────────────────────────────────────

    async def escalate_discrepancy(
        self,
        tenant_id: UUID,
        store_id: UUID,
        discrepancy_fen: int,
        report: dict[str, Any],
    ) -> None:
        """根据差异金额分级通知相关人员。

        差异 50-200分：通知店长确认。
        差异 >200分：升级通知区域经理 + 费控管理员。

        Args:
            tenant_id: 租户 UUID
            store_id: 门店 UUID
            discrepancy_fen: 差异绝对值（分）
            report: generate_reconciliation_report() 返回的报告 dict
        """
        is_escalated = discrepancy_fen > _STORE_MANAGER_THRESHOLD

        notification_targets = ["store_manager"]
        if is_escalated:
            notification_targets += ["area_manager", "expense_admin"]

        level = "escalated" if is_escalated else "store_manager"
        discrepancy_yuan = round(discrepancy_fen / 100, 2)

        log.warning(
            "a6_discrepancy_notification",
            tenant_id=str(tenant_id),
            store_id=str(store_id),
            report_date=report.get("report_date"),
            discrepancy_fen=discrepancy_fen,
            discrepancy_yuan=discrepancy_yuan,
            notification_level=level,
            targets=notification_targets,
            conclusion=report.get("conclusion"),
        )

        # 调用通知服务（失败不向上抛出，保证对账主流程不受影响）
        try:
            from ..services import notification_service
            from ..models.expense_enums import NotificationEventType

            event_type = (
                NotificationEventType.PETTY_CASH_LARGE_DISCREPANCY
                if is_escalated
                else NotificationEventType.PETTY_CASH_DISCREPANCY
            )

            await notification_service.send(
                tenant_id=tenant_id,
                event_type=event_type,
                store_id=store_id,
                context={
                    "discrepancy_fen": discrepancy_fen,
                    "discrepancy_yuan": discrepancy_yuan,
                    "report_date": report.get("report_date"),
                    "conclusion": report.get("conclusion"),
                    "account_balance_fen": report.get("account_balance_fen"),
                    "pos_balance_fen": report.get("pos_balance_fen"),
                    "notification_targets": notification_targets,
                },
            )
        except ImportError:
            log.warning(
                "a6_notification_service_not_available",
                note="Notification service not available; discrepancy logged only.",
            )
        except (ConnectionError, TimeoutError, RuntimeError, SQLAlchemyError) as exc:
            log.error(
                "a6_notification_failed",
                tenant_id=str(tenant_id),
                store_id=str(store_id),
                error=str(exc),
                exc_info=True,
            )

    # ── 4. 更新 daily_cost_reports.pos_data_source ────────────────────────

    async def _update_cost_report_pos_source(
        self,
        db: AsyncSession,
        tenant_id: UUID,
        store_id: UUID,
        report_date: date,
        pos_source: str,
    ) -> bool:
        """更新或创建 daily_cost_reports 中的 pos_data_source 字段。

        如果当日日报不存在，创建一条 pending 状态的占位记录。
        返回 True 表示成功更新，False 表示无记录（占位记录已创建）。
        """
        from ..models.cost_report import DailyCostReport
        from sqlalchemy.dialects.postgresql import insert as pg_insert

        # 尝试更新已有记录
        stmt_update = (
            update(DailyCostReport.__table__)
            .where(
                DailyCostReport.__table__.c.tenant_id == tenant_id,
                DailyCostReport.__table__.c.store_id == store_id,
                DailyCostReport.__table__.c.report_date == report_date,
            )
            .values(
                pos_data_source=pos_source,
                updated_at=datetime.now(timezone.utc),
            )
            .returning(DailyCostReport.__table__.c.id)
        )
        result = await db.execute(stmt_update)
        updated_row = result.fetchone()

        if updated_row:
            await db.flush()
            log.info(
                "a6_cost_report_pos_source_updated",
                store_id=str(store_id),
                report_date=report_date.isoformat(),
                pos_source=pos_source,
            )
            return True

        # 不存在时插入占位记录（Worker 稍后会填充完整数据）
        stmt_insert = pg_insert(DailyCostReport.__table__).values(
            tenant_id=tenant_id,
            store_id=store_id,
            report_date=report_date,
            pos_data_source=pos_source,
            data_status="pending",
        ).on_conflict_do_update(
            constraint="uq_daily_cost_reports_tenant_store_date",
            set_={
                "pos_data_source": pos_source,
                "updated_at": datetime.now(timezone.utc),
            },
        )
        await db.execute(stmt_insert)
        await db.flush()

        log.info(
            "a6_cost_report_placeholder_created",
            store_id=str(store_id),
            report_date=report_date.isoformat(),
            pos_source=pos_source,
        )
        return False

    # ── 5. 统一 run 入口 ──────────────────────────────────────────────────

    async def run(
        self,
        event_type: str,
        event_data: dict[str, Any],
        db: AsyncSession,
    ) -> None:
        """统一事件处理入口（供 event_consumer_service 调用）。

        Args:
            event_type: 事件类型字符串，当前支持 "ops.daily_close.completed"
            event_data: 事件 payload
            db: AsyncSession
        """
        if event_type == "ops.daily_close.completed":
            await self.handle_daily_close(event_data, db)
        else:
            log.warning(
                "a6_unsupported_event_type",
                event_type=event_type,
                supported=["ops.daily_close.completed"],
            )


# ─────────────────────────────────────────────────────────────────────────────
# 模块级便捷入口（保持与其他 Agent 模块接口一致）
# ─────────────────────────────────────────────────────────────────────────────

async def run(
    event_type: str,
    event_data: dict[str, Any],
    db: AsyncSession,
) -> dict[str, Any]:
    """模块级入口，供 event_consumer_service 直接调用。

    Returns:
        handle_daily_close 返回的对账结果 dict
    """
    agent = A6POSReconciliationAgent()
    return await agent.handle_daily_close(event_data, db)
