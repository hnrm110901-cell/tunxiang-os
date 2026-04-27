"""结算通知服务 — 结算批次状态变更通知

通知场景：
  1. 批次生成（draft）→ 通知财务审核
  2. 批次确认（confirmed）→ 通知门店/总部
  3. 批次完成（settled）→ 通知各方到账确认

通知渠道（按优先级）：
  - 企业微信消息推送
  - 站内通知（notification 表）
  - 邮件（可选）

当前为骨架实现，真实推送需对接企业微信/邮件服务。
"""

from __future__ import annotations

import uuid
from typing import Any, Dict

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

log = structlog.get_logger(__name__)


class SettlementNotifyService:
    """结算通知服务"""

    def __init__(self, db: AsyncSession, tenant_id: str) -> None:
        self.db = db
        self.tenant_id = tenant_id
        self._tid = uuid.UUID(tenant_id)

    async def notify_batch_created(
        self,
        batch_id: str,
        batch_no: str,
        total_records: int,
        total_amount_fen: int,
        period_start: str,
        period_end: str,
    ) -> Dict[str, Any]:
        """结算批次生成通知 — 发送给财务审核人员

        通知内容：
          [储值分账结算] 新批次待审核
          批次号: {batch_no}
          周期: {period_start} ~ {period_end}
          总笔数: {total_records}
          总金额: {total_amount_yuan} 元
        """
        amount_yuan = round(total_amount_fen / 100, 2)
        message = (
            f"[储值分账结算] 新批次待审核\n"
            f"批次号: {batch_no}\n"
            f"周期: {period_start} ~ {period_end}\n"
            f"总笔数: {total_records}\n"
            f"总金额: {amount_yuan} 元"
        )

        # 发送通知（当前为日志记录，后续对接企业微信）
        log.info(
            "sv_settlement.notify_created",
            batch_id=batch_id,
            batch_no=batch_no,
            total_records=total_records,
            total_amount_yuan=amount_yuan,
            tenant_id=self.tenant_id,
        )

        # 写入站内通知（如果 notifications 表存在）
        await self._save_notification(
            title="储值分账结算 - 待审核",
            content=message,
            category="settlement",
            ref_id=batch_id,
        )

        return {
            "notified": True,
            "batch_id": batch_id,
            "channel": "internal",
            "message": message,
        }

    async def notify_batch_confirmed(
        self,
        batch_id: str,
        batch_no: str,
        settled_count: int,
        total_amount_fen: int,
    ) -> Dict[str, Any]:
        """结算批次确认通知 — 发送给门店管理者和总部

        通知内容：
          [储值分账结算] 批次已确认
          批次号: {batch_no}
          已结算笔数: {settled_count}
          总金额: {total_amount_yuan} 元
        """
        amount_yuan = round(total_amount_fen / 100, 2)
        message = (
            f"[储值分账结算] 批次已确认\n"
            f"批次号: {batch_no}\n"
            f"已结算笔数: {settled_count}\n"
            f"总金额: {amount_yuan} 元"
        )

        log.info(
            "sv_settlement.notify_confirmed",
            batch_id=batch_id,
            batch_no=batch_no,
            settled_count=settled_count,
            tenant_id=self.tenant_id,
        )

        await self._save_notification(
            title="储值分账结算 - 已确认",
            content=message,
            category="settlement",
            ref_id=batch_id,
        )

        return {
            "notified": True,
            "batch_id": batch_id,
            "channel": "internal",
            "message": message,
        }

    async def notify_batch_settled(
        self,
        batch_id: str,
        batch_no: str,
    ) -> Dict[str, Any]:
        """结算批次打款完成通知"""
        message = (
            f"[储值分账结算] 打款已完成\n"
            f"批次号: {batch_no}\n"
            f"状态: 已结算"
        )

        log.info(
            "sv_settlement.notify_settled",
            batch_id=batch_id,
            batch_no=batch_no,
            tenant_id=self.tenant_id,
        )

        await self._save_notification(
            title="储值分账结算 - 已到账",
            content=message,
            category="settlement",
            ref_id=batch_id,
        )

        return {
            "notified": True,
            "batch_id": batch_id,
            "channel": "internal",
            "message": message,
        }

    async def notify_settlement_anomaly(
        self,
        batch_id: str,
        batch_no: str,
        anomaly_type: str,
        detail: str,
    ) -> Dict[str, Any]:
        """结算异常通知 — 金额不一致/超时未确认等"""
        message = (
            f"[储值分账结算] 异常告警\n"
            f"批次号: {batch_no}\n"
            f"异常类型: {anomaly_type}\n"
            f"详情: {detail}"
        )

        log.warning(
            "sv_settlement.notify_anomaly",
            batch_id=batch_id,
            batch_no=batch_no,
            anomaly_type=anomaly_type,
            detail=detail,
            tenant_id=self.tenant_id,
        )

        await self._save_notification(
            title=f"储值分账结算 - 异常: {anomaly_type}",
            content=message,
            category="settlement_alert",
            ref_id=batch_id,
        )

        return {
            "notified": True,
            "batch_id": batch_id,
            "anomaly_type": anomaly_type,
            "channel": "internal",
            "message": message,
        }

    # ══════════════════════════════════════════════════════════════
    # 内部方法
    # ══════════════════════════════════════════════════════════════

    async def _save_notification(
        self,
        title: str,
        content: str,
        category: str,
        ref_id: str,
    ) -> None:
        """保存站内通知（降级容忍：表不存在时跳过）"""
        try:
            await self.db.execute(
                text("""
                    INSERT INTO notifications (id, tenant_id, title, content, category, ref_id)
                    VALUES (:id, :tid, :title, :content, :category, :ref_id)
                """),
                {
                    "id": uuid.uuid4(),
                    "tid": self._tid,
                    "title": title,
                    "content": content,
                    "category": category,
                    "ref_id": ref_id,
                },
            )
        except Exception:
            # notifications 表可能不存在，降级跳过
            log.debug(
                "sv_settlement.notification_save_skipped",
                title=title,
                reason="notifications table may not exist",
            )
