"""备用金月末核销定时任务

每月25日 00:30 自动触发：
  1. 为所有租户的所有门店生成月末核销草稿
  2. 统计未核销流水，推送催办通知
  3. 生成品牌财务月度汇总简报

调度方式：由 APScheduler 或 Celery Beat 调用（参照项目现有调度方式）。
"""
from __future__ import annotations

import asyncio
import os
from datetime import date, datetime
from typing import Any
from uuid import UUID

import structlog

log = structlog.get_logger(__name__)


class MonthlyPettyCashSettlementWorker:
    """备用金月末核销批量处理器

    外部调用入口:
        worker = MonthlyPettyCashSettlementWorker()
        await worker.run(settlement_month="2026-04")
    """

    async def _get_active_tenant_ids(self) -> list[str]:
        """获取所有活跃租户 ID 列表。

        TODO P1: 从 tx-org 或共享配置中获取所有活跃租户列表，
        当前用环境变量 DEFAULT_TENANT_ID 作为单租户兜底。
        """
        default_tenant = os.environ.get("DEFAULT_TENANT_ID")
        if not default_tenant:
            log.warning("monthly_settlement_no_tenant_configured")
            return []
        return [default_tenant]  # P1 扩展为多租户

    async def _process_tenant(
        self,
        tenant_id: UUID,
        settlement_month: str,
    ) -> dict[str, Any]:
        """为单个租户执行月末核销处理。

        Args:
            tenant_id: 租户 UUID
            settlement_month: "YYYY-MM" 格式月份字符串

        Returns:
            {settlements_generated, accounts_processed, notifications_sent}
        """
        from ..agents.a1_petty_cash_guardian import run as a1_run

        # TODO P1: 注入真实 DB session，参照项目 get_async_session 方式
        # async with get_async_session() as db:
        #     result = await a1_run(
        #         db, tenant_id, "monthly_settlement",
        #         {"settlement_month": settlement_month}
        #     )
        #     return result

        # 占位：当 DB session 接入后取消注释上方代码块，删除下方日志行
        log.info(
            "tenant_monthly_settlement_queued",
            tenant_id=str(tenant_id),
            settlement_month=settlement_month,
            note="db_session_pending_p1",
        )
        return {"settlements_generated": 0, "accounts_processed": 0, "notifications_sent": 0}

    async def run(self, settlement_month: str | None = None) -> dict[str, Any]:
        """多租户月末核销批量处理主函数。

        Args:
            settlement_month: "YYYY-MM" 格式，默认当月。

        Returns:
            {total_tenants, total_accounts, total_settlements, errors}
        """
        if not settlement_month:
            settlement_month = datetime.now().strftime("%Y-%m")

        log.info("monthly_settlement_worker_start", settlement_month=settlement_month)

        results: dict[str, Any] = {
            "total_tenants": 0,
            "total_accounts": 0,
            "total_settlements": 0,
            "errors": [],
        }

        tenant_ids = await self._get_active_tenant_ids()
        if not tenant_ids:
            log.warning("monthly_settlement_no_tenants_found", settlement_month=settlement_month)
            return results

        for tenant_id_str in tenant_ids:
            try:
                tenant_id = UUID(tenant_id_str)
                tenant_result = await self._process_tenant(tenant_id, settlement_month)
                results["total_tenants"] += 1
                results["total_accounts"] += tenant_result.get("accounts_processed", 0)
                results["total_settlements"] += tenant_result.get("settlements_generated", 0)
                log.info(
                    "tenant_settlement_completed",
                    tenant_id=tenant_id_str,
                    settlement_month=settlement_month,
                    **tenant_result,
                )
            except ValueError as exc:
                log.error(
                    "tenant_settlement_invalid_uuid",
                    tenant_id=tenant_id_str,
                    error=str(exc),
                    exc_info=True,
                )
                results["errors"].append({"tenant_id": tenant_id_str, "error": str(exc)})
            except Exception as exc:  # noqa: BLE001 — 外层兜底，保证其他租户继续处理
                log.error(
                    "tenant_settlement_failed",
                    tenant_id=tenant_id_str,
                    error=str(exc),
                    exc_info=True,
                )
                results["errors"].append({"tenant_id": tenant_id_str, "error": str(exc)})

        log.info("monthly_settlement_worker_complete", **results)
        return results


def get_next_settlement_date() -> date:
    """计算下次执行日期（每月25日）。"""
    today = date.today()
    if today.day <= 25:
        return date(today.year, today.month, 25)
    # 下个月25日
    if today.month == 12:
        return date(today.year + 1, 1, 25)
    return date(today.year, today.month + 1, 25)


async def run_monthly_settlement_for_all_tenants(settlement_month: str | None = None) -> dict[str, Any]:
    """模块级入口函数，供 APScheduler / Celery Beat 直接调用。

    Args:
        settlement_month: "YYYY-MM" 格式，默认当月。

    Returns:
        {total_tenants, total_accounts, total_settlements, errors}
    """
    worker = MonthlyPettyCashSettlementWorker()
    return await worker.run(settlement_month=settlement_month)


if __name__ == "__main__":
    # 支持直接运行：python -m src.workers.monthly_petty_cash
    asyncio.run(run_monthly_settlement_for_all_tenants())
