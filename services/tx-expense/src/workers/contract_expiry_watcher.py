"""合同到期预警定时任务

每日 08:00 运行，检查即将到期的合同并推送续签提醒，
同时触发 A4 预算预警 Agent 的每日检查。

预警分级：
  - 30天：黄色预警（提前规划续签）
  -  7天：橙色预警（紧急跟进）
  -  1天：红色预警（明日到期，立即处理）
"""

from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta, timezone
from typing import Any

import structlog
from sqlalchemy.exc import SQLAlchemyError

log = structlog.get_logger(__name__)

# 预警阈值（天）
_WARN_YELLOW_DAYS = 30
_WARN_ORANGE_DAYS = 7
_WARN_RED_DAYS = 1


class ContractExpiryWatcher:
    """合同到期预警处理器

    外部调用入口:
        watcher = ContractExpiryWatcher()
        await watcher.run()
    """

    async def run(self, check_date: date | None = None) -> dict[str, Any]:
        """合同到期检查主逻辑。

        Args:
            check_date: 检查基准日期，默认当日。

        Returns:
            {
                "status": str,
                "check_date": str,
                "expiring_contracts": int,
                "red_count": int,
                "orange_count": int,
                "yellow_count": int,
                "a4_result": dict,
                "errors": list[str],
            }
        """
        from ..agents.a4_budget_alert import A4BudgetAlertAgent
        from ..services.contract_ledger_service import ContractLedgerService

        started_at = datetime.now(timezone.utc)
        check_date = check_date or date.today()
        errors: list[str] = []

        log.info(
            "contract_expiry_watcher_start",
            check_date=check_date.isoformat(),
            warn_dates={
                "red": (check_date + timedelta(days=_WARN_RED_DAYS)).isoformat(),
                "orange": (check_date + timedelta(days=_WARN_ORANGE_DAYS)).isoformat(),
                "yellow": (check_date + timedelta(days=_WARN_YELLOW_DAYS)).isoformat(),
            },
        )

        contract_svc = ContractLedgerService()
        a4_agent = A4BudgetAlertAgent()

        red_count = 0
        orange_count = 0
        yellow_count = 0
        expiring_total = 0
        a4_result: dict = {}

        import os
        import uuid as _uuid

        from shared.ontology.src.database import TenantSession

        tenant_id_str = os.environ.get("DEFAULT_TENANT_ID", "")
        if not tenant_id_str:
            log.warning(
                "contract_expiry_watcher_no_tenant",
                hint="设置 DEFAULT_TENANT_ID 环境变量或接入多租户列表",
            )
            return {
                "status": "skipped",
                "check_date": check_date.isoformat(),
                "reason": "no_tenant_configured",
                "expiring_contracts": 0,
                "red_count": 0,
                "orange_count": 0,
                "yellow_count": 0,
                "a4_result": {},
                "errors": [],
            }

        tenant_id = _uuid.UUID(tenant_id_str)

        try:
            async with TenantSession(tenant_id_str) as db:
                # ── 1. 查询即将到期合同 ─────────────────────────────────────
                expiring = await contract_svc.check_expiring_contracts(db=db, tenant_id=tenant_id)
                expiring_total = len(expiring)

                for contract in expiring:
                    if contract.end_date is None:
                        continue
                    days_left = (contract.end_date - check_date).days

                    if days_left <= _WARN_RED_DAYS:
                        red_count += 1
                        log.warning(
                            "contract_expiry_red",
                            contract_id=str(contract.id),
                            contract_name=contract.contract_name,
                            end_date=contract.end_date.isoformat(),
                            days_left=days_left,
                        )
                    elif days_left <= _WARN_ORANGE_DAYS:
                        orange_count += 1
                        log.warning(
                            "contract_expiry_orange",
                            contract_id=str(contract.id),
                            contract_name=contract.contract_name,
                            end_date=contract.end_date.isoformat(),
                            days_left=days_left,
                        )
                    else:
                        yellow_count += 1
                        log.info(
                            "contract_expiry_yellow",
                            contract_id=str(contract.id),
                            contract_name=contract.contract_name,
                            end_date=contract.end_date.isoformat(),
                            days_left=days_left,
                        )

                # ── 2. 触发 A4 Agent 每日检查（费用执行率 + 合同预警生成推送）──
                a4_result = await a4_agent.run_daily_check(db=db, tenant_id=tenant_id)
                await db.commit()

        except (OSError, RuntimeError, ValueError, SQLAlchemyError) as exc:
            error_msg = f"{type(exc).__name__}: {exc}"
            errors.append(error_msg)
            log.error(
                "contract_expiry_watcher_error",
                error=error_msg,
                exc_info=True,
            )

        elapsed = (datetime.now(timezone.utc) - started_at).total_seconds()

        result = {
            "status": "ok" if not errors else "partial_error",
            "check_date": check_date.isoformat(),
            "expiring_contracts": expiring_total,
            "red_count": red_count,
            "orange_count": orange_count,
            "yellow_count": yellow_count,
            "a4_result": a4_result,
            "errors": errors,
            "elapsed_seconds": round(elapsed, 2),
        }

        log.info(
            "contract_expiry_watcher_complete",
            **{k: v for k, v in result.items() if k != "errors"},
            error_count=len(errors),
        )
        return result


async def run_contract_expiry_check(check_date: date | None = None) -> dict[str, Any]:
    """模块级入口函数，供 APScheduler / Celery Beat 直接调用。

    每日 08:00 执行：
      1. check_expiring_contracts() — 合同到期分级预警
      2. a4_agent.run_daily_check() — 费用执行率 + 合同预警推送

    Args:
        check_date: 检查基准日期，默认当日。

    Returns:
        {status, check_date, expiring_contracts, red_count, orange_count,
         yellow_count, a4_result, errors, elapsed_seconds}
    """
    watcher = ContractExpiryWatcher()
    return await watcher.run(check_date=check_date)


if __name__ == "__main__":
    asyncio.run(run_contract_expiry_check())
