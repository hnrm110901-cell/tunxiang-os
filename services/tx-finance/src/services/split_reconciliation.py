"""分账对账服务 — 比对 split engine 记录与支付通道实付金额

核心功能：
  1. 定期比对 profit_split_records 与支付通道实付流水
  2. 发现分账差异（金额不符 / 通道拒绝 / 超时未结算）
  3. 生成对账报告，标记异常记录
  4. 支持人工确认后重试（reprocess）

触发方式：
  - 定时任务（cron / scheduler）：每日凌晨对账前一日
  - 手动触发：admin API 调用
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from .split_engine import SplitEngine

logger = structlog.get_logger(__name__)

# 分账异常类型
RECON_ERROR_TYPE = "split_mismatch"  # 金额/状态与通道不一致
RECON_ERROR_TIMEOUT = "split_timeout"  # 超过 24h 仍 pending
RECON_ERROR_CHANNEL_REJECT = "split_channel_reject"  # 通道明确拒绝


class SplitReconciler:
    """分账对账服务"""

    def __init__(self, db: AsyncSession, tenant_id: str) -> None:
        self.db = db
        self.tenant_id = tenant_id
        self.engine = SplitEngine(db, tenant_id)

    async def get_pending_timeouts(
        self, older_than_hours: int = 24
    ) -> List[Dict[str, Any]]:
        """查找超过指定时间仍为 pending 的分账记录。

        Args:
            older_than_hours: 超时阈值（小时），默认 24 小时

        Returns:
            超时的 pending 记录列表
        """
        await self.db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": self.tenant_id},
        )

        threshold = datetime.now(timezone.utc) - timedelta(hours=older_than_hours)
        result = await self.db.execute(
            text("""
                SELECT r.id, r.order_id, r.store_id, r.channel,
                       r.recipient_type, r.recipient_id,
                       r.split_amount_fen, r.status, r.created_at,
                       rl.name AS rule_name
                FROM profit_split_records r
                LEFT JOIN profit_split_rules rl ON rl.id = r.rule_id
                WHERE r.tenant_id = (current_setting('app.tenant_id', true))::uuid
                  AND r.status = 'pending'
                  AND r.created_at < :threshold
                ORDER BY r.created_at ASC
            """),
            {"threshold": threshold},
        )

        rows = result.fetchall()
        return [
            {
                "record_id": str(row.id),
                "order_id": str(row.order_id),
                "store_id": str(row.store_id),
                "channel": row.channel,
                "recipient_type": row.recipient_type,
                "recipient_id": str(row.recipient_id) if row.recipient_id else None,
                "split_amount_fen": row.split_amount_fen,
                "rule_name": row.rule_name,
                "hours_pending": round(
                    (datetime.now(timezone.utc) - row.created_at).total_seconds() / 3600, 1
                ),
            }
            for row in rows
        ]

    async def detect_amount_mismatches(
        self, start_date: Optional[date] = None, end_date: Optional[date] = None
    ) -> List[Dict[str, Any]]:
        """比对 profit_split_records 的总分账金额与日流水中的实际分账金额。

        在真实生产中，需要从支付通道（微信/支付宝）获取实际结算数据。
        本方法目前基于内部数据的自检。

        Args:
            start_date: 对账开始日期
            end_date: 对账结束日期

        Returns:
            比对后的异常一览
        """
        t_date = start_date or date.today()
        e_date = end_date or date.today()

        await self.db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": self.tenant_id},
        )

        # 查询指定日期范围内的分账记录
        result = await self.db.execute(
            text("""
                SELECT
                    r.recipient_type,
                    r.recipient_id,
                    COUNT(*) AS total_records,
                    SUM(r.split_amount_fen) AS total_split_fen,
                    SUM(CASE WHEN r.status = 'settled' THEN r.split_amount_fen ELSE 0 END) AS settled_fen,
                    SUM(CASE WHEN r.status = 'pending' THEN r.split_amount_fen ELSE 0 END) AS pending_fen,
                    SUM(CASE WHEN r.status = 'cancelled' THEN r.split_amount_fen ELSE 0 END) AS cancelled_fen,
                    MIN(r.created_at) AS earliest,
                    MAX(r.created_at) AS latest
                FROM profit_split_records r
                WHERE r.tenant_id = (current_setting('app.tenant_id', true))::uuid
                  AND r.created_at::date >= :start_date
                  AND r.created_at::date <= :end_date
                GROUP BY r.recipient_type, r.recipient_id
                ORDER BY total_split_fen DESC
            """),
            {"start_date": t_date, "end_date": e_date},
        )

        rows = result.fetchall()
        summary = []
        for row in rows:
            total = int(row.total_split_fen or 0)
            settled = int(row.settled_fen or 0)
            pending = int(row.pending_fen or 0)
            cancelled = int(row.cancelled_fen or 0)

            entry = {
                "recipient_type": row.recipient_type,
                "recipient_id": str(row.recipient_id) if row.recipient_id else None,
                "total_split_yuan": round(total / 100, 2),
                "settled_yuan": round(settled / 100, 2),
                "pending_yuan": round(pending / 100, 2),
                "cancelled_yuan": round(cancelled / 100, 2),
                "settlement_rate": round(settled / total, 4) if total > 0 else 0,
                "risk_level": _assess_risk(pending, total),
            }
            summary.append(entry)

        return summary

    async def cancel_stale_pending(
        self, older_than_hours: int = 72
    ) -> Dict[str, Any]:
        """取消超过指定时间仍 pending 的记录（长时间未结算视为通道拒绝）。

        Args:
            older_than_hours: 超时阈值，默认 72 小时

        Returns:
            取消结果摘要
        """
        await self.db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": self.tenant_id},
        )

        threshold = datetime.now(timezone.utc) - timedelta(hours=older_than_hours)
        result = await self.db.execute(
            text("""
                UPDATE profit_split_records
                SET status = 'cancelled',
                    settled_at = NOW()
                WHERE tenant_id = (current_setting('app.tenant_id', true))::uuid
                  AND status = 'pending'
                  AND created_at < :threshold
            """),
            {"threshold": threshold},
        )
        await self.db.flush()
        cancelled_count = result.rowcount

        logger.info(
            "split_reconciliation.stale_cancelled",
            tenant_id=self.tenant_id,
            older_than_hours=older_than_hours,
            cancelled_count=cancelled_count,
        )

        return {
            "ok": True,
            "data": {
                "cancelled_records": cancelled_count,
                "older_than_hours": older_than_hours,
            },
        }

    async def generate_reconciliation_report(
        self, start_date: Optional[date] = None, end_date: Optional[date] = None
    ) -> Dict[str, Any]:
        """生成分账对账综合报告。

        包含：
        - 超时未结算记录
        - 金额差异摘要
        - 风险评级
        """
        t_date = start_date or date.today()
        e_date = end_date or date.today()

        # 并行查询
        timeouts = await self.get_pending_timeouts(older_than_hours=24)
        risk_breakdown = await self.detect_amount_mismatches(t_date, e_date)

        # 汇总
        total_pending = sum(r["pending_yuan"] for r in risk_breakdown)
        total_settled = sum(r["settled_yuan"] for r in risk_breakdown)
        high_risk_count = sum(1 for r in risk_breakdown if r["risk_level"] == "high")

        report = {
            "period": {"start": t_date.isoformat(), "end": e_date.isoformat()},
            "summary": {
                "total_pending_yuan": total_pending,
                "total_settled_yuan": total_settled,
                "timeout_count": len(timeouts),
                "high_risk_recipients": high_risk_count,
            },
            "timeouts": timeouts[:20],  # Top 20 超时记录
            "risk_breakdown": risk_breakdown,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

        logger.info(
            "split_reconciliation.report_generated",
            tenant_id=self.tenant_id,
            timeout_count=len(timeouts),
            high_risk_count=high_risk_count,
        )

        return {"ok": True, "data": report}


def _assess_risk(pending_fen: int, total_fen: int) -> str:
    """评估分账风险等级。

    - pending > 30% 的流水 → high
    - pending > 10% 的流水 → medium
    - pending <= 10% → low
    """
    if total_fen <= 0:
        return "low"
    ratio = pending_fen / total_fen
    if ratio > 0.3:
        return "high"
    if ratio > 0.1:
        return "medium"
    return "low"
