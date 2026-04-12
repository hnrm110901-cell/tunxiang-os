"""合同到期预警定时任务

每日 09:00 检查即将到期的合同，推送续签提醒。
合同台账在 P1-S5 建设，此文件为占位框架。

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

log = structlog.get_logger(__name__)

# 预警阈值（天）
_WARN_YELLOW_DAYS = 30
_WARN_ORANGE_DAYS = 7
_WARN_RED_DAYS = 1


class ContractExpiryWatcher:
    """合同到期预警处理器（P1-S5 实现）

    外部调用入口:
        watcher = ContractExpiryWatcher()
        await watcher.run()
    """

    async def run(self, check_date: date | None = None) -> dict[str, Any]:
        """合同到期检查主逻辑。

        Args:
            check_date: 检查基准日期，默认当日。

        Returns:
            {status, check_date, red_count, orange_count, yellow_count, errors}

        TODO P1-S5: 实现合同到期预警
          1. 查询 contract_ledger WHERE effective_to BETWEEN check_date AND check_date+30d
             AND status NOT IN ('terminated', 'renewed')
          2. 按到期距离分级：
             - days_to_expiry <= 1  → red（推送红色预警给合同负责人 + 品牌财务总监）
             - days_to_expiry <= 7  → orange（推送橙色预警给合同负责人 + 品牌财务）
             - days_to_expiry <= 30 → yellow（推送黄色预警给合同负责人）
          3. 通过 notification_service 发送企业微信/站内消息
          4. 发射 ExpenseEventType.CONTRACT_EXPIRING 事件到事件总线
        """
        started_at = datetime.now(timezone.utc)
        check_date = check_date or date.today()

        log.info(
            "contract_expiry_watcher_start",
            check_date=check_date.isoformat(),
            warn_dates={
                "red": (check_date + timedelta(days=_WARN_RED_DAYS)).isoformat(),
                "orange": (check_date + timedelta(days=_WARN_ORANGE_DAYS)).isoformat(),
                "yellow": (check_date + timedelta(days=_WARN_YELLOW_DAYS)).isoformat(),
            },
            status="placeholder_p1_s5",
        )

        # TODO P1-S5: 替换占位实现
        # async with get_async_session() as db:
        #     contracts = await contract_service.get_expiring_contracts(
        #         db, check_date, check_date + timedelta(days=_WARN_YELLOW_DAYS)
        #     )
        #     red = [c for c in contracts if (c.effective_to - check_date).days <= _WARN_RED_DAYS]
        #     orange = [c for c in contracts if _WARN_RED_DAYS < (c.effective_to - check_date).days <= _WARN_ORANGE_DAYS]
        #     yellow = [c for c in contracts if _WARN_ORANGE_DAYS < (c.effective_to - check_date).days <= _WARN_YELLOW_DAYS]
        #     for c in red:
        #         await notification_service.send_contract_expiry_alert(db, c, level="red")
        #     for c in orange:
        #         await notification_service.send_contract_expiry_alert(db, c, level="orange")
        #     for c in yellow:
        #         await notification_service.send_contract_expiry_alert(db, c, level="yellow")

        elapsed = (datetime.now(timezone.utc) - started_at).total_seconds()

        log.info(
            "contract_expiry_watcher_complete",
            check_date=check_date.isoformat(),
            status="placeholder_p1_s5",
            elapsed_seconds=round(elapsed, 2),
        )

        return {
            "status": "placeholder",
            "sprint": "P1-S5",
            "check_date": check_date.isoformat(),
            "red_count": 0,
            "orange_count": 0,
            "yellow_count": 0,
            "errors": [],
        }


async def run_contract_expiry_check(check_date: date | None = None) -> dict[str, Any]:
    """模块级入口函数，供 APScheduler / Celery Beat 直接调用。

    Args:
        check_date: 检查基准日期，默认当日。

    Returns:
        {status, check_date, red_count, orange_count, yellow_count, errors}
    """
    watcher = ContractExpiryWatcher()
    return await watcher.run(check_date=check_date)


if __name__ == "__main__":
    asyncio.run(run_contract_expiry_check())
